#Logic for discord bot
#calls messagefetcher and proccesses it here

import asyncio
import os
from collections import defaultdict
from dotenv import load_dotenv
import google.generativeai as genai
from messagefetcher import fetch_all

load_dotenv()

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-pro')

SPAM_WINDOW_SECONDS = 10
SPAM_THRESHOLD = 5


# ── Processor ────────────────────────────────────────────────────────────────

def process_messages(raw_messages):
    """
    Takes raw Discord message objects and computes per-user metrics.
    Returns a dict keyed by user ID.
    """
    results = {}
    by_user = defaultdict(list)

    for msg in raw_messages:
        if msg.get('author', {}).get('bot'):
            continue
        by_user[msg['author']['id']].append(msg)

    for user_id, messages in by_user.items():
        results[user_id] = {
            'username': messages[0]['author']['username'],
            'messageCount': len(messages),
            'spamCount': _detect_spam(messages),
            'avgResponseSeconds': _calc_response_times(messages),
            'sentimentTotal': 0.0,
            'positiveMessages': 0,
            'negativeMessages': 0,
        }

    return results


def _snowflake_to_unix(snowflake_id):
    return ((int(snowflake_id) >> 22) + 1420070400000) / 1000


def _detect_spam(messages):
    timestamps = sorted([_snowflake_to_unix(m['id']) for m in messages])
    spam_count = 0
    for i, t in enumerate(timestamps):
        window = [x for x in timestamps if 0 <= x - t < SPAM_WINDOW_SECONDS]
        if len(window) >= SPAM_THRESHOLD:
            spam_count += 1
    return spam_count


def _calc_response_times(messages):
    timestamps = sorted([_snowflake_to_unix(m['id']) for m in messages])
    if len(timestamps) < 2:
        return None
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    return round(sum(gaps) / len(gaps), 2)


# ── Sentiment ─────────────────────────────────────────────────────────────────

async def _score(content):
    prompt = f"""Rate the tone of this message as a number from -2 (very negative) 
to +2 (very positive). Reply with only the number.
Message: \"{content}\""""
    try:
        response = await model.generate_content_async(prompt)
        return float(response.text.strip())
    except (ValueError, Exception):
        return None


async def batch_score(results, raw_messages):
    """
    Score sentiment for every non-bot message and accumulate onto results.
    Also tracks positive/negative message counts separately.
    """
    for msg in raw_messages:
        user_id = msg.get('author', {}).get('id')
        if not user_id or not msg.get('content') or msg.get('author', {}).get('bot'):
            continue
        if user_id not in results:
            continue

        score = await _score(msg['content'])
        if score is None:
            continue

        results[user_id]['sentimentTotal'] += score
        if score > 0:
            results[user_id]['positiveMessages'] += 1
        elif score < 0:
            results[user_id]['negativeMessages'] += 1

    return results


# ── Main ──────────────────────────────────────────────────────────────────────


# print_leaderboard is a placeholder!!!!
def print_leaderboard(results):
    sorted_users = sorted(results.values(), key=lambda u: u['messageCount'], reverse=True)
    print("\n── Leaderboard ──────────────────────────────")
    for i, user in enumerate(sorted_users, 1):
        print(
            f"{i}. {user['username']:<20} "
            f"msgs: {user['messageCount']:<6} "
            f"vibe: {round(user['sentimentTotal'], 1):<6} "
            f"spam: {user['spamCount']:<4} "
            f"avg response: {user['avgResponseSeconds']}s"
        )
    print("─────────────────────────────────────────────\n")


async def main():
    print("Fetching messages...")
    raw = await fetch_all()

    print("Processing metrics...")
    results = process_messages(raw)

    print("Scoring sentiment...")
    results = await batch_score(results, raw)

    print_leaderboard(results)
    return results


if __name__ == '__main__':
    asyncio.run(main())