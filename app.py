from flask import Flask, redirect, url_for, session, request, render_template, Response
import os
import requests
from discord_logic import fetch_latest_messages, analyse_sentiment
from commentator.commentator import generate_commentary_audio
import json
from pathlib import Path
import uuid

from werkzeug.utils import secure_filename

#Setup constants
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
REDIRECT_URI = 'http://localhost:5000/discord_callback'
DISCORD_AUTH_URL = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds+bot&permissions=65536&prompt=consent"

#Start Flask app
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = "bum"
app.config['UPLOAD_FOLDER'] = str(Path("static") / "uploads")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


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



import time
import hashlib

# Store commentary history per guild (list of dicts with timestamp, style, script, audio)
commentary_history = {}
# Track last generation time per guild
last_generated = {}


def collect_discord_events(dashboard_id):
    """Fetch messages from all text channels in a guild and build a commentator events dict."""
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    r = requests.get(f"https://discord.com/api/v10/guilds/{dashboard_id}/channels", headers=headers)
    if r.status_code != 200:
        return None

    channels = r.json()
    text_channels = [c for c in channels if c["type"] == 0]

    all_messages = []
    for c in text_channels:
        all_messages.extend(fetch_latest_messages(c["id"], headers))

    sentiment = analyse_sentiment(all_messages)
    print(f"Discord analysis — sentiment: {sentiment}")

    return {
        "discord_sentiment": sentiment,
        "discord_spam_count": 0,
        "recent_commits": [],
        "pull_requests_merged": 0,
    }


#Home screen
@app.route('/')
def index():
    #If not logged in, send to login page
    if 'access_token' not in session:
        return render_template("login.html", auth_url=DISCORD_AUTH_URL)

    #Get all the servers the bot is in
    bot_servers = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bot {BOT_TOKEN}"}).json()
    bot_server_ids = set([g["id"] for g in bot_servers])

    #Get all the servers the user is in
    user_servers = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session['access_token']}"}).json()
    
    #Make a list of all servers we can participate in
    servers = []
    for s in user_servers:
        if s["id"] in bot_server_ids:
            s["bot_exists"] = True
            servers.append(s)
        elif int(s['permissions']) & 0x20:
            servers.append(s)
    
    #Show the page
    return render_template(
        "index.html",
        guilds=servers,
        username=session['username'],
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        current_user=_profile_context(),
    )



#Callback page
@app.route('/discord_callback')
def callback():
    #Get code from Discord callback for handshake
    code = request.args.get('code')
    
    #Perform handshake
    data = {'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}
    r = requests.post("https://discord.com/api/oauth2/token", data=data).json()
    
    #Get new access token
    session['access_token'] = r.get('access_token')
    
    #Get username
    user_data = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {session['access_token']}"}).json()
    session['username'] = user_data.get('username')
    
    return redirect(url_for('index'))



#Dashboard
@app.route('/dashboard/<dashboard_id>')
def dashboard(dashboard_id):
    #Fetch a list of all channels in the server
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    r = requests.get(f"https://discord.com/api/v10/guilds/{dashboard_id}/channels", headers=headers)
    if r.status_code != 200:
        return f"Error: Could not fetch channels. Is the bot in the server? (Code: {r.status_code})"

    #Collect Discord events and generate commentary
    events = collect_discord_events(dashboard_id)
    print(f"DEBUG: events = {events}")
    if events:
        from commentator.commentator import determine_style, generate_script, generate_audio_from_text
        print("DEBUG: Starting commentary generation...")
        style = determine_style(events)
        print(f"DEBUG: Style determined = {style}")
        script = generate_script(events, style=style)
        print(f"DEBUG: Script generated = {script[:50]}...")
        audio = generate_audio_from_text(script, style=style)
        print(f"DEBUG: Audio length = {len(audio)} bytes")

        if audio:
            timestamp = time.time()
            entry_id = hashlib.md5(f"{dashboard_id}_{timestamp}".encode()).hexdigest()[:12]

            # Initialize history list if needed
            if dashboard_id not in commentary_history:
                commentary_history[dashboard_id] = []

            # Add to history (keep last 10)
            commentary_history[dashboard_id].append({
                "id": entry_id,
                "timestamp": timestamp,
                "style": style,
                "script": script,
                "audio": audio
            })
            commentary_history[dashboard_id] = commentary_history[dashboard_id][-10:]
            last_generated[dashboard_id] = timestamp
            print(f"DEBUG: Commentary added to history!")

    with open('players.json', 'r') as file:
        data = json.load(file)

    return render_template("dashboard.html", players=data, current_user=_profile_context())


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

    # Regenerate if >60s since last generation
    if now - last_gen > 60:
        events = collect_discord_events(dashboard_id)
        if events:
            from commentator.commentator import determine_style, generate_script, generate_audio_from_text
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