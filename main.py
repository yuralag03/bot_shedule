import asyncio
import os
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from config import BOT_TOKEN, ADMIN_IDS
from db import (init_db, set_user_settings, get_user_settings, get_semester_start,
                get_week_parity, get_schedule_for_day, get_all_groups,
                add_override, get_overrides, delete_override, clear_all_overrides, group_exists)
from parser import parse_and_save_schedule
from states import UploadSchedule, EditLesson

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

DAYS_MAP = {0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}
WEEK_DAYS_ORDER = [0, 1, 2, 3, 4, 5]

print(f"🔑 BOT_TOKEN loaded: {len(BOT_TOKEN)} chars")
print(f"🔑 Token starts with: {BOT_TOKEN[:10]}...")

# ==================== START & MAIN MENU ====================
@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await show_main_menu(message, edit=False)


async def show_main_menu(target: types.Message, edit: bool = False):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="today"),
         InlineKeyboardButton(text="📆 Завтра", callback_data="tomorrow")],
        [InlineKeyboardButton(text="🗓 На неделю", callback_data="week:0"),
         InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")]
    ])
    text = "Главное меню. Выберите действие:"
    if edit:
        try:
            await target.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            pass
    else:
        await target.answer(text, reply_markup=kb)


# ==================== SCHEDULE VIEWING ====================
@router.callback_query(F.data.in_(["today", "tomorrow"]))
async def process_day_schedule(callback: types.CallbackQuery):
    group_name, subgroup = await get_user_settings(callback.from_user.id)
    if not group_name or not subgroup:
        await callback.answer("Сначала выберите группу и подгруппу в Настройках ⚙️", show_alert=True)
        return

    start_date = await get_semester_start()
    today = datetime.today().weekday()

    if callback.data == "today":
        day_idx = today if today < 6 else 0
    else:
        day_idx = (today + 1) % 7
        if day_idx == 6: day_idx = 0

    day_name = DAYS_MAP[day_idx]
    parity = get_week_parity(start_date)
    parity_text = "Числитель (нечётная)" if parity == 1 else "Знаменатель (чётная)"

    await show_day_schedule(callback.message, day_name, group_name, subgroup, parity_text, parity,
                            callback.from_user.id)


@router.callback_query(F.data.startswith("week:"))
async def process_week_schedule(callback: types.CallbackQuery):
    group_name, subgroup = await get_user_settings(callback.from_user.id)
    if not group_name or not subgroup:
        await callback.answer("Сначала выберите группу и подгруппу в Настройках ⚙️", show_alert=True)
        return

    week_offset = int(callback.data.split(":")[1])
    await show_week_schedule(callback.message, group_name, subgroup, week_offset, callback.from_user.id)


@router.callback_query(F.data.in_(["today", "tomorrow"]))
async def process_day_schedule(callback: types.CallbackQuery):
    # Сразу снимаем "нагрузку" с кнопки, чтобы она перестала крутиться
    await callback.answer()

    group_name, subgroup = await get_user_settings(callback.from_user.id)
    if not group_name or not subgroup:
        await callback.answer("Сначала выберите группу и подгруппу в Настройках ⚙️", show_alert=True)
        return

    start_date = await get_semester_start()
    today = datetime.today().weekday()

    if callback.data == "today":
        # Если сегодня воскресенье (6), показываем понедельник (0)
        day_idx = today if today < 6 else 0
    else:  # tomorrow
        day_idx = (today + 1) % 7
        # Если завтра воскресенье (6), перескакиваем на понедельник (0)
        if day_idx == 6:
            day_idx = 0

    day_name = DAYS_MAP[day_idx]
    parity = get_week_parity(start_date)
    parity_text = "Числитель (нечётная)" if parity == 1 else "Знаменатель (чётная)"

    await show_day_schedule(callback.message, day_name, group_name, subgroup, parity_text, parity,
                            callback.from_user.id)


