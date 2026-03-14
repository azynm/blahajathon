from flask import Flask, redirect, url_for, session, request, render_template
import os
import requests
from discord_logic import fetch_all_messages
from github_logic import get_detailed_github_data
import json
from datetime import datetime, timedelta

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


#Actually starts web server
if __name__ == '__main__':
    app.run(debug=True, port=5000)