import asyncio
import os
import aiohttp
from aiohttp import web
from main import main as bot_main

APP_URL = os.environ.get("APP_URL", "https://bot-shedule.onrender.com")

async def handle(request):
    return web.Response(text="🤖 Бот работает!")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Веб-сервер запущен на порту {port}")
    while True:
        await asyncio.sleep(3600)

async def keep_alive():
    """Пингует сам себя каждые 10 минут, чтобы Render не усыплял сервис"""
    await asyncio.sleep(60)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(APP_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    print(f"💓 keep-alive ping: {resp.status}")
            except Exception as e:
                print(f"⚠️ keep-alive ping failed: {e}")
            await asyncio.sleep(600)

async def main():
    await asyncio.gather(
        bot_main(),
        run_web_server(),
        keep_alive(),
    )

if __name__ == "__main__":
    asyncio.run(main())