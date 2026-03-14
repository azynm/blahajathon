#Logic for discord bot
#calls messagefetcher and proccesses it here
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

CHANNEL_ID = os.getenv('CHANNEL_ID')
TOKEN = os.getenv('DISCORD_TOKEN')

async def main():
    headers = {"Authorization": f"Bot {TOKEN}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages",
            headers=headers,
            params={"limit": 100}
        ) as response:
            data = await response.json()
            for msg in data:
                if msg['type'] != 0:  # skip system messages
                    continue
                print(f"[{msg['timestamp']}] {msg['author']['username']}: {msg['content']}")
             # see what Discord is actually returning

if __name__ == '__main__':
    asyncio.run(main())