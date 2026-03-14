import os
import time
import hashlib
import requests
from dotenv import load_dotenv

CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Load environment variables
load_dotenv(override=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

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
    escalates through martin_tyler -> peter_drury -> super_angry.
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
        return "peter_drury"
    return "martin_tyler"


def generate_script(events: dict, style: str = "martin_tyler") -> str:
    """
    Takes an event dictionary and generates an e-sports style commentary script using Gemini.
    """
    prompt = f"""
        You are an energetic, dramatic, and humorous football-esque commentator for a software development group project.
        There is a 'league table' for the workplace where a point system is based off various git and discord related metrics,
        including:
            - Commits
            - Review/approval of merges
                - was the review positive or negative? and did they let a buggy branch get merged?
            - Positive Messages
                - Kind manners, encouragement, general positive vibes
            - Negative Messages
                - Insults, harassment, general negative vibes
            - Inactivity/Activity
                - How active they are in the discord server
            - Response Times
                - How quickly they respond to messages
            - Spam
                - How much they spam in the discord server - avoids statpadding by penalising it
            - Commit Name
                - How explanatory and concise commit names are - do you know what the commit does just from the name?
            - Branch Usage
                - How often they use branches
                - penalise working on main

                

    
    {events}
    
    Your job is to generate a commentary line based on the event(s) that took place matching this specific commentary style:
    {STYLE_MAPPING.get(style, STYLE_MAPPING["martin_tyler"])["description"]}
    
    Focus on the action that occurs and the impact it might have on the league table. Important things are:

    - If it results in a positional change (especially if it is to do with the top spots)
    - Any major fouls (e.g. serious negative language, or mountainous merge conflicts)
    - Any clutch moments (e.g. huge pull requests, or last minute bug fixes)
    - Any moments of brilliance (e.g. perfect commit names, or well-timed positive messages)
    - Any moments of failure (e.g last minute bug fixes)


    Use football-like terminology to describe the events (e.g. 'howler' for big blunders and 'screamers' for insane positive moments)

    Output should be short and snappy - no more than 2 sentences, with a word cap of 40.

    """
    
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
            else:
                print(f"Error generating script: {e}")
                break
        except Exception as e:
            print(f"Error generating script: {e}")
            break
            
    return "Oh, and we're experiencing some technical difficulties down on the pitch! The data feed is down!"

def generate_audio_from_text(text: str, style: str = "martin_tyler") -> bytes:
    """
    Takes the generated text and converts it to audio using ElevenLabs.
    Returns the audio bytes.
    """
    # Enforce a strict character limit to protect your ElevenLabs credits
    if len(text) > 300:
        print(f"Warning: Script too long ({len(text)} chars). Truncating to save credits.")
        text = text[:297] + "..."

    # Lookup the specific voice ID for the requested style
    voice_id = STYLE_MAPPING.get(style, STYLE_MAPPING["martin_tyler"])["voice_id"]

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

if __name__ == "__main__":
    test_scenarios = {
        # Calm game — should resolve to martin_tyler
        "calm": {
            "recent_commits": [
                {"author": "Sophie", "message": "add unit tests for auth module", "lines_changed": 35},
                {"author": "Dan", "message": "update README with setup instructions", "lines_changed": 12}
            ],
            "pull_requests_merged": 2,
            "discord_sentiment": "positive",
            "discord_spam_count": 3
        },
        # Heating up — should resolve to peter_drury (drama 3: toxic sentiment)
        "dramatic": {
            "recent_commits": [
                {"author": "Liam", "message": "refactor payment service into microservice", "lines_changed": 180},
            ],
            "pull_requests_merged": 4,
            "discord_sentiment": "toxic",
            "discord_spam_count": 10,
            "position_change_top3": False,
            "merge_conflicts": 1
        },
        # Drama score blowout — should resolve to super_angry via score (drama 7: toxic + spam + merge conflicts)
        "chaos": {
            "recent_commits": [
                {"author": "Raj", "message": "wip", "lines_changed": 502},
                {"author": "Emily", "message": "idk", "lines_changed": 87}
            ],
            "pull_requests_merged": 0,
            "discord_sentiment": "toxic",
            "discord_spam_count": 55,
            "merge_conflicts": 6,
            "position_change_top3": False
        },
        # Instant red card — committed to main
        "red_card_main": {
            "recent_commits": [
                {"author": "Tom", "message": "quick fix", "lines_changed": 4, "branch": "main"},
            ],
            "pull_requests_merged": 0,
            "discord_sentiment": "neutral",
            "discord_spam_count": 0
        },
        # Instant red card — buggy merge approved
        "red_card_buggy": {
            "recent_commits": [
                {"author": "Priya", "message": "approve merge for release", "lines_changed": 20},
            ],
            "pull_requests_merged": 1,
            "discord_sentiment": "negative",
            "discord_spam_count": 5,
            "buggy_merge_approved": True
        },
    }

    output_dir = "outputs"
    os.makedirs(output_dir, exist_ok=True)

    for name, events in test_scenarios.items():
        style = determine_style(events)
        print(f"\n{'='*50}")
        print(f"Scenario: {name} -> style: {style}")
        print(f"{'='*50}")
        audio_data = generate_commentary_audio(events)

        if audio_data:
            filepath = os.path.join(output_dir, f"test_{name}.mp3")
            with open(filepath, "wb") as f:
                f.write(audio_data)
            print(f"Saved to {filepath}")
        else:
            print("Failed to generate audio.")