async def show_day_schedule(message: types.Message, day_name: str, group_name: str, subgroup: int, parity_text: str, parity: int, user_id: int, edit: bool = True):
    lessons = await get_schedule_for_day(group_name, day_name, subgroup, parity)
    overrides = await get_overrides(user_id)

    lessons_with_notes = _apply_overrides_to_lessons_with_notes(lessons, overrides, day_name, parity)

    day_idx = next((k for k, v in DAYS_MAP.items() if v == day_name), 0)

    header = f"📅 <b>{day_name}</b> ({parity_text})\n🏫 Группа: {group_name} | 👥 Подгруппа: {subgroup}\n\n"
    kb_buttons = [[InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")]]

    if not lessons_with_notes:
        text = header + "🎉 <b>Пар нет!</b> Можно выдыхать."
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    else:
        text = header
        buttons = []
        for i, lesson_data in enumerate(lessons_with_notes, 1):
            time_str, l_type, subject, teacher, room, note = lesson_data
            time_clean = _format_time(time_str)
            text += (f"<b>{i}.</b> <code>{time_clean}</code>\n"
                     f"📚 <i>{l_type}</i>: <b>{subject}</b>\n"
                     f"👨‍🏫 {teacher}\n"
                     f"🚪 Ауд. {room}\n")
            if note:
                text += f"📝 <i>{note}</i>\n"
            text += "\n"
            buttons.append([InlineKeyboardButton(text=f"✏️ {i}. {subject[:20]}", callback_data=f"edit:{day_idx}:{i}:{parity}")])

        buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    if edit:
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                print(f"⚠️ Ошибка редактирования сообщения: {e}")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

async def show_week_schedule(message: types.Message, group_name: str, subgroup: int, week_offset: int, user_id: int):
    start_date = await get_semester_start()

    today = datetime.today().date()
    delta_days = (today - start_date).days
    current_week_number = delta_days // 7 + 1
    target_week_number = current_week_number + week_offset

    parity = 1 if target_week_number % 2 != 0 else 2
    parity_text = "Числитель (нечётная)" if parity == 1 else "Знаменатель (чётная)"

    overrides = await get_overrides(user_id)

    header = f"🗓 <b>Расписание на неделю</b> ({parity_text})\n🏫 Группа: {group_name} | 👥 Подгруппа: {subgroup}\n\n"

    full_text = header
    has_any_lessons = False

    for day_idx in WEEK_DAYS_ORDER:
        day_name = DAYS_MAP[day_idx]
        lessons = await get_schedule_for_day(group_name, day_name, subgroup, parity)
        lessons = _apply_overrides_to_lessons_with_notes(lessons, overrides, day_name, parity)

        if lessons:
            has_any_lessons = True
            full_text += f"📅 <b>{day_name}</b>\n"
            for i, lesson in enumerate(lessons, 1):
                time_str, l_type, subject, teacher, room = lesson
                time_clean = _format_time(time_str)
                full_text += (f"  <b>{i}.</b> <code>{time_clean}</code>\n"
                              f"     📚 <i>{l_type}</i>: <b>{subject}</b>\n"
                              f"     👨‍🏫 {teacher}\n"
                              f"     🚪 Ауд. {room}\n")
            full_text += "\n"

    if not has_any_lessons:
        full_text += "🎉 <b>На этой неделе пар нет!</b> Можно выдыхать."

    nav_buttons = [
        InlineKeyboardButton(text="⬅️ Пред. неделя", callback_data=f"week:{week_offset - 1}"),
        InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu"),
        InlineKeyboardButton(text="След. неделя ➡️", callback_data=f"week:{week_offset + 1}")
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=[nav_buttons])

    try:
        await message.edit_text(full_text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass

def _subjects_match(subj1, subj2):
    """Проверяет, совпадают ли предметы, игнорируя переносы строк, пробелы и регистр"""
    if not subj1 or not subj2:
        return False

    # Очищаем строки: убираем переносы, лишние пробелы, приводим к нижнему регистру
    clean1 = ' '.join(str(subj1).strip().split()).lower()
    clean2 = ' '.join(str(subj2).strip().split()).lower()

    return clean1 == clean2

def _norm_part(t: str) -> str:
    """'12' → '12:00', '8:30' → '08:30', '12:00:00' → '12:00'"""
    t = str(t or '').strip()
    m = re.fullmatch(r'(\d{1,2}):(\d{2})(?::\d{2})?', t)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.fullmatch(r'(\d{1,2})', t)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return t

def _format_time(time_str) -> str:
    s = str(time_str or '')
    if ' - ' in s:
        a, b = s.split(' - ', 1)
        return f"{_norm_part(a)} - {_norm_part(b)}"
    return _norm_part(s)

def _time_to_minutes(t) -> int:
    m = re.match(r'(\d{1,2}):(\d{2})', _norm_part(t))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 9999

def _sort_lessons(lessons):
    return sorted(lessons, key=lambda lesson: _time_to_minutes(str(lesson[0]).split(' - ')[0]))

# ==================== EDIT LESSON ====================
@router.callback_query(F.data.startswith("edit:"))
async def start_edit_lesson(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    day_idx = int(parts[1])
    lesson_idx = int(parts[2])
    parity = int(parts[3])

    day_name = DAYS_MAP[day_idx]
    group_name, subgroup = await get_user_settings(callback.from_user.id)

    lessons = await get_schedule_for_day(group_name, day_name, subgroup, parity)
    overrides = await get_overrides(callback.from_user.id)
    lessons = _apply_overrides_to_lessons_with_notes(lessons, overrides, day_name, parity)

    if lesson_idx <= len(lessons):
        time_str, l_type, subject, teacher, room, note = lessons[lesson_idx - 1]

        await state.update_data(
            edit_day=day_name,
            edit_time=time_str,
            edit_subject=subject,
            edit_parity=parity,
            edit_l_type=l_type,
            edit_teacher=teacher,
            edit_room=room
        )
        await state.set_state(EditLesson.waiting_for_action)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перенести на другой день", callback_data="edit_action:move")],
            [InlineKeyboardButton(text="❌ Отменить пару", callback_data="edit_action:cancel")],
            [InlineKeyboardButton(text="📝 Добавить заметку", callback_data="edit_action:note")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_day")]
        ])

        await callback.message.edit_text(
            f"✏️ <b>Редактирование пары</b>\n\n"
            f"📅 {day_name} | 🕐 {time_str}\n"
            f"📚 {subject}\n\n"
            f"Что сделать?",
            reply_markup=kb, parse_mode="HTML"
        )
    else:
        await callback.answer("Пара не найдена. Возможно, расписание обновилось.", show_alert=True)


@router.callback_query(F.data == "back_to_day")
async def back_to_day(callback: types.CallbackQuery, state: FSMContext):
    # СНАЧАЛА получаем данные из состояния
    data = await state.get_data()
    day_name = data.get("edit_day")

    # ПОТОМ очищаем состояние
    await state.clear()

    # Защита от None или некорректного значения
    if not day_name or day_name not in DAYS_MAP.values():
        await callback.answer("Ошибка: день недели не определён. Возвращаю в меню.", show_alert=True)
        await show_main_menu(callback.message, edit=True)
        return

    group_name, subgroup = await get_user_settings(callback.from_user.id)
    start_date = await get_semester_start()
    parity = get_week_parity(start_date)
    parity_text = "Числитель (нечётная)" if parity == 1 else "Знаменатель (чётная)"

    await show_day_schedule(callback.message, day_name, group_name, subgroup, parity_text, parity,
                            callback.from_user.id)


@router.callback_query(F.data.startswith("edit_action:"))
async def process_edit_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()

    if action == "move":
        await state.set_state(EditLesson.waiting_for_new_day)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Понедельник", callback_data="set_day:Понедельник")],
            [InlineKeyboardButton(text="Вторник", callback_data="set_day:Вторник")],
            [InlineKeyboardButton(text="Среда", callback_data="set_day:Среда")],
            [InlineKeyboardButton(text="Четверг", callback_data="set_day:Четверг")],
            [InlineKeyboardButton(text="Пятница", callback_data="set_day:Пятница")],
            [InlineKeyboardButton(text="Суббота", callback_data="set_day:Суббота")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_edit")]
        ])
        await callback.message.edit_text("Выберите новый день:", reply_markup=kb)

    elif action == "cancel":
        await add_override(
            callback.from_user.id, "cancel",
            data["edit_day"], data["edit_time"], data["edit_subject"], data["edit_parity"]
        )
        await callback.answer("Пара отменена!")
        await state.clear()
        await back_to_day(callback, state)

    elif action == "note":
        await state.set_state(EditLesson.waiting_for_note)
        await callback.message.edit_text("Введите заметку:")


@router.callback_query(F.data == "back_to_edit")
async def back_to_edit(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditLesson.waiting_for_action)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Перенести на другой день", callback_data="edit_action:move")],
        [InlineKeyboardButton(text="❌ Отменить пару", callback_data="edit_action:cancel")],
        [InlineKeyboardButton(text="🚪 Изменить аудиторию", callback_data="edit_action:room")],
        [InlineKeyboardButton(text="👨‍🏫 Изменить преподавателя", callback_data="edit_action:teacher")],
        [InlineKeyboardButton(text="📝 Добавить заметку", callback_data="edit_action:note")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_day")]
    ])
    await callback.message.edit_text("Что сделать?", reply_markup=kb)


@router.callback_query(F.data.startswith("set_day:"))
async def set_new_day(callback: types.CallbackQuery, state: FSMContext):
    new_day = callback.data.split(":")[1]
    data = await state.get_data()

    await add_override(
        callback.from_user.id, "move",
        data["edit_day"], data["edit_time"], data["edit_subject"], data["edit_parity"],
        new_day=new_day,
        new_time=data["edit_time"],
        new_teacher=data["edit_teacher"],
        new_room=data["edit_room"]
    )
    await callback.answer(f"Пара перенесена на {new_day}!")
    await state.clear()
    await back_to_day(callback, state)


@router.message(EditLesson.waiting_for_note, F.text)
async def receive_note(message: types.Message, state: FSMContext):
    note = message.text.strip()
    data = await state.get_data()

    await add_override(
        message.from_user.id, "edit",
        data["edit_day"], data["edit_time"], data["edit_subject"], data["edit_parity"],
        note=note
    )
    await message.answer(f"✅ Заметка добавлена: {note}")
    await state.clear()

    group_name, subgroup = await get_user_settings(message.from_user.id)
    start_date = await get_semester_start()
    parity = get_week_parity(start_date)
    parity_text = "Числитель (нечётная)" if parity == 1 else "Знаменатель (чётная)"

    # Передаем edit=False, чтобы бот отправил НОВОЕ сообщение, а не редактировал сообщение пользователя
    await show_day_schedule(message, data["edit_day"], group_name, subgroup, parity_text, parity, message.from_user.id,
                            edit=False)


# ==================== USER SETTINGS ====================
@router.callback_query(F.data == "settings")
async def show_settings(callback: types.CallbackQuery):
    group_name, subgroup = await get_user_settings(callback.from_user.id)
    text = "⚙️ <b>Настройки</b>\n\n"
    text += f"🏫 Группа: <b>{group_name or 'Не выбрана'}</b>\n"
    text += f"👥 Подгруппа: <b>{subgroup or 'Не выбрана'}</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏫 Сменить группу", callback_data="change_group")],
        [InlineKeyboardButton(text="👥 Сменить подгруппу", callback_data="change_subgroup")],
        [InlineKeyboardButton(text="🗑 Сбросить все изменения", callback_data="reset_overrides")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "reset_overrides")
