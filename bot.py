import asyncio
import json
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web
import aiohttp_cors

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8588347661:AAHkO30efmgcanwAYQtgqOFzkO3U4Rvv4Rs"
ADMIN_ID = 1179985543

# УКАЖИ IP СВОЕГО СЕРВЕРА
SERVER_IP = "92.38.48.203"
APP_URL = "https://collar-weekly-trademark-lance.trycloudflare.com"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "users.json")
HTML_FILE = os.path.join(BASE_DIR, "index.html")

bot = Bot(token=TOKEN)
dp = Dispatcher()

class WithdrawState(StatesGroup):
    wait_amount = State()
    wait_requisites = State()

# --- РАБОТА С БД ---
def load_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding='utf-8') as f:
            json.dump({}, f)
        return {}
    try:
        with open(DB_FILE, "r", encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Ошибка чтения БД: {e}")
        return {}

def save_db(data):
    try:
        with open(DB_FILE, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Ошибка записи БД: {e}")

# --- API ХЕНДЛЕРЫ ---

async def handle_index(request):
    # Читаем файл каждый раз, чтобы изменения в HTML подхватывались сразу
    if os.path.exists(HTML_FILE):
        return web.FileResponse(HTML_FILE)
    return web.Response(text="Файл index.html не найден на сервере", status=404)

async def handle_get_user(request):
    user_id = request.query.get("userId")
    if not user_id:
        return web.json_response({"error": "no_id"}, status=400)

    db = load_db()
    user_data = db.get(str(user_id), {"balance": 0, "lastSpinTime": 0})
    return web.json_response(user_data)

async def handle_update_balance(request):
    try:
        data = await request.json()
        user_id = str(data.get("userId"))
        db = load_db()

        if user_id not in db:
            db[user_id] = {"balance": 0, "username": "unknown", "lastSpinTime": 0}

        db[user_id]["balance"] = data.get("balance")
        db[user_id]["lastSpinTime"] = data.get("lastSpinTime")
        save_db(db)

        return web.json_response({"status": "ok"})
    except Exception as e:
        logging.error(f"❌ Ошибка API: {e}")
        return web.json_response({"status": "error"}, status=400)

# --- ЛОГИКА ТЕЛЕГРАМ БОТА ---
@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = str(message.from_user.id)
    db = load_db()

    if user_id not in db:
        db[user_id] = {"balance": 0, "username": message.from_user.username or "user", "lastSpinTime": 0}
        save_db(db)

    # 1. Кнопка прямо под сообщением (самая надежная для ID)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 ИГРАТЬ", web_app=WebAppInfo(url=APP_URL))]
    ])

    # 2. Кнопки внизу (Баланс и Вывод)
    reply_kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="💸 Вывод")]
    ], resize_keyboard=True)

    await message.answer(
        f"Привет, {message.from_user.first_name}! Твой баланс: {db[user_id]['balance']} 💰\nЖми 'Играть', чтобы крутить колесо!",
        reply_markup=reply_kb  # Устанавливаем нижние кнопки
    )

    # Отправляем отдельное сообщение с Inline-кнопкой для гарантии
    await message.answer("Открыть игровое поле:", reply_markup=inline_kb)


@dp.message(F.text == "💰 Баланс")
async def show_balance(message: types.Message):
    db = load_db()
    user_id = str(message.from_user.id)
    balance = db.get(user_id, {}).get("balance", 0)
    await message.answer(f"Ваш текущий баланс: {balance} очков.")

@dp.message(F.text == "💸 Вывод")
async def withdraw_start(message: types.Message, state: FSMContext):
    db = load_db()
    balance = db.get(str(message.from_user.id), {}).get("balance", 0)
    if balance < 5000:
        return await message.answer(f"Минимальный вывод — 5000. У тебя {balance}.")

    await state.update_data(balance=balance)

    await message.answer("Введите сумму для вывода:")
    await state.set_state(WithdrawState.wait_amount)

@dp.message(WithdrawState.wait_amount)
async def process_amount(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Введите число.")

    amount = int(message.text)
    data = await state.get_data()

    if amount > data['balance']:
        return await message.answer("Недостаточно средств.")

    await state.update_data(withdraw_amount=amount)
    await message.answer("Введите реквизиты (Visa/Номер Kaspi):")
    await state.set_state(WithdrawState.wait_requisites)

@dp.message(WithdrawState.wait_requisites)
async def process_req(message: types.Message, state: FSMContext):
    data = await state.get_data()
    admin_text = (f"🚨 <b>ЗАЯВКА</b>\n"
                  f"👤 Юзер: @{message.from_user.username}\n"
                  f"💰 Сумма: {data['withdraw_amount']}\n"
                  f"💳 Реквизиты: {message.text}")

    await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    await message.answer("✅ Заявка отправлена!")
    await state.clear()

# --- ЗАПУСК ---

async def main():
    app = web.Application()

    # Настройка CORS для работы браузера с твоим IP
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        )
    })

    app.router.add_get('/', handle_index)
    app.router.add_get('/get_user', handle_get_user)
    app.router.add_post('/update_balance', handle_update_balance)

    for route in list(app.router.routes()):
        cors.add(route)

    # Запуск API сервера
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

    logging.info(f"🚀 Сервер запущен на {APP_URL}")

    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")
