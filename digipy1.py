# index.py
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
import re
import json
import asyncio
from enum import Enum

from telegram import Update, Chat, ChatMember, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ChatType, ChatMemberStatus

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تنظیمات ربات
TOKEN = "8573030745:AAG6Lzn0La7mywT80q9lJ7yMIBKv2PIdgsg"
ADMIN_IDS = [6508600903]  # ادمین‌های اصلی ربات (شناسه عددی)

# ساختارهای داده
class LockType(Enum):
    LINKS = "links"
    INVITE_LINKS = "invite_links"
    MENTIONS = "mentions"
    HASHTAGS = "hashtags"
    PHONE = "phone"
    FORWARD = "forward"
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    GIF = "gif"
    STICKER = "sticker"
    VOICE = "voice"
    FILE = "file"
    BOTS = "bots"
    GAMES = "games"
    LONG_TEXT = "long_text"
    EMOJI = "emoji"
    SPAM = "spam"

# کلاس مدیریت داده‌های گروه
class GroupData:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.banned_users = set()
        self.muted_users = {}  # user_id: expiration_time
        self.warnings = {}  # user_id: warning_count
        self.max_warnings = 3  # تعداد اخطارهای مجاز
        self.filtered_words = set()
        self.admins = set()
        self.special_users = set()
        self.locks = {lock_type: False for lock_type in LockType}
        self.welcome_enabled = False
        self.welcome_message = "خوش آمدید {user} به گروه {chat}!"
        self.last_messages = []  # برای تشخیص اسپم
        self.user_join_times = {}  # زمان‌های ورود کاربران

    def to_dict(self):
        return {
            'banned_users': list(self.banned_users),
            'muted_users': self.muted_users.copy(),
            'warnings': self.warnings.copy(),
            'max_warnings': self.max_warnings,
            'filtered_words': list(self.filtered_words),
            'admins': list(self.admins),
            'special_users': list(self.special_users),
            'locks': {lock_type.value: status for lock_type, status in self.locks.items()},
            'welcome_enabled': self.welcome_enabled,
            'welcome_message': self.welcome_message
        }
    
    @classmethod
    def from_dict(cls, chat_id: int, data: dict):
        group = cls(chat_id)
        group.banned_users = set(data.get('banned_users', []))
        group.muted_users = data.get('muted_users', {})
        group.warnings = data.get('warnings', {})
        group.max_warnings = data.get('max_warnings', 3)
        group.filtered_words = set(data.get('filtered_words', []))
        group.admins = set(data.get('admins', []))
        group.special_users = set(data.get('special_users', []))
        
        locks_data = data.get('locks', {})
        for lock_type in LockType:
            group.locks[lock_type] = locks_data.get(lock_type.value, False)
        
        group.welcome_enabled = data.get('welcome_enabled', False)
        group.welcome_message = data.get('welcome_message', "خوش آمدید {user} به گروه {chat}!")
        return group