async def reset_overrides(callback: types.CallbackQuery):
    await clear_all_overrides(callback.from_user.id)
    await callback.answer("Все изменения сброшены!")
    await show_settings(callback)


@router.callback_query(F.data == "change_subgroup")
async def change_subgroup_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 подгруппа", callback_data="set_sub_1"),
         InlineKeyboardButton(text="2 подгруппа", callback_data="set_sub_2")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings")]
    ])
    try:
        await callback.message.edit_text("Выберите подгруппу:", reply_markup=kb)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("set_sub_"))
async def set_subgroup(callback: types.CallbackQuery):
    subgroup = int(callback.data.split("_")[2])
    group_name, _ = await get_user_settings(callback.from_user.id)
    await set_user_settings(callback.from_user.id, group_name or "Не выбрана", subgroup)
    await callback.answer("Сохранено!")
    await show_settings(callback)


@router.callback_query(F.data == "change_group")
async def change_group_menu(callback: types.CallbackQuery):
    groups = await get_all_groups()
    if not groups:
        await callback.answer("В базе пока нет групп. Попросите админа загрузить расписание!", show_alert=True)
        return

    buttons = []
    for i in range(0, len(groups), 2):
        row = [InlineKeyboardButton(text=g, callback_data=f"set_grp_{g}") for g in groups[i:i + 2]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text("Выберите группу:", reply_markup=kb)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("set_grp_"))
