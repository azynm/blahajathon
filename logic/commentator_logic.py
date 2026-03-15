import os
import time
import hashlib
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time
from logic.github_logic import get_detailed_github_data
from logic.discord_logic import fetch_all_messages, analyse_sentiment, read_storage, update_storage
from logic.scoring_logic import update_scores

CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Load environment variables
load_dotenv(override=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

# Username to display name mapping for commentary
USERNAME_MAP = {
    "azynm": "Zayn",
    "zayn": "Zayn",
    "lackshaj": "Lacksha",
    "lacksha.": "Lacksha",
    "aadideepchand20": "Aadi",
    "aadi deepchand": "Aadi",
    "sophacode": "Sophia",
    "soph.advinc": "Sophia",
    "soupdewoop": "Sophia",
}

# Pre-defined styles mapping a descriptor to a specific ElevenLabs voice ID
# Adam (pNInz6obpgDQGcFmaJgB) gives a deep, dramatic play-by-play feel (Tyler)
# Brian (nPczCjzI2devNBz1zQrb) is often used for dramatic, poetic storytelling (Drury)
STYLE_MAPPING = {
    "calm": {
        "voice_id": "15BYGLy7C839syL1CSTP",
        "description": "Martin Tyler's traditional, factual, play-by-play approach to commentary."
    },
    "poetic": {
        "voice_id": "xKtsGy3Sb1IXFmCXPB77", 
        "description": "Peter Drury's style of metaphorical, poetic, and highly dramatic storytelling."
    },
    "super_angry": {
        "voice_id": "EFMtHCoh8D21fdE8gAo3", 
        "description": "A very angry commentator who is "
    }
}

def determine_style(events: dict) -> str:
    """
    Determines commentary style based on event severity.
    Some events are instant triggers for super_angry, otherwise a drama score
    escalates through calm -> poetic -> super_angry.
    """
    # Instant red cards — always trigger super_angry
    if events.get("discord_sentiment") in ("highly toxic",):
        return "super_angry"
    if any(c.get("branch", "") == "main" for c in events.get("recent_commits", [])):
        return "super_angry"
    if events.get("buggy_merge_approved"):
        return "super_angry"

    # Drama score for gradual escalation
    drama = 0
    if events.get("discord_sentiment") == "toxic":
        drama += 3
    if events.get("discord_sentiment") == "negative":
        drama += 1
    if events.get("discord_spam_count", 0) > 30:
        drama += 2
    if events.get("merge_conflicts", 0) > 3:
        drama += 2
    if any(c.get("lines_changed", 0) > 300 for c in events.get("recent_commits", [])):
        drama += 1
    if events.get("position_change_top3"):
        drama += 2

    if drama >= 4:
        return "super_angry"
    if drama >= 2:
        return "poetic"
    return "calm"

def generate_script(events: dict, style: str = "calm") -> str:
    """
    Takes an event dictionary and generates an e-sports style commentary script using Gemini.
    """
    # Build highlights section if available, sanitizing offensive content
    highlights = events.get("discord_highlights", [])
    highlights_text = ""
    if highlights:
        # Sanitize highlights - remove actual slurs/threats, keep the structure
        sanitized = []
        for h in highlights:
            cleaned = h.replace("KILL YOURSELF", "[sent threats to]")
            cleaned = cleaned.replace("kill yourself", "[sent threats to]")
            cleaned = cleaned.replace("GO KILL URSELF", "[sent threats to]")
            cleaned = cleaned.replace("kill myself", "[made concerning statements]")
            cleaned = cleaned.replace("PAKI", "[used slurs against]")
            cleaned = cleaned.replace("death threats", "serious insults")
            # Replace raw usernames with display names
            for username, display_name in USERNAME_MAP.items():
                cleaned = cleaned.replace(username, display_name)
            sanitized.append(cleaned)
        highlights_text = "\n\nNOTABLE MOMENTS (describe dramatically but keep it broadcast-safe):\n" + "\n".join(f"- {h}" for h in sanitized)

    # Build commit info with real names
    commits = events.get("recent_commits", [])
    commit_lines = []
    for c in commits:
        author = USERNAME_MAP.get(c.get("author", ""), c.get("author", "unknown"))
        commit_lines.append(f"{author}: {c.get('message', '')}")
    commits_text = ""
    if commit_lines:
        commits_text = "\n\nRECENT COMMITS:\n" + "\n".join(f"- {line}" for line in commit_lines[:5])

    # Team roster for Gemini to use
    team_text = "\n\nTEAM MEMBERS: Zayn, Lacksha, Aadi, Sophia. Use ONLY these names."

    prompt = f"""You are an energetic, dramatic football commentator for a software development team's league table.

CURRENT SITUATION:
- Discord mood: {events.get('discord_sentiment', 'neutral')}
- Recent commits: {len(events.get('recent_commits', []))}
- PRs merged: {events.get('pull_requests_merged', 0)}{highlights_text}{commits_text}{team_text}

COMMENTARY STYLE: {STYLE_MAPPING.get(style, STYLE_MAPPING["calm"])["description"]}

CRITICAL RULES:
1. Mention people BY NAME using ONLY the names from TEAM MEMBERS above. Do NOT invent names.
2. Use mannerisms of football commentators but in places where they would say football terms, use appropriate discord/git terminology
3. Match the energy to the style - calm is measured, poetic is flowery, super_angry is EXPLOSIVE

Output: 1-2 sentences, max 40 words. No asterisks or markdown."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            text = data['candidates'][0]['content']['parts'][0]['text']
            return text.strip()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                wait_time = 5 * (2 ** attempt)  # 5s, 10s, 20s
                print(f"Rate limited (429). Retrying in {wait_time} seconds (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            elif response.status_code == 400:
                # Content blocked by safety filters - return dramatic fallback
                print(f"Content blocked by safety filters, using fallback")
                sentiment = events.get('discord_sentiment', 'neutral')
                if sentiment in ('toxic', 'highly toxic'):
                    return "ABSOLUTE CHAOS! Ugly scenes in the Discord channel - multiple red cards being shown! The referee has completely lost control of this match!"
                else:
                    return "Some heated exchanges in the team chat today. The manager will want to have words about that."
            else:
                print(f"Error generating script: {e}")
                break
        except Exception as e:
            print(f"Error generating script: {e}")
            break

    return "Oh, and we're experiencing some technical difficulties down on the pitch! The data feed is down!"

def generate_audio_from_text(text: str, style: str = "calm") -> bytes:
    """
    Takes the generated text and converts it to audio using ElevenLabs.
    Returns the audio bytes.
    """
    # Enforce a strict character limit to protect your ElevenLabs credits
    if len(text) > 300:
        print(f"Warning: Script too long ({len(text)} chars). Truncating to save credits.")
        text = text[:297] + "..."

    # Lookup the specific voice ID for the requested style
    voice_id = STYLE_MAPPING.get(style, STYLE_MAPPING["calm"])["voice_id"]

    # Check local cache before making API call
    # Include voice_id in hash so changing the ID triggers a recount
    text_hash = hashlib.md5(f"{voice_id}_{text}".encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{text_hash}.mp3")
    
    if os.path.exists(cache_path):
        print("Audio found in cache! Skipping ElevenLabs API call.")
        with open(cache_path, "rb") as f:
            return f.read()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        # Save to cache
        audio_data = response.content
        with open(cache_path, "wb") as f:
            f.write(audio_data)
            
        return audio_data
    except Exception as e:
        print(f"Error generating audio: {e}")
        return b""

def generate_commentary_audio(events: dict, style: str = None) -> bytes:
    """
    Main entry point: takes events, generates script via Gemini, and returns audio via ElevenLabs.
    Style is auto-determined from events if not provided.
    """
    if style is None:
        style = determine_style(events)
    script = generate_script(events, style=style)
    print(f"Generated Script [{style}]:\n{script}\n")
    audio = generate_audio_from_text(script, style=style)
    return audio

def collect_events(dashboard_id, discord_headers, github_headers, repo_name):
    now = datetime.now()
    last_time = now - timedelta(seconds=120)
    last_time_git = now - timedelta(seconds=120)    

    discord_messages = fetch_all_messages(dashboard_id, discord_headers, last_time)
    github_data = get_detailed_github_data(repo_name, github_headers, last_time_git)
    
    print(github_data)

    #Checks if there are new updates
    if len(discord_messages) > 0 or len(github_data) > 0:
        sentiment = analyse_sentiment(discord_messages)
    
        # Build events dict for commentator
        events = {
            "discord_sentiment": sentiment["overall"],
            "discord_highlights": sentiment["highlights"],
            "discord_spam_count": 0,
            "recent_commits": [],
            "pull_requests_merged": 0,
        }
        
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
        update_scores(discord_messages, sentiment, github_data)

        return events
    else:
        return None