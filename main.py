import asyncio
import uuid

import httpx
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


@app.get("/api/trending")
async def get_trending(genre: str = "all", limit: int = 12):
    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
        # Используем Omni-Search как наиболее стабильный источник данных
        search_query = "Top" if genre == "all" else genre
        session_id = str(uuid.uuid4())

        print(f"Fetching games for query '{search_query}' via Omni-Search...")

        search_resp = await client.get(
            "https://apis.roblox.com/search-api/omni-search",
            params={
                "searchQuery": search_query,
                "sessionId": session_id,
                "pageType": "GameSearchResult",
            },
        )

        if search_resp.status_code != 200:
            print(f"Search error: {search_resp.status_code} - {search_resp.text}")
            return {
                "error": "Failed to fetch from Roblox Search",
                "status": search_resp.status_code,
            }

        search_data = search_resp.json()

        # Извлекаем universeId из результатов поиска
        ids = []
        for section in search_data.get("searchResults", []):
            for item in section.get("contents", []):
                u_id = item.get("universeId")
                if u_id and u_id not in ids:
                    ids.append(u_id)

        ids = ids[:limit]
        print(f"Found {len(ids)} unique universeIds")

        if not ids:
            return []

        # Параллельная сборка деталей и иконок (твоя рабочая схема)
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
            return {"error": "Failed to fetch details", "details": detail_resp.text}

        icons = {
            i["targetId"]: i["imageUrl"] for i in icons_resp.json().get("data", [])
        }

        result = detail_resp.json().get("data", [])
        for g in result:
            g["iconUrl"] = icons.get(g["id"], "")

        return result
