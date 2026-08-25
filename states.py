from aiogram.fsm.state import State, StatesGroup

class UploadSchedule(StatesGroup):
    waiting_for_file = State()
    waiting_for_group_name = State()

class EditLesson(StatesGroup):
    waiting_for_action = State()
    waiting_for_new_day = State()
    waiting_for_note = State()