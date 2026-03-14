from flask import Flask, redirect, url_for, session, request, render_template_string
import os
import requests

#Setup constants
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
REDIRECT_URI = 'http://127.0.0.1:5000/callback'
DISCORD_AUTH_URL = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds+bot&permissions=65536&prompt=consent"

#Start Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24) #Remove this line to have persistency

#Home screen
@app.route('/')
def index():
    #If not logged in, send to login page
    if 'access_token' not in session:
        return render_template_string("login.html", auth_url=DISCORD_AUTH_URL, setup_done=False)

    #Get all the servers the bot is in
    bot_servers = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bot {BOT_TOKEN}"}).json()
    bot_server_ids = set([g["id"] for g in bot_servers])

    #Get all the servers the user is in
    user_servers = requests.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session['access_token']}"}).json()
    
    servers = []
    for s in user_servers:
        if s["id"] in bot_server_ids:
            servers.append(s)
        elif int(g['permissions']) & 0x20:
            g['id'] in bot_guild_ids
            managed_guilds.append(g)
            