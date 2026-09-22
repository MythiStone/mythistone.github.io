import os
import json
import asyncio
import aiohttp
import aiofiles

# ensure output dir exists
os.makedirs("data/icons", exist_ok=True)

# load derived consumable catalog (written by processConsumables.py)
with open("data/static/consumables.json", "r", encoding="utf-8") as f:
    consumables = json.load(f)

icon_names = {c["icon"] for c in consumables if c.get("icon")}

# Temp weapon enchants (oils/whetstones) are no longer in consumables.json but their
# item icons are still rendered by the "Weapon Enchant" section, so fetch them too.
try:
    with open("data/static/temp-enchants.json", "r", encoding="utf-8") as f:
        temp_enchants = json.load(f)
    icon_names |= {e["icon"] for e in temp_enchants if e.get("icon")}
except (OSError, ValueError):
    pass

SEM_LIMIT = 100  # max concurrent fetches


async def fetch_and_save(session: aiohttp.ClientSession, sem: asyncio.Semaphore, icon: str):
    url = f"https://www.raidbots.com/static/images/icons/56/{icon}.png"
    out_path = os.path.join("data", "icons", f"{icon}.png")
    async with sem:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    async with aiofiles.open(out_path, "wb") as out_f:
                        await out_f.write(content)
                    print(f"Saved {icon}")
                else:
                    print(f"⚠️  Failed to fetch {icon}: HTTP {resp.status}")
        except Exception as e:
            print(f"⚠️  Error fetching {icon}: {e}")


async def main():
    sem = asyncio.Semaphore(SEM_LIMIT)
    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(fetch_and_save(session, sem, icon))
            for icon in icon_names
        ]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
