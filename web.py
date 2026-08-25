import asyncio
import os
from aiohttp import web
from main import main as bot_main

async def handle(request):
    return web.Response(text="🤖 Бот работает!")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render передаёт порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Веб-сервер запущен на порту {port}")
    # Держим сервер вечно
    while True:
        await asyncio.sleep(3600)

async def main():
    # Запускаем бота и веб-сервер параллельно
    await asyncio.gather(
        bot_main(),
        run_web_server()
    )

if __name__ == "__main__":
    asyncio.run(main())