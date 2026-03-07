import os
import sqlite3
import shutil
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

BASE_DIR = os.path.dirname(__file__)
DB_NAME = os.path.join(BASE_DIR, "addresses.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backup")

user_city = {}
edit_sessions = {}

# ---------- АДМИН ПАНЕЛЬ ----------

admin_add_address = {}
admin_delete_address = {}
admin_add_admin = {}

os.makedirs(BACKUP_DIR, exist_ok=True)


def db():
    return sqlite3.connect(DB_NAME)

# ---------- ПРОВЕРКА АДМИНА ----------

def is_admin(user_id):

    conn = db()
    cursor = conn.cursor()

    cursor.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,))
    r = cursor.fetchone()

    conn.close()

    return r is not None


# ---------- ЛОГ ----------

def log_action(user, action):

    conn = db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO logs(user_id,user_name,action,time)
    VALUES(?,?,?,?)
    """,(
        user.id,
        user.full_name,
        action,
        datetime.now().strftime("%d.%m.%Y %H:%M")
    ))

    conn.commit()
    conn.close()

# ---------- СОЗДАНИЕ ТАБЛИЦ ----------

def init_db():
    conn = db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        address_id INTEGER,
        box TEXT,
        access TEXT,
        cross TEXT,
        changed_by TEXT,
        changed_by_id INTEGER,
        changed_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS locks(
        address_id INTEGER PRIMARY KEY,
        user_id INTEGER,
        user_name TEXT,
        started_at INTEGER
    )
    """)

    conn.commit()
    conn.close()


# ---------- БЭКАП ----------

async def backup_loop():
    while True:
        await asyncio.sleep(21600)

        now = datetime.now().strftime("%Y%m%d_%H%M")
        backup_file = os.path.join(BACKUP_DIR, f"addresses_{now}.db")

        shutil.copy(DB_NAME, backup_file)
        print("Backup created:", backup_file)


# ---------- ОЧИСТКА LOCK ----------

async def lock_cleaner():

    while True:

        await asyncio.sleep(60)

        conn = db()
        cursor = conn.cursor()

        now = int(datetime.now().timestamp())

        cursor.execute("""
        DELETE FROM locks
        WHERE started_at < ?
        """,(now-300,))

        conn.commit()
        conn.close()


# ---------- АДМИН ПАНЕЛЬ ----------

@dp.message_handler(commands=["admin"])
async def admin_panel(message: types.Message):

    if not is_admin(message.from_user.id):
        return

    keyboard = InlineKeyboardMarkup()

    keyboard.add(
        InlineKeyboardButton("➕ Добавить адрес", callback_data="admin_add_address")
    )

    keyboard.add(
    InlineKeyboardButton("🗑 Удалить адрес", callback_data="admin_delete_address")
    )

    keyboard.add(
        InlineKeyboardButton("👤 Добавить админа", callback_data="admin_add_admin")
    )

    keyboard.add(
        InlineKeyboardButton("📜 Логи", callback_data="admin_logs")
    )

    await message.answer("👑 Админ панель", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data=="admin_add_address")
async def admin_add_addr(callback: types.CallbackQuery):

    admin_add_address[callback.from_user.id] = True

    await bot.send_message(
        callback.from_user.id,
        "Введите адрес\n\nФормат:\nГород|улица дом\n\nПример:\nКалуга|Солнечный 18"
    )


