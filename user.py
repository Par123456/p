import asyncio
import logging
import re
import sqlite3
import tempfile
import os
from typing import Optional, List, Tuple
from datetime import datetime

from telethon import TelegramClient, events, errors, functions
from telethon.tl.functions.users import GetFullUserRequest

# -----------------------------
# CONFIGURATION (مقداردهی کنید)
# -----------------------------
API_ID = 1234567            # مقدار از my.telegram.org
API_HASH = "your_api_hash"  # مقدار از my.telegram.org
BOT_TOKEN = ""  # "12345:abcd..."  # اگر می‌خواهید از Bot API نیز استفاده کنید؛ اختیاری است
SESSION_USER = "monitor_user_session"
SESSION_BOT = "monitor_bot_session"
ADMIN_IDS = [111111111]     # آیدی‌های عددی ادمین(ها)
ADMIN_CONTACT = "@AnishtayiN"
MAX_FREE_TARGETS = 5

# پیام‌ها (قابل تغییر)
MSG_WELCOME = "سلام! برای افزودن یک اکانت که می‌خواهید تغییرات پروفایلش را دریافت کنید، از دستور /register <username|id> استفاده کنید."
MSG_NOT_ALLOWED = "شما مسدود شده‌اید یا دسترسی ندارید."
MSG_NEED_JOIN = "برای ادامه باید عضو چنل(ها) یا گروه(های) اجباری زیر باشید. لطفاً جوین کنید و سپس /start را بزنید."

