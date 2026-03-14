# talks to discord's api
# requests messages 

import aiohttp
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

BASE = "https://discord.com/api/v10"
CHANNEL_IDS = os.getenv('CHANNEL_IDS', '').split(',')

def _headers():
    return {"Authorization": f"Bot {os.getenv('DISCORD_TOKEN')}"}

async def fetch_messages(session, channel_id, limit=200):
    """
    Fetch the most recent messages from a channel.
    Paginates until the requested limit is reached or no more messages exist.
    """
    all_messages = []
    before = None

    while len(all_messages) < limit:
        params = {"limit": min(100, limit - len(all_messages))}
        if before:
            params["before"] = before

        async with session.get(
            f"{BASE}/channels/{channel_id}/messages",
            headers=_headers(),
            params=params
        ) as response:

            if response.status == 429:
                data = await response.json()
                retry_after = data.get('retry_after', 1)
                print(f"Rate limited, retrying in {retry_after}s")
                await asyncio.sleep(retry_after)
                continue

            if response.status != 200:
                print(f"Error fetching channel {channel_id}: HTTP {response.status}")
                break

            batch = await response.json()

            if not batch:
                break

            all_messages.extend(batch)

            if len(batch) < 100:
                break

            before = batch[-1]['id']

    return all_messages


async def fetch_all():
    """
    Fetch messages from all channels in CHANNEL_IDS.
    Returns a flat list of raw Discord message objects.
    """
    all_messages = []

    async with aiohttp.ClientSession() as session:
        for channel_id in CHANNEL_IDS:
            channel_id = channel_id.strip()
            if not channel_id:
                continue

            messages = await fetch_messages(session, channel_id)
            print(f"Fetched {len(messages)} messages from channel {channel_id}")
            all_messages.extend(messages)

    return all_messages