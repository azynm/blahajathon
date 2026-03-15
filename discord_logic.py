import os
from dotenv import load_dotenv
load_dotenv(override=True)

import time
import json
import requests
from datetime import datetime, timedelta

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
channels = 0

def fetch_all_messages(dashboard_id, headers, last_time):
    global channels
    #Fetch a list of all channels in the server
    if channels == 0:
        r = requests.get(f"https://discord.com/api/v10/guilds/{dashboard_id}/channels", headers=headers)
        if r.status_code != 200:
            return f"Error: Could not fetch channels. Is the bot in the server? (Code: {r.status_code})"

        #Filter for text channels and scrape messages
        channels = r.json()
    
    text_channels = [c for c in channels if c['type'] == 0 and c.get('name', '').lower() != 'keys']
    out = []
    for c in text_channels:
        out.extend(fetch_latest_messages(c['id'], headers, last_time))
        time.sleep(0.5)  # Rate limit protection: 500ms between channels

    return out

def fetch_latest_messages(channel_id, headers, since_datetime):
    #Get snowflake for most recent time
    after_id = datetime_to_snowflake(since_datetime)    
    all_messages = []
    
    #Loops to get 100 messages at a time
    while True:
        #Fetch latest messages from a channel
        r = requests.get(f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=100&after={after_id}", headers=headers)
        if r.status_code == 429:
            time.sleep(r.json().get('retry_after', 1))
            continue
        
        #Format data
        data = r.json()
        if not data:
            break 
        for m in data:
            all_messages.append({
                "author": m['author']['username'],
                "content": m['content'],
                "timestamp": m['timestamp'],
                "reactions": m.get('reactions', [])
            })

        #If this is the last page, break loop
        if len(data) < 100:
            break

        #Prepare for next loop
        after_id = data[0]['id'] 

    return all_messages
    
#Converts python datetime to snowflake
def datetime_to_snowflake(dt_obj):
    discord_epoch = 1420070400000
    timestamp_ms = int(dt_obj.timestamp() * 1000)
    snowflake = (timestamp_ms - discord_epoch) << 22
    return snowflake

def analyse_sentiment(messages):
    """
    Send a batch of Discord messages to Gemini and get detailed sentiment analysis.
    Returns a dict with:
      - overall: one of "positive", "neutral", "negative", "toxic", "highly toxic"
      - highlights: list of notable moments with person names and what they did
    """
    if not messages:
        return {"overall": "neutral", "highlights": []}

    conversation = "\n".join(f"{m['author']}: {m['content']} - {m['reactions']}" for m in messages)

    prompt = f"""Analyze these Discord messages from a software development team.

Messages:
{conversation}

Respond in this EXACT JSON format (no markdown, no code blocks):
{{"overall": "LABEL", "highlights": ["highlight1", "highlight2"]}}

Where:
- LABEL is exactly one of: positive, neutral, negative, toxic, highly toxic
- highlights is a list of 1-3 notable moments that a sports commentator would call out. Be SPECIFIC about WHO did what. Examples:
  - "Dave insulted Mike's code review skills"
  - "Sarah encouraged the team after a bug was found"
  - "Tom went on an angry rant about merge conflicts"
  - "Everyone is being supportive and productive"

If nothing notable happened, use an empty list for highlights."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

            # Strip markdown code blocks if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(text)

            valid = {"positive", "neutral", "negative", "toxic", "highly toxic"}
            overall = result.get("overall", "neutral").lower()
            if overall not in valid:
                overall = "neutral"

            return {
                "overall": overall,
                "highlights": result.get("highlights", [])
            }
        except requests.exceptions.HTTPError:
            if response.status_code == 429:
                wait_time = 5 * (2 ** attempt)
                print(f"Sentiment rate limited (429). Retrying in {wait_time}s (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"Sentiment analysis failed: {response.status_code} - {response.text[:500]}")
                break
        except Exception as e:
            print(f"Sentiment analysis failed: {e}")
            break
    return {"overall": "neutral", "highlights": []}

def get_repo_name(guild_id, discord_headers):
    global channels
    if channels == 0:
        r = requests.get(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=discord_headers)
        if r.status_code == 429:
            time.sleep(r.json().get('retry_after', 1))
            return get_repo_name(guild_id, discord_headers)
        if r.status_code != 200:
            return f"Error: Could not fetch channels. Is the bot in the server? (Code: {r.status_code})"

        #Filter for text channels and scrape messages
        channels = r.json()


    config_channel = next((c for c in channels if c['name'] == 'bot-internal-config'), None)

    if config_channel:
        # Fetch the first message in that channel
        msg_resp = requests.get(f"https://discord.com/api/v10/channels/{config_channel['id']}/messages?limit=1", headers=discord_headers)
        if msg_resp.status_code == 429:
            time.sleep(msg_resp.json().get('retry_after', 1))
            return get_repo_name(guild_id, discord_headers)
        messages = msg_resp.json()
        if messages:
            return messages[0]['content']
    else:
        return None
    
def create_storage_channel(guild_id, repo_name, discord_headers):
    global channels
    create_payload = {
            "name": "bot-internal-config",
            "type": 0,
            "permission_overwrites": [
                {"id": guild_id, "type": 0, "deny": "1024"} # Deny View Channel for @everyone (1024 is VIEW_CHANNEL)
            ]
        }
    new_chan = requests.post(f"https://discord.com/api/v10/guilds/{guild_id}/channels", headers=discord_headers, json=create_payload).json()
    
    if 'id' in new_chan:
        # Success! Save the data.
        requests.post(f"https://discord.com/api/v10/channels/{new_chan['id']}/messages", 
                        headers=discord_headers, json={"content": repo_name})
        return repo_name
    else:
        # Failure! Log the error so you can see it in your terminal
        print(f"Failed to create channel in {guild_id}. Response: {new_chan}")
        return None