async def set_group(callback: types.CallbackQuery):
    group_name = callback.data.split("set_grp_", 1)[1]
    _, subgroup = await get_user_settings(callback.from_user.id)
    await set_user_settings(callback.from_user.id, group_name, subgroup or 1)
    await callback.answer("Сохранено!")
    await show_settings(callback)


def _apply_overrides_to_lessons_with_notes(lessons, overrides, day_name, parity):
    """Применяет изменения пользователя к расписанию, включая заметки"""
    result = []
    cancelled_or_moved_indices = set()

    # Находим отменённые и перенесённые пары в исходном дне
    for override in overrides:
        (ov_id, ov_type, ov_day, ov_time, ov_subject, ov_parity,
         new_day, new_time, new_room, new_teacher, note) = override

        if ov_day == day_name and ov_parity == parity:
            for i, lesson in enumerate(lessons):
                time_str, l_type, subject, teacher, room = lesson
                if ov_time == time_str and _subjects_match(ov_subject, subject):
                    if ov_type in ["cancel", "move"]:
                        cancelled_or_moved_indices.add(i)

    # Собираем пары, применяя заметки
    for i, lesson in enumerate(lessons):
        if i in cancelled_or_moved_indices:
            continue

        time_str, l_type, subject, teacher, room = lesson
        current_note = None

        for override in overrides:
            (ov_id, ov_type, ov_day, ov_time, ov_subject, ov_parity,
             new_day, new_time, new_room, new_teacher, note) = override

            if ov_day == day_name and ov_time == time_str and ov_parity == parity and _subjects_match(ov_subject,
                                                                                                      subject):
                if ov_type == "edit" and note:
                    current_note = note
                    break

        result.append((time_str, l_type, subject, teacher, room, current_note))

    # Добавляем перенесённые пары в этот день (с проверкой на отмену и заметками!)
    for override in overrides:
        (ov_id, ov_type, ov_day, ov_time, ov_subject, ov_parity,
         new_day, new_time, new_room, new_teacher, note) = override

        if ov_type == "move" and new_day == day_name and ov_parity == parity:
            final_time = new_time or ov_time

            # ПРОВЕРЯЕМ: не отменена ли перенесённая пара в новом дне?
            is_cancelled = False
            for ov2 in overrides:
                (ov2_id, ov2_type, ov2_day, ov2_time, ov2_subject, ov2_parity,
                 ov2_new_day, ov2_new_time, ov2_new_room, ov2_new_teacher, ov2_note) = ov2

                if (ov2_type == "cancel" and ov2_day == day_name and ov2_parity == parity
                        and ov2_time == final_time and _subjects_match(ov2_subject, ov_subject)):
                    is_cancelled = True
                    break

            if is_cancelled:
                continue  # Пропускаем отменённую перенесённую пару

            # Ищем заметку для перенесённой пары среди записей типа "edit"
            moved_note = None
            for ov2 in overrides:
                (ov2_id, ov2_type, ov2_day, ov2_time, ov2_subject, ov2_parity,
                 ov2_new_day, ov2_new_time, ov2_new_room, ov2_new_teacher, ov2_note) = ov2

                if (ov2_type == "edit" and ov2_day == day_name and ov2_parity == parity
                        and ov2_time == final_time and _subjects_match(ov2_subject, ov_subject)):
                    if ov2_note:
                        moved_note = ov2_note
                        break

            result.append((
                final_time,
                "Перенесено",
                ov_subject,
                new_teacher or "Не указан",
                new_room or "Не указана",
                moved_note or note
            ))

    return _sort_lessons(result)

