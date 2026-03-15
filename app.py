from flask import Flask, redirect, url_for, session, request, render_template, Response
import os
from dotenv import load_dotenv
load_dotenv(override=True)

import hashlib
import requests
from discord_logic import fetch_all_messages, analyse_sentiment
from commentator.commentator import generate_commentary_audio
from github_logic import get_detailed_github_data
import json
from pathlib import Path
import uuid
from commentator.commentator import determine_style, generate_script, generate_audio_from_text
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
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# Global state for commentary caching
commentary_history = {}  # {dashboard_id: [list of commentary entries]}
last_generated = {}      # {dashboard_id: timestamp of last generation}
last_message_hash = {}   # {dashboard_id: hash of last messages to detect changes}


def collect_discord_events(dashboard_id, github_token=None):
    """
    Fetch Discord messages and GitHub data, transform into events dict for commentator.
    Returns (events_dict, messages_hash) tuple, or (None, None) on failure.
    """
    discord_headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    now = datetime.now()
    last_time = now - timedelta(hours=3)

    # Fetch Discord messages
    discord_messages = fetch_all_messages(dashboard_id, discord_headers, last_time)
    if isinstance(discord_messages, str):  # Error message
        print(f"Discord fetch error: {discord_messages}")
        return None, None

    # Create hash to detect changes
    msg_str = "|".join(f"{m['author']}:{m['content']}:{m['timestamp']}" for m in discord_messages)
    msg_hash = hashlib.md5(msg_str.encode()).hexdigest()

    # Analyze sentiment
    sentiment = analyse_sentiment(discord_messages)
    print(f"Discord analysis — sentiment: {sentiment}, messages: {len(discord_messages)}")

    # Build events dict for commentator
    events = {
        "discord_sentiment": sentiment["overall"],
        "discord_highlights": sentiment["highlights"],
        "discord_spam_count": 0,
        "recent_commits": [],
        "pull_requests_merged": 0,
    }

    # Add GitHub data if token available
    if github_token:
        github_headers = {"Authorization": f"token {github_token}"}
        github_data = get_detailed_github_data("azynm/blahajathon", github_headers, last_time)

        for item in github_data:
            if item["type"] == "commit":
                events["recent_commits"].append({
                    "author": item["author"],
                    "message": item["message"],
                    "branch": "feature",  # Default, could parse from message
                    "lines_changed": 50,  # Placeholder
                })
            elif item["type"] == "merge":
                # Check if merged to main
                events["recent_commits"].append({
                    "author": item["author"],
                    "message": item["message"],
                    "branch": "main" if "main" in item["message"].lower() else "feature",
                    "lines_changed": 100,
                })
            elif item["type"] == "merge_request":
                events["pull_requests_merged"] += 1
                # Check if merged to main branch
                if item.get("target_branch") == "main":
                    events["recent_commits"].append({
                        "author": item["author"],
                        "message": item["title"],
                        "branch": "main",
                        "lines_changed": 100,
                    })

        print(f"GitHub data — commits: {len(events['recent_commits'])}, PRs merged: {events['pull_requests_merged']}")

    # Limit commits to avoid prompt being too long
    events["recent_commits"] = events["recent_commits"][:5]

    return events, msg_hash


def _is_allowed_image(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def _profile_context() -> dict[str, str]:
    username = session.get('username', 'Guest User')
    return {
        "name": session.get('profile_name', username),
        "role": session.get('profile_role', 'Player'),
        "avatar": session.get('profile_picture', ''),
    }

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
    bot_server_ids = set([g["id"] for g in bot_servers])

    #Get all the servers the user is in
    user_servers = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session['discord_access_token']}"}).json()
    
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
    #Setup headers
    discord_headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    github_headers = {"Authorization": f"token {session['github_access_token']}"}
    now = datetime.now()
    last_time = now - timedelta(hours=3)
    
    #Fetch all data
    github_data = get_detailed_github_data("azynm/blahajathon", github_headers, last_time)
    discord_data = fetch_all_messages(dashboard_id, discord_headers, last_time)
    
    print(github_data, discord_data) 
    
    with open('players.json', 'r') as file:
        data = json.load(file)

    return render_template("dashboard.html", players=data)



#Logout page
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'access_token' not in session:
        return redirect(url_for('index'))

    error_message = ""

    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        picture_file = request.files.get('picture_file')

        if display_name:
            session['profile_name'] = display_name

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
            return redirect(url_for('settings', saved='1'))

    saved = request.args.get('saved') == '1'
    return render_template(
        'settings.html',
        current_user=_profile_context(),
        saved=saved,
        error_message=error_message,
    )


@app.route('/api/commentary-history/<dashboard_id>')
def commentary_history_api(dashboard_id):
    """Return list of recent commentary entries (without audio bytes)."""
    now = time.time()
    last_gen = last_generated.get(dashboard_id, 0)

    # Regenerate if >60s since last generation AND messages have changed
    if now - last_gen > 20:
        github_token = session.get('github_access_token')
        events, msg_hash = collect_discord_events(dashboard_id, github_token)

        # Only generate if we got events AND messages have changed
        if events and msg_hash != last_message_hash.get(dashboard_id):
            print(f"DEBUG: Messages changed! Old hash: {last_message_hash.get(dashboard_id)}, New hash: {msg_hash}")
            style = determine_style(events)
            script = generate_script(events, style=style)
            audio = generate_audio_from_text(script, style=style)

            if audio:
                timestamp = time.time()
                entry_id = hashlib.md5(f"{dashboard_id}_{timestamp}".encode()).hexdigest()[:12]

                if dashboard_id not in commentary_history:
                    commentary_history[dashboard_id] = []

                commentary_history[dashboard_id].append({
                    "id": entry_id,
                    "timestamp": timestamp,
                    "style": style,
                    "script": script,
                    "audio": audio
                })
                commentary_history[dashboard_id] = commentary_history[dashboard_id][-10:]
                last_generated[dashboard_id] = timestamp
                last_message_hash[dashboard_id] = msg_hash
        else:
            print(f"DEBUG: No new messages, skipping commentary generation")
            last_generated[dashboard_id] = now  # Update timestamp to prevent checking again immediately

    history = commentary_history.get(dashboard_id, [])
    # Return without audio bytes
    return json.dumps([{
        "id": e["id"],
        "timestamp": e["timestamp"],
        "style": e["style"],
        "script": e["script"]
    } for e in history])


@app.route('/api/commentary/<dashboard_id>/<entry_id>')
def commentary_audio(dashboard_id, entry_id):
    """Serve audio for a specific commentary entry."""
    history = commentary_history.get(dashboard_id, [])
    entry = next((e for e in history if e["id"] == entry_id), None)

    if not entry or not entry.get("audio"):
        return "", 404

    return Response(entry["audio"], mimetype="audio/mpeg")


@app.route('/api/commentary/<dashboard_id>')
def commentary_latest(dashboard_id):
    """Legacy endpoint - redirects to latest entry."""
    history = commentary_history.get(dashboard_id, [])
    if not history:
        return "", 204

    latest = history[-1]
    return Response(latest["audio"], mimetype="audio/mpeg")


#Actually starts web server
if __name__ == '__main__':
    app.run(debug=True, port=5000)