@dp.callback_query_handler(lambda c: c.data=="admin_delete_address")
async def admin_delete_addr(callback: types.CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    admin_delete_address[callback.from_user.id] = True

    await bot.send_message(
        callback.from_user.id,
        "Введите адрес для удаления\n\nПример:\nСолнечный 18"
    )


@dp.callback_query_handler(lambda c: c.data=="admin_add_admin")
async def admin_add_admin_btn(callback: types.CallbackQuery):

    admin_add_admin[callback.from_user.id] = True

    await bot.send_message(
        callback.from_user.id,
        "Введите Telegram ID нового админа"
    )


@dp.callback_query_handler(lambda c: c.data=="admin_logs")
async def admin_logs(callback: types.CallbackQuery):

    conn = db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT user_name,action,time
    FROM logs
    ORDER BY id DESC
    LIMIT 10
    """)

    rows = cursor.fetchall()

    conn.close()

    text = "📜 Последние действия:\n"

    for r in rows:
        text += f"\n{r[2]} — {r[0]} — {r[1]}"

    await callback.message.answer(text)

# ---------- СТАРТ ----------

@dp.message_handler(commands=["start"])
async def start(message: types.Message):

    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)

    keyboard.add(
        KeyboardButton("Калуга"),
        KeyboardButton("Воротынск"),
        KeyboardButton("Мстихино"),
        KeyboardButton("Резвань")
    )

    await message.answer("Выберите населенный пункт", reply_markup=keyboard)


# ---------- ВЫБОР ГОРОДА ----------

@dp.message_handler(lambda m: m.text in ["Калуга","Воротынск","Мстихино","Резвань"])
async def choose_city(message: types.Message):

    user_city[message.from_user.id] = message.text

    await message.answer(f"📍 Город выбран: {message.text}\n\nВведите улицу и номер дома")


# ---------- ПОИСК ----------

def search_address(city, text):

    conn = db()
    cursor = conn.cursor()

    text = text.lower().replace("ё", "е")
    words = text.split()

    cursor.execute("SELECT id,address FROM addresses WHERE city=?", (city,))
    rows = cursor.fetchall()

    conn.close()

    results = []

    for row in rows:

        addr = row[1].lower().replace("ё", "е")

        ok = True

        for w in words:
            if w not in addr:
                ok = False
                break

        if ok:
            results.append(row)

    return results[:10]


# ---------- ПОКАЗ ДОМА ----------

async def show_house(message, house_id):

    conn = db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT city,address,box,access,cross,updated,updated_by,updated_by_id
    FROM addresses
    WHERE id=?
    """,(house_id,))

    house = cursor.fetchone()

    keyboard = InlineKeyboardMarkup()

    keyboard.add(
        InlineKeyboardButton("✏ Изменить", callback_data=f"editmenu|{house_id}")
    )

    keyboard.add(
        InlineKeyboardButton("📜 История", callback_data=f"history|{house_id}")
    )

    keyboard.add(
        InlineKeyboardButton("↩ Отменить", callback_data=f"undo|{house_id}")
    )

    user_link=""

    if house[7]:
        user_link=f'<a href="tg://user?id={house[7]}">{house[6]}</a>'
    else:
        user_link=house[6] or ""

    text=f"""
🏠 {house[0]} {house[1]}

📦 Ящик: {house[2] or ""}
🚪 Доступ: {house[3] or ""}
🔌 Кросс/патч: {house[4] or ""}

🕒 Обновлено: {house[5] or ""}
👤 Изменил: {user_link}
"""

    await message.answer(text,reply_markup=keyboard,parse_mode="HTML")


# ---------- МЕНЮ РЕДАКТИРОВАНИЯ ----------

@dp.callback_query_handler(lambda c: c.data.startswith("editmenu|"))
async def edit_menu(callback: types.CallbackQuery):

    house_id = callback.data.split("|")[1]

    conn=db()
    cursor=conn.cursor()

    cursor.execute("SELECT user_id,user_name,started_at FROM locks WHERE address_id=?",(house_id,))
    lock=cursor.fetchone()

    now=int(datetime.now().timestamp())

    if lock:

        if now-lock[2] < 300 and lock[0] != callback.from_user.id:

            await callback.message.answer(
                f"⚠ Этот адрес сейчас редактирует:\n{lock[1]}"
            )

            conn.close()
            return

        cursor.execute("DELETE FROM locks WHERE address_id=?",(house_id,))

    cursor.execute("""
    INSERT INTO locks(address_id,user_id,user_name,started_at)
    VALUES(?,?,?,?)
    """,(house_id,callback.from_user.id,callback.from_user.full_name,now))

    conn.commit()
    conn.close()

    keyboard=InlineKeyboardMarkup()

    keyboard.add(
        InlineKeyboardButton("📦 Ящик",callback_data=f"editbox|{house_id}")
    )

    keyboard.add(
        InlineKeyboardButton("🚪 Доступ",callback_data=f"editaccess|{house_id}")
    )

    keyboard.add(
        InlineKeyboardButton("🔌 Кросс/патч",callback_data=f"editcross|{house_id}")
    )

    await callback.message.answer("Что изменить?",reply_markup=keyboard)




