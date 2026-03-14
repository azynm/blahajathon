import os
import requests
from flask import Flask, redirect, url_for, session, request, render_template_string

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- CONFIGURATION ---
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
REDIRECT_URI = 'http://127.0.0.1:5000/callback'

# Added 'bot' and 'permissions=65536' (Read Message History)
AUTH_URL = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds+bot&permissions=65536&prompt=consent"

BASE_HTML = """
<h1>Discord Scraper Panel</h1>
{% if not setup_done %}
    <a href="{{ auth_url }}"><button style="padding:10px 20px;">Step 1: Link Discord & Add Bot</button></a>
{% else %}
    <h3>Welcome, {{ username }}!</h3>
    <p>Manage your servers below:</p>
    <ul>
    {% for guild in guilds %}
        <li>
            <b>{{ guild.name }}</b> 
            {% if guild.bot_exists %}
                ✅ <a href="/select_guild/{{ guild.id }}">Select Server</a>
            {% else %}
                ❌ <a href="https://discord.com/api/oauth2/authorize?client_id={{ client_id }}&scope=bot&permissions=65536&guild_id={{ guild.id }}&disable_guild_select=true&redirect_uri={{ redirect_uri }}&response_type=code">
                    <button>Add Bot to this Server</button>
                </a>
            {% endif %}
        </li>
    {% endfor %}
    </ul>
    <hr>
    <a href="/">Reset Session</a>
{% endif %}
"""

@app.route('/')
def index():
    if 'access_token' not in session:
        return render_template_string(BASE_HTML, auth_url=AUTH_URL, setup_done=False)
    
    # 1. Get User's Guilds
    user_guilds = requests.get("https://discord.com/api/users/@me/guilds", 
                               headers={"Authorization": f"Bearer {session['access_token']}"}).json()
    
    # 2. Get Bot's Guilds
    bot_guilds = requests.get("https://discord.com/api/users/@me/guilds", 
                               headers={"Authorization": f"Bot {BOT_TOKEN}"}).json()
    bot_guild_ids = [g['id'] for g in bot_guilds]

    # 3. Filter for servers where user has 'Manage Server' (0x20)
    managed_guilds = []
    for g in user_guilds:
        if int(g['permissions']) & 0x20:
            g['bot_exists'] = g['id'] in bot_guild_ids
            managed_guilds.append(g)

    return render_template_string(BASE_HTML, guilds=managed_guilds, username=session['username'], 
                                 setup_done=True, client_id=CLIENT_ID, redirect_uri=REDIRECT_URI)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    # If the user just added the bot, Discord might include ?guild_id=...
    # We can ignore it for now as our 'index' check will handle it.
    
    data = {
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI
    }
    r = requests.post("https://discord.com/api/oauth2/token", data=data).json()
    session['access_token'] = r.get('access_token')
    
    user_data = requests.get("https://discord.com/api/users/@me", 
                             headers={"Authorization": f"Bearer {session['access_token']}"}).json()
    session['username'] = user_data.get('username')
    
    return redirect(url_for('index'))

@app.route('/select_guild/<guild_id>')
def select_guild(guild_id):
    """Fetches text channels for the chosen server so the user can pick one."""
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    # Get all channels in the guild
    r = requests.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=headers)
    
    if r.status_code != 200:
        return f"Error: Could not fetch channels. Is the bot in the server? (Code: {r.status_code})"

    channels = r.json()
    # Filter for Text Channels only (Type 0)
    text_channels = [c for c in channels if c['type'] == 0]

    # Simple HTML to display the channels
    html = "<h3>Select a Channel to Scrape:</h3><ul>"
    for chan in text_channels:
        html += f'<li><a href="/fetch/{chan["id"]}">{chan["name"]}</a></li>'
    html += '</ul><br><a href="/">Back to Server List</a>'
    
    return html

@app.route('/fetch/<channel_id>')
def fetch_messages(channel_id):
    """The final step: fetches the messages from the selected channel."""
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    # Limit to 20 messages for a quick view
    r = requests.get(f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=20", headers=headers)
    
    if r.status_code == 200:
        data = r.json()
        messages = [f"<b>{m['author']['username']}</b>: {m['content']}" for m in data]
        
        output = f"<h3>Recent Messages in <small>{channel_id}</small></h3>"
        output += "<ul>" + "".join([f"<li>{m}</li>" for m in messages]) + "</ul>"
        output += '<br><a href="/">Start Over</a>'
        return output
    else:
        return f"Failed to fetch messages. Error: {r.text}"

if __name__ == '__main__':
    app.run(debug=True)