# ==================== ADMIN UPLOAD (FSM) ====================
@router.message(Command("upload"))
async def cmd_upload(message: types.Message, state: FSMContext):
    # Теперь доступно ВСЕМ пользователям
    await state.set_state(UploadSchedule.waiting_for_file)
    await message.answer("📥 Отправьте Excel файл (.xlsx) с расписанием.")


@router.message(UploadSchedule.waiting_for_group_name, F.text)
async def receive_group_name(message: types.Message, state: FSMContext):
    group_name = message.text.strip()
    data = await state.get_data()
    file_path = data["file_path"]

    # Если группа уже есть — спрашиваем подтверждение
    if await group_exists(group_name):
        await state.update_data(group_name=group_name)
        await state.set_state(UploadSchedule.waiting_for_confirm)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, перезаписать", callback_data="confirm_upload:yes"),
             InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_upload:no")]
        ])
        await message.answer(
            f"⚠️ Расписание для группы <b>{group_name}</b> уже есть в базе.\nПерезаписать его?",
            reply_markup=kb, parse_mode="HTML"
        )
        return

    await _process_upload(message, file_path, group_name, state)


@router.callback_query(UploadSchedule.waiting_for_confirm, F.data.startswith("confirm_upload:"))
async def confirm_upload(callback: types.CallbackQuery, state: FSMContext):
    answer = callback.data.split(":")[1]
    data = await state.get_data()

    if answer == "no":
        if os.path.exists(data["file_path"]):
            os.remove(data["file_path"])
        await state.clear()
        await callback.message.edit_text("❌ Загрузка отменена.")
        return

    await state.set_state(None)
    await _process_upload(callback.message, data["file_path"], data["group_name"], state, user=callback.from_user)


