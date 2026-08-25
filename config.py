import os

# Получаем токен из переменной окружения или используем заглушку
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(os.getenv("ADMIN_ID", "123456789"))]
SEMESTER_START = "2025-09-01"

# КРИТИЧНО: проверяем, что токен получен
if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в переменных окружения!")
    print("💡 Добавьте переменную BOT_TOKEN в настройках Render")
else:
    print(f"✅ BOT_TOKEN получен: длина {len(BOT_TOKEN)}, начинается с {BOT_TOKEN[:10]}...")