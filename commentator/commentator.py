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
    "martin_tyler": {
        "voice_id": "xKtsGy3Sb1IXFmCXPB77",
        "description": "Martin Tyler's traditional, factual, play-by-play approach to commentary."
    },
    "peter_drury": {
        "voice_id": "xKtsGy3Sb1IXFmCXPB77", 
        "description": "Peter Drury's style of metaphorical, poetic, and highly dramatic storytelling."
    }
}

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

def generate_commentary_audio(events: dict, style: str = "martin_tyler") -> bytes:
    """
    Main entry point: takes events, generates script via Gemini, and returns audio via ElevenLabs.
    """
    script = generate_script(events, style=style)
    print(f"Generated Script [{style}]:\n{script}\n")
    audio = generate_audio_from_text(script, style=style)
    return audio

if __name__ == "__main__":
    # Test the commentator
    mock_events = {
        "recent_commits": [
            {"author": "Zayn", "message": "fixed the catastrophic memory leak in prod", "lines_changed": 420},
            {"author": "Alex", "message": "typo in readme", "lines_changed": 2}
        ],
        "pull_requests_merged": 1,
        "discord_sentiment": "highly toxic",
        "discord_spam_count": 45
    }
    
    print("Testing Commentator pipeline...")
    audio_data = generate_commentary_audio(mock_events)
    
    if audio_data:
        output_dir = "outputs"
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, "test_commentary.mp3")
        with open(filepath, "wb") as f:
            f.write(audio_data)
        print(f"Success! Saved output to {filepath}")
    else:
        print("Failed to generate audio.")
