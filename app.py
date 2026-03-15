from flask import Flask, redirect, url_for, session, request, render_template, Response, jsonify
import os
from dotenv import load_dotenv
load_dotenv(override=True)

import hashlib
import requests
from discord_logic import fetch_all_messages
from commentator_logic import collect_events
from settings_logic import _is_allowed_image, _profile_context
from github_logic import get_detailed_github_data
from scoring_logic import get_leaderboard, get_scores_last_updated, set_display_name, resolve_player
import json
from pathlib import Path
import uuid
from commentator_logic import determine_style, generate_script, generate_audio_from_text
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import time

#Setup constants
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
REDIRECT_URI = "http://127.0.0.1:5000/discord_callback"
DISCORD_AUTH_URL = f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds+bot&permissions=65536&prompt=consent"
GITHUB_AUTH_URL = f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}&scope=repo" 

#Start Flask app
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = "bum2"
app.config['UPLOAD_FOLDER'] = str(Path("static") / "uploads")

# Global state for commentary caching
commentary_history = {}  # {dashboard_id: [list of commentary entries]}
last_generated = {}      # {dashboard_id: timestamp of last generation}
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

    #Get all the servers the bot is in
    bot_servers = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bot {BOT_TOKEN}"}).json()
    if not isinstance(bot_servers, list):
        # Bot token error - clear session and re-login
        return render_template("login.html", step=1, discord_auth_url=DISCORD_AUTH_URL, github_auth_url=GITHUB_AUTH_URL)
    bot_server_ids = set([g["id"] for g in bot_servers])

    #Get all the servers the user is in
    user_servers = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session['discord_access_token']}"}).json()
    if not isinstance(user_servers, list):
        # Token expired or invalid - clear session and re-login
        session.clear()
        return redirect(url_for('index'))

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
    #Get code from Discord callback for handshake
    code = request.args.get('code')
    
    #Perform handshake
    data = {'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}
    r = requests.post("https://discord.com/api/oauth2/token", data=data).json()
    
    #Get new access token
    session['discord_access_token'] = r.get('access_token')
    
    #Get username
    user_data = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {session['discord_access_token']}"}).json()
    session['username'] = user_data.get('username')
    
    return redirect(url_for('index'))

#Github callback page
@app.route('/github_callback')
def github_callback(): 
    #Get code from Github callback for handshake
    code = request.args.get('code')
    
    data = {'client_id': GITHUB_CLIENT_ID, 'client_secret': GITHUB_CLIENT_SECRET, 'code': code}
    r = requests.post("https://github.com/login/oauth/access_token", data=data, headers={'Accept': 'application/json'}).json()
    
    #Get new access token
    session['github_access_token'] = r.get('access_token')
    
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
    discord_data = fetch_all_messages(dashboard_id, discord_headers, last_time)

    project_name = dashboard_id
    try:
        guild_resp = requests.get(
            f"https://discord.com/api/guilds/{dashboard_id}",
            headers=discord_headers,
            timeout=10,
        )
        if guild_resp.ok:
            guild_data = guild_resp.json()
            project_name = guild_data.get("name", dashboard_id)
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
    if now - last_gen > 20:
        discord_headers = {"Authorization": f"Bot {BOT_TOKEN}"}
        github_headers = {"Authorization": f"token {session['github_access_token']}"}
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
if __name__ == '__main__':
    app.run(debug=True, port=5000)