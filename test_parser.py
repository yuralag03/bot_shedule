import asyncio
from parser import parse_and_save_schedule
from db import init_db


async def main():
    print("Инициализация базы данных...")
    await init_db()

    print("Запуск парсера...")
    await parse_and_save_schedule('bIPT_252.xlsx', 'бИПТ-252')


if __name__ == "__main__":
    asyncio.run(main())