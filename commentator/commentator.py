import os
import time
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

def generate_script(events: dict) -> str:
    """
    Takes an event dictionary and generates an e-sports style commentary script using Gemini.
    """
    prompt = f"""
    You are an energetic, dramatic, and humorous e-sports/football commentator for a 'DevOps Fantasy League'.
    You are providing live commentary on a software engineering team's recent activities. 
    Here is the latest event data from their GitHub and Discord:
    
    {events}
    
    Write a short, punchy (2-4 sentences max) live commentary reacting to this data.
    Make it sound like FIFA or an intense e-sports match. Mention developer names if available in the data!
    Focus on the "action" (e.g. huge pull requests, toxic discord sentiment, clutch bug fixes).
    Only return the spoken commentary text. Do not include sound effects in brackets or any other formatting.
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

def generate_audio_from_text(text: str) -> bytes:
    """
    Takes the generated text and converts it to audio using ElevenLabs.
    Returns the audio bytes.
    """
    # Adam voice ID: pNInz6obpgDQGcFmaJgB
    voice_id = "pNInz6obpgDQGcFmaJgB"
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
        return response.content
    except Exception as e:
        print(f"Error generating audio: {e}")
        return b""

def generate_commentary_audio(events: dict) -> bytes:
    """
    Main entry point: takes events, generates script via Gemini, and returns audio via ElevenLabs.
    """
    script = generate_script(events)
    print(f"Generated Script:\n{script}\n")
    audio = generate_audio_from_text(script)
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
        with open("test_commentary.mp3", "wb") as f:
            f.write(audio_data)
        print("Success! Saved output to test_commentary.mp3")
    else:
        print("Failed to generate audio.")