# سیستم ذخیره‌سازی
class Storage:
    def __init__(self):
        self.groups: Dict[int, GroupData] = {}
        self.load_data()
    
    def load_data(self):
        try:
            with open('data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                for chat_id_str, group_data in data.items():
                    chat_id = int(chat_id_str)
                    self.groups[chat_id] = GroupData.from_dict(chat_id, group_data)
        except FileNotFoundError:
            pass
    
    def save_data(self):
        data = {}
        for chat_id, group in self.groups.items():
            data[str(chat_id)] = group.to_dict()
        
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get_group(self, chat_id: int) -> GroupData:
        if chat_id not in self.groups:
            self.groups[chat_id] = GroupData(chat_id)
        return self.groups[chat_id]

storage = Storage()

# تابع کمکی برای ذخیره خودکار
def auto_save(func):
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        storage.save_data()
        return result
    return wrapper

# تایمر برای بررسی سکوت‌های زمان‌دار
async def check_mute_timers(context: ContextTypes.DEFAULT_TYPE):
    current_time = datetime.now()
    for chat_id, group in storage.groups.items():
        users_to_unmute = []
        for user_id, mute_time in group.muted_users.items():
            if isinstance(mute_time, datetime) and mute_time <= current_time:
                users_to_unmute.append(user_id)
        
        for user_id in users_to_unmute:
            try:
                await unmute_user(context.bot, chat_id, user_id)
                del group.muted_users[user_id]
            except Exception as e:
                logger.error(f"Error unmuting user {user_id}: {e}")
    
    storage.save_data()

# دستورات شروع و راهنما
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            "🤖 ربات مدیریت گروه دیجی آنتی\n\n"
            "برای استفاده از ربات، آن را به گروه اضافه کنید و دسترسی ادمین کامل به آن بدهید.\n\n"
            "📋 دستورات اصلی:\n"
            "/help - نمایش راهنمای کامل\n"
            "/settings - تنظیمات گروه\n"
            "/lock - مدیریت قفل‌ها\n"
            "/filter - مدیریت فیلتر کلمات\n"
            "/warn - اخطار دادن به کاربر\n"
            "/ban - بن کردن کاربر\n"
            "/mute - سکوت کردن کاربر\n"
            "/unban - رفع بن کاربر\n"
            "/unmute - رفع سکوت کاربر\n"
            "/clean - پاکسازی گروه\n"
            "/admin - مدیریت ادمین‌ها"
        )
    else:
        await update.message.reply_text(
            "ربات دیجی آنتی فعال شد! برای مدیریت گروه از دستورات استفاده کنید.\n"
            "برای مشاهده دستورات: /help"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 **راهنمای دستورات ربات دیجی آنتی**

👥 **مدیریت کاربران:**
/ban [آیدی] - بن کردن کاربر
/unban [آیدی] - رفع بن کاربر
/banlist - لیست کاربران بن شده
/mute [آیدی] [زمان] - سکوت کاربر (زمان: 10m, 1h, 1d)
/unmute [آیدی] - رفع سکوت کاربر
/mutelist - لیست کاربران ساکت
/warn [آیدی] - اخطار دادن
/unwarn [آیدی] - حذف اخطار
/warnlist - لیست اخطارها
/kick [آیدی] - اخراج کاربر

👮 **مدیریت ادمین‌ها:**
/admin add [آیدی] - افزودن ادمین
/admin remove [آیدی] - حذف ادمین
/admin list - لیست ادمین‌ها
/special add [آیدی] - افزودن کاربر ویژه
/special remove [آیدی] - حذف کاربر ویژه
/special list - لیست کاربران ویژه

🔒 **قفل‌ها:**
/lock - نمایش منوی قفل‌ها
/lock links - قفل لینک
/lock forward - قفل فوروارد
/lock photo - قفل عکس
/unlock [نوع] - باز کردن قفل

🔤 **فیلتر کلمات:**
/filter add [کلمه] - افزودن کلمه فیلتر
/filter remove [کلمه] - حذف کلمه فیلتر
/filter list - لیست کلمات فیلتر

🧹 **نظافت:**
/clean [تعداد] - پاکسازی پیام‌ها
/clean spam - پاکسازی اسپم
/clean bans - پاکسازی لیست بن
/clean mutes - پاکسازی لیست سکوت

⚙️ **تنظیمات:**
/settings - تنظیمات گروه
/welcome [پیام] - تنظیم خوشامدگویی
/welcome on/off - فعال/غیرفعال خوشامدگویی
"""
    await update.message.reply_text(help_text)

# دستورات مدیریت کاربران
@auto_save
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    # بررسی سوپرگروه بودن
    if chat.type != ChatType.SUPERGROUP:
        await update.message.reply_text("این دستور فقط در سوپرگروه کار می‌کند!")
        return
    
    # بررسی ادمین بودن کاربر
    if not await is_admin(update, context, user.id):
        await update.message.reply_text("شما دسترسی لازم را ندارید!")
        return
    
    # بررسی ادمین بودن ربات
    if not await is_bot_admin(update, context):
        await update.message.reply_text("ربات باید ادمین با دسترسی کامل باشد!")
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("لطفاً یک کاربر را ریپلای کنید یا آیدی آن را وارد کنید!")
        return
    
    # بررسی اینکه کاربر ادمین نیست
    if await is_admin(update, context, target_user.id):
        await update.message.reply_text("شما نمی‌توانید ادمین‌ها را بن کنید!")
        return
    
    group = storage.get_group(chat.id)
    group.banned_users.add(target_user.id)
    
    try:
        await chat.ban_member(target_user.id)
        await update.message.reply_text(f"✅ کاربر {target_user.first_name} بن شد!")
    except Exception as e:
        await update.message.reply_text(f"خطا در بن کردن کاربر: {e}")

@auto_save
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("لطفاً یک کاربر را ریپلای کنید یا آیدی آن را وارد کنید!")
        return
    
    group = storage.get_group(chat.id)
    if target_user.id in group.banned_users:
        group.banned_users.remove(target_user.id)
    
    try:
        await chat.unban_member(target_user.id)
        await update.message.reply_text(f"✅ کاربر {target_user.first_name} از بن خارج شد!")
    except Exception as e:
        await update.message.reply_text(f"خطا در رفع بن کاربر: {e}")

async def banlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    group = storage.get_group(chat.id)
    
    if not group.banned_users:
        await update.message.reply_text("📭 لیست بن خالی است!")
        return
    
    message = "📋 لیست کاربران بن شده:\n\n"
    for user_id in group.banned_users:
        try:
            user = await context.bot.get_chat(user_id)
            message += f"👤 {user.first_name} - آیدی: `{user_id}`\n"
        except:
            message += f"👤 کاربر حذف شده - آیدی: `{user_id}`\n"
    
    await update.message.reply_text(message)

@auto_save
async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("لطفاً یک کاربر را ریپلای کنید یا آیدی آن را وارد کنید!")
        return
    
    if await is_admin(update, context, target_user.id):
        await update.message.reply_text("شما نمی‌توانید ادمین‌ها را سکوت کنید!")
        return
    
    # تعیین زمان سکوت
    mute_duration = None
    if context.args:
        time_arg = context.args[-1]
        if time_arg.endswith('m'):
            minutes = int(time_arg[:-1])
            mute_duration = timedelta(minutes=minutes)
        elif time_arg.endswith('h'):
            hours = int(time_arg[:-1])
            mute_duration = timedelta(hours=hours)
        elif time_arg.endswith('d'):
            days = int(time_arg[:-1])
            mute_duration = timedelta(days=days)
    
    permissions = ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False
    )
    
    group = storage.get_group(chat.id)
    
    if mute_duration:
        until_date = datetime.now() + mute_duration
        group.muted_users[target_user.id] = until_date
        try:
            await chat.restrict_member(target_user.id, permissions, until_date=until_date)
            await update.message.reply_text(f"✅ کاربر {target_user.first_name} برای {mute_duration} سکوت شد!")
        except Exception as e:
            await update.message.reply_text(f"خطا در سکوت کاربر: {e}")
    else:
        group.muted_users[target_user.id] = None  # سکوت دائمی
        try:
            await chat.restrict_member(target_user.id, permissions)
            await update.message.reply_text(f"✅ کاربر {target_user.first_name} سکوت شد!")
        except Exception as e:
            await update.message.reply_text(f"خطا در سکوت کاربر: {e}")

@auto_save
async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("لطفاً یک کاربر را ریپلای کنید یا آیدی آن را وارد کنید!")
        return
    
    group = storage.get_group(chat.id)
    if target_user.id in group.muted_users:
        del group.muted_users[target_user.id]
    
    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False
    )
    
    try:
        await chat.restrict_member(target_user.id, permissions)
        await update.message.reply_text(f"✅ کاربر {target_user.first_name} از سکوت خارج شد!")
    except Exception as e:
        await update.message.reply_text(f"خطا در رفع سکوت کاربر: {e}")

async def mutelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    group = storage.get_group(chat.id)
    
    if not group.muted_users:
        await update.message.reply_text("📭 لیست سکوت خالی است!")
        return
    
    message = "📋 لیست کاربران ساکت:\n\n"
    for user_id, mute_time in group.muted_users.items():
        try:
            user = await context.bot.get_chat(user_id)
            if mute_time:
                message += f"👤 {user.first_name} - تا: {mute_time.strftime('%Y-%m-%d %H:%M')}\n"
            else:
                message += f"👤 {user.first_name} - دائمی\n"
        except:
            message += f"👤 کاربر حذف شده - آیدی: `{user_id}`\n"
    
    await update.message.reply_text(message)

@auto_save
async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("لطفاً یک کاربر را ریپلای کنید یا آیدی آن را وارد کنید!")
        return
    
    if await is_admin(update, context, target_user.id):
        await update.message.reply_text("شما نمی‌توانید به ادمین‌ها اخطار دهید!")
        return
    
    group = storage.get_group(chat.id)
    
    if target_user.id not in group.warnings:
        group.warnings[target_user.id] = 0
    
    group.warnings[target_user.id] += 1
    
    warning_count = group.warnings[target_user.id]
    max_warnings = group.max_warnings
    
    await update.message.reply_text(
        f"⚠️ اخطار به کاربر {target_user.first_name}\n"
        f"تعداد اخطار: {warning_count}/{max_warnings}"
    )
    
    # بررسی رسیدن به حداکثر اخطار
    if warning_count >= max_warnings:
        try:
            await chat.ban_member(target_user.id)
            await update.message.reply_text(f"🚫 کاربر {target_user.first_name} به دلیل دریافت {max_warnings} اخطار بن شد!")
            group.banned_users.add(target_user.id)
            del group.warnings[target_user.id]
        except Exception as e:
            await update.message.reply_text(f"خطا در بن کردن کاربر: {e}")

@auto_save
async def unwarn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("لطفاً یک کاربر را ریپلای کنید یا آیدی آن را وارد کنید!")
        return
    
    group = storage.get_group(chat.id)
    
    if target_user.id in group.warnings:
        group.warnings[target_user.id] = max(0, group.warnings[target_user.id] - 1)
        if group.warnings[target_user.id] == 0:
            del group.warnings[target_user.id]
        
        await update.message.reply_text(f"✅ یک اخطار از کاربر {target_user.first_name} حذف شد!")
    else:
        await update.message.reply_text("این کاربر اخطاری ندارد!")

async def warnlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    group = storage.get_group(chat.id)
    
    if not group.warnings:
        await update.message.reply_text("📭 لیست اخطارها خالی است!")
        return
    
    message = "📋 لیست اخطارهای کاربران:\n\n"
    for user_id, warn_count in group.warnings.items():
        try:
            user = await context.bot.get_chat(user_id)
            message += f"👤 {user.first_name} - {warn_count} اخطار\n"
        except:
            message += f"👤 کاربر حذف شده - آیدی: `{user_id}` - {warn_count} اخطار\n"
    
    await update.message.reply_text(message)

@auto_save
async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    target_user = await get_target_user(update, context)
    if not target_user:
        await update.message.reply_text("لطفاً یک کاربر را ریپلای کنید یا آیدی آن را وارد کنید!")
        return
    
    if await is_admin(update, context, target_user.id):
        await update.message.reply_text("شما نمی‌توانید ادمین‌ها را اخراج کنید!")
        return
    
    try:
        await chat.ban_member(target_user.id)
        await asyncio.sleep(2)
        await chat.unban_member(target_user.id)
        await update.message.reply_text(f"✅ کاربر {target_user.first_name} اخراج شد!")
    except Exception as e:
        await update.message.reply_text(f"خطا در اخراج کاربر: {e}")

# مدیریت ادمین‌ها
@auto_save
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context, require_owner=True):
        return
    
    if not context.args:
        keyboard = [
            [InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin_add")],
            [InlineKeyboardButton("➖ حذف ادمین", callback_data="admin_remove")],
            [InlineKeyboardButton("📋 لیست ادمین‌ها", callback_data="admin_list")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("مدیریت ادمین‌ها:", reply_markup=reply_markup)
        return
    
    action = context.args[0].lower()
    
    if action == "add":
        if len(context.args) < 2:
            await update.message.reply_text("لطفاً آیدی کاربر را وارد کنید!")
            return
        
        target_user = await get_target_user(update, context)
        if not target_user:
            await update.message.reply_text("کاربر یافت نشد!")
            return
        
        group = storage.get_group(chat.id)
        group.admins.add(target_user.id)
        await update.message.reply_text(f"✅ کاربر {target_user.first_name} به لیست ادمین‌ها اضافه شد!")
    
    elif action == "remove":
        if len(context.args) < 2:
            await update.message.reply_text("لطفاً آیدی کاربر را وارد کنید!")
            return
        
        target_user = await get_target_user(update, context)
        if not target_user:
            await update.message.reply_text("کاربر یافت نشد!")
            return
        
        group = storage.get_group(chat.id)
        if target_user.id in group.admins:
            group.admins.remove(target_user.id)
            await update.message.reply_text(f"✅ کاربر {target_user.first_name} از لیست ادمین‌ها حذف شد!")
        else:
            await update.message.reply_text("این کاربر در لیست ادمین‌ها نیست!")
    
    elif action == "list":
        group = storage.get_group(chat.id)
        
        if not group.admins:
            await update.message.reply_text("📭 لیست ادمین‌ها خالی است!")
            return
        
        message = "📋 لیست ادمین‌های ربات:\n\n"
        for user_id in group.admins:
            try:
                user = await context.bot.get_chat(user_id)
                message += f"👤 {user.first_name} - آیدی: `{user_id}`\n"
            except:
                message += f"👤 کاربر حذف شده - آیدی: `{user_id}`\n"
        
        await update.message.reply_text(message)

# مدیریت کاربران ویژه
@auto_save
async def special_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(
            "دستورات کاربران ویژه:\n"
            "/special add [آیدی] - افزودن کاربر ویژه\n"
            "/special remove [آیدی] - حذف کاربر ویژه\n"
            "/special list - لیست کاربران ویژه"
        )
        return
    
    action = context.args[0].lower()
    group = storage.get_group(chat.id)
    
    if action == "add":
        if len(context.args) < 2:
            await update.message.reply_text("لطفاً آیدی کاربر را وارد کنید!")
            return
        
        target_user = await get_target_user(update, context)
        if not target_user:
            await update.message.reply_text("کاربر یافت نشد!")
            return
        
        group.special_users.add(target_user.id)
        await update.message.reply_text(f"✅ کاربر {target_user.first_name} به لیست کاربران ویژه اضافه شد!")
    
    elif action == "remove":
        if len(context.args) < 2:
            await update.message.reply_text("لطفاً آیدی کاربر را وارد کنید!")
            return
        
        target_user = await get_target_user(update, context)
        if not target_user:
            await update.message.reply_text("کاربر یافت نشد!")
            return
        
        if target_user.id in group.special_users:
            group.special_users.remove(target_user.id)
            await update.message.reply_text(f"✅ کاربر {target_user.first_name} از لیست کاربران ویژه حذف شد!")
        else:
            await update.message.reply_text("این کاربر در لیست کاربران ویژه نیست!")
    
    elif action == "list":
        if not group.special_users:
            await update.message.reply_text("📭 لیست کاربران ویژه خالی است!")
            return
        
        message = "📋 لیست کاربران ویژه:\n\n"
        for user_id in group.special_users:
            try:
                user = await context.bot.get_chat(user_id)
                message += f"👤 {user.first_name} - آیدی: `{user_id}`\n"
            except:
                message += f"👤 کاربر حذف شده - آیدی: `{user_id}`\n"
        
        await update.message.reply_text(message)

# مدیریت قفل‌ها
async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    if not context.args:
        keyboard = [
            [InlineKeyboardButton("🔗 قفل لینک", callback_data="lock_links")],
            [InlineKeyboardButton("📤 قفل فوروارد", callback_data="lock_forward")],
            [InlineKeyboardButton("📷 قفل عکس", callback_data="lock_photo")],
            [InlineKeyboardButton("🎥 قفل ویدیو", callback_data="lock_video")],
            [InlineKeyboardButton("🎭 قفل استیکر", callback_data="lock_sticker")],
            [InlineKeyboardButton("🔊 قفل ویس", callback_data="lock_voice")],
            [InlineKeyboardButton("📄 قفل فایل", callback_data="lock_file")],
            [InlineKeyboardButton("🤖 قفل ربات‌ها", callback_data="lock_bots")],
            [InlineKeyboardButton("📞 قفل شماره", callback_data="lock_phone")],
            [InlineKeyboardButton("@ قفل منشن", callback_data="lock_mentions")],
            [InlineKeyboardButton("# قفل هشتگ", callback_data="lock_hashtags")],
            [InlineKeyboardButton("😀 قفل ایموجی", callback_data="lock_emoji")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("انتخاب نوع قفل:", reply_markup=reply_markup)
        return
    
    lock_type_str = context.args[0].lower()
    try:
        lock_type = LockType(lock_type_str)
        group = storage.get_group(chat.id)
        group.locks[lock_type] = True
        await update.message.reply_text(f"✅ قفل {lock_type.value} فعال شد!")
    except ValueError:
        await update.message.reply_text("نوع قفل نامعتبر است!")

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    if not context.args:
        await update.message.reply_text("لطفاً نوع قفل را مشخص کنید!")
        return
    
    lock_type_str = context.args[0].lower()
    try:
        lock_type = LockType(lock_type_str)
        group = storage.get_group(chat.id)
        group.locks[lock_type] = False
        await update.message.reply_text(f"✅ قفل {lock_type.value} غیرفعال شد!")
    except ValueError:
        await update.message.reply_text("نوع قفل نامعتبر است!")

# مدیریت فیلتر کلمات
@auto_save
async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(
            "دستورات فیلتر کلمات:\n"
            "/filter add [کلمه] - افزودن کلمه فیلتر\n"
            "/filter remove [کلمه] - حذف کلمه فیلتر\n"
            "/filter list - لیست کلمات فیلتر\n"
            "/filter clear - پاکسازی لیست فیلتر"
        )
        return
    
    action = context.args[0].lower()
    group = storage.get_group(chat.id)
    
    if action == "add":
        if len(context.args) < 2:
            await update.message.reply_text("لطفاً کلمه مورد نظر را وارد کنید!")
            return
        
        word = ' '.join(context.args[1:])
        group.filtered_words.add(word.lower())
        await update.message.reply_text(f"✅ کلمه '{word}' به لیست فیلتر اضافه شد!")
    
    elif action == "remove":
        if len(context.args) < 2:
            await update.message.reply_text("لطفاً کلمه مورد نظر را وارد کنید!")
            return
        
        word = ' '.join(context.args[1:])
        if word.lower() in group.filtered_words:
            group.filtered_words.remove(word.lower())
            await update.message.reply_text(f"✅ کلمه '{word}' از لیست فیلتر حذف شد!")
        else:
            await update.message.reply_text("این کلمه در لیست فیلتر وجود ندارد!")
    
    elif action == "list":
        if not group.filtered_words:
            await update.message.reply_text("📭 لیست کلمات فیلتر خالی است!")
            return
        
        message = "📋 لیست کلمات فیلتر شده:\n\n"
        for word in group.filtered_words:
            message += f"• {word}\n"
        
        await update.message.reply_text(message)
    
    elif action == "clear":
        group.filtered_words.clear()
        await update.message.reply_text("✅ لیست کلمات فیلتر پاکسازی شد!")

# دستورات نظافت
async def clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(
            "دستورات نظافت:\n"
            "/clean [تعداد] - حذف تعداد مشخصی پیام\n"
            "/clean spam - پاکسازی اسپم\n"
            "/clean bans - پاکسازی لیست بن\n"
            "/clean mutes - پاکسازی لیست سکوت\n"
            "/clean warns - پاکسازی اخطارها"
        )
        return
    
    action = context.args[0].lower()
    group = storage.get_group(chat.id)
    
    if action.isdigit():
        count = int(action)
        if count > 100:
            count = 100
        
        deleted_count = 0
        try:
            async for message in chat.history(limit=count + 1):
                if message.message_id != update.message.message_id:
                    try:
                        await message.delete()
                        deleted_count += 1
                        await asyncio.sleep(0.1)
                    except:
                        pass
            
            msg = await update.message.reply_text(f"✅ {deleted_count} پیام حذف شد!")
            await asyncio.sleep(3)
            await msg.delete()
            
        except Exception as e:
            await update.message.reply_text(f"خطا در حذف پیام‌ها: {e}")
    
    elif action == "spam":
        # پاکسازی پیام‌های اسپم
        await update.message.reply_text("این قابلیت نیاز به توسعه بیشتر دارد!")
    
    elif action == "bans":
        group.banned_users.clear()
        await update.message.reply_text("✅ لیست بن پاکسازی شد!")
    
    elif action == "mutes":
        group.muted_users.clear()
        await update.message.reply_text("✅ لیست سکوت پاکسازی شد!")
    
    elif action == "warns":
        group.warnings.clear()
        await update.message.reply_text("✅ لیست اخطارها پاکسازی شد!")

# تنظیمات گروه
@auto_save
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    group = storage.get_group(chat.id)
    
    locks_status = ""
    for lock_type in LockType:
        if group.locks[lock_type]:
            locks_status += f"✅ {lock_type.value}\n"
    
    settings_text = f"""
⚙️ **تنظیمات گروه {chat.title}**

🔒 **قفل‌های فعال:**
{locks_status if locks_status else "هیچ قفلی فعال نیست"}

👥 **آمار:**
کاربران بن شده: {len(group.banned_users)}
کاربران ساکت: {len(group.muted_users)}
کلمات فیلتر: {len(group.filtered_words)}
اخطارها: {sum(group.warnings.values())}

📊 **تنظیمات:**
حداکثر اخطار: {group.max_warnings}
خوشامدگویی: {'فعال ✅' if group.welcome_enabled else 'غیرفعال ❌'}
    """
    
    keyboard = [
        [InlineKeyboardButton("🔧 تغییر حداکثر اخطار", callback_data="set_max_warn")],
        [InlineKeyboardButton(f"{'❌ غیرفعال' if group.welcome_enabled else '✅ فعال'} خوشامدگویی", 
                              callback_data="toggle_welcome")],
        [InlineKeyboardButton("📝 ویرایش پیام خوشامد", callback_data="edit_welcome")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(settings_text, reply_markup=reply_markup)

@auto_save
async def welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if not await check_permissions(update, context):
        return
    
    if not context.args:
        await update.message.reply_text(
            "دستورات خوشامدگویی:\n"
            "/welcome [پیام] - تنظیم پیام خوشامد\n"
            "میتوانید از متغیرها استفاده کنید:\n"
            "{user} - نام کاربر\n"
            "{chat} - نام گروه\n"
            "{time} - زمان فعلی\n\n"
            "/welcome on - فعال کردن خوشامدگویی\n"
            "/welcome off - غیرفعال کردن خوشامدگویی\n"
            "مثال: /welcome خوش آمدی {user} به گروه {chat}!"
        )
        return
    
    group = storage.get_group(chat.id)
    
    if context.args[0].lower() == "on":
        group.welcome_enabled = True
        await update.message.reply_text("✅ خوشامدگویی فعال شد!")
    
    elif context.args[0].lower() == "off":
        group.welcome_enabled = False
        await update.message.reply_text("✅ خوشامدگویی غیرفعال شد!")
    
    else:
        welcome_message = ' '.join(context.args)
        group.welcome_message = welcome_message
        await update.message.reply_text("✅ پیام خوشامدگویی تنظیم شد!")

# هندلر پیام‌ها برای اعمال قوانین
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    
    chat = update.effective_chat
    user = update.message.from_user
    message = update.message
    
    # بررسی سوپرگروه
    if chat.type != ChatType.SUPERGROUP:
        return
    
    # بررسی ادمین بودن ربات
    if not await is_bot_admin(update, context):
        return
    
    group = storage.get_group(chat.id)
    
    # بررسی کاربران ویژه
    if user.id in group.special_users:
        return
    
    # بررسی بن بودن کاربر
    if user.id in group.banned_users:
        try:
            await message.delete()
        except:
            pass
        return
    
    # بررسی سکوت بودن کاربر
    if user.id in group.muted_users:
        try:
            await message.delete()
        except:
            pass
        return
    
    # بررسی کلمات فیلتر
    if message.text and group.filtered_words:
        text = message.text.lower()
        for word in group.filtered_words:
            if word in text:
                try:
                    await message.delete()
                    
                    # افزایش اخطار
                    if user.id not in group.warnings:
                        group.warnings[user.id] = 0
                    group.warnings[user.id] += 1
                    
                    warning_count = group.warnings[user.id]
                    if warning_count >= group.max_warnings:
                        await chat.ban_member(user.id)
                        await message.reply_text(
                            f"🚫 کاربر {user.first_name} به دلیل استفاده از کلمات ممنوعه بن شد!"
                        )
                    else:
                        await message.reply_text(
                            f"⚠️ کاربر {user.first_name} به دلیل استفاده از کلمات ممنوعه اخطار دریافت کرد!\n"
                            f"تعداد اخطار: {warning_count}/{group.max_warnings}"
                        )
                    
                    storage.save_data()
                except:
                    pass
                return
    
    # بررسی قفل‌ها
    if group.locks[LockType.LINKS] and contains_links(message):
        await delete_message_with_notice(message, "ارسال لینک در این گروه ممنوع است!")
        return
    
    if group.locks[LockType.PHOTO] and message.photo:
        await delete_message_with_notice(message, "ارسال عکس در این گروه ممنوع است!")
        return
    
    if group.locks[LockType.VIDEO] and message.video:
        await delete_message_with_notice(message, "ارسال ویدیو در این گروه ممنوع است!")
        return
    
    if group.locks[LockType.STICKER] and message.sticker:
        await delete_message_with_notice(message, "ارسال استیکر در این گروه ممنوع است!")
        return
    
    if group.locks[LockType.VOICE] and message.voice:
        await delete_message_with_notice(message, "ارسال ویس در این گروه ممنوع است!")
        return
    
    if group.locks[LockType.FILE] and message.document:
        await delete_message_with_notice(message, "ارسال فایل در این گروه ممنوع است!")
        return
    
    if group.locks[LockType.FORWARD] and message.forward_date:
        await delete_message_with_notice(message, "فوروارد پیام در این گروه ممنوع است!")
        return
    
    if group.locks[LockType.BOTS] and message.new_chat_members:
        for new_member in message.new_chat_members:
            if new_member.is_bot:
                try:
                    await chat.ban_member(new_member.id)
                    await message.reply_text(f"🤖 ربات {new_member.first_name} از گروه حذف شد!")
                except:
                    pass
                return
    
    # تشخیص اسپم
    await detect_spam(message, group, context)

# هندلر کاربران جدید
async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    
    chat = update.effective_chat
    group = storage.get_group(chat.id)
    
    if not group.welcome_enabled:
        return
    
    for new_member in update.message.new_chat_members:
        # ثبت زمان ورود
        group.user_join_times[new_member.id] = datetime.now()
        
        # ارسال پیام خوشامد
        welcome_msg = group.welcome_message
        welcome_msg = welcome_msg.replace("{user}", new_member.first_name)
        welcome_msg = welcome_msg.replace("{chat}", chat.title)
        welcome_msg = welcome_msg.replace("{time}", datetime.now().strftime("%H:%M"))
        
        await update.message.reply_text(welcome_msg)

# هندلر کاربران خروج
async def left_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    
    chat = update.effective_chat
    left_member = update.message.left_chat_member
    
    # حذف از لیست‌ها
    group = storage.get_group(chat.id)
    
    if left_member.id in group.banned_users:
        group.banned_users.remove(left_member.id)
    
    if left_member.id in group.muted_users:
        del group.muted_users[left_member.id]
    
    if left_member.id in group.warnings:
        del group.warnings[left_member.id]
    
    if left_member.id in group.user_join_times:
        del group.user_join_times[left_member.id]
    
    storage.save_data()

# توابع کمکی
async def check_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE, require_owner: bool = False) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type != ChatType.SUPERGROUP:
        await update.message.reply_text("❌ این دستور فقط در سوپرگروه کار می‌کند!")
        return False
    
    if not await is_bot_admin(update, context):
        await update.message.reply_text("❌ ربات باید ادمین با دسترسی کامل باشد!")
        return False
    
    if not await is_admin(update, context, user.id):
        await update.message.reply_text("❌ شما دسترسی لازم را ندارید!")
        return False
    
    if require_owner:
        chat_member = await chat.get_member(user.id)
        if chat_member.status != ChatMemberStatus.OWNER:
            await update.message.reply_text("❌ فقط صاحب گروه می‌تواند از این دستور استفاده کند!")
            return False
    
    return True

async def is_bot_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    try:
        bot_member = await chat.get_member(context.bot.id)
        return (bot_member.status == ChatMemberStatus.ADMINISTRATOR and 
                bot_member.can_restrict_members and 
                bot_member.can_delete_messages)
    except:
        return False

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    chat = update.effective_chat
    group = storage.get_group(chat.id)
    
    # بررسی لیست ادمین‌های ربات
    if user_id in group.admins:
        return True
    
    # بررسی ادمین‌های تلگرام
    try:
        chat_member = await chat.get_member(user_id)
        return chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except:
        return False

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    
    if context.args:
        try:
            user_id = int(context.args[0])
            return await context.bot.get_chat(user_id)
        except:
            # ممکن است username باشد
            username = context.args[0].lstrip('@')
            try:
                return await context.bot.get_chat(username)
            except:
                return None
    
    return None

async def unmute_user(bot, chat_id: int, user_id: int):
    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False
    )
    
    await bot.restrict_chat_member(chat_id, user_id, permissions)

def contains_links(message) -> bool:
    if message.text:
        # الگوی ساده برای تشخیص لینک
        import re
        pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        return bool(re.search(pattern, message.text))
    return False

async def delete_message_with_notice(message, notice: str):
    try:
        await message.delete()
        notice_msg = await message.reply_text(f"⚠️ {notice}")
        await asyncio.sleep(5)
        await notice_msg.delete()
    except:
        pass

async def detect_spam(message, group, context: ContextTypes.DEFAULT_TYPE):
    user_id = message.from_user.id
    current_time = datetime.now()
    
    # ثبت پیام
    group.last_messages.append({
        'user_id': user_id,
        'time': current_time,
        'message_id': message.message_id
    })
    
    # نگه داشتن فقط 10 پیام آخر
    if len(group.last_messages) > 10:
        group.last_messages.pop(0)
    
    # بررسی اسپم: 5 پیام در 10 ثانیه
    user_messages = [m for m in group.last_messages if m['user_id'] == user_id]
    if len(user_messages) >= 5:
        time_diff = (current_time - user_messages[0]['time']).total_seconds()
        if time_diff <= 10:
            try:
                await message.chat.ban_member(user_id)
                await message.reply_text(f"🚫 کاربر {message.from_user.first_name} به دلیل اسپم بن شد!")
                group.banned_users.add(user_id)
                storage.save_data()
            except:
                pass

# هندلر دکمه‌های اینلاین
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat = update.effective_chat
    user = update.effective_user
    
    if not await is_admin(update, context, user.id):
        await query.message.reply_text("❌ شما دسترسی لازم را ندارید!")
        return
    
    data = query.data
    group = storage.get_group(chat.id)
    
    if data.startswith("lock_"):
        lock_type_str = data[5:]
        try:
            lock_type = LockType(lock_type_str)
            current_status = group.locks[lock_type]
            group.locks[lock_type] = not current_status
            
            status_text = "فعال ✅" if not current_status else "غیرفعال ❌"
            await query.message.reply_text(f"قفل {lock_type.value} {status_text} شد!")
            
            # به‌روزرسانی پیام
            keyboard = [
                [InlineKeyboardButton(f"{'❌' if group.locks[LockType.LINKS] else '✅'} لینک", 
                                      callback_data="lock_links")],
                [InlineKeyboardButton(f"{'❌' if group.locks[LockType.FORWARD] else '✅'} فوروارد", 
                                      callback_data="lock_forward")],
                # اضافه کردن دکمه‌های دیگر...
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_reply_markup(reply_markup)
            
            storage.save_data()
        except ValueError:
            pass
    
    elif data == "set_max_warn":
        await query.message.reply_text("لطفاً تعداد اخطار مجاز را وارد کنید (عدد بین 1 تا 10):")
        # نیاز به پیاده‌سازی سیستم حالت
    
    elif data == "toggle_welcome":
        group.welcome_enabled = not group.welcome_enabled
        status = "فعال ✅" if group.welcome_enabled else "غیرفعال ❌"
        await query.message.reply_text(f"خوشامدگویی {status} شد!")
        storage.save_data()
    
    elif data == "edit_welcome":
        await query.message.reply_text(
            "لطفاً پیام خوشامد جدید را ارسال کنید:\n"
            "میتوانید از متغیرها استفاده کنید:\n"
            "{user} - نام کاربر\n"
            "{chat} - نام گروه\n"
            "{time} - زمان فعلی"
        )
        # نیاز به پیاده‌سازی سیستم حالت

# تایمرهای دوره‌ای
async def periodic_tasks(context: ContextTypes.DEFAULT_TYPE):
    # بررسی سکوت‌های زمان‌دار
    await check_mute_timers(context)
    
    # پاکسازی کاربران غیرفعال
    await clean_inactive_users(context)

async def clean_inactive_users(context: ContextTypes.DEFAULT_TYPE):
    current_time = datetime.now()
    for chat_id, group in storage.groups.items():
        users_to_remove = []
        for user_id, join_time in group.user_join_times.items():
            if (current_time - join_time).days > 30:
                users_to_remove.append(user_id)
        
        for user_id in users_to_remove:
            del group.user_join_times[user_id]
    
    storage.save_data()

# تنظیم ربات
def main():
    # ایجاد اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # دستورات اصلی
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # دستورات مدیریت کاربران
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("banlist", banlist_command))
    application.add_handler(CommandHandler("mute", mute_command))
    application.add_handler(CommandHandler("unmute", unmute_command))
    application.add_handler(CommandHandler("mutelist", mutelist_command))
    application.add_handler(CommandHandler("warn", warn_command))
    application.add_handler(CommandHandler("unwarn", unwarn_command))
    application.add_handler(CommandHandler("warnlist", warnlist_command))
    application.add_handler(CommandHandler("kick", kick_command))
    
    # مدیریت ادمین‌ها
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("special", special_command))
    
    # قفل‌ها
    application.add_handler(CommandHandler("lock", lock_command))
    application.add_handler(CommandHandler("unlock", unlock_command))
    
    # فیلتر کلمات
    application.add_handler(CommandHandler("filter", filter_command))
    
    # نظافت
    application.add_handler(CommandHandler("clean", clean_command))
    
    # تنظیمات
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("welcome", welcome_command))
    
    # هندلرهای پیام
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_handler(MessageHandler(filters.PHOTO, message_handler))
    application.add_handler(MessageHandler(filters.VIDEO, message_handler))
    application.add_handler(MessageHandler(filters.STICKER, message_handler))
    application.add_handler(MessageHandler(filters.VOICE, message_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, message_handler))
    
    # هندلرهای کاربران
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, left_member_handler))
    
    # هندلر دکمه‌ها
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # تایمرهای دوره‌ای
    job_queue = application.job_queue
    job_queue.run_repeating(periodic_tasks, interval=60, first=10)  # هر 1 دقیقه
    
    # شروع ربات
    print("🤖 ربات دیجی آنتی شروع به کار کرد...")
    application.run_polling(allowed_updates=Update.ALL_UPDATES)

if __name__ == '__main__':
    main()