# ---------- РЕДАКТИРОВАНИЕ ----------

@dp.callback_query_handler(lambda c: c.data.startswith("editbox|"))
async def edit_box(callback: types.CallbackQuery):

    house_id=callback.data.split("|")[1]
    edit_sessions[callback.from_user.id]=("box",house_id)

    await bot.send_message(callback.from_user.id,"Введите новый Ящик")


@dp.callback_query_handler(lambda c: c.data.startswith("editaccess|"))
async def edit_access(callback: types.CallbackQuery):

    house_id=callback.data.split("|")[1]
    edit_sessions[callback.from_user.id]=("access",house_id)

    await bot.send_message(callback.from_user.id,"Введите новый Доступ")


@dp.callback_query_handler(lambda c: c.data.startswith("editcross|"))
async def edit_cross(callback: types.CallbackQuery):

    house_id=callback.data.split("|")[1]
    edit_sessions[callback.from_user.id]=("cross",house_id)

    await bot.send_message(callback.from_user.id,"Введите новый Кросс/патч")


# ---------- УДАЛЕНИЕ АДРЕСА (АДМИН) ----------

@dp.callback_query_handler(lambda c: c.data.startswith("admin_delete_confirm|"))
async def admin_delete_confirm(callback: types.CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    house_id = callback.data.split("|")[1]

    conn = db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM addresses WHERE id=?", (house_id,))
    cursor.execute("DELETE FROM history WHERE address_id=?", (house_id,))
    cursor.execute("DELETE FROM locks WHERE address_id=?", (house_id,))

    conn.commit()
    conn.close()

    await callback.message.answer("🗑 Адрес удалён")


# ---------- ОБРАБОТКА ВВОДА ----------

@dp.message_handler()
async def handle(message: types.Message):

    user_id = message.from_user.id
    text = message.text.strip()

    # ---------- ДОБАВЛЕНИЕ АДРЕСА ----------

    if user_id in admin_add_address:

        try:

            city,address = text.split("|")

            conn = db()
            cursor = conn.cursor()

            cursor.execute(
                "INSERT INTO addresses(city,address) VALUES(?,?)",
                (city.strip(), address.strip())
            )

            conn.commit()
            conn.close()

            log_action(message.from_user,"add address")

            await message.answer("Адрес добавлен")

        except:
            await message.answer("Неверный формат")

        del admin_add_address[user_id]
        return


# ---------- УДАЛЕНИЕ АДРЕСА ----------

    if user_id in admin_delete_address:

        conn = db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id,address FROM addresses WHERE LOWER(address) LIKE ?",
            (f"%{text.lower()}%",)
        )

        rows = cursor.fetchall()

        if not rows:
            await message.answer("Адрес не найден")
            del admin_delete_address[user_id]
            conn.close()
            return

        keyboard = InlineKeyboardMarkup()

        for r in rows:
            keyboard.add(
                InlineKeyboardButton(
                    f"Удалить {r[1]}",
                    callback_data=f"admin_delete_confirm|{r[0]}"
                )
            )

        await message.answer(
            "Выберите адрес для удаления:",
            reply_markup=keyboard
        )

        conn.close()
        del admin_delete_address[user_id]
        return
    

    # ---------- ДОБАВЛЕНИЕ АДМИНА ----------

    if user_id in admin_add_admin:

        try:

            new_admin = int(text)

            conn = db()
            cursor = conn.cursor()

            cursor.execute(
                "INSERT INTO admins(user_id) VALUES(?)",
                (new_admin,)
            )

            conn.commit()
            conn.close()

            await message.answer("Админ добавлен")

        except:
            await message.answer("Ошибка")

        del admin_add_admin[user_id]
        return


    # ---------- РЕДАКТИРОВАНИЕ ----------

    if user_id in edit_sessions:

        field,house_id = edit_sessions[user_id]

        conn=db()
        cursor=conn.cursor()

        cursor.execute("SELECT box,access,cross FROM addresses WHERE id=?",(house_id,))
        old=cursor.fetchone()

        cursor.execute("""
        INSERT INTO history(address_id,box,access,cross,changed_by,changed_by_id,changed_at)
        VALUES(?,?,?,?,?,?,?)
        """,(
            house_id,
            old[0],
            old[1],
            old[2],
            message.from_user.full_name,
            message.from_user.id,
            datetime.now().strftime("%d.%m.%Y %H:%M")
        ))

        now=datetime.now().strftime("%d.%m.%Y %H:%M")

        cursor.execute(f"""
        UPDATE addresses
        SET {field}=?,updated=?,updated_by=?,updated_by_id=?
        WHERE id=?
        """,(text,now,message.from_user.full_name,message.from_user.id,house_id))

        cursor.execute("DELETE FROM locks WHERE address_id=?",(house_id,))

        conn.commit()
        conn.close()

        del edit_sessions[user_id]

        await message.answer("✅ Информация обновлена")

        return


    # ---------- ПРОВЕРКА ГОРОДА ----------

    if user_id not in user_city:
        await message.answer("Сначала выберите город (/start)")
        return

    city=user_city[user_id]


    # ---------- ПОИСК ----------

    results=search_address(city,text)

    if not results:
        await message.answer("❌ Дом не найден")
        return


    if len(results)==1:
        await show_house(message,results[0][0])
        return


    keyboard=InlineKeyboardMarkup()

    for r in results:
        keyboard.add(
            InlineKeyboardButton(
                r[1],
                callback_data=f"house|{r[0]}"
            )
        )

    await message.answer("Найдено несколько домов:",reply_markup=keyboard)


