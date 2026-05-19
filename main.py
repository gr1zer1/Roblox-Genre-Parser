import asyncio
import datetime
import os
import uuid

import httpx
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

EXCEL_FILE = "roblox_trends.xlsx"


async def fetch_trending_games(genre: str = "all", limit: int = 12):
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
        search_query = "Top" if genre == "all" else genre
        session_id = str(uuid.uuid4())

        print(
            f"[{datetime.datetime.now()}] Fetching games for query '{search_query}'..."
        )

        try:
            search_resp = await client.get(
                "https://apis.roblox.com/search-api/omni-search",
                params={
                    "searchQuery": search_query,
                    "sessionId": session_id,
                    "pageType": "GameSearchResult",
                },
            )

            if search_resp.status_code != 200:
                print(f"Search error: {search_resp.status_code}")
                return []

            search_data = search_resp.json()
            ids = []
            for section in search_data.get("searchResults", []):
                for item in section.get("contents", []):
                    u_id = item.get("universeId")
                    if u_id and u_id not in ids:
                        ids.append(u_id)

            ids = ids[:limit]
            if not ids:
                return []

            detail_resp, icons_resp = await asyncio.gather(
                client.get(
                    "https://games.roblox.com/v1/games",
                    params={"universeIds": ",".join(map(str, ids))},
                ),
                client.get(
                    "https://thumbnails.roblox.com/v1/games/icons",
                    params={
                        "universeIds": ",".join(map(str, ids)),
                        "size": "150x150",
                        "format": "Png",
                        "returnPolicy": "PlaceHolder",
                    },
                ),
            )

            if detail_resp.status_code != 200 or icons_resp.status_code != 200:
                return []

            icons = {
                i["targetId"]: i["imageUrl"] for i in icons_resp.json().get("data", [])
            }

            result = detail_resp.json().get("data", [])
            for g in result:
                g["iconUrl"] = icons.get(g["id"], "")

            return result
        except Exception as e:
            print(f"Error during fetch: {e}")
            return []


def save_to_excel(games):
    if not games:
        return

    df_new = pd.DataFrame(games)
    # Добавляем временную метку
    df_new["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Выбираем нужные колонки для удобства
    columns = [
        "timestamp",
        "name",
        "playing",
        "visits",
        "favoritedCount",
        "id",
        "creator",
    ]
    # Не все колонки могут быть в ответе, фильтруем существующие
    df_new = df_new[[c for c in columns if c in df_new.columns]]

    if os.path.exists(EXCEL_FILE):
        df_old = pd.read_excel(EXCEL_FILE)
        df_combined = pd.concat([df_old, df_new], ignore_index=True)
        df_combined.to_excel(EXCEL_FILE, index=False)
    else:
        df_new.to_excel(EXCEL_FILE, index=False)

    print(f"Saved {len(games)} games to {EXCEL_FILE}")


async def background_worker():
    """Фоновая задача, которая запускается раз в 30 минут"""
    while True:
        games = await fetch_trending_games(limit=50)  # Собираем побольше для истории
        save_to_excel(games)
        await asyncio.sleep(60)  # 1800 секунд = 30 минут


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_worker())


@app.get("/api/trending")
async def get_trending(genre: str = "all", limit: int = 12):
    return await fetch_trending_games(genre, limit)
