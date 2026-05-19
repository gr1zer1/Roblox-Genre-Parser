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

    # Используем json_normalize для "выпрямления" вложенных структур (например, creator.name станет колонкой creator.name)
    df_new = pd.json_normalize(games)

    # Добавляем временную метку сбора в начало таблицы
    df_new.insert(
        0, "fetch_timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    # Преобразуем списки и словари в строки для совместимости с Excel
    for col in df_new.columns:
        if df_new[col].apply(lambda x: isinstance(x, (list, dict))).any():
            df_new[col] = df_new[col].apply(lambda x: str(x) if x is not None else "")

    if os.path.exists(EXCEL_FILE):
        try:
            df_old = pd.read_excel(EXCEL_FILE)
            # Объединяем, сохраняя все уникальные колонки из обоих наборов данных
            df_combined = pd.concat([df_old, df_new], ignore_index=True, sort=False)
            df_combined.to_excel(EXCEL_FILE, index=False)
        except Exception as e:
            print(f"Error updating Excel: {e}. Creating new file.")
            df_new.to_excel(EXCEL_FILE, index=False)
    else:
        df_new.to_excel(EXCEL_FILE, index=False)

    print(
        f"Saved {len(games)} games with {len(df_new.columns)} detailed fields to {EXCEL_FILE}"
    )


async def background_worker():
    """Фоновая задача, которая циклично обходит разные категории игр"""
    # Список запросов для охвата большего количества разных игр
    search_queries = [
        "Top",
        "Trending",
        "Popular",
        "New",
        "Obby",
        "Tycoon",
        "Simulator",
        "RP",
        "Roleplay",
        "Anime",
        "Horror",
        "Fighting",
    ]

    query_index = 0

    while True:
        current_query = search_queries[query_index]
        print(
            f"[{datetime.datetime.now()}] Switching to search category: {current_query}"
        )

        # Собираем до 100 игр по текущему запросу
        games = await fetch_trending_games(genre=current_query, limit=100)

        if games:
            save_to_excel(games)

        # Переходим к следующему запросу в списке
        query_index = (query_index + 1) % len(search_queries)

        # Ждем 30 минут перед следующим сбором
        # Если хочешь быстрее собрать базу из разных категорий в начале, можно уменьшить время
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_worker())


@app.get("/api/trending")
async def get_trending(genre: str = "all", limit: int = 12):
    return await fetch_trending_games(genre, limit)
