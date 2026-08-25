import aiosqlite
from config import SEMESTER_START
from datetime import datetime, date


async def init_db():
    async with aiosqlite.connect('bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, 
                             group_name TEXT, 
                             subgroup INTEGER)''')

        await db.execute('''CREATE TABLE IF NOT EXISTS settings 
                            (key TEXT PRIMARY KEY, value TEXT)''')
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('semester_start', ?)", (SEMESTER_START,))

        await db.execute('''CREATE TABLE IF NOT EXISTS schedule 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             group_name TEXT,
                             day TEXT, time TEXT, type TEXT, subject TEXT, 
                             teacher TEXT, room TEXT, subgroup INTEGER,
                             week_parity INTEGER)''')

        # Добавляем таблицу персональных изменений
        await db.execute('''CREATE TABLE IF NOT EXISTS user_overrides 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             user_id INTEGER,
                             override_type TEXT,
                             original_day TEXT,
                             original_time TEXT,
                             original_subject TEXT,
                             week_parity INTEGER,
                             new_day TEXT,
                             new_time TEXT,
                             new_room TEXT,
                             new_teacher TEXT,
                             note TEXT)''')

        await db.commit()


async def set_user_settings(user_id: int, group_name: str, subgroup: int):
    async with aiosqlite.connect('bot.db') as db:
        await db.execute("INSERT OR REPLACE INTO users (user_id, group_name, subgroup) VALUES (?, ?, ?)",
                         (user_id, group_name, subgroup))
        await db.commit()


async def get_user_settings(user_id: int):
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT group_name, subgroup FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row if row else (None, None)


async def get_semester_start():
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'semester_start'") as cursor:
            row = await cursor.fetchone()
            return datetime.strptime(row[0], "%Y-%m-%d").date() if row else None


def get_week_parity(start_date: date) -> int:
    today = date.today()
    if today < start_date:
        return 1
    delta_days = (today - start_date).days
    week_number = delta_days // 7 + 1
    return 1 if week_number % 2 != 0 else 2


async def get_schedule_for_day(group_name: str, day_name: str, subgroup: int, week_parity: int):
    async with aiosqlite.connect('bot.db') as db:
        # Фильтруем по четности недели: показываем либо "обе недели" (0), либо текущую четность
        async with db.execute(
                "SELECT time, type, subject, teacher, room FROM schedule WHERE group_name = ? AND day = ? AND subgroup = ? AND (week_parity = 0 OR week_parity = ?) ORDER BY time",
                (group_name, day_name, subgroup, week_parity)
        ) as cursor:
            return await cursor.fetchall()


async def get_all_groups():
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT DISTINCT group_name FROM schedule ORDER BY group_name") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def add_override(user_id: int, override_type: str, original_day: str, original_time: str,
                       original_subject: str, week_parity: int, **kwargs):
    """Добавляет персональное изменение расписания"""
    async with aiosqlite.connect('bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS user_overrides 
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             user_id INTEGER,
                             override_type TEXT,
                             original_day TEXT,
                             original_time TEXT,
                             original_subject TEXT,
                             week_parity INTEGER,
                             new_day TEXT,
                             new_time TEXT,
                             new_room TEXT,
                             new_teacher TEXT,
                             note TEXT)''')

        await db.execute('''INSERT INTO user_overrides 
                            (user_id, override_type, original_day, original_time, original_subject, 
                             week_parity, new_day, new_time, new_room, new_teacher, note)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                         (user_id, override_type, original_day, original_time, original_subject,
                          week_parity, kwargs.get('new_day'), kwargs.get('new_time'),
                          kwargs.get('new_room'), kwargs.get('new_teacher'), kwargs.get('note')))
        await db.commit()


async def get_overrides(user_id: int):
    """Получает все изменения пользователя"""
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute('''SELECT id, override_type, original_day, original_time, original_subject,
                                        week_parity, new_day, new_time, new_room, new_teacher, note
                                 FROM user_overrides WHERE user_id = ?''', (user_id,)) as cursor:
            return await cursor.fetchall()


async def delete_override(user_id: int, override_id: int):
    """Удаляет изменение"""
    async with aiosqlite.connect('bot.db') as db:
        await db.execute("DELETE FROM user_overrides WHERE user_id = ? AND id = ?", (user_id, override_id))
        await db.commit()

async def clear_all_overrides(user_id: int):
    """Удаляет все персональные изменения пользователя"""
    async with aiosqlite.connect('bot.db') as db:
        await db.execute("DELETE FROM user_overrides WHERE user_id = ?", (user_id,))
        await db.commit()

async def group_exists(group_name: str) -> bool:
    """Проверяет, есть ли уже расписание для этой группы"""
    async with aiosqlite.connect('bot.db') as db:
        async with db.execute("SELECT COUNT(*) FROM schedule WHERE group_name = ?", (group_name,)) as cursor:
            row = await cursor.fetchone()
            return row[0] > 0