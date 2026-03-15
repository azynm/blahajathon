from flask import Flask, redirect, url_for, session, request, render_template, Response, jsonify
import os
from dotenv import load_dotenv
load_dotenv(override=True)

import hashlib
import requests
from logic.discord_logic import fetch_all_messages, create_storage_channel, get_repo_name
from logic.commentator_logic import collect_events
from logic.settings_logic import _is_allowed_image, _profile_context
from logic.github_logic import get_detailed_github_data
from logic.scoring_logic import get_leaderboard, get_scores_last_updated, set_display_name, resolve_player
import json
from pathlib import Path
import uuid
from logic.commentator_logic import determine_style, generate_script, generate_audio_from_text
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import time
#import gunicorn
#import elevenlabs

#Setup constants
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
REDIRECT_URI = "http://127.0.0.1:5000/discord_callback"
GITHUB_REDIRECT_URI = "http://127.0.0.1:5000/github_callback"
DISCORD_AUTH_URL = f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds+bot&permissions=268437520"
GITHUB_AUTH_URL = f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}&redirect_uri={GITHUB_REDIRECT_URI}&scope=repo" 

#Start Flask app
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = "bum4"
app.config['UPLOAD_FOLDER'] = str(Path("static") / "uploads")
app.permanent_session_lifetime = timedelta(days=7)

# Global state for commentary caching
commentary_history = {}  # {dashboard_id: [list of commentary entries]}
last_generated = {}      # {dashboard_id: timestamp of last generation}

# Discord API cache to reduce rate limiting
discord_cache = {}  # {cache_key: {"data": ..., "timestamp": ...}}
CACHE_TTL = 300  # Cache TTL in seconds (5 minutes)

def get_cached(key):
    """Get cached data if not expired."""
    if key in discord_cache:
        entry = discord_cache[key]
        if time.time() - entry["timestamp"] < CACHE_TTL:
            print(f"[CACHE HIT] {key}")
            return entry["data"]
    return None

def set_cached(key, data):
    """Store data in cache."""
    discord_cache[key] = {"data": data, "timestamp": time.time()}

def invalidate_cache(key_prefix):
    """Invalidate cache entries matching prefix."""
    keys_to_delete = [k for k in discord_cache if k.startswith(key_prefix)]
    for k in keys_to_delete:
        del discord_cache[k]

#Home screen
@app.route('/')
def index():
    #If not logged in, send to appropriate login page
    if 'discord_access_token' not in session:
        if 'github_access_token' not in session:
            return render_template("login.html", step=2, discord_auth_url=DISCORD_AUTH_URL, github_auth_url=GITHUB_AUTH_URL)
        else:
            return render_template("login.html", step=0, discord_auth_url=DISCORD_AUTH_URL, github_auth_url=GITHUB_AUTH_URL)
    if 'github_access_token' not in session:
        return render_template("login.html", step=1, discord_auth_url=DISCORD_AUTH_URL, github_auth_url=GITHUB_AUTH_URL)

    #Get all the servers the bot is in (cached)
    bot_server_ids = get_cached("bot_server_ids")
    if bot_server_ids is None:
        print("[DISCORD API] GET /users/@me/guilds (bot token) - index page load")
        bot_resp = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bot {BOT_TOKEN}"})
        if bot_resp.status_code == 429:
            print(f"[RATE LIMITED] bot guilds call, retry_after={bot_resp.json().get('retry_after', '?')}")
            bot_server_ids = []
        elif not bot_resp.ok:
            return render_template("login.html", step=1, discord_auth_url=DISCORD_AUTH_URL, github_auth_url=GITHUB_AUTH_URL)
        else:
            bot_servers = bot_resp.json()
            if not isinstance(bot_servers, list):
                return render_template("login.html", step=1, discord_auth_url=DISCORD_AUTH_URL, github_auth_url=GITHUB_AUTH_URL)
            bot_server_ids = []
            for g in bot_servers:
                # Check per-guild cache first
                repo_cache_key = f"repo_name_{g['id']}"
                cached_name = get_cached(repo_cache_key)
                if cached_name is not None:
                    if cached_name != "__none__":
                        bot_server_ids.append(g["id"])
                    continue
                print(f"[DISCORD API] get_repo_name for guild {g['id']} - index page load")
                name = get_repo_name(g["id"], {"Authorization": f"Bot {BOT_TOKEN}"})
                set_cached(repo_cache_key, name if name is not None else "__none__")
                if name is not None:
                    bot_server_ids.append(g["id"])
                time.sleep(0.3)  # Rate limit protection between guilds
            set_cached("bot_server_ids", bot_server_ids)

    #Get all the servers the user is in (cached per user)
    user_cache_key = f"user_servers_{session.get('username', 'unknown')}"
    user_servers = get_cached(user_cache_key)
    if user_servers is None:
        print("[DISCORD API] GET /users/@me/guilds (user token) - index page load")
        user_resp = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session['discord_access_token']}"})
        if user_resp.status_code == 429:
            # Rate limited - use empty list but don't nuke the session
            print(f"[RATE LIMITED] user guilds call, retry_after={user_resp.json().get('retry_after', '?')}")
            user_servers = []
        elif user_resp.status_code == 401:
            # Token actually expired - clear session and re-login
            session.clear()
            return redirect(url_for('index'))
        else:
            user_servers = user_resp.json()
            if not isinstance(user_servers, list):
                session.clear()
                return redirect(url_for('index'))
            set_cached(user_cache_key, user_servers)

    #Make a list of all servers we can participate in
    servers = []
    for s in user_servers:
        if s["id"] in bot_server_ids:
            s["bot_exists"] = True
            servers.append(s)
        elif int(s['permissions']) & 0x20:
            servers.append(s)

    #Show the page
    return render_template("index.html", guilds=servers, username=session['username'], client_id=DISCORD_CLIENT_ID, redirect_uri=REDIRECT_URI) 

