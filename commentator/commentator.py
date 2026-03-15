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
            sanitized.append(cleaned)
        highlights_text = "\n\nNOTABLE MOMENTS (describe dramatically but keep it broadcast-safe):\n" + "\n".join(f"- {h}" for h in sanitized)

    prompt = f"""You are an energetic, dramatic football commentator for a software development team's league table.

CURRENT SITUATION:
- Discord mood: {events.get('discord_sentiment', 'neutral')}
- Recent commits: {len(events.get('recent_commits', []))}
- PRs merged: {events.get('pull_requests_merged', 0)}{highlights_text}

COMMENTARY STYLE: {STYLE_MAPPING.get(style, STYLE_MAPPING["calm"])["description"]}

CRITICAL RULES:
1. Mention people BY NAME and describe the drama in broadcast-safe football terms
2. Use football terms: howler, screamer, red card, yellow card, own goal, sending off, VAR check, ugly scenes
3. Match the energy to the style - calm is measured, poetic is flowery, super_angry is EXPLOSIVE
4. For toxic content, use phrases like "ugly scenes", "lost their head", "seeing red", "straight red card offense"

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

if __name__ == "__main__":
    test_scenarios = {
        # Calm game — should resolve to calm
        "calm": {
            "recent_commits": [
                {"author": "Sophie", "message": "add unit tests for auth module", "lines_changed": 35},
                {"author": "Dan", "message": "update README with setup instructions", "lines_changed": 12}
            ],
            "pull_requests_merged": 2,
            "discord_sentiment": "positive",
            "discord_spam_count": 3
        },
        # Heating up — should resolve to poetic (drama 3: toxic sentiment)
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
