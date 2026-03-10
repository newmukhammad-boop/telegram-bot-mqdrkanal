import asyncio
import logging
import json
import os
import uuid
import threading
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from flask import Flask, request, jsonify
from flask_cors import CORS

# ===================== CONFIG =====================
BOT_TOKEN = "8341456394:AAFpVwaU7cFqfL41iPYmmNQSwFQIIcoFS10"
CHANNEL_ID = "@muxammadqodir_sayidov"
ADMIN_IDS = [1604056228]
DB_FILE = "materials.json"
API_PORT = 5000
# ==================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ─── Flask app ───────────────────────────────────
app = Flask(__name__)
CORS(app)

# ─── Database helpers ────────────────────────────
def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        return {"materials": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_material(mat_id: str):
    return load_db()["materials"].get(mat_id)

def add_material(mat_id: str, info: dict):
    db = load_db()
    info.setdefault("downloads", 0)
    db["materials"][mat_id] = info
    save_db(db)

def delete_material(mat_id: str) -> bool:
    db = load_db()
    if mat_id in db["materials"]:
        del db["materials"][mat_id]
        save_db(db)
        return True
    return False

def increment_downloads(mat_id: str):
    db = load_db()
    if mat_id in db["materials"]:
        db["materials"][mat_id]["downloads"] = db["materials"][mat_id].get("downloads", 0) + 1
        save_db(db)

# ─── Flask API endpoints ─────────────────────────
@app.route("/api/materials", methods=["GET"])
def api_get_materials():
    db = load_db()
    return jsonify(list(db["materials"].values()))

@app.route("/api/materials/<mat_id>", methods=["DELETE"])
def api_delete_material(mat_id):
    if delete_material(mat_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Not found"}), 404

@app.route("/api/stats", methods=["GET"])
def api_stats():
    db = load_db()
    mats = list(db["materials"].values())
    return jsonify({
        "total": len(mats),
        "photos": sum(1 for m in mats if m.get("type") == "photo"),
        "others": sum(1 for m in mats if m.get("type") != "photo"),
        "downloads": sum(m.get("downloads", 0) for m in mats)
    })

@app.route("/", methods=["GET"])
def health():
    return "Bot is running!", 200

# ─── Channel membership check ────────────────────
async def is_member(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramBadRequest:
        return False

# ─── Send material ───────────────────────────────
async def send_material(chat_id: int, mat: dict):
    caption = mat.get("caption", "")
    file_id = mat.get("file_id")
    file_type = mat.get("type")
    if file_type == "photo":
        await bot.send_photo(chat_id, file_id, caption=caption)
    elif file_type == "video":
        await bot.send_video(chat_id, file_id, caption=caption)
    elif file_type == "document":
        await bot.send_document(chat_id, file_id, caption=caption)
    else:
        await bot.send_message(chat_id, "❌ Material topilmadi.")

# ─── /start ──────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: types.Message):
    args = msg.text.split()
    mat_id = args[1] if len(args) > 1 else None

    if not mat_id:
        await msg.answer(
            "👋 Salom! Ushbu bot maxsus materiallarni tarqatish uchun ishlatiladi.\n\n"
            "Material olish uchun maxsus link orqali kiring."
        )
        return

    mat = get_material(mat_id)
    if not mat:
        await msg.answer("❌ Bunday material mavjud emas yoki muddati o'tgan.")
        return

    if await is_member(msg.from_user.id):
        increment_downloads(mat_id)
        await msg.answer("✅ Rahmat! Mana sizning materialingiz:")
        await send_material(msg.chat.id, mat)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga a'zo bo'lish", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")],
            [InlineKeyboardButton(text="✅ A'zo bo'ldim, tekshir", callback_data=f"check:{mat_id}")]
        ])
        await msg.answer(
            "⚠️ Materialni olish uchun avval kanalga a'zo bo'ling!\n\n"
            f"Kanal: {CHANNEL_ID}\n\nA'zo bo'lgach, pastdagi tugmani bosing 👇",
            reply_markup=kb
        )

# ─── Callback ────────────────────────────────────
@dp.callback_query(F.data.startswith("check:"))
async def check_membership(cb: types.CallbackQuery):
    mat_id = cb.data.split(":", 1)[1]
    mat = get_material(mat_id)
    if not mat:
        await cb.answer("❌ Material topilmadi.", show_alert=True)
        return
    if await is_member(cb.from_user.id):
        increment_downloads(mat_id)
        await cb.message.edit_text("✅ Rahmat! Mana sizning materialingiz:")
        await send_material(cb.message.chat.id, mat)
    else:
        await cb.answer("❌ Siz hali kanalga a'zo bo'lmadingiz!", show_alert=True)

# ─── Admin: fayl qabul qilish ────────────────────
@dp.message(F.from_user.id.in_(set(ADMIN_IDS)) & (F.photo | F.video | F.document))
async def receive_material(msg: types.Message):
    mat_id = uuid.uuid4().hex[:8]
    if msg.photo:
        file_id = msg.photo[-1].file_id
        ftype = "photo"
        fname = "rasm.jpg"
    elif msg.video:
        file_id = msg.video.file_id
        ftype = "video"
        fname = msg.video.file_name or "video.mp4"
    elif msg.document:
        file_id = msg.document.file_id
        ftype = "document"
        fname = msg.document.file_name or "fayl"
    else:
        return

    caption = msg.caption or ""
    add_material(mat_id, {
        "id": mat_id,
        "file_id": file_id,
        "type": ftype,
        "caption": caption,
        "name": caption or fname,
        "fileName": fname,
        "downloads": 0
    })

    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={mat_id}"
    await msg.answer(
        f"✅ Material saqlandi!\n\n"
        f"🆔 ID: <code>{mat_id}</code>\n"
        f"🔗 Link: {link}",
        parse_mode="HTML"
    )

# ─── Admin: /materials ───────────────────────────
@dp.message(Command("materials"), F.from_user.id.in_(set(ADMIN_IDS)))
async def list_materials(msg: types.Message):
    db = load_db()
    mats = db["materials"]
    if not mats:
        await msg.answer("📭 Hech qanday material yo'q.")
        return
    bot_info = await bot.get_me()
    lines = []
    for mid, m in mats.items():
        link = f"https://t.me/{bot_info.username}?start={mid}"
        lines.append(
            f"• <b>{m.get('name', mid)}</b>\n"
            f"  👥 {m.get('downloads', 0)} marta yuklandi\n"
            f"  🔗 {link}"
        )
    await msg.answer("📦 Materiallar:\n\n" + "\n\n".join(lines), parse_mode="HTML")

# ─── Admin: /delete ──────────────────────────────
@dp.message(Command("delete"), F.from_user.id.in_(set(ADMIN_IDS)))
async def delete_mat(msg: types.Message):
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("❗ Ishlatish: /delete <material_id>")
        return
    if delete_material(parts[1]):
        await msg.answer(f"🗑 Material <code>{parts[1]}</code> o'chirildi.", parse_mode="HTML")
    else:
        await msg.answer("❌ Bunday material topilmadi.")

# ─── Run Flask in thread ─────────────────────────
def run_flask():
    app.run(host="0.0.0.0", port=API_PORT, debug=False, use_reloader=False)

# ─── Main ────────────────────────────────────────
async def main():
    if not os.path.exists(DB_FILE):
        save_db({"materials": {}})
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