#Discord callback page
@app.route('/discord_callback')
def discord_callback(): 
    state_str = request.args.get('state')
    
    if state_str:
        state_data = json.loads(state_str)
        guild_id = state_data.get('guild_id')
        repo = state_data.get('repo')
        discord_headers = {"Authorization": f"Bot {BOT_TOKEN}"}

        print(f"[DISCORD API] create_storage_channel for guild {guild_id} - bot setup")
        name = create_storage_channel(guild_id, repo, discord_headers)
        if name is not None:
            print(f"Bot added to Guild: {guild_id} for Repo: {repo}")
            invalidate_cache("bot_server_ids")  # Refresh bot server list
        else:
            print("error")
            
        return redirect(url_for('index'))

    #Get code from Discord callback for handshake
    code = request.args.get('code')
    
    #Perform handshake
    print("[DISCORD API] POST /oauth2/token - discord callback token exchange")
    data = {'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}
    r = requests.post("https://discord.com/api/oauth2/token", data=data).json()
    
    #Get new access token
    session.permanent = True
    session['discord_access_token'] = r.get('access_token')
    
    #Get username
    print("[DISCORD API] GET /users/@me - discord callback get username")
    user_data = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {session['discord_access_token']}"}).json()
    session['username'] = user_data.get('username')
    invalidate_cache(f"user_servers_{session['username']}")  # Fresh data on login
    
    return redirect(url_for('index'))
          

#Github callback page
@app.route('/github_callback')
def github_callback():
    #Get code from Github callback for handshake
    code = request.args.get('code')

    if not code:
        # No code provided, redirect back to login
        return redirect(url_for('index'))

    data = {'client_id': GITHUB_CLIENT_ID, 'client_secret': GITHUB_CLIENT_SECRET, 'code': code, 'redirect_uri': GITHUB_REDIRECT_URI}
    r = requests.post("https://github.com/login/oauth/access_token", data=data, headers={'Accept': 'application/json'}).json()

    #Get new access token
    access_token = r.get('access_token')
    if not access_token:
        # Token exchange failed, clear any partial state and redirect
        session.pop('github_access_token', None)
        return redirect(url_for('index'))

    session.permanent = True
    session['github_access_token'] = access_token

    return redirect(url_for('index'))

#Dashboard page for each league/server
@app.route('/dashboard/<dashboard_id>')
def dashboard(dashboard_id):
    # Redirect to login if not authenticated
    if 'discord_access_token' not in session or 'github_access_token' not in session:
        return redirect(url_for('index'))

    #Setup headers
    discord_headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    github_headers = {"Authorization": f"token {session['github_access_token']}"}
    now = datetime.now()
    last_time = now - timedelta(hours=3)

    #Fetch all data
    github_data = get_detailed_github_data("azynm/blahajathon", github_headers, last_time)
    print(f"[DISCORD API] fetch_all_messages for guild {dashboard_id} - dashboard load")
    discord_data = fetch_all_messages(dashboard_id, discord_headers, last_time)

    project_name = get_cached(f"guild_name_{dashboard_id}")
    if project_name is None:
        project_name = dashboard_id
        try:
            print(f"[DISCORD API] GET /guilds/{dashboard_id} - dashboard get guild name")
            guild_resp = requests.get(
                f"https://discord.com/api/guilds/{dashboard_id}",
                headers=discord_headers,
                timeout=10,
            )
            if guild_resp.ok:
                guild_data = guild_resp.json()
                project_name = guild_data.get("name", dashboard_id)
                set_cached(f"guild_name_{dashboard_id}", project_name)
        except requests.RequestException:
            project_name = dashboard_id
    
    leaderboard = get_leaderboard()
    last_updated = get_scores_last_updated()

    return render_template(
        "dashboard.html",
        players=leaderboard,
        project_name=project_name,
        autoplay_commentary=session.get('autoplay_commentary', False),
        last_updated=last_updated,
    )

#Logout page
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'discord_access_token' not in session or 'github_access_token' not in session:
        return redirect(url_for('index'))

    error_message = ""

    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        picture_file = request.files.get('picture_file')

        if display_name:
            session['profile_name'] = display_name
            # Persist display name to scoring system
            discord_username = session.get('username', '')
            canonical = resolve_player(discord_username)
            if canonical:
                set_display_name(canonical, display_name)

        if picture_file and picture_file.filename:
            if _is_allowed_image(picture_file.filename):
                upload_dir = Path(app.config['UPLOAD_FOLDER'])
                upload_dir.mkdir(parents=True, exist_ok=True)

                original_name = secure_filename(picture_file.filename)
                extension = original_name.rsplit('.', 1)[1].lower()
                file_name = f"{uuid.uuid4().hex}.{extension}"
                save_path = upload_dir / file_name
                picture_file.save(save_path)

                session['profile_picture'] = url_for('static', filename=f'uploads/{file_name}')
            else:
                error_message = "Unsupported image format. Use png, jpg, jpeg, gif, or webp."

        if not error_message:
            # Save autoplay preference
            autoplay = request.form.get('autoplay_commentary', '0')
            session['autoplay_commentary'] = autoplay == '1'
            return redirect(url_for('settings', saved='1'))

    saved = request.args.get('saved') == '1'
    return render_template(
        'settings.html',
        current_user=_profile_context(session),
        saved=saved,
        error_message=error_message,
        autoplay_commentary=session.get('autoplay_commentary', False),
    )

#Endpoint for commentator
@app.route('/api/commentary-history/<dashboard_id>')
def commentary_history_api(dashboard_id):
    """Return list of recent commentary entries (without audio bytes)."""
    now = time.time()
    last_gen = last_generated.get(dashboard_id, 0)

    # Regenerate if >60s since last generation AND messages have changed
    if now - last_gen > 60:
        discord_headers = {"Authorization": f"Bot {BOT_TOKEN}"}
        github_headers = {"Authorization": f"token {session['github_access_token']}"}
        print(f"[DISCORD API] collect_events for guild {dashboard_id} - commentary generation")
        events = collect_events(dashboard_id, discord_headers, github_headers, "azynm/CoLeague")

        # Only generate if we got events AND messages have changed
        if events is not None:
            style = determine_style(events)
            script = generate_script(events, style=style)
            audio = generate_audio_from_text(script, style=style)

            if audio:
                timestamp = time.time()
                entry_id = hashlib.md5(f"{dashboard_id}_{timestamp}".encode()).hexdigest()[:12]

                # Build event log bullets
                event_log = []
                for h in events.get("discord_highlights", []):
                    event_log.append(h)
                for c in events.get("recent_commits", []):
                    event_log.append(f"{c['author']} committed: {c['message']}")
                pr_count = events.get("pull_requests_merged", 0)
                if pr_count:
                    event_log.append(f"{pr_count} pull request(s) merged")

                if dashboard_id not in commentary_history:
                    commentary_history[dashboard_id] = []

                commentary_history[dashboard_id].append({
                    "id": entry_id,
                    "timestamp": timestamp,
                    "style": style,
                    "script": script,
                    "audio": audio,
                    "event_log": event_log
                })
                commentary_history[dashboard_id] = commentary_history[dashboard_id][-10:]
                last_generated[dashboard_id] = timestamp
        else:
            print(f"DEBUG: No new messages, skipping commentary generation")
            last_generated[dashboard_id] = now

    history = commentary_history.get(dashboard_id, [])
    # Return without audio bytes
    return json.dumps([{
        "id": e["id"],
        "timestamp": e["timestamp"],
        "style": e["style"],
        "script": e["script"],
        "event_log": e.get("event_log", [])
    } for e in history])

#Endpoint for audio playback
@app.route('/api/commentary/<dashboard_id>/<entry_id>')
def commentary_audio(dashboard_id, entry_id):
    """Serve audio for a specific commentary entry."""
    history = commentary_history.get(dashboard_id, [])
    entry = next((e for e in history if e["id"] == entry_id), None)

    if not entry or not entry.get("audio"):
        return "", 404

    return Response(entry["audio"], mimetype="audio/mpeg")

#Endpoint to fetch repos
@app.route('/api/github-repos')
def github_repos():
    """Fetch the user's GitHub repositories."""
    if 'github_access_token' not in session:
        return json.dumps({"error": "Not authenticated with GitHub"}), 401

    github_headers = {"Authorization": f"token {session['github_access_token']}"}
    response = requests.get(
        "https://api.github.com/user/repos?per_page=100&sort=updated",
        headers=github_headers
    )

    if response.status_code != 200:
        return json.dumps({"error": "Failed to fetch repos"}), 500

    repos = response.json()
    # Return simplified repo data
    return json.dumps([{
        "id": repo["id"],
        "name": repo["name"],
        "full_name": repo["full_name"],
        "private": repo["private"],
        "description": repo.get("description", ""),
        "url": repo["html_url"]
    } for repo in repos])


@app.route('/api/leaderboard')
def leaderboard_api():
    """Return the current leaderboard with scores."""
    leaderboard = get_leaderboard()
    return jsonify({
        "players": leaderboard,
        "last_updated": get_scores_last_updated(),
    })


#Actually starts web server
if __name__ == "__main__":
    '''
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
    '''
    app.run(debug=True, port=5000)