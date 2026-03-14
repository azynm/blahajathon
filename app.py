from flask import Flask, redirect, url_for, session, request, render_template
import os
import requests
from discord_logic import fetch_latest_messages
import json
from pathlib import Path
import uuid

from werkzeug.utils import secure_filename

#Setup constants
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
REDIRECT_URI = 'http://127.0.0.1:5000/callback'
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
@app.route('/callback')
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



#
@app.route('/dashboard/<dashboard_id>')
def dashboard(dashboard_id):
    #Fetch a list of all channels in the server
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    r = requests.get(f"https://discord.com/api/v10/guilds/{dashboard_id}/channels", headers=headers)
    if r.status_code != 200:
        return f"Error: Could not fetch channels. Is the bot in the server? (Code: {r.status_code})"

    #Filter for text channels and scrape messages
    channels = r.json()
    text_channels = [c for c in channels if c['type'] == 0]
    for c in text_channels:
        print(fetch_latest_messages(c['id'], headers))
    
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


#Actually starts web server
if __name__ == '__main__':
    app.run(debug=True, port=5000)