async def _process_upload(message, file_path, group_name, state, user=None):
    await message.answer("⏳ Обрабатываю файл, пожалуйста подождите...")
    try:
        count = await parse_and_save_schedule(file_path, group_name)
        if os.path.exists(file_path):
            os.remove(file_path)
        await state.clear()

        # Логируем, кто загрузил (для контроля)
        if user:
            print(f"📤 Загрузил: @{user.username or user.first_name} (id={user.id}) → группа {group_name}")

        await message.answer(
            f"✅ Расписание для группы <b>{group_name}</b> успешно загружено!\nСохранено записей: {count}",
            parse_mode="HTML"
        )
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Ошибка при обработке файла: {e}")


@router.message(UploadSchedule.waiting_for_file, F.document)
async def receive_file(message: types.Message, state: FSMContext):
    file = await bot.get_file(message.document.file_id)
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{message.document.file_name}"
    await bot.download_file(file.file_path, file_path)

    await state.update_data(file_path=file_path)
    await state.set_state(UploadSchedule.waiting_for_group_name)
    await message.answer("✅ Файл получен. Теперь введите название группы (например, бИПТ-252):")

@router.message(UploadSchedule.waiting_for_file)
async def wrong_file_type(message: types.Message):
    await message.answer("Пожалуйста, отправьте именно файл (.xlsx), а не текст или картинку.")


@router.message(UploadSchedule.waiting_for_group_name)
async def wrong_group_name(message: types.Message):
    await message.answer("Пожалуйста, отправьте название группы текстом.")


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(callback.message, edit=True)


# ==================== STARTUP ====================
async def main():
    await init_db()
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())