# -----------------------------
# logging
# -----------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# -----------------------------
# Database (SQLite)
# جداول:
# - users (user_id, username, banned, has_sub)
# - targets (id, owner_user_id, target_input, target_entity_id, added_at)
# - target_states (target_id, fullname, username, bio, photo_unique_id, last_updated)
# - required_channels (id, channel_text)
# -----------------------------
DB_PATH = "data.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        banned INTEGER DEFAULT 0,
        has_sub INTEGER DEFAULT 0
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_user_id INTEGER,
        target_input TEXT,
        target_entity_id INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(owner_user_id) REFERENCES users(user_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS target_states (
        target_id INTEGER PRIMARY KEY,
        fullname TEXT,
        username TEXT,
        bio TEXT,
        photo_unique_id TEXT,
        last_updated TIMESTAMP,
        FOREIGN KEY(target_id) REFERENCES targets(id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS required_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_text TEXT
    )
    """)
    conn.commit()
    conn.close()


# DB helper
def db_execute(query: str, params: tuple = (), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(query, params)
    if fetch:
        rows = cur.fetchall()
        conn.commit()
        conn.close()
        return rows
    else:
        conn.commit()
        conn.close()
        return None


def ensure_user_record(user_id: int, username: Optional[str]):
    rows = db_execute("SELECT user_id FROM users WHERE user_id=?", (user_id,), fetch=True)
    if not rows:
        db_execute("INSERT INTO users(user_id, username) VALUES(?, ?)", (user_id, username))
    else:
        db_execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))


def is_banned(user_id: int) -> bool:
    rows = db_execute("SELECT banned FROM users WHERE user_id=?", (user_id,), fetch=True)
    if not rows:
        return False
    return bool(rows[0][0])


def has_subscription(user_id: int) -> bool:
    rows = db_execute("SELECT has_sub FROM users WHERE user_id=?", (user_id,), fetch=True)
    if not rows:
        return False
    return bool(rows[0][0])


def set_subscription(user_id: int, value: bool):
    db_execute("UPDATE users SET has_sub=? WHERE user_id=?", (1 if value else 0, user_id))


def ban_user(user_id: int):
    db_execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))


def unban_user(user_id: int):
    db_execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))


def add_required_channel(text: str):
    db_execute("INSERT INTO required_channels(channel_text) VALUES(?)", (text,))


def remove_required_channel_by_id(ch_id: int):
    db_execute("DELETE FROM required_channels WHERE id=?", (ch_id,))


def list_required_channels() -> List[Tuple[int, str]]:
    return db_execute("SELECT id, channel_text FROM required_channels", fetch=True)


def add_target(owner_id: int, target_input: str, entity_id: int) -> int:
    db_execute("INSERT INTO targets(owner_user_id, target_input, target_entity_id) VALUES(?,?,?)",
               (owner_id, target_input, entity_id))
    rows = db_execute("SELECT id FROM targets WHERE owner_user_id=? ORDER BY added_at DESC LIMIT 1", (owner_id,), fetch=True)
    return rows[0][0] if rows else None


def remove_target_by_id(owner_id: int, target_id: int) -> bool:
    rows = db_execute("SELECT id FROM targets WHERE id=? AND owner_user_id=?", (target_id, owner_id), fetch=True)
    if not rows:
        return False
    db_execute("DELETE FROM targets WHERE id=? AND owner_user_id=?", (target_id, owner_id))
    db_execute("DELETE FROM target_states WHERE target_id=?", (target_id,))
    return True


def list_targets_for_user(owner_id: int) -> List[Tuple]:
    return db_execute("SELECT id, target_input, target_entity_id, added_at FROM targets WHERE owner_user_id=?",
                      (owner_id,), fetch=True)


def count_targets_for_user(owner_id: int) -> int:
    rows = db_execute("SELECT COUNT(*) FROM targets WHERE owner_user_id=?", (owner_id,), fetch=True)
    return rows[0][0] if rows else 0


def find_watchers_for_entity(entity_id: int) -> List[int]:
    rows = db_execute("SELECT owner_user_id FROM targets WHERE target_entity_id=?", (entity_id,), fetch=True)
    return [r[0] for r in rows]


def get_state_for_target(target_id: int) -> Optional[Tuple]:
    rows = db_execute("SELECT fullname, username, bio, photo_unique_id, last_updated FROM target_states WHERE target_id=?",
                      (target_id,), fetch=True)
    return rows[0] if rows else None


def set_state_for_target(target_id: int, fullname: str, username: Optional[str], bio: Optional[str], photo_unique_id: Optional[str]):
    now = datetime.utcnow().isoformat()
    rows = db_execute("SELECT target_id FROM target_states WHERE target_id=?", (target_id,), fetch=True)
    if not rows:
        db_execute("INSERT INTO target_states(target_id, fullname, username, bio, photo_unique_id, last_updated) VALUES(?,?,?,?,?,?)",
                   (target_id, fullname, username, bio, photo_unique_id, now))
    else:
        db_execute("UPDATE target_states SET fullname=?, username=?, bio=?, photo_unique_id=?, last_updated=? WHERE target_id=?",
                   (fullname, username, bio, photo_unique_id, now, target_id))


def find_target_ids_by_entity(entity_id: int) -> List[int]:
    rows = db_execute("SELECT id FROM targets WHERE target_entity_id=?", (entity_id,), fetch=True)
    return [r[0] for r in rows]

# -----------------------------
# Telethon clients
# -----------------------------
user_client = TelegramClient(SESSION_USER, API_ID, API_HASH)
bot_client: Optional[TelegramClient] = None
if BOT_TOKEN and BOT_TOKEN != "":
    bot_client = TelegramClient(SESSION_BOT, API_ID, API_HASH).start(bot_token=BOT_TOKEN)
else:
    bot_client = None

# choose client for commands and for sending messages
command_client = bot_client if bot_client else user_client


async def send_message_to_user(user_id: int, text: str, file: Optional[str] = None):
    """
    اگر file مشخص شود، آن فایل را همراه پیام می‌فرستیم.
    ارسال از طریق bot_client در صورت وجود، در غیر اینصورت از user_client استفاده می‌شود.
    """
    try:
        client = bot_client if bot_client else user_client
        if file:
            await client.send_file(user_id, file, caption=text)
        else:
            await client.send_message(user_id, text)
    except errors.TelegramError as e:
        log.warning(f"send_message_to_user error to {user_id}: {e}")


# -----------------------------
# Helpers برای واکشی جزئیات profile
# -----------------------------
async def fetch_profile_summary(entity_id: int) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    بازگرداند: (fullname, username, bio, photo_unique_id)
    photo_unique_id: unique_id از عکسِ پروفایل (برای تشخیص تغییر عکس)
    """
    try:
        full = await user_client(functions.users.GetFullUserRequest(entity_id))
        user = full.user
        first = getattr(user, 'first_name', '') or ''
        last = getattr(user, 'last_name', '') or ''
        fullname = (first + ' ' + last).strip()
        username = getattr(user, 'username', None)
        bio = getattr(full, 'about', None)
    except Exception as e:
        log.warning(f"fetch_profile_summary:GetFullUserRequest failed for {entity_id}: {e}")
        # fallback to get_entity
        try:
            user = await user_client.get_entity(entity_id)
            first = getattr(user, 'first_name', '') or ''
            last = getattr(user, 'last_name', '') or ''
            fullname = (first + ' ' + last).strip()
            username = getattr(user, 'username', None)
            bio = None
        except Exception as e2:
            log.exception(f"fetch_profile_summary fallback failed for {entity_id}: {e2}")
            return ("", None, None, None)
    # photo unique id:
    try:
        photos = await user_client.get_profile_photos(entity_id, limit=1)
        if photos.total > 0:
            p = photos[0]
            # Telethon photo object has .photo and .id; there is 'photo.file_id' in other libs.
            # Use .id as surrogate and .photo.access_hash if present. To be safer, use str(p.id).
            photo_unique_id = str(getattr(p, 'id', None))
        else:
            photo_unique_id = None
    except Exception:
        photo_unique_id = None
    return (fullname, username, bio, photo_unique_id)


async def download_latest_profile_photo(entity_id: int) -> Optional[str]:
    """
    دانلود عکس پروفایل آخر و بازگرداندن path فایل موقت یا None اگر عکسی نباشد.
    فایل موقت حذف نمی‌شود (فرستاده می‌شود)، بعد از ارسال باید حذف شود.
    """
    try:
        photos = await user_client.get_profile_photos(entity_id, limit=1)
        if photos.total == 0:
            return None
        # دانلود به فایل موقت
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.close()
        path = tmp.name
        await user_client.download_profile_photo(entity_id, file=path)
        return path
    except Exception as e:
        log.exception(f"download_latest_profile_photo failed for {entity_id}: {e}")
        return None


# -----------------------------
# Event handler: دقیق‌تر کردن پیام‌های تغییرات
# -----------------------------
@user_client.on(events.UserUpdate)
async def handler_user_update(event):
    """
    دریافت raw update برای یک user؛
    برای آن entity_id، لیست target_ids را می‌گیریم، سپس برای هر target مقایسه با state ذخیره‌شده انجام می‌دهیم،
    پیام تفصیلی همراه با عکس جدید (در صورت تغییر عکس) می‌فرستیم و state را آپدیت می‌کنیم.
    """
    try:
        entity_id = event.user_id
        if not entity_id:
            return
        watcher_ids = find_watchers_for_entity(entity_id)
        if not watcher_ids:
            return  # هیچکس این entity را دنبال نمی‌کند
        # fetch current profile summary
        fullname, username, bio, photo_uid = await fetch_profile_summary(entity_id)
        # find targets that correspond to this entity (multiple users ممکن است یکی را ثبت کرده باشند؛ هر target یک سطر است)
        target_ids = find_target_ids_by_entity(entity_id)
        if not target_ids:
            return
        # برای هر target مقایسه و نوتیفیکیشن انجام می‌دهیم
        for tid in target_ids:
            old_state = get_state_for_target(tid)
            # اگر state قبلی وجود ندارد، آن را بساز (init) بدون ارسال تغییر
            if not old_state:
                set_state_for_target(tid, fullname, username, bio, photo_uid)
                continue
            old_fullname, old_username, old_bio, old_photo_uid, old_updated = old_state
            changes = []
            if (fullname or "") != (old_fullname or ""):
                changes.append(("نام کامل", old_fullname or "(خالی)", fullname or "(خالی)"))
            # username مقایسه
            if (username or "") != (old_username or ""):
                changes.append(("یوزرنیم", ("@" + old_username) if old_username else "(نداشت)", ("@" + username) if username else "(ندارد)"))
            if (bio or "") != (old_bio or ""):
                changes.append(("بیو/دسکریپشن", old_bio or "(خالی)", bio or "(خالی)"))
            photo_changed = False
            if (photo_uid or "") != (old_photo_uid or ""):
                photo_changed = True
                changes.append(("عکس پروفایل", old_photo_uid or "(نداشته)", photo_uid or "(ندارد)"))
            # اگر تغییری وجود داشته باشد، برای همه watcherها پیام می‌فرستیم
            if changes:
                # متن پیام
                header = f"⚠️ تغییر در پروفایل کاربر ({entity_id}) شناسایی شد.\n"
                header += f"نام/یوزرنیم فعلی: {fullname or '(بدون نام)'} — {('@'+username) if username else '(ندارد)'}\n\n"
                body = ""
                for field, oldv, newv in changes:
                    body += f"• {field}:\n    قبلی: {oldv}\n    جدید: {newv}\n"
                body += f"\nشناسه عددی: {entity_id}\n"
                # اگر عکس تغییر کرده، عکس جدید را دانلود و همراه پیام بفرست
                photo_path = None
                if photo_changed:
                    photo_path = await download_latest_profile_photo(entity_id)
                # ارسال پیام به تمام watcherها (هر watcher از پایگاه‌داده آمده است)
                for watcher in set(watcher_ids):
                    if is_banned(watcher):
                        continue
                    try:
                        if photo_path:
                            await send_message_to_user(watcher, header + body, file=photo_path)
                        else:
                            await send_message_to_user(watcher, header + body)
                    except Exception as e:
                        log.warning(f"notify watcher {watcher} failed: {e}")
                # پاک کردن فایل موقت عکس بعد از ارسال
                if photo_path and os.path.exists(photo_path):
                    try:
                        os.remove(photo_path)
                    except Exception:
                        pass
                # بروزرسانی state برای این target
                set_state_for_target(tid, fullname, username, bio, photo_uid)
    except Exception as e:
        log.exception(f"Error in handler_user_update: {e}")


# -----------------------------
# Command handlers (register/list/remove/start)
# -----------------------------
@command_client.on(events.NewMessage(pattern=r'^/start$'))
async def cmd_start(event):
    user = await event.get_sender()
    uid = user.id
    username = user.username or ""
    ensure_user_record(uid, username)
    if is_banned(uid):
        await event.reply(MSG_NOT_ALLOWED)
        return
    # بررسی چنل‌های اجباری
    required = list_required_channels()
    missing = []
    for ch_id, ch_text in required:
        try:
            ch_ent = await user_client.get_entity(ch_text)
            try:
                await user_client.get_participant(ch_ent, uid)
            except Exception:
                missing.append(ch_text)
        except Exception:
            log.warning(f"required channel {ch_text} not resolvable")
            continue
    if missing:
        txt = MSG_NEED_JOIN + "\n\n"
        for ch in missing:
            txt += f"• {ch}\n"
        txt += f"\nپس از جوین شدن، /start را دوباره بزنید."
        await event.reply(txt)
        return
    await event.reply(MSG_WELCOME + "\n\n" +
                      f"برای افزودن اکانت: /register <username|id>\nبرای لیست اهداف: /list\nبرای حذف: /remove <target_id>\n\nبرای خرید اشتراک به {ADMIN_CONTACT} مراجعه کنید.")


@command_client.on(events.NewMessage(pattern=r'^/register (.+)'))
async def cmd_register(event):
    user = await event.get_sender()
    uid = user.id
    username = user.username or ""
    ensure_user_record(uid, username)
    if is_banned(uid):
        await event.reply(MSG_NOT_ALLOWED)
        return
    target_input = event.pattern_match.group(1).strip()
    cnt = count_targets_for_user(uid)
    if cnt >= MAX_FREE_TARGETS and not has_subscription(uid):
        await event.reply(f"شما فقط مجاز به ثبت {MAX_FREE_TARGETS} هدف هستید. برای ثبت بیشتر باید اشتراک تهیه کنید. برای خرید به {ADMIN_CONTACT} پیغام دهید.")
        return
    await event.reply("در حال بررسی و ثبت ... لطفاً صبر کنید.")
    # resolve entity async
    try:
        # numeric id?
        if re.match(r"^-?\d+$", target_input.strip()):
            ent = await user_client.get_entity(int(target_input.strip()))
        else:
            txt = target_input.strip().replace("t.me/", "").lstrip("@")
            ent = await user_client.get_entity(txt)
        ent_id = ent.id
    except Exception as e:
        log.warning(f"register resolve failed for {target_input}: {e}")
        await event.reply("خطا: نتوانستم اکانت را پیدا کنم. مطمئن شوید یوزرنیم یا آیدی را درست وارد کرده‌اید و حساب مورد نظر پابلیک است یا کلاینت ما دسترسی دارد.")
        return
    # ثبت target
    tid = add_target(uid, target_input, ent_id)
    # مقداردهی اولیه state با اطلاعات فعلی (تا در اولین آپدیت پیام اشتباه داده نشود)
    fullname, uname, bio, photo_uid = await fetch_profile_summary(ent_id)
    set_state_for_target(tid, fullname, uname, bio, photo_uid)
    await event.reply(f"✅ ثبت شد. target_id={tid} | entity_id={ent_id}\nاز این پس تغییرات پروفایل آن برای شما ارسال خواهد شد.")


@command_client.on(events.NewMessage(pattern=r'^/list$'))
async def cmd_list(event):
    user = await event.get_sender()
    uid = user.id
    ensure_user_record(uid, user.username or "")
    rows = list_targets_for_user(uid)
    if not rows:
        await event.reply("لیست اهداف شما خالی است.")
        return
    txt = "اهداف ثبت‌شده:\n\n"
    for r in rows:
        tid, tinput, tentid, added = r
        state = get_state_for_target(tid)
        fullname = state[0] if state else "(نامشخص)"
        username = state[1] if state else "(نامشخص)"
        txt += f"ID: {tid} | input: {tinput} | entity_id: {tentid} | name: {fullname} | username: {username} | added: {added}\n"
    await event.reply(txt)


@command_client.on(events.NewMessage(pattern=r'^/remove (\d+)$'))
async def cmd_remove(event):
    user = await event.get_sender()
    uid = user.id
    tid = int(event.pattern_match.group(1))
    ok = remove_target_by_id(uid, tid)
    if ok:
        await event.reply("✅ حذف شد.")
    else:
        await event.reply("خطا: هدف مورد نظر یافت نشد یا متعلق به شما نیست.")


# -----------------------------
# Admin commands (unchanged core, اما با پیام‌های فارسی)
# -----------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@command_client.on(events.NewMessage(pattern=r'^/grantsub (\d+)$'))
async def cmd_grantsub(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    target_id = int(event.pattern_match.group(1))
    ensure_user_record(target_id, None)
    set_subscription(target_id, True)
    await event.reply(f"اشتراک برای {target_id} فعال شد.")
    await send_message_to_user(target_id, "✅ اشتراک شما فعال شد. اکنون می‌توانید بیشتر از حد رایگان هدف ثبت کنید.")


@command_client.on(events.NewMessage(pattern=r'^/revokesub (\d+)$'))
async def cmd_revokesub(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    target_id = int(event.pattern_match.group(1))
    ensure_user_record(target_id, None)
    set_subscription(target_id, False)
    await event.reply(f"اشتراک برای {target_id} لغو شد.")
    await send_message_to_user(target_id, "اشتراک شما لغو شد.")


@command_client.on(events.NewMessage(pattern=r'^/ban (\d+)$'))
async def cmd_ban(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    target_id = int(event.pattern_match.group(1))
    ensure_user_record(target_id, None)
    ban_user(target_id)
    await event.reply(f"کاربر {target_id} بن شد.")
    await send_message_to_user(target_id, "شما توسط ادمین مسدود شده‌اید.")


@command_client.on(events.NewMessage(pattern=r'^/unban (\d+)$'))
async def cmd_unban(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    target_id = int(event.pattern_match.group(1))
    ensure_user_record(target_id, None)
    unban_user(target_id)
    await event.reply(f"کاربر {target_id} از حالت بن خارج شد.")
    await send_message_to_user(target_id, "دسترسی شما بازگردانده شد.")


@command_client.on(events.NewMessage(pattern=r'^/addchannel (.+)'))
async def cmd_addchannel(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    ch = event.pattern_match.group(1).strip()
    add_required_channel(ch)
    await event.reply(f"کانال/گروه اجباری اضافه شد: {ch}")


@command_client.on(events.NewMessage(pattern=r'^/removechannel (\d+)$'))
async def cmd_removechannel(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    ch_id = int(event.pattern_match.group(1))
    remove_required_channel_by_id(ch_id)
    await event.reply(f"کانال اجباری با id={ch_id} حذف شد.")


@command_client.on(events.NewMessage(pattern=r'^/channels$'))
async def cmd_channels(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    rows = list_required_channels()
    if not rows:
        await event.reply("لیست کانال‌های اجباری خالی است.")
        return
    txt = "کانال‌های اجباری:\n\n"
    for r in rows:
        txt += f"id: {r[0]} | {r[1]}\n"
    await event.reply(txt)


@command_client.on(events.NewMessage(pattern=r'^/broadcast (.+)', flags=re.DOTALL))
async def cmd_broadcast(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    text = event.pattern_match.group(1).strip()
    rows = db_execute("SELECT user_id FROM users", fetch=True)
    if not rows:
        await event.reply("هیچ کاربری ثبت نشده است.")
        return
    await event.reply(f"ارسال پیام به {len(rows)} کاربر آغاز شد.")
    for r in rows:
        uid = r[0]
        try:
            await send_message_to_user(uid, f"[پیام همگانی]\n\n{text}")
        except Exception as e:
            log.warning(f"broadcast to {uid} failed: {e}")
    await event.reply("ارسال پیام همگانی به پایان رسید.")


@command_client.on(events.NewMessage(pattern=r'^/users$'))
async def cmd_users(event):
    user = await event.get_sender()
    if not is_admin(user.id):
        await event.reply("فقط ادمین مجوز اجرای این دستور را دارد.")
        return
    rows = db_execute("SELECT user_id, username, banned, has_sub FROM users", fetch=True)
    if not rows:
        await event.reply("هیچ کاربری ثبت نشده.")
        return
    txt = "کاربران:\n\n"
    for r in rows:
        txt += f"{r[0]} | username={r[1]} | banned={r[2]} | sub={r[3]}\n"
    await event.reply(txt)


# -----------------------------
# Run
# -----------------------------
async def main():
    init_db()
    await user_client.start()
    log.info("User client started.")
    if bot_client:
        await bot_client.start()
        log.info("Bot client started.")
    print("ربات اجرا شد. برای خروج Ctrl+C")
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("خروج...")
