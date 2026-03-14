import os
import time
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def fetch_latest_messages(channel_id, headers):
    """Fetch messages from a channel as structured dicts."""
    r = requests.get(f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=20", headers=headers)
    if r.status_code == 200:
        data = r.json()
        return [
            {
                "author": m["author"]["username"],
                "content": m["content"],
                "timestamp": m["timestamp"],
            }
            for m in data
            if m["content"]  # skip empty messages (images-only, embeds, etc.)
        ]
    else:
        print(f"Failed to fetch messages from channel {channel_id}: {r.text}")
        return []


def analyse_sentiment(messages):
    """
    Send a batch of Discord messages to Gemini and get an overall sentiment label.
    Returns one of: "positive", "neutral", "negative", "toxic", "highly toxic"
    """
    if not messages:
        return "neutral"

    conversation = "\n".join(f"{m['author']}: {m['content']}" for m in messages)

    prompt = f"""Classify the overall sentiment of these Discord messages into exactly one of these labels:
positive, neutral, negative, toxic, highly toxic

Messages:
{conversation}

Respond with ONLY the label, nothing else."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            label = data["candidates"][0]["content"]["parts"][0]["text"].strip().lower()
            valid = {"positive", "neutral", "negative", "toxic", "highly toxic"}
            if label in valid:
                return label
            print(f"Gemini returned unexpected sentiment label: {label!r}, defaulting to neutral")
            return "neutral"
        except requests.exceptions.HTTPError:
            if response.status_code == 429:
                wait_time = 5 * (2 ** attempt)
                print(f"Sentiment rate limited (429). Retrying in {wait_time}s (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"Sentiment analysis failed: {response.status_code}")
                break
        except Exception as e:
            print(f"Sentiment analysis failed: {e}")
            break
    return "neutral"