# ---------- ОТКРЫТЬ ДОМ ----------

@dp.callback_query_handler(lambda c: c.data.startswith("house|"))
async def open_house(callback: types.CallbackQuery):

    house_id = callback.data.split("|")[1]

    await show_house(callback.message, house_id)

# ---------- ИСТОРИЯ ----------

@dp.callback_query_handler(lambda c: c.data.startswith("history|"))
async def history(callback: types.CallbackQuery):

    house_id=callback.data.split("|")[1]

    conn=db()
    cursor=conn.cursor()

    cursor.execute("""
    SELECT box,access,cross,changed_by,changed_at
    FROM history
    WHERE address_id=?
    ORDER BY id DESC LIMIT 5
    """,(house_id,))

    rows=cursor.fetchall()
    conn.close()

    if not rows:
        await callback.message.answer("История изменений пуста")
        return

    text="📜 Последние изменения:\n"

    for r in rows:
        text+=f"\n{r[4]} — {r[3]}\n📦 {r[0]}\n🚪 {r[1]}\n🔌 {r[2]}\n"

    await callback.message.answer(text)


# ---------- ОТМЕНА ----------

@dp.callback_query_handler(lambda c: c.data.startswith("undo|"))
async def undo(callback: types.CallbackQuery):

    house_id=callback.data.split("|")[1]

    conn=db()
    cursor=conn.cursor()

    cursor.execute("""
    SELECT box,access,cross
    FROM history
    WHERE address_id=?
    ORDER BY id DESC LIMIT 1
    """,(house_id,))

    last=cursor.fetchone()

    if not last:
        await callback.message.answer("Нет предыдущих изменений")
        return

    cursor.execute("""
    UPDATE addresses
    SET box=?,access=?,cross=?
    WHERE id=?
    """,(last[0],last[1],last[2],house_id))

    conn.commit()
    conn.close()

    await callback.message.answer("↩ Последнее изменение отменено")


# ---------- СТАТИСТИКА ----------

@dp.message_handler(commands=["stats"])
async def stats(message: types.Message):

    conn=db()
    cursor=conn.cursor()

    cursor.execute("""
    SELECT updated_by,COUNT(*)
    FROM addresses
    WHERE updated_by IS NOT NULL
    GROUP BY updated_by
    ORDER BY COUNT(*) DESC
    """)

    rows=cursor.fetchall()
    conn.close()

    text="📊 Статистика изменений:\n"

    for r in rows:
        text+=f"\n{r[0]} — {r[1]}"

    await message.answer(text)


# ---------- ЗАПУСК ----------

async def on_startup(dp):
    init_db()
    asyncio.create_task(backup_loop())
    asyncio.create_task(lock_cleaner())


if __name__=="__main__":
    executor.start_polling(dp,skip_updates=True,on_startup=on_startup)
