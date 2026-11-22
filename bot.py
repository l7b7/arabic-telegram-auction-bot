import sys
import urllib.parse
import os
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

# 
# 
# استيراد المكتبات 
# 



import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import sqlite3
from datetime import datetime, timedelta
import random
import re
import logging
import threading
import time
import json
import hashlib
import ssl
import traceback
import certifi
from collections import defaultdict, deque

# Binance 
try:
    from binance.client import Client as BinanceClient
    from binance.exceptions import BinanceAPIException
    BINANCE_ENABLED = True
except ImportError:
    BINANCE_ENABLED = False
    logging.warning("python-binance غير مثبت — بوابة الدفع معطلة")

# تكوين السجلات
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# إعدادات البوت — تُقرأ من متغيرات البيئة (.env) لحماية البيانات الحساسة
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and configure it.")
if OWNER_ID == 0:
    raise RuntimeError("OWNER_ID is missing. Set it in the environment.")
DATABASE_PATH = os.getenv("DATABASE_PATH", "auction_bot.db")

# (تم حذف إعدادات API الخارجية — الذكاء الاصطناعي مدمج محلياً)

# إعدادات بوابة الدفع (Binance) 

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
# سعر الصرف الافتراضي (يُستخدم عند فشل جلب السعر من Binance)
USDT_TO_USD_RATE_FALLBACK = 1.0  # 1 USDT = $1
# نسبة الخصم على سعر كريبتو (7.62% → السعر الداخلي = سعر السوق × (1 - 0.0762))
USDT_DISCOUNT_RATE = 0.0

def get_usdt_rate() -> float:
    """1 USDT = 1 USD — العملة الداخلية هي الدولار الأمريكي"""
    return 1.0

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    BINANCE_ENABLED = False

if BINANCE_ENABLED:
    try:
        binance_client = BinanceClient(BINANCE_API_KEY, BINANCE_API_SECRET)
    except Exception:
        binance_client = None
        BINANCE_ENABLED = False
else:
    binance_client = None

# إعدادات السحب
MIN_WITHDRAW = 1.0          # الحد الأدنى للسحب بالدولار
WITHDRAW_FEE_PERCENT = 0.0  # رسوم السحب (0 = بدون رسوم)
MAX_WITHDRAWALS_PER_DAY = 3 # أقصى عدد طلبات سحب في اليوم

# معلومات زين كاش للشحن (تُعدَّل من .env أو مباشرة)
ZAIN_CASH_PHONE = os.getenv("ZAIN_CASH_PHONE", "")
ASIACELL_PHONE = os.getenv("ASIACELL_PHONE", "")

# معلومات كي كارد للشحن
KYCARD_NUMBER = os.getenv("KYCARD_NUMBER", "XXXX-XXXX-XXXX")
KYCARD_NAME   = os.getenv("KYCARD_NAME",   "اسم صاحب البطاقة")

# خطط الشحن عبر Binance 
CHARGE_PLANS = {
    'plan_5':   {'usdt': 5,   'usd': 5.0,   'label': '$5  — 5 USDT'},
    'plan_10':  {'usdt': 10,  'usd': 10.0,  'label': '$10 — 10 USDT'},
    'plan_25':  {'usdt': 25,  'usd': 25.0,  'label': '$25 — 25 USDT'},
    'plan_50':  {'usdt': 50,  'usd': 50.0,  'label': '$50 — 50 USDT'},
    'plan_100': {'usdt': 100, 'usd': 100.0, 'label': '$100 — 100 USDT'},
}

# خطط الشحن عبر نجوم تيليجرام 
# كل نجمة = كم$؟
STAR_TO_USD_RATE = 0.017  # كل نجمة = $0.017 (تقريباً)
# كل نجمة ≈ $0.017
STARS_PLANS = {
    'stars_60':  {'stars': 60,   'usd': 1.0,   'label': '60 نجمة  — $1'},
    'stars_300': {'stars': 300,  'usd': 5.0,   'label': '300 نجمة — $5'},
    'stars_600': {'stars': 600,  'usd': 10.0,  'label': '600 نجمة — $10'},
    'stars_1500':{'stars': 1500, 'usd': 25.0,  'label': '1500 نجمة — $25'},
    'stars_3000':{'stars': 3000, 'usd': 50.0,  'label': '3000 نجمة — $50'},
    'stars_6000':{'stars': 6000, 'usd': 100.0, 'label': '6000 نجمة — $100'},
}

def md_escape(text: str) -> str:
    """يؤمّن النص من كسر تنسيق Markdown في تيليجرام (V1)"""
    if not text:
        return ""
    # الأحرف الخاصة في Markdown V1: _ * ` [
    return str(text).replace('_', r'\_').replace('*', r'\*').replace('`', r'\`').replace('[', r'\[')

# 
# أدوات تنسيق HTML — تُستخدم في كل رسائل البوت بدل Markdown 
# 

def html_escape(text) -> str:
    """يؤمّن أي نص قبل إدراجه داخل رسالة HTML (يمنع كسر التنسيق أو حقن أكواد)"""
    if text is None:
        return ""
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )

def hb(text) -> str:
    """نص عريض (Bold) — يهرّب المحتوى أولاً"""
    return f"<b>{html_escape(text)}</b>"

def hi(text) -> str:
    """نص مائل (Italic) — يهرّب المحتوى أولاً"""
    return f"<i>{html_escape(text)}</i>"

def hc(text) -> str:
    """نص أحادي المسافة (Code/Mono) — يهرّب المحتوى أولاً، مفيد للأرقام والمعرّفات"""
    return f"<code>{html_escape(text)}</code>"

def hquote(text) -> str:
    """اقتباس مرئي (Blockquote) — يهرّب المحتوى أولاً"""
    return f"<blockquote>{html_escape(text)}</blockquote>"

def hlink(text, url) -> str:
    """رابط نصي قابل للنقر"""
    return f'<a href="{html_escape(url)}">{html_escape(text)}</a>'

DIVIDER = "━━━━━━━━━━━━━━━━━━━"

# ====== نظام التنقل الذكي (Smart Back Navigation) ======
# كل مستخدم عنده stack من آخر 8 صفحات زار
_nav_stacks: dict = defaultdict(lambda: deque(maxlen=8))
_nav_lock = threading.Lock()

# خريطة اسم الصفحة → اسم عربي جميل (للـ breadcrumb)
NAV_LABELS = {
    "back_to_main":   "🏠 الرئيسية",
    "wallet":         "👛 المحفظة",
    "show_auctions":  "📋 المزادات",
    "my_auctions":    "📦 مزاداتي",
    "my_bids":        "🙋 مزايداتي",
    "show_contests":  "🎯 المسابقات",
    "my_cards":       "🃏 كروتي",
    "charge":         "📥 الشحن",
    "transfer_money": "🔄 التحويل",
    "admin_panel":    "🔧 الإدارة",
    "admin_contests": "🎯 مسابقات الإدارة",
    "admin_brokers":  "🤝 الوسطاء",
    "admin_agents":   "🧑‍💼 الوكلاء",
    "my_broker_panel":"🤝 لوحة الوسيط",
    "my_agent_panel": "🤝 لوحة الوكيل",
    "show_agents":    "🧑‍💼 الوكلاء",
    "show_brokers":   "🤝 الوسطاء",
    "lucky_wheel":    "🎰 عجلة الحظ",
    "ai_support":     "🛠️ الدعم الفني",
    "rules":          "📜 القوانين",
    "balance":        "💰 الرصيد",
    "wallet_history": "📋 سجل العمليات",
    "new_auction":    "📢 نشر مزاد",
    "withdraw_request":"📤 سحب الرصيد",
}

def nav_push(user_id: int, page: str):
    """أضف صفحة لـ stack التنقل الخاص بالمستخدم."""
    with _nav_lock:
        stack = _nav_stacks[user_id]
        # لا تضيف نفس الصفحة مرتين متتاليتين
        if not stack or stack[-1] != page:
            stack.append(page)

def nav_pop(user_id: int) -> str:
    """ارجع للصفحة السابقة. لو ما في سابقة ارجع للرئيسية."""
    with _nav_lock:
        stack = _nav_stacks[user_id]
        if len(stack) >= 2:
            stack.pop()  # الصفحة الحالية
            return stack[-1]  # الصفحة السابقة
        elif len(stack) == 1:
            stack.pop()
        return "back_to_main"

def nav_peek(user_id: int) -> str:
    """اطلع على الصفحة الحالية بدون حذف."""
    with _nav_lock:
        stack = _nav_stacks[user_id]
        return stack[-1] if stack else "back_to_main"

def nav_prev(user_id: int) -> str:
    """اطلع على الصفحة اللي قبل الحالية (الـ back destination) بدون حذف."""
    with _nav_lock:
        stack = _nav_stacks[user_id]
        if len(stack) >= 2:
            return stack[-2]
        return "back_to_main"

def nav_clear(user_id: int):
    """امسح stack التنقل."""
    with _nav_lock:
        _nav_stacks[user_id].clear()

def nav_back_button(user_id: int, fallback: str = "back_to_main") -> "types.InlineKeyboardButton":
    """ارجع زر رجوع ذكي يشير للصفحة الفعلية السابقة."""
    prev = nav_prev(user_id)
    if not prev:
        prev = fallback
    label = NAV_LABELS.get(prev, "🔙 رجوع")
    # نستخدم callback خاص nav_back_ لتشغيل nav_pop
    return types.InlineKeyboardButton(f"🔙 {label.split(' ', 1)[-1]}", callback_data=f"nav_back", style="primary")

# ====== تصنيف موحّد لأنواع العمليات المالية — يُستخدم في سجل العمليات وإحصائيات المحفظة ======
# كل عنصر: (مُعرّف التصنيف، التسمية المعروضة، قائمة أنواع العمليات الحقيقية المخزنة في عمود type)
TX_CATEGORIES = [
    ('charge',    '💰 الشحن',              ['recharge_code', 'binance_deposit', 'stars_deposit', 'charge_manual', 'agent_charge']),
    ('transfers', '🔄 التحويلات والهدايا',   ['transfer_sent', 'transfer_received', 'gift_link_sent', 'gift_link_received', 'transfer_code_sent', 'transfer_code_received']),
    ('auctions',  '🏆 المزادات',            ['auction_bid', 'auction_sale', 'auction_starting_price', 'commission', 'bid_refund', 'starting_price_refund', 'refund']),
    ('wheel',     '🎡 عجلة الحظ',           ['lucky_wheel', 'weekly_bonus_wheel']),
    ('withdraw',  '📤 السحب',               ['withdraw', 'withdrawal_pending', 'withdrawal_refund']),
    ('agent_ops', '🧑‍💼 عمليات الوكيل',      ['agent_code_create', 'agent_transfer', 'agent_transfer_out']),
    ('admin',     '🛠️ تعديلات الإدارة',      ['admin_add', 'admin_deduct', 'admin_adjustment']),
]

# تسمية عربية مفصّلة لكل نوع عملية — تُستخدم عند عرض تفاصيل العملية في سجل العمليات
TX_TYPE_LABELS = {
    'recharge_code': 'شحن - كود', 'binance_deposit': 'شحن - Binance',
    'stars_deposit': 'شحن - نجوم تيليجرام', 'charge_manual': 'شحن يدوي',
    'agent_charge': 'شحن عبر وكيل',
    'transfer_sent': 'تحويل صادر', 'transfer_received': 'تحويل وارد',
    'gift_link_sent': 'هدية مرسلة', 'gift_link_received': 'هدية مستلمة',
    'transfer_code_sent': 'كود تحويل صادر', 'transfer_code_received': 'كود تحويل وارد',
    'auction_bid': 'مزايدة', 'auction_sale': 'بيع مزاد',
    'auction_starting_price': 'سعر بدء مزاد', 'commission': 'عمولة نشر',
    'bid_refund': 'استرداد مزايدة', 'starting_price_refund': 'استرداد سعر بدء',
    'refund': 'استرداد (مزاد مرفوض)',
    'lucky_wheel': 'عجلة الحظ', 'weekly_bonus_wheel': 'العجلة الأسبوعية المجانية',
    'withdraw': 'طلب سحب', 'withdrawal_pending': 'سحب قيد الانتظار',
    'withdrawal_refund': 'استرداد سحب مرفوض',
    'agent_code_create': 'إنشاء كود شحن (وكيل)', 'agent_transfer': 'تحويل من وكيل',
    'agent_transfer_out': 'تحويل وكيل صادر',
    'admin_add': 'إضافة من الإدارة', 'admin_deduct': 'خصم من الإدارة',
    'admin_adjustment': 'تعديل إداري',
}

# رموز الخط الدوّار في منتصف عجلة الحظ — يعطي إحساس "السهم يدور" بين الإطارات
WHEEL_SPIN_GLYPHS = ["│", "╲", "─", "╱"]

# ====== عجلة الحظ بشكل أزرار حقيقية (بدلاً من رسم نصي) — ترتيب القطاعات حول الحلقة ======
WHEEL_LEFT_ORDER = [13, 12, 11, 10]   # من الأعلى للأسفل على الجانب الأيسر
WHEEL_RIGHT_ORDER = [3, 4, 5, 6]      # من الأعلى للأسفل على الجانب الأيمن

def _wheel_seg_button(segs, idx, active_idx=-1, won_idx=None):
    """زر شفاف يمثل قطاعاً واحداً من عجلة الحظ، مع تمييز القطاع النشط/الفائز"""
    value = segs[idx]
    if won_idx is not None and idx == won_idx:
        label = f"🏆 {value}$ 🏆"
    elif idx == active_idx and won_idx is None:
        label = f"🔸{value}$🔸"
    else:
        label = f"{value}$"
    return types.InlineKeyboardButton(label, callback_data=f"wheel_info_{value}")

def build_wheel_keyboard(segs, active_idx=-1, spin_glyph=None, won_idx=None, extra_rows=None):
    """
    يبني لوحة مفاتيح تمثل عجلة الحظ بشكل دائري منظم:
    صف علوي (3 قطاعات) + 4 صفوف وسطى (قطاع يسار / مؤشر دوّار في المنتصف / قطاع يمين) + صف سفلي (3 قطاعات).
    أزرار القطاعات شفافة وتعرض القيمة، والمؤشر الأوسط يدور بين إطارات الدوران ليعطي إحساس "السهم/الخط الذي يحدد الجائزة".
    """
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        _wheel_seg_button(segs, 0, active_idx, won_idx),
        _wheel_seg_button(segs, 1, active_idx, won_idx),
        _wheel_seg_button(segs, 2, active_idx, won_idx),
    )
    glyph = spin_glyph if spin_glyph else ("🎯" if won_idx is not None else "·")
    for li, ri in zip(WHEEL_LEFT_ORDER, WHEEL_RIGHT_ORDER):
        keyboard.row(
            _wheel_seg_button(segs, li, active_idx, won_idx),
            types.InlineKeyboardButton(glyph, callback_data="wheel_spin_indicator"),
            _wheel_seg_button(segs, ri, active_idx, won_idx),
        )
    keyboard.row(
        _wheel_seg_button(segs, 9, active_idx, won_idx),
        _wheel_seg_button(segs, 8, active_idx, won_idx),
        _wheel_seg_button(segs, 7, active_idx, won_idx),
    )
    if extra_rows:
        for row in extra_rows:
            keyboard.row(*row)
    return keyboard

def fmt_money(amount) -> str:
    """تنسيق موحّد للمبالغ المالية بالدولار"""
    try:
        return f"{float(amount):,.2f}$"
    except (TypeError, ValueError):
        return f"{amount}$"

def progress_bar(ratio: float, length: int = 10) -> str:
    """شريط تقدّم مرئي (▰/▱) — يُستخدم لعرض الوقت المتبقي في المزادات بشكل احترافي"""
    ratio = max(0.0, min(1.0, ratio))
    filled = int(round(ratio * length))
    return "▰" * filled + "▱" * (length - filled)

def auction_time_block(ends_at_dt, duration_hours: float = None, created_at_dt=None) -> str:
    """
    يُعيد سطرين جاهزين: الوقت المتبقي بصيغة مقروءة + شريط تقدّم مرئي.
    يحسب النسبة بالاعتماد على وقت الإنشاء والمدة الكلية إن توفّرا، وإلا يفترض تقدّماً افتراضياً.
    """
    if not ends_at_dt:
        return f"⏳ {hb('الوقت المتبقي:')} غير محدد"

    now = datetime.now()
    diff = (ends_at_dt - now).total_seconds()

    if diff <= 0:
        return f"⏳ {hb('الوقت المتبقي:')} انتهى المزاد {progress_bar(0)}"

    h = int(diff // 3600)
    m = int((diff % 3600) // 60)
    time_str = f"{h}:{m:02d} ساعة" if h > 0 else f"{m} دقيقة"

    if created_at_dt and duration_hours:
        total_seconds = max(duration_hours * 3600, 1)
        ratio = diff / total_seconds
    else:
        # تقدير تقريبي إذا لم تتوفر بيانات الإنشاء (لا يكسر العرض، فقط أقل دقة)
        ratio = min(1.0, diff / (5 * 3600))

    bar = progress_bar(ratio)
    return f"⏳ {hb('الوقت المتبقي:')} {time_str}\n{bar}"

# إصلاح مشكلة شهادات SSL
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
os.environ['SSL_CERT_FILE'] = certifi.where()

# إنشاء البوت
bot = telebot.TeleBot(BOT_TOKEN)

# ===== إيموجي بريميوم مخصص (Custom Emoji - Bot API 9.4) =====
# ⚠️ يشتغل فقط إذا مالك البوت (صاحب التوكن) عنده اشتراك Telegram Premium،
# أو إذا البوت اشترى يوزرنيمات إضافية من Fragment.
#
# الباكيج المستخدم: https://t.me/addemoji/tgiosicons
# يتم تحميل كل الإيموجي وأيدياتها (custom_emoji_id) تلقائياً من تيليجرام عند تشغيل البوت،
# وتُربط بأسماء مفهومة بالقاموس CUSTOM_EMOJI أدناه عبر EMOJI_NAME_MAP.

CUSTOM_EMOJI_SET_NAME = "tgiosicons"

# ربط: اسم مستخدم بالكود ⇄ الإيموجي (يونيكود) الموجود فعلياً داخل الباكيج.
# إذا الإيموجي اليونيكود تغير بالباكيج، حدّث القيمة هنا فقط (مو بكل الكود).
EMOJI_NAME_MAP = {
    "fire": "🔥",
    "success": "✅",
    "hammer": "🔨",
    "money": "💰",
    "bell": "🔔",
    "star": "⭐",
    "trophy": "🏆",
    "rocket": "🚀",
    "lock": "🔒",
    "warning": "⚠️",
}

CUSTOM_EMOJI = {}  # يُملأ تلقائياً بـ load_custom_emoji_pack()

def load_custom_emoji_pack():
    """يجلب باكيج tgiosicons من تيليجرام ويبني قاموس CUSTOM_EMOJI {name: custom_emoji_id}."""
    global CUSTOM_EMOJI
    try:
        sticker_set = bot.get_sticker_set(CUSTOM_EMOJI_SET_NAME)
        # خريطة عكسية: إيموجي يونيكود → custom_emoji_id من الباكيج
        emoji_to_id = {}
        all_ids_in_order = []
        for sticker in sticker_set.stickers:
            cid = getattr(sticker, "custom_emoji_id", None)
            if cid:
                all_ids_in_order.append((sticker.emoji, cid))
                if sticker.emoji:
                    emoji_to_id[sticker.emoji] = cid

        built = {}
        unmatched_names = []
        for name, unicode_emoji in EMOJI_NAME_MAP.items():
            if unicode_emoji in emoji_to_id:
                built[name] = emoji_to_id[unicode_emoji]
            else:
                unmatched_names.append(name)

        # إذا ولا اسم تطابق، اربط الأسماء بالترتيب مع محتوى الباكيج كحل احتياطي
        # (يضمن ظهور إيموجي بريميوم حقيقي حتى لو الرموز اليونيكود غير مطابقة)
        if not built and all_ids_in_order:
            names = list(EMOJI_NAME_MAP.keys())
            for i, name in enumerate(names):
                if i < len(all_ids_in_order):
                    built[name] = all_ids_in_order[i][1]
            logger.warning(
                "لا تطابق رموز EMOJI_NAME_MAP مع الباكيج — تم الربط بالترتيب بدلاً من ذلك (احتياطي)."
            )

        CUSTOM_EMOJI = built
        logger.info(f"تم تحميل {len(CUSTOM_EMOJI)} إيموجي بريميوم من باكيج {CUSTOM_EMOJI_SET_NAME}")
        # اطبع محتوى الباكيج الفعلي حتى تقدر تقارنه بـ EMOJI_NAME_MAP وتعدّله بدقة
        logger.info("محتوى الباكيج (إيموجي → custom_emoji_id):")
        for emo, cid in all_ids_in_order:
            logger.info(f"  '{emo}' -> {cid}")
        if unmatched_names:
            logger.info(f"أسماء بدون تطابق مباشر: {unmatched_names}")
    except Exception as e:
        logger.warning(f"تعذر تحميل باكيج الإيموجي البريميوم ({CUSTOM_EMOJI_SET_NAME}): {e}")
        CUSTOM_EMOJI = {}

def tg_emoji(key, fallback="✨"):
    """يبني وسم <tg-emoji> متحرك (للاستخدام داخل نص الرسالة مع parse_mode='HTML')."""
    emoji_id = CUSTOM_EMOJI.get(key)
    if not emoji_id:
        return fallback
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

def premium_button(text, custom_emoji_key=None, **kwargs):
    """ينشئ InlineKeyboardButton مع أيقونة إيموجي بريميوم متحركة (إن وُجد ID)."""
    emoji_id = CUSTOM_EMOJI.get(custom_emoji_key) if custom_emoji_key else None
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    return types.InlineKeyboardButton(text, **kwargs)

# Cache لمعلومات البوت لتجنب استدعاء API في كل مرة 
_bot_info_cache = {}

def safe_answer_callback_query(call_id, text=None, show_alert=False):
    """
    نسخة آمنة من answer_callback_query: لا ترمي استثناء إذا كان
    الـ callback query قديم/منتهي الصلاحية أو غير صالح
    (Bad Request: query is too old / query ID is invalid).
    """
    try:
        bot.answer_callback_query(call_id, text, show_alert=show_alert)
        return True
    except ApiTelegramException as e:
        # تجاهل أخطاء انتهاء صلاحية الـ callback فقط، وسجل أي خطأ آخر غير متوقع
        if "query is too old" in str(e) or "query ID is invalid" in str(e) or "QUERY_ID_INVALID" in str(e):
            return False
        logger.error(f"answer_callback_query failed: {e}")
        return False
    except Exception as e:
        logger.error(f"answer_callback_query failed: {e}")
        return False

def notify_owner_button_error(call, e, user_id=None):
    """يرسل تفاصيل أي خطأ يصير بأي زر مباشرة للمالك عبر البوت (لمعرفة الخلل فوراً بدل انتظار شكوى)"""
    uid = user_id if user_id is not None else getattr(getattr(call, 'from_user', None), 'id', '?')
    tb = traceback.format_exc()
    logger.error(f"Error handling callback '{getattr(call, 'data', '?')}': {e}\n{tb}")
    try:
        short_tb = tb[-3000:]
        bot.send_message(
            OWNER_ID,
            f"⚠️ *خطأ في زر*\n\n"
            f"الزر: `{getattr(call, 'data', '?')}`\n"
            f"المستخدم: `{uid}`\n"
            f"الخطأ: `{str(e)[:200]}`\n\n"
            f"```\n{short_tb}\n```",
            parse_mode="Markdown"
        )
    except Exception:
        try:
            bot.send_message(OWNER_ID, f"خطأ في زر '{getattr(call, 'data', '?')}' من المستخدم {uid}: {str(e)[:300]}")
        except Exception:
            pass

def get_bot_info():
    """يُعيد معلومات البوت مع caching لتجنب API calls متكررة"""
    global _bot_info_cache
    if not _bot_info_cache:
        try:
            info = bot.get_me()
            _bot_info_cache = {'id': info.id, 'username': info.username}
        except Exception as e:
            logger.error(f"Error getting bot info: {e}")
            return {'id': 0, 'username': ''}
    return _bot_info_cache

# أنواع المزادات
AUCTION_TYPES = {
    "username": "معرف",
    "channel": "قناة",
    "group": "مجموعة",
    "bot": "معرف بوت",
    "gift": "هدية تيليجرام"
}

# مدة المزاد الافتراضية (بالساعات) — يمكن للأدمن تغييرها من لوحة الإدارة
DEFAULT_AUCTION_DURATION = 5 # ساعات

# رسوم العمولة (2% من سعر البيع بالدولار)
COMMISSION_RATE = 0.02 # 2%

# عمولة التحويل بين المستخدمين
TRANSFER_COMMISSION_RATE = 0.02 # 2%

# المزاد العاجل: مدة ساعة واحدة وعمولة أعلى
URGENT_AUCTION_DURATION = 1 # ساعة واحدة
URGENT_COMMISSION_RATE = 0.05 # 5%
URGENT_LISTING_FEE = 0.03 # رسوم نشر أعلى من العادية (0.01$)

# فئات المزادات
CATEGORIES = {
    "usernames": "معرفات",
    "channels": "قنوات",
    "groups": "مجموعات",
    "bots": "بوتات",
    "gifts": "هدايا",
    "all": "الكل"
}

SOCIAL_PLATFORMS = {}  # البوت يدعم تيليجرام فقط

class Database:
    _sub_cache = {} # كاش التحقق من الاشتراك: {user_id: timestamp}
    _SUB_CACHE_TTL = 300 # صلاحية الكاش 5 دقائق

    def parse_datetime(self, dt_str):
        if not dt_str:
            return None
        if isinstance(dt_str, datetime):
            return dt_str
        try:
            return datetime.strptime(str(dt_str)[:19], "%Y-%m-%d %H:%M:%S")
        except:
            try:
                return datetime.strptime(str(dt_str), "%Y-%m-%dT%H:%M:%S.%f")
            except:
                logger.warning(f"parse_datetime: فشل تحليل التاريخ '{dt_str}'")
                return None

    def __init__(self, db_name="auction_bot.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL") # أداء أفضل مع أمان مقبول
        self.conn.execute("PRAGMA foreign_keys=ON") # تفعيل Foreign Key constraints
        self.conn.execute("PRAGMA busy_timeout=5000") # انتظر 5 ثانية عند lock بدل رمي خطأ
        self.conn.execute("PRAGMA cache_size=-8000") # 8MB cache
        self._lock = threading.Lock()
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                balance REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_new INTEGER DEFAULT 1,
                notified INTEGER DEFAULT 0
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auctions (
                auction_id TEXT PRIMARY KEY,
                user_id INTEGER,
                auction_type TEXT,
                title TEXT,
                target TEXT,
                description TEXT,
                starting_price REAL DEFAULT 0.0,
                current_price REAL DEFAULT 0.0,
                current_bidder INTEGER,
                status TEXT DEFAULT 'pending',
                duration_hours INTEGER DEFAULT 5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ends_at TIMESTAMP,
                views INTEGER DEFAULT 0,
                bids_count INTEGER DEFAULT 0,
                sold_to INTEGER,
                sold_at TIMESTAMP,
                sold_price REAL DEFAULT 0.0,
                platform TEXT DEFAULT '',
                commission_paid BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bids (
                bid_id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id TEXT,
                user_id INTEGER,
                amount REAL,
                bid_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_refunded BOOLEAN DEFAULT 0,
                refunded_at TIMESTAMP,
                FOREIGN KEY (auction_id) REFERENCES auctions (auction_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                channel_username TEXT,
                channel_title TEXT,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                is_broadcast_only BOOLEAN DEFAULT 1,
                FOREIGN KEY (added_by) REFERENCES users (user_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_channels (
                channel_id INTEGER PRIMARY KEY,
                channel_username TEXT,
                channel_title TEXT,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                subscriber_count INTEGER DEFAULT 0,
                max_subscribers INTEGER DEFAULT 0,
                last_checked TIMESTAMP,
                sub_type TEXT DEFAULT 'permanent',
                FOREIGN KEY (added_by) REFERENCES users (user_id)
            )
        """)
        # إضافة عمود sub_type إذا لم يكن موجوداً (للقواعد القديمة)
        try:
            cursor.execute("ALTER TABLE subscription_channels ADD COLUMN sub_type TEXT DEFAULT 'permanent'")
            self.conn.commit()
        except Exception:
            pass
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                type TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT,
                data TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recharge_codes (
                code_id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                amount REAL DEFAULT 0.0,
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                created_by INTEGER,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (created_by) REFERENCES users (user_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS code_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_id INTEGER,
                user_id INTEGER,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (code_id) REFERENCES recharge_codes (code_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS binance_payments (
                pay_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                usdt_amount REAL,
                usd_amount REAL,
                wallet_address TEXT,
                status TEXT DEFAULT 'pending',
                binance_tx TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stars_payments (
                pay_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                stars_amount INTEGER,
                usd_amount REAL,
                telegram_charge_id TEXT,
                invoice_payload TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS revenues (
                revenue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id TEXT,
                amount REAL DEFAULT 0.0,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (auction_id) REFERENCES auctions (auction_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auction_broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id TEXT,
                channel_id INTEGER,
                message_id INTEGER,
                FOREIGN KEY (auction_id) REFERENCES auctions (auction_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS money_transfers (
                transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                to_user_id INTEGER,
                amount REAL DEFAULT 0.0,
                commission REAL DEFAULT 0.0,
                net_amount REAL DEFAULT 0.0,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_user_id) REFERENCES users (user_id),
                FOREIGN KEY (to_user_id) REFERENCES users (user_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channel_subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                user_id INTEGER,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES subscription_channels (channel_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                UNIQUE(channel_id, user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                banned_by INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # إدراج القيمة الافتراضية لمدة المزاد إن لم تكن موجودة
        cursor.execute(
            "INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('auction_duration', ?)",
            (str(DEFAULT_AUCTION_DURATION),)
        )

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gift_links (
                gift_id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE,
                from_user_id INTEGER,
                amount REAL DEFAULT 0.0,
                is_used BOOLEAN DEFAULT 0,
                used_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP,
                FOREIGN KEY (from_user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transfer_codes (
                tc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                from_user_id INTEGER,
                amount REAL DEFAULT 0.0,
                is_used BOOLEAN DEFAULT 0,
                used_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP,
                FOREIGN KEY (from_user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lucky_wheel_spins (
                spin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_won REAL DEFAULT 0.0,
                spun_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weekly_bonus_spins (
                spin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_won REAL DEFAULT 0.0,
                spun_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_onboarding (
                user_id INTEGER PRIMARY KEY,
                completed BOOLEAN DEFAULT 0,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reported_user_id INTEGER,
                reporter_user_id INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (reported_user_id) REFERENCES users (user_id)
            )
        """)

        # جدول الوكلاء (يبيعون رصيداً)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                name TEXT,
                description TEXT,
                contact TEXT,
                is_active BOOLEAN DEFAULT 1,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        # جدول الوسطاء (يضمنون الصفقات)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS brokers (
                broker_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                name TEXT,
                description TEXT,
                contact TEXT,
                is_active BOOLEAN DEFAULT 1,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        # بلاغات على وكيل
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_user_id INTEGER,
                reporter_user_id INTEGER,
                charge_code TEXT,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_user_id) REFERENCES agents (user_id),
                FOREIGN KEY (reporter_user_id) REFERENCES users (user_id)
            )
        """)

        # عمليات بوساطة الوسيط
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broker_deals (
                deal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_user_id INTEGER,
                buyer_user_id INTEGER,
                seller_user_id INTEGER,
                amount REAL DEFAULT 0.0,
                description TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (broker_user_id) REFERENCES brokers (user_id),
                FOREIGN KEY (buyer_user_id) REFERENCES users (user_id),
                FOREIGN KEY (seller_user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auction_reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id TEXT,
                reporter_user_id INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (auction_id) REFERENCES auctions (auction_id),
                FOREIGN KEY (reporter_user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_verification (
                user_id INTEGER PRIMARY KEY,
                phone TEXT,
                location_lat REAL,
                location_lon REAL,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                status TEXT DEFAULT 'open',
                ai_history TEXT DEFAULT '[]',
                summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL DEFAULT 0.0,
                method TEXT,
                details TEXT,
                status TEXT DEFAULT 'pending',
                admin_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        # أضف عمود terms_accepted للمستخدمين القدامى
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN terms_accepted INTEGER DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass

        # أضف عمود is_urgent للمزادات العاجلة
        try:
            cursor.execute("ALTER TABLE auctions ADD COLUMN is_urgent BOOLEAN DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass

        # أضف عمود buy_now_price لميزة "اشتري الآن" 
        try:
            cursor.execute("ALTER TABLE auctions ADD COLUMN buy_now_price REAL DEFAULT 0.0")
            self.conn.commit()
        except Exception:
            pass

        # جدول متابعة المزادات (Watch) 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auction_watches (
                watch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(auction_id, user_id),
                FOREIGN KEY (auction_id) REFERENCES auctions(auction_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # جدول تقييمات البائعين 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seller_ratings (
                rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id TEXT,
                seller_id INTEGER,
                buyer_id INTEGER,
                rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(auction_id, buyer_id)
            )
        """)

        # جدول طلبات عمليات الوكلاء المعلقة (كود أو تحويل)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_pending_ops (
                op_id INTEGER PRIMARY KEY AUTOINCREMENT,
                op_type TEXT NOT NULL,
                agent_id INTEGER NOT NULL,
                target_uid INTEGER,
                amount REAL NOT NULL,
                code TEXT,
                status TEXT DEFAULT 'pending',
                admin_note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP
            )
        """)

        # جدول طلبات الشحن عبر الوكيل 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_charge_requests (
                req_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                agent_user_id INTEGER,
                amount REAL DEFAULT 0.0,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                admin_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (agent_user_id) REFERENCES agents (user_id)
            )
        """)

        # جدول طلبات الوساطة 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broker_requests (
                req_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                broker_user_id INTEGER,
                service_type TEXT,
                details TEXT,
                status TEXT DEFAULT 'pending',
                admin_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (broker_user_id) REFERENCES brokers (user_id)
            )
        """)

        # رابط مجموعة الوساطة 
        # إضافة عمود is_broadcast_only للقواعد القديمة
        try:
            cursor.execute("ALTER TABLE channels ADD COLUMN is_broadcast_only BOOLEAN DEFAULT 1")
            self.conn.commit()
        except Exception:
            pass

        cursor.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('broker_group_link', '')")
        cursor.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('broker_group_id', '')")

        # إعداد تفعيل/تعطيل الحماية (هاتف + موقع) 
        cursor.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('verification_enabled', '1')")

        # تقييمات الوكلاء 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_ratings (
                rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_user_id INTEGER,
                user_id INTEGER,
                req_id INTEGER,
                rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, req_id),
                FOREIGN KEY (agent_user_id) REFERENCES agents (user_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        # تقييمات الوسطاء 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broker_ratings (
                rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_user_id INTEGER,
                user_id INTEGER,
                req_id INTEGER,
                rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, req_id),
                FOREIGN KEY (broker_user_id) REFERENCES brokers (user_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        # أرباح الوكلاء 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_profits (
                profit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_user_id INTEGER,
                req_id INTEGER,
                amount REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # تنبيهات وبلاغات الإدارة الموجهة للوكلاء (لوحة تحكم الوكلاء) 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_warnings (
                warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_user_id INTEGER,
                warning_type TEXT DEFAULT 'warning',
                reason TEXT,
                issued_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_user_id) REFERENCES agents (user_id)
            )
        """)

        # أرباح الوسطاء 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broker_profits (
                profit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_user_id INTEGER,
                req_id INTEGER,
                amount REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # تنبيهات وبلاغات الإدارة الموجهة للوسطاء (لوحة تحكم الوسطاء) 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broker_warnings (
                warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_user_id INTEGER,
                warning_type TEXT DEFAULT 'warning',
                reason TEXT,
                issued_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (broker_user_id) REFERENCES brokers (user_id)
            )
        """)

        # نظام الكروت والإحالات 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS referral_cards (
                card_id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_number TEXT UNIQUE,
                owner_user_id INTEGER,
                referred_user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_user_id) REFERENCES users (user_id),
                FOREIGN KEY (referred_user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_user_id INTEGER,
                referred_user_id INTEGER UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_user_id) REFERENCES users (user_id),
                FOREIGN KEY (referred_user_id) REFERENCES users (user_id)
            )
        """)

        # نظام المسابقات 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contests (
                contest_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                prize_amount REAL DEFAULT 0.0,
                start_at TIMESTAMP,
                status TEXT DEFAULT 'scheduled',
                channel_message_id INTEGER,
                channel_id INTEGER,
                winner_card TEXT,
                winner_user_id INTEGER,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                prize_description TEXT DEFAULT '',
                winner_prize_code TEXT DEFAULT '',
                FOREIGN KEY (created_by) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contest_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER,
                user_id INTEGER,
                cards_count INTEGER DEFAULT 0,
                entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(contest_id, user_id),
                FOREIGN KEY (contest_id) REFERENCES contests (contest_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contest_entry_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER,
                user_id INTEGER,
                card_number TEXT,
                FOREIGN KEY (contest_id) REFERENCES contests (contest_id)
            )
        """)

        # جدول منفصل لرسائل قنوات المسابقة (يدعم أكثر من قناة)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contest_channel_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                UNIQUE(contest_id, channel_id)
            )
        """)

        # جدول ملصقات البوت — ملصقات يضيفها الأدمن ترتبط بمناسبات معينة (فوز، مزاد جديد...)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_stickers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                added_by INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جدول سجل محادثات الذكاء الاصطناعي — لتتبّع الأسئلة، نتيجة الفهم، وتقييم المستخدم
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_conversation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_message TEXT NOT NULL,
                matched_intent TEXT,
                confidence REAL,
                was_unknown INTEGER DEFAULT 0,
                feedback TEXT,
                resolved_by_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جدول الأنماط المُتعلَّمة — يضيفها الأدمن من مراجعة الأسئلة الفاشلة، تُدمج تلقائياً بمحرك الفهم
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_learned_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                intent TEXT NOT NULL,
                pattern_text TEXT NOT NULL,
                added_by INTEGER,
                source_log_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()

        # migration: إضافة أعمدة جديدة للقواعد القديمة
        for col, definition in [
            ("prize_description", "TEXT DEFAULT ''"),
            ("winner_prize_code", "TEXT DEFAULT ''"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE contests ADD COLUMN {col} {definition}")
                self.conn.commit()
            except Exception:
                pass

        # Indexes لتحسين الأداء 
        index_statements = [
            "CREATE INDEX IF NOT EXISTS idx_auctions_status ON auctions(status)",
            "CREATE INDEX IF NOT EXISTS idx_auctions_user_id ON auctions(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_auctions_ends_at ON auctions(ends_at)",
            "CREATE INDEX IF NOT EXISTS idx_bids_auction_id ON bids(auction_id)",
            "CREATE INDEX IF NOT EXISTS idx_bids_user_id ON bids(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_states_user_id ON user_states(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_broker_req_broker ON broker_requests(broker_user_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_agent_req_agent ON agent_charge_requests(agent_user_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_referral_cards_owner ON referral_cards(owner_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_contest_entry_contest ON contest_entry_cards(contest_id)",
            "CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals(referred_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_bot_stickers_event ON bot_stickers(event_type, is_active)",
            "CREATE INDEX IF NOT EXISTS idx_ai_log_unknown ON ai_conversation_log(was_unknown, resolved_by_admin)",
            "CREATE INDEX IF NOT EXISTS idx_ai_learned_intent ON ai_learned_patterns(intent)",
        ]
        for stmt in index_statements:
            try:
                cursor.execute(stmt)
            except Exception:
                pass
        self.conn.commit()
        pass

    def set_user_state(self, user_id, state, data=None):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                if data and not isinstance(data, str):
                    data = json.dumps(data, ensure_ascii=False)
                cursor.execute("INSERT OR REPLACE INTO user_states (user_id, state, data, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (user_id, state, data))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error setting user state: {e}")
                return False
    
    def get_user_state(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT state, data FROM user_states WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                data = json.loads(result[1]) if result[1] else None
            except:
                data = result[1]
            return {"state": result[0], "data": data}
        return None
    
    def clear_user_state(self, user_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error clearing user state: {e}")
                return False
    
    def add_user(self, user_id, username, first_name, last_name):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                existing_user = cursor.fetchone()
                if existing_user:
                    cursor.execute("UPDATE users SET username = ?, first_name = ?, last_name = ?, is_new = 0 WHERE user_id = ?", (username, first_name, last_name, user_id))
                    is_new = False
                else:
                    cursor.execute("INSERT INTO users (user_id, username, first_name, last_name, is_new, notified) VALUES (?, ?, ?, ?, 1, 0)", (user_id, username, first_name, last_name))
                    is_new = True
                self.conn.commit()
                return is_new
            except Exception as e:
                logger.error(f"Error adding user: {e}")
                return False
    
    def get_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return {
                'user_id': row[0], 'username': row[1], 'first_name': row[2],
                'last_name': row[3], 'balance': row[4], 'created_at': row[5],
                'is_new': bool(row[6]), 'notified': bool(row[7]),
                'terms_accepted': bool(row[8]) if len(row) > 8 and row[8] is not None else False
            }
        return None

    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    
    def mark_user_notified(self, user_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("UPDATE users SET notified = 1 WHERE user_id = ?", (user_id,))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error marking user as notified: {e}")
                return False
    
    def get_new_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE is_new = 1 AND notified = 0")
        rows = cursor.fetchall()
        users = []
        for row in rows:
            users.append({'user_id': row[0], 'username': row[1], 'first_name': row[2], 'last_name': row[3], 'balance': row[4], 'created_at': row[5], 'is_new': bool(row[6]), 'notified': bool(row[7])})
        return users
    
    def update_balance(self, user_id, amount):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error updating balance: {e}")
                return False
    
    def get_balance(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0.0
    
    def add_auction(self, auction_id, user_id, auction_type, target, title=None, platform="", starting_price=0.0, duration_hours=None, is_urgent=False):
        with self._lock:
            cursor = self.conn.cursor()
            duration = duration_hours if duration_hours else self.get_auction_duration()
            ends_at = datetime.now() + timedelta(hours=duration)
            try:
                cursor.execute(
                    "INSERT INTO auctions (auction_id, user_id, auction_type, target, title, ends_at, platform, starting_price, current_price, duration_hours, is_urgent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (auction_id, user_id, auction_type, target, title, ends_at, platform, starting_price, starting_price, duration, 1 if is_urgent else 0)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error adding auction: {e}")
                return False
    
    def approve_auction(self, auction_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                # احسب ends_at من وقت الموافقة الفعلي
                cursor.execute("SELECT duration_hours FROM auctions WHERE auction_id = ?", (auction_id,))
                row = cursor.fetchone()
                duration = row[0] if row and row[0] else self.get_auction_duration()
                ends_at = datetime.now() + timedelta(hours=duration)
                cursor.execute(
                    "UPDATE auctions SET status = 'active', ends_at = ? WHERE auction_id = ?",
                    (ends_at, auction_id)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error approving auction: {e}")
                return False
    
    def reject_auction(self, auction_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("DELETE FROM auctions WHERE auction_id = ?", (auction_id,))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error rejecting auction: {e}")
                return False
    
    def get_pending_auctions(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM auctions WHERE status = 'pending' ORDER BY created_at DESC")
        rows = cursor.fetchall()
        auctions = []
        for row in rows:
            auctions.append({'auction_id': row[0], 'user_id': row[1], 'auction_type': row[2], 'title': row[3], 'target': row[4], 'description': row[5], 'starting_price': row[6] or 0.0, 'current_price': row[7] or 0.0, 'current_bidder': row[8], 'status': row[9], 'duration_hours': row[10] or 5, 'created_at': row[11], 'ends_at': row[12], 'views': row[13] or 0, 'bids_count': row[14] or 0, 'sold_to': row[15], 'sold_at': row[16], 'sold_price': row[17] or 0.0, 'platform': row[18] or '', 'commission_paid': bool(row[19])})
        return auctions
    
    def get_active_auctions(self, category="all", platform_filter=None):
        cursor = self.conn.cursor()
        if category == "all":
            if platform_filter:
                cursor.execute("SELECT * FROM auctions WHERE status = 'active' AND platform = ? ORDER BY created_at DESC", (platform_filter,))
            else:
                cursor.execute("SELECT * FROM auctions WHERE status = 'active' ORDER BY created_at DESC")
        elif category == "social":
            # legacy — treat same as usernames
            cursor.execute("SELECT * FROM auctions WHERE status = 'active' AND auction_type = 'username' ORDER BY created_at DESC")
        else:
            category_mapping = {"usernames": "username", "channels": "channel", "groups": "group", "bots": "bot", "gifts": "gift"}
            auction_type = category_mapping.get(category, category)
            if platform_filter and auction_type == "username":
                cursor.execute("SELECT * FROM auctions WHERE status = 'active' AND auction_type = ? AND platform = ? ORDER BY created_at DESC", (auction_type, platform_filter))
            else:
                cursor.execute("SELECT * FROM auctions WHERE status = 'active' AND auction_type = ? ORDER BY created_at DESC", (auction_type,))
        rows = cursor.fetchall()
        auctions = []
        for row in rows:
            auctions.append({'auction_id': row[0], 'user_id': row[1], 'auction_type': row[2], 'title': row[3], 'target': row[4], 'description': row[5], 'starting_price': row[6] or 0.0, 'current_price': row[7] or 0.0, 'current_bidder': row[8], 'status': row[9], 'duration_hours': row[10] or 5, 'created_at': row[11], 'ends_at': row[12], 'views': row[13] or 0, 'bids_count': row[14] or 0, 'sold_to': row[15], 'sold_at': row[16], 'sold_price': row[17] or 0.0, 'platform': row[18] or '', 'commission_paid': bool(row[19])})
        active_auctions = []
        for auction in auctions:
            ends_at = auction['ends_at']
            if ends_at:
                ends_at_dt = self.parse_datetime(ends_at) if isinstance(ends_at, str) else ends_at
                if ends_at_dt and ends_at_dt > datetime.now():
                    active_auctions.append(auction)
        return active_auctions
    
    def get_user_auctions(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM auctions WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        rows = cursor.fetchall()
        auctions = []
        for row in rows:
            auctions.append({'auction_id': row[0], 'user_id': row[1], 'auction_type': row[2], 'title': row[3], 'target': row[4], 'description': row[5], 'starting_price': row[6] or 0.0, 'current_price': row[7] or 0.0, 'current_bidder': row[8], 'status': row[9], 'duration_hours': row[10] or 5, 'created_at': row[11], 'ends_at': row[12], 'views': row[13] or 0, 'bids_count': row[14] or 0, 'sold_to': row[15], 'sold_at': row[16], 'sold_price': row[17] or 0.0, 'platform': row[18] or '', 'commission_paid': bool(row[19])})
        return auctions
    
    def get_auction_by_id(self, auction_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM auctions WHERE auction_id = ?", (auction_id,))
        row = cursor.fetchone()
        if row:
            return {'auction_id': row[0], 'user_id': row[1], 'auction_type': row[2], 'title': row[3], 'target': row[4], 'description': row[5], 'starting_price': row[6] or 0.0, 'current_price': row[7] or 0.0, 'current_bidder': row[8], 'status': row[9], 'duration_hours': row[10] or 5, 'created_at': row[11], 'ends_at': row[12], 'views': row[13] or 0, 'bids_count': row[14] or 0, 'sold_to': row[15], 'sold_at': row[16], 'sold_price': row[17] or 0.0, 'platform': row[18] or '', 'commission_paid': bool(row[19]), 'is_urgent': bool(row[20]) if len(row) > 20 else False, 'buy_now_price': row[21] if len(row) > 21 and row[21] else 0.0}
        return None
    
    def add_bid(self, auction_id, user_id, amount):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                # ← تحقق ذرّي (داخل القفل) من حالة المزاد والسعر — يمنع تضارب المزايدات المتزامنة
                cursor.execute(
                    "SELECT status, current_price, ends_at FROM auctions WHERE auction_id=?",
                    (auction_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return False, "المزاد غير موجود!"
                status, current_price, ends_at = row
                if status != 'active':
                    return False, "انتهى وقت المزاد!"
                if ends_at:
                    parsed_end = self.parse_datetime(ends_at)
                    if parsed_end and parsed_end <= datetime.now():
                        return False, "انتهى وقت المزاد!"
                if amount <= current_price:
                    return False, f"تغيّر السعر! الحالي الآن: {current_price:.2f}$"

                user_balance = self.get_balance(user_id)
                if user_balance < amount:
                    return False, "رصيدك غير كافي!"

                # ← استرداد المزايدات السابقة لنفس المستخدم في هذا المزاد قبل خصم الجديدة
                cursor.execute(
                    "SELECT bid_id, amount FROM bids WHERE auction_id=? AND user_id=? AND is_refunded=0",
                    (auction_id, user_id)
                )
                prev_bids = cursor.fetchall()
                prev_total = 0.0
                for pb in prev_bids:
                    prev_total += pb[1]
                    cursor.execute(
                        "UPDATE bids SET is_refunded=1, refunded_at=CURRENT_TIMESTAMP WHERE bid_id=?",
                        (pb[0],)
                    )
                if prev_total > 0:
                    # ← لا نستخدم self.update_balance هنا لأنها تحاول حجز self._lock من جديد
                    # وهذا يسبب deadlock دائم (القفل غير قابل لإعادة الحجز) لأننا بالفعل داخل القفل
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prev_total, user_id))

                cursor.execute("INSERT INTO bids (auction_id, user_id, amount) VALUES (?, ?, ?)", (auction_id, user_id, amount))
                cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                # ← شرط WHERE current_price < ? يمنع أي احتمال نادر لتجاوز مزايدة أعلى وصلت للتو
                cursor.execute(
                    "UPDATE auctions SET current_price = ?, current_bidder = ?, bids_count = bids_count + 1 WHERE auction_id = ? AND status='active' AND current_price < ?",
                    (amount, user_id, auction_id, amount)
                )
                if cursor.rowcount == 0:
                    self.conn.rollback()
                    return False, "تغيّر السعر للتو! حاول مرة أخرى."
                # ← تمديد 5 دقائق فقط إذا تبقى أقل من 5 دقائق (Anti-Snipe)
                cursor.execute(
                    """UPDATE auctions SET ends_at = datetime(ends_at, '+5 minutes')
                       WHERE auction_id=? AND status='active'
                       AND (julianday(ends_at) - julianday('now')) * 1440 < 5""",
                    (auction_id,)
                )
                extended = cursor.rowcount > 0
                self.conn.commit()
                msg = "تمت المزايدة بنجاح!"
                if extended:
                    msg += " ⏱️ تم تمديد المزاد 5 دقائق إضافية!"
                return True, msg
            except Exception as e:
                self.conn.rollback()
                logger.error(f"Error adding bid: {e}")
                return False, "حدث خطأ أثناء المزايدة"
    
    def get_user_bids(self, user_id, auction_id=None):
        cursor = self.conn.cursor()
        if auction_id:
            cursor.execute("SELECT * FROM bids WHERE user_id = ? AND auction_id = ? AND is_refunded = 0 ORDER BY bid_time DESC", (user_id, auction_id))
        else:
            cursor.execute("SELECT * FROM bids WHERE user_id = ? AND is_refunded = 0 ORDER BY bid_time DESC", (user_id,))
        rows = cursor.fetchall()
        bids = []
        for row in rows:
            bids.append({'bid_id': row[0], 'auction_id': row[1], 'user_id': row[2], 'amount': row[3], 'bid_time': row[4], 'is_refunded': row[5], 'refunded_at': row[6]})
        return bids
    
    def refund_bid(self, bid_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                # تحقق أن المزايدة لم تُسترد مسبقاً (حماية من double refund)
                cursor.execute(
                    "SELECT user_id, amount FROM bids WHERE bid_id = ? AND is_refunded = 0",
                    (bid_id,)
                )
                result = cursor.fetchone()
                if not result:
                    return False  # غير موجودة أو مستردة مسبقاً
                user_id, amount = result
                # علّم أولاً ثم أضف الرصيد
                cursor.execute(
                    "UPDATE bids SET is_refunded = 1, refunded_at = CURRENT_TIMESTAMP WHERE bid_id = ?",
                    (bid_id,)
                )
                self.conn.commit()
                # ← لا نستخدم self.update_balance هنا (نفس سبب deadlock في add_bid أعلاه)
                with_lock_cursor = self.conn.cursor()
                with_lock_cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                self.conn.commit()
                return True
            except Exception as e:
                self.conn.rollback()
                logger.error(f"Error refunding bid: {e}")
                return False
    
    def set_buy_now_price(self, auction_id, price):
        """تحديث سعر الشراء الفوري للمزاد"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("UPDATE auctions SET buy_now_price=? WHERE auction_id=?", (price, auction_id))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error setting buy_now_price: {e}")
                return False

    def execute_buy_now(self, auction_id, buyer_id):
        """تنفيذ الشراء الفوري — يتحقق من الرصيد ويُغلق المزاد فوراً"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("SELECT buy_now_price, status, current_bidder, user_id, starting_price FROM auctions WHERE auction_id=?", (auction_id,))
                row = cursor.fetchone()
                if not row:
                    return False, "المزاد غير موجود"
                buy_now_price, status, current_bidder, owner_id, starting_price = row
                if status != 'active':
                    return False, "المزاد غير نشط"
                if not buy_now_price or buy_now_price <= 0:
                    return False, "الشراء الفوري غير مفعّل"
                if buyer_id == owner_id:
                    return False, "لا يمكنك شراء مزادك الخاص"
                balance = self.get_balance(buyer_id)
                if balance < buy_now_price:
                    return False, f"رصيدك غير كافٍ!\n\nرصيدك: {balance:.2f}$\nالمطلوب: {buy_now_price:.2f}$"
                # خصم المبلغ من المشتري فوراً
                cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (buy_now_price, buyer_id))
                # إغلاق المزاد
                cursor.execute(
                    "UPDATE auctions SET status='sold', sold_to=?, sold_at=CURRENT_TIMESTAMP, sold_price=?, current_bidder=?, current_price=? WHERE auction_id=? AND status='active'",
                    (buyer_id, buy_now_price, buyer_id, buy_now_price, auction_id)
                )
                if cursor.rowcount == 0:
                    self.conn.rollback()
                    return False, "تعذّر إغلاق المزاد (ربما أُغلق للتو)"
                self.conn.commit()
                return True, buy_now_price
            except Exception as e:
                self.conn.rollback()
                logger.error(f"execute_buy_now error: {e}")
                return False, "خطأ داخلي"

    def watch_auction(self, auction_id, user_id):
        """إضافة مزاد للمتابعة بدون مزايدة"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("INSERT OR IGNORE INTO auction_watches (auction_id, user_id) VALUES (?,?)", (auction_id, user_id))
                self.conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"watch_auction error: {e}")
                return False

    def unwatch_auction(self, auction_id, user_id):
        """إزالة مزاد من المتابعة"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("DELETE FROM auction_watches WHERE auction_id=? AND user_id=?", (auction_id, user_id))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"unwatch_auction error: {e}")
                return False

    def is_watching(self, auction_id, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM auction_watches WHERE auction_id=? AND user_id=?", (auction_id, user_id))
        return cursor.fetchone() is not None

    def get_auction_watchers(self, auction_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM auction_watches WHERE auction_id=?", (auction_id,))
        return [r[0] for r in cursor.fetchall()]

    def get_auction_bids(self, auction_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT b.*, u.username, u.first_name FROM bids b LEFT JOIN users u ON b.user_id = u.user_id WHERE b.auction_id = ? AND b.is_refunded = 0 ORDER BY b.bid_time DESC", (auction_id,))
        rows = cursor.fetchall()
        bids = []
        for row in rows:
            bids.append({'bid_id': row[0], 'auction_id': row[1], 'user_id': row[2], 'amount': row[3], 'bid_time': row[4], 'is_refunded': row[5], 'refunded_at': row[6], 'username': row[7], 'first_name': row[8]})
        return bids
    
    def complete_auction(self, auction_id, sold_to, sold_price):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("UPDATE auctions SET status = 'sold', sold_to = ?, sold_at = CURRENT_TIMESTAMP, sold_price = ? WHERE auction_id = ? AND status = 'active'", (sold_to, sold_price, auction_id))
                self.conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Error completing auction: {e}")
                return False
    
    def expire_auction(self, auction_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "UPDATE auctions SET status = 'expired' WHERE auction_id = ? AND status = 'active'",
                    (auction_id,)
                )
                self.conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Error expiring auction: {e}")
                return False
    
    def add_channel(self, channel_id, channel_username, channel_title, added_by):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR REPLACE INTO channels (channel_id, channel_username, channel_title, added_by, is_active, is_broadcast_only) VALUES (?, ?, ?, ?, 1, 1)",
                    (channel_id, channel_username, channel_title, added_by)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error adding channel: {e}")
                return False

    def get_all_channels(self):
        """إرجاع قنوات البث فقط (ليست قنوات الاشتراك الإجباري)"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM channels WHERE is_active = 1 ORDER BY added_at DESC")
        rows = cursor.fetchall()
        channels = []
        for row in rows:
            channels.append({
                'channel_id': row[0], 'channel_username': row[1], 'channel_title': row[2],
                'added_by': row[3], 'added_at': row[4], 'is_active': row[5],
                'is_broadcast_only': row[6] if len(row) > 6 else 1
            })
        return channels
    
    def add_subscription_channel(self, channel_id, channel_username, channel_title, added_by, max_subscribers=0, sub_type='permanent'):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT OR REPLACE INTO subscription_channels (channel_id, channel_username, channel_title, added_by, is_active, subscriber_count, max_subscribers, last_checked, sub_type) VALUES (?, ?, ?, ?, 1, 0, ?, CURRENT_TIMESTAMP, ?)", (channel_id, channel_username, channel_title, added_by, max_subscribers, sub_type))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding subscription channel: {e}")
            return False
    
    def update_subscriber_count(self, channel_id, count):
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE subscription_channels SET subscriber_count = ?, last_checked = CURRENT_TIMESTAMP WHERE channel_id = ?", (count, channel_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating subscriber count: {e}")
            return False
    
    def get_subscription_channel_by_id(self, channel_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM subscription_channels WHERE channel_id = ?", (channel_id,))
        row = cursor.fetchone()
        if row:
            return {'channel_id': row[0], 'channel_username': row[1], 'channel_title': row[2], 'added_by': row[3], 'added_at': row[4], 'is_active': row[5], 'subscriber_count': row[6] or 0, 'max_subscribers': row[7] or 0, 'last_checked': row[8], 'sub_type': row[9] if len(row) > 9 and row[9] else 'permanent'}
        return None
    
    def add_channel_subscriber(self, channel_id, user_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO channel_subscribers (channel_id, user_id) VALUES (?, ?)", (channel_id, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding channel subscriber: {e}")
            return False
    
    def get_channel_subscriber_count(self, channel_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM channel_subscribers WHERE channel_id = ?", (channel_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def get_subscription_channels(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM subscription_channels WHERE is_active = 1 ORDER BY added_at DESC")
        rows = cursor.fetchall()
        channels = []
        for row in rows:
            channels.append({
                'channel_id': row[0], 'channel_username': row[1], 'channel_title': row[2],
                'added_by': row[3], 'added_at': row[4], 'is_active': row[5],
                'subscriber_count': row[6] or 0, 'max_subscribers': row[7] or 0,
                'last_checked': row[8],
                'sub_type': row[9] if len(row) > 9 and row[9] else 'permanent'
            })
        return channels
    
    def deactivate_subscription_channel(self, channel_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE subscription_channels SET is_active = 0 WHERE channel_id = ?", (channel_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deactivating subscription channel: {e}")
            return False

    def delete_subscription_channel(self, channel_id):
        """حذف كامل لقناة الاشتراك المدفوع عند انتهاء الاشتراكات"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("DELETE FROM subscription_channels WHERE channel_id = ?", (channel_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting subscription channel: {e}")
            return False
    
    def check_user_subscription(self, user_id):
        import time as _time
        channels = self.get_subscription_channels()
        if not channels:
            return True, []

        # تحقق من الكاش
        now = _time.time()
        cache_key = user_id
        cached = Database._sub_cache.get(cache_key)
        if cached and now - cached < Database._SUB_CACHE_TTL:
            return True, []

        not_subscribed = []
        for channel in channels:
            try:
                # تخطي القنوات التي وصلت للحد الأقصى
                if channel['max_subscribers'] > 0 and channel['subscriber_count'] >= channel['max_subscribers']:
                    continue
                # تحقق لحظي من Telegram API
                try:
                    member = bot.get_chat_member(channel['channel_id'], user_id)
                except Exception as api_err:
                    err_str = str(api_err).lower()
                    # البوت ليس في القناة أو القناة محذوفة → نتجاهلها فقط
                    if 'chat not found' in err_str or 'bot was kicked' in err_str or 'not a member' in err_str:
                        logger.warning(f"[SUB] تجاهل القناة {channel['channel_id']}: {api_err}")
                        continue
                    # خطأ مؤقت → نضيف القناة للقائمة لإجبار المستخدم على التحقق لاحقاً
                    logger.error(f"[SUB] خطأ مؤقت القناة {channel['channel_id']}: {api_err}")
                    not_subscribed.append(channel)
                    continue

                is_member = member.status in ['creator', 'administrator', 'member']
                if member.status == 'restricted':
                    is_member = getattr(member, 'is_member', False)

                if not is_member:
                    not_subscribed.append(channel)
                else:
                    self.add_channel_subscriber(channel['channel_id'], user_id)

            except Exception as e:
                logger.error(f"[SUB] خطأ غير متوقع للقناة {channel['channel_id']}: {e}")
                continue

        if len(not_subscribed) == 0:
            Database._sub_cache[cache_key] = now

        return len(not_subscribed) == 0, not_subscribed
    
    def add_transaction(self, user_id, amount, trans_type, description):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)", (user_id, amount, trans_type, description))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error adding transaction: {e}")
                return False
    
    def add_money_transfer(self, from_user_id, to_user_id, amount, commission, net_amount, description=""):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("INSERT INTO money_transfers (from_user_id, to_user_id, amount, commission, net_amount, description) VALUES (?, ?, ?, ?, ?, ?)", (from_user_id, to_user_id, amount, commission, net_amount, description))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error adding money transfer: {e}")
                return False
    
    def get_money_transfers(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM money_transfers WHERE from_user_id = ? OR to_user_id = ? ORDER BY created_at DESC", (user_id, user_id))
        rows = cursor.fetchall()
        transfers = []
        for row in rows:
            transfers.append({'transfer_id': row[0], 'from_user_id': row[1], 'to_user_id': row[2], 'amount': row[3], 'commission': row[4], 'net_amount': row[5], 'description': row[6], 'created_at': row[7]})
        return transfers
    
    def add_revenue(self, auction_id, amount, source):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("INSERT INTO revenues (auction_id, amount, source) VALUES (?, ?, ?)", (auction_id, amount, source))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error adding revenue: {e}")
                return False
    
    def get_total_revenue(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT SUM(amount) FROM revenues")
        result = cursor.fetchone()
        return result[0] if result and result[0] else 0.0

    def save_broadcast_message(self, auction_id, channel_id, message_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO auction_broadcasts (auction_id, channel_id, message_id) VALUES (?, ?, ?)",
                    (auction_id, channel_id, message_id)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error saving broadcast message: {e}")
                return False

    def get_broadcast_messages(self, auction_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT channel_id, message_id FROM auction_broadcasts WHERE auction_id = ?",
            (auction_id,)
        )
        rows = cursor.fetchall()
        return [{'channel_id': row[0], 'message_id': row[1]} for row in rows]

    def delete_broadcast_messages(self, auction_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("DELETE FROM auction_broadcasts WHERE auction_id = ?", (auction_id,))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error deleting broadcast messages: {e}")
                return False
    
    def deduct_commission(self, user_id, auction_id, listing_fee=0.01):
        cursor = self.conn.cursor()
        try:
            commission_amount = listing_fee
            balance = self.get_balance(user_id)
            if balance < commission_amount:
                return False
            self.update_balance(user_id, -commission_amount)
            self.add_revenue(auction_id, commission_amount, "listing_fee")
            self.add_transaction(user_id, -commission_amount, "commission", f"رسوم نشر مزاد #{auction_id}")
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deducting commission: {e}")
            return False
    
    def get_stats(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_new = 1")
        new_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM auctions WHERE status = 'active'")
        active_auctions = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM auctions WHERE status = 'pending'")
        pending_auctions = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM auctions WHERE status = 'sold'")
        sold_auctions = cursor.fetchone()[0]
        total_revenue = self.get_total_revenue()
        cursor.execute("SELECT COUNT(*) FROM channels WHERE is_active = 1")
        total_channels = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM subscription_channels WHERE is_active = 1")
        total_subscription_channels = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(subscriber_count) FROM subscription_channels WHERE is_active = 1")
        total_subscribers = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM bids")
        total_bids = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(current_price) FROM auctions WHERE status = 'active'")
        total_active_value = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(sold_price) FROM auctions WHERE status = 'sold'")
        total_sold_value = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(amount) FROM money_transfers")
        total_transfers = cursor.fetchone()[0] or 0
        return {'total_users': total_users, 'new_users': new_users, 'active_auctions': active_auctions, 'pending_auctions': pending_auctions, 'sold_auctions': sold_auctions, 'total_revenue': total_revenue, 'total_channels': total_channels, 'total_subscription_channels': total_subscription_channels, 'total_subscribers': total_subscribers, 'total_bids': total_bids, 'total_active_value': total_active_value, 'total_sold_value': total_sold_value, 'total_transfers': total_transfers}

    def get_extended_stats(self):
        """إحصائيات موسّعة مع مقارنة اليوم/الأمس والأسبوع/الشهر"""
        cursor = self.conn.cursor()
        # إيرادات اليوم
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM revenues WHERE date(created_at)=date('now')")
        revenue_today = cursor.fetchone()[0]
        # إيرادات الأمس
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM revenues WHERE date(created_at)=date('now','-1 day')")
        revenue_yesterday = cursor.fetchone()[0]
        # إيرادات الأسبوع
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM revenues WHERE created_at >= datetime('now','-7 days')")
        revenue_week = cursor.fetchone()[0]
        # إيرادات الشهر
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM revenues WHERE created_at >= datetime('now','-30 days')")
        revenue_month = cursor.fetchone()[0]
        # مستخدمون جدد اليوم
        cursor.execute("SELECT COUNT(*) FROM users WHERE date(created_at)=date('now')")
        users_today = cursor.fetchone()[0]
        # مستخدمون جدد الأمس
        cursor.execute("SELECT COUNT(*) FROM users WHERE date(created_at)=date('now','-1 day')")
        users_yesterday = cursor.fetchone()[0]
        # مزادات اليوم
        cursor.execute("SELECT COUNT(*) FROM auctions WHERE date(created_at)=date('now')")
        auctions_today = cursor.fetchone()[0]
        # مبيعات اليوم
        cursor.execute("SELECT COUNT(*) FROM auctions WHERE status='sold' AND date(sold_at)=date('now')")
        sales_today = cursor.fetchone()[0]
        # أعلى 5 مستخدمين نشاطاً
        cursor.execute("""
            SELECT u.user_id, COALESCE(u.username,'?'), COUNT(b.bid_id) as bid_count
            FROM users u LEFT JOIN bids b ON u.user_id=b.user_id
            GROUP BY u.user_id ORDER BY bid_count DESC LIMIT 5
        """)
        top_bidders = cursor.fetchall()
        return {
            'revenue_today': revenue_today, 'revenue_yesterday': revenue_yesterday,
            'revenue_week': revenue_week, 'revenue_month': revenue_month,
            'users_today': users_today, 'users_yesterday': users_yesterday,
            'auctions_today': auctions_today, 'sales_today': sales_today,
            'top_bidders': top_bidders
        }
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM users ORDER BY created_at DESC")
        return [row[0] for row in cursor.fetchall()]
    
    def create_agent_pending_op(self, op_type, agent_id, amount, target_uid=None, code=None):
        """إنشاء عملية وكيل معلقة تنتظر موافقة الأدمن"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO agent_pending_ops (op_type, agent_id, target_uid, amount, code) VALUES (?,?,?,?,?)",
                    (op_type, agent_id, target_uid, amount, code)
                )
                self.conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"create_agent_pending_op error: {e}")
                return None

    def get_agent_pending_op(self, op_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM agent_pending_ops WHERE op_id=?", (op_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {'op_id': row[0], 'op_type': row[1], 'agent_id': row[2], 'target_uid': row[3],
                'amount': row[4], 'code': row[5], 'status': row[6], 'admin_note': row[7],
                'created_at': row[8], 'resolved_at': row[9]}

    def resolve_agent_pending_op(self, op_id, status, admin_note=''):
        """قبول أو رفض عملية وكيل معلقة"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "UPDATE agent_pending_ops SET status=?, admin_note=?, resolved_at=CURRENT_TIMESTAMP WHERE op_id=? AND status='pending'",
                    (status, admin_note, op_id)
                )
                self.conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"resolve_agent_pending_op error: {e}")
                return False

    def add_seller_rating(self, auction_id, seller_id, buyer_id, rating, comment=""):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO seller_ratings (auction_id, seller_id, buyer_id, rating, comment) VALUES (?,?,?,?,?)",
                    (auction_id, seller_id, buyer_id, rating, comment)
                )
                self.conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"add_seller_rating error: {e}")
                return False

    def get_seller_rating(self, seller_id):
        """متوسط تقييم البائع وعدد التقييمات"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT AVG(rating), COUNT(*) FROM seller_ratings WHERE seller_id=?",
            (seller_id,)
        )
        row = cursor.fetchone()
        avg = round(row[0], 1) if row[0] else 0.0
        count = row[1] or 0
        return avg, count

    def has_rated(self, auction_id, buyer_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM seller_ratings WHERE auction_id=? AND buyer_id=?", (auction_id, buyer_id))
        return cursor.fetchone() is not None

    def create_recharge_code(self, amount, max_uses, expires_days, created_by):
        cursor = self.conn.cursor()
        try:
            code = generate_code()
            expires_at = datetime.now() + timedelta(days=expires_days)
            cursor.execute("INSERT INTO recharge_codes (code, amount, max_uses, created_by, expires_at) VALUES (?, ?, ?, ?, ?)", (code, amount, max_uses, created_by, expires_at))
            self.conn.commit()
            return code
        except Exception as e:
            logger.error(f"Error creating recharge code: {e}")
            return None
    
    def get_recharge_code(self, code):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM recharge_codes WHERE code = ? AND is_active = 1", (code,))
        row = cursor.fetchone()
        if row:
            return {'code_id': row[0], 'code': row[1], 'amount': row[2], 'max_uses': row[3], 'used_count': row[4], 'created_by': row[5], 'expires_at': row[6], 'created_at': row[7], 'is_active': row[8]}
        return None
    
    def use_recharge_code(self, code_id, user_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("SELECT amount, max_uses, used_count FROM recharge_codes WHERE code_id = ?", (code_id,))
                code_info = cursor.fetchone()
                if not code_info:
                    return False, "الكود غير موجود"
                amount, max_uses, used_count = code_info
                if used_count >= max_uses:
                    return False, "تم استخدام الكود بالكامل"
                cursor.execute("SELECT * FROM code_usage WHERE code_id = ? AND user_id = ?", (code_id, user_id))
                if cursor.fetchone():
                    return False, "لقد استخدمت هذا الكود من قبل"
                cursor.execute("UPDATE recharge_codes SET used_count = used_count + 1 WHERE code_id = ?", (code_id,))
                cursor.execute("INSERT INTO code_usage (code_id, user_id) VALUES (?, ?)", (code_id, user_id))
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)", (user_id, amount, "recharge_code", f"شحن باستخدام كود"))
                self.conn.commit()
                return True, f"تم شحن {amount:.2f}$ بنجاح"
            except Exception as e:
                self.conn.rollback()
                logger.error(f"Error using recharge code: {e}")
                return False, "حدث خطأ أثناء استخدام الكود"
    
    def get_all_recharge_codes(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM recharge_codes ORDER BY created_at DESC")
        rows = cursor.fetchall()
        codes = []
        for row in rows:
            codes.append({'code_id': row[0], 'code': row[1], 'amount': row[2], 'max_uses': row[3], 'used_count': row[4], 'created_by': row[5], 'expires_at': row[6], 'created_at': row[7], 'is_active': row[8]})
        return codes

    # رابط الهدية
    def create_gift_link(self, from_user_id, amount):
        import secrets
        token = secrets.token_urlsafe(16)
        cursor = self.conn.cursor()
        try:
            balance = self.get_balance(from_user_id)
            if balance < amount:
                return False, "رصيدك غير كاف", None
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, from_user_id))
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                           (from_user_id, -amount, "gift_link_sent", f"إنشاء رابط هدية بقيمة {amount:.2f}$"))
            cursor.execute("INSERT INTO gift_links (token, from_user_id, amount) VALUES (?, ?, ?)",
                           (token, from_user_id, amount))
            self.conn.commit()
            return True, "تم إنشاء رابط الهدية", token
        except Exception as e:
            self.conn.rollback()
            return False, f"خطا: {e}", None

    def use_gift_link(self, token, user_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT * FROM gift_links WHERE token = ?", (token,))
            row = cursor.fetchone()
            if not row:
                return False, "رابط الهدية غير صالح"
            gift = {'gift_id': row[0], 'token': row[1], 'from_user_id': row[2], 'amount': row[3], 'is_used': row[4]}
            if gift['is_used']:
                return False, "تم استخدام هذا الرابط مسبقا"
            if gift['from_user_id'] == user_id:
                return False, "لا يمكنك استخدام رابط هديتك الخاص"
            cursor.execute("UPDATE gift_links SET is_used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP WHERE token = ?",
                           (user_id, token))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                           (gift['amount'], user_id))
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                           (user_id, gift['amount'], "gift_link_received", f"استلام هدية بقيمة {gift['amount']:.2f}$"))
            self.conn.commit()
            return True, gift['amount']
        except Exception as e:
            self.conn.rollback()
            return False, f"خطا: {e}"

    # كود التحويل
    def create_transfer_code(self, from_user_id, amount):
        import secrets
        code = "TC-" + secrets.token_hex(4).upper()
        cursor = self.conn.cursor()
        try:
            balance = self.get_balance(from_user_id)
            if balance < amount:
                return False, "رصيدك غير كاف", None
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, from_user_id))
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                           (from_user_id, -amount, "transfer_code_sent", f"إنشاء كود تحويل بقيمة {amount:.2f}$"))
            cursor.execute("INSERT INTO transfer_codes (code, from_user_id, amount) VALUES (?, ?, ?)",
                           (code, from_user_id, amount))
            self.conn.commit()
            return True, "تم إنشاء الكود", code
        except Exception as e:
            self.conn.rollback()
            return False, f"خطا: {e}", None

    def use_transfer_code(self, code, user_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT * FROM transfer_codes WHERE code = ?", (code,))
            row = cursor.fetchone()
            if not row:
                return False, "الكود غير صالح"
            tc = {'tc_id': row[0], 'code': row[1], 'from_user_id': row[2], 'amount': row[3], 'is_used': row[4]}
            if tc['is_used']:
                return False, "تم استخدام هذا الكود مسبقا"
            if tc['from_user_id'] == user_id:
                return False, "لا يمكنك استخدام كودك الخاص"
            cursor.execute("UPDATE transfer_codes SET is_used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP WHERE code = ?",
                           (user_id, code))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                           (tc['amount'], user_id))
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                           (user_id, tc['amount'], "transfer_code_received", f"استخدام كود تحويل بقيمة {tc['amount']:.2f}$"))
            self.conn.commit()
            return True, tc['amount']
        except Exception as e:
            self.conn.rollback()
            return False, f"خطا: {e}"

    # ====== نظام الكروت والإحالات ======

    def get_referral_link_prefix(self, bot_username):
        return f"https://t.me/{bot_username}?start=ref_"

    def register_referral(self, referrer_user_id, referred_user_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT referral_id FROM referrals WHERE referred_user_id=?", (referred_user_id,))
            if cursor.fetchone():
                return False, "سبق إحالته"
            if referrer_user_id == referred_user_id:
                return False, "لا يمكن إحالة نفسك"
            cursor.execute(
                "INSERT INTO referrals (referrer_user_id, referred_user_id) VALUES (?,?)",
                (referrer_user_id, referred_user_id)
            )
            card_number = self._generate_card_number()
            cursor.execute(
                "INSERT INTO referral_cards (card_number, owner_user_id, referred_user_id) VALUES (?,?,?)",
                (card_number, referrer_user_id, referred_user_id)
            )
            self.conn.commit()
            return True, card_number
        except Exception as e:
            self.conn.rollback()
            logger.error(f"register_referral error: {e}")
            return False, str(e)

    def _generate_card_number(self):
        import secrets as _s
        for _ in range(20):
            num = "".join([str(_s.randbelow(10)) for _ in range(13)])
            cursor = self.conn.cursor()
            cursor.execute("SELECT card_id FROM referral_cards WHERE card_number=?", (num,))
            if not cursor.fetchone():
                return num
        raise Exception("فشل توليد رقم كارت فريد")

    def get_user_cards(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT card_number, created_at FROM referral_cards WHERE owner_user_id=? ORDER BY created_at DESC",
            (user_id,)
        )
        return [{'card_number': r[0], 'created_at': r[1]} for r in cursor.fetchall()]

    def get_user_free_cards_count(self, user_id, contest_id=None):
        """
        يُرجع عدد كروت المستخدم غير المستخدمة.
        - contest_id=None  → الكروت غير المسجّلة في أي مسابقة (للقائمة الرئيسية).
        - contest_id=N     → الكروت غير المسجّلة في هذه المسابقة تحديداً (لصفحة التفاصيل).
        """
        cursor = self.conn.cursor()
        if contest_id is not None:
            cursor.execute(
                "SELECT COUNT(*) FROM referral_cards WHERE owner_user_id=? "
                "AND card_number NOT IN "
                "(SELECT card_number FROM contest_entry_cards WHERE contest_id=?)",
                (user_id, contest_id)
            )
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM referral_cards WHERE owner_user_id=? AND card_number NOT IN "
                "(SELECT card_number FROM contest_entry_cards)",
                (user_id,)
            )
        return cursor.fetchone()[0] or 0

    def get_user_referral_count(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_user_id=?", (user_id,))
        return cursor.fetchone()[0] or 0

    # ====== نظام المسابقات ======

    def create_contest(self, name, description, prize_amount, start_at, created_by, prize_description=''):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO contests (name, description, prize_amount, start_at, created_by, prize_description) VALUES (?,?,?,?,?,?)",
                (name, description, prize_amount, start_at, created_by, prize_description)
            )
            self.conn.commit()
            return True, cursor.lastrowid
        except Exception as e:
            logger.error(f"create_contest error: {e}")
            return False, str(e)

    def get_contest(self, contest_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM contests WHERE contest_id=?", (contest_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {'contest_id': row[0], 'name': row[1], 'description': row[2],
                'prize_amount': row[3], 'start_at': row[4], 'status': row[5],
                'channel_message_id': row[6], 'channel_id': row[7],
                'winner_card': row[8], 'winner_user_id': row[9],
                'created_by': row[10], 'created_at': row[11],
                'prize_description': row[12] if len(row) > 12 else '',
                'winner_prize_code': row[13] if len(row) > 13 else ''}

    def get_all_contests(self, status=None):
        cursor = self.conn.cursor()
        if status:
            cursor.execute("SELECT * FROM contests WHERE status=? ORDER BY created_at DESC", (status,))
        else:
            cursor.execute("SELECT * FROM contests ORDER BY created_at DESC LIMIT 20")
        rows = cursor.fetchall()
        return [{'contest_id': r[0], 'name': r[1], 'description': r[2],
                 'prize_amount': r[3], 'start_at': r[4], 'status': r[5],
                 'channel_message_id': r[6], 'channel_id': r[7],
                 'winner_card': r[8], 'winner_user_id': r[9],
                 'created_by': r[10], 'created_at': r[11],
                 'prize_description': r[12] if len(r) > 12 else '',
                 'winner_prize_code': r[13] if len(r) > 13 else ''} for r in rows]

    def update_contest(self, contest_id, **kwargs):
        cursor = self.conn.cursor()
        allowed = {'name', 'description', 'prize_amount', 'start_at', 'status',
                   'channel_message_id', 'channel_id', 'winner_card', 'winner_user_id',
                   'prize_description', 'winner_prize_code'}
        fields = [f"{k}=?" for k in kwargs if k in allowed]
        vals = [v for k, v in kwargs.items() if k in allowed]
        if not fields:
            return
        vals.append(contest_id)
        cursor.execute(f"UPDATE contests SET {', '.join(fields)} WHERE contest_id=?", vals)
        self.conn.commit()

    def save_contest_message(self, contest_id, channel_id, message_id):
        """يحفظ رسالة المسابقة لكل قناة في جدول منفصل (يدعم أكثر من قناة)"""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO contest_channel_messages (contest_id, channel_id, message_id) VALUES (?,?,?)",
            (contest_id, channel_id, message_id)
        )
        # نحدث أيضاً حقل القناة الأولى في جدول contests للتوافق مع الكود القديم
        cursor.execute(
            "UPDATE contests SET channel_id=?, channel_message_id=? WHERE contest_id=? AND channel_message_id IS NULL",
            (channel_id, message_id, contest_id)
        )
        self.conn.commit()

    def get_contest_channel_messages(self, contest_id):
        """يُرجع كل رسائل المسابقة في القنوات"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT channel_id, message_id FROM contest_channel_messages WHERE contest_id=?",
            (contest_id,)
        )
        return [{'channel_id': r[0], 'message_id': r[1]} for r in cursor.fetchall()]

    def delete_contest_channel_messages(self, contest_id):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM contest_channel_messages WHERE contest_id=?", (contest_id,))
        self.conn.commit()

    def enter_contest(self, contest_id, user_id):
        """يشترك المستخدم بجميع كروته الحرة في هذه المسابقة تحديداً"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                "SELECT card_number FROM referral_cards WHERE owner_user_id=? "
                "AND card_number NOT IN (SELECT card_number FROM contest_entry_cards WHERE contest_id=?)",
                (user_id, contest_id)
            )
            free_cards = [r[0] for r in cursor.fetchall()]
            if not free_cards:
                self.conn.rollback()
                return False, 0
            for cn in free_cards:
                cursor.execute(
                    "INSERT OR IGNORE INTO contest_entry_cards (contest_id, user_id, card_number) VALUES (?,?,?)",
                    (contest_id, user_id, cn)
                )
            cursor.execute(
                "INSERT INTO contest_entries (contest_id, user_id, cards_count) VALUES (?,?,?) "
                "ON CONFLICT(contest_id, user_id) DO UPDATE SET cards_count=cards_count+?",
                (contest_id, user_id, len(free_cards), len(free_cards))
            )
            self.conn.commit()
            return True, len(free_cards)
        except Exception as e:
            self.conn.rollback()
            logger.error(f"enter_contest error: {e}")
            return False, 0

    def get_contest_participants_count(self, contest_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM contest_entry_cards WHERE contest_id=?", (contest_id,))
        return cursor.fetchone()[0] or 0

    def get_contest_all_cards(self, contest_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT card_number, user_id FROM contest_entry_cards WHERE contest_id=?", (contest_id,)
        )
        return [{'card_number': r[0], 'user_id': r[1]} for r in cursor.fetchall()]

    def draw_contest_winner(self, contest_id):
        cards = self.get_contest_all_cards(contest_id)
        if not cards:
            return None, None
        import random as _r
        winner = _r.choice(cards)
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE contests SET status='completed', winner_card=?, winner_user_id=? WHERE contest_id=?",
            (winner['card_number'], winner['user_id'], contest_id)
        )
        self.conn.commit()
        return winner['card_number'], winner['user_id']

    # ====== نهاية نظام الكروت والمسابقات ======

    # عجلة الحظ (محتفظ بها للتوافق)
    def can_spin_wheel(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT spun_at FROM lucky_wheel_spins WHERE user_id = ? ORDER BY spun_at DESC LIMIT 1",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return True, None
        last_spin = datetime.strptime(str(row[0])[:19], "%Y-%m-%d %H:%M:%S")
        next_spin = last_spin + timedelta(hours=24)
        now = datetime.now()
        if now >= next_spin:
            return True, None
        remaining = next_spin - now
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        seconds = int(remaining.total_seconds() % 60)
        return False, (hours, minutes, seconds)

    def record_spin(self, user_id, amount_won):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT INTO lucky_wheel_spins (user_id, amount_won) VALUES (?, ?)", (user_id, amount_won))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount_won, user_id))
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                           (user_id, amount_won, "lucky_wheel", f"ربح عجلة الحظ: {amount_won:.2f}$"))
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            return False

    # دورة بونص أسبوعية للمستخدمين النشطين 
    def is_active_user_this_week(self, user_id):
        """نشط = شارك بمزايدة، طلب وساطة، أو طلب شحن خلال آخر 7 أيام"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM bids WHERE user_id=? AND bid_time >= datetime('now', '-7 days')",
            (user_id,)
        )
        bid_count = cursor.fetchone()[0] or 0
        if bid_count > 0:
            return True
        cursor.execute(
            "SELECT COUNT(*) FROM broker_requests WHERE user_id=? AND created_at >= datetime('now', '-7 days')",
            (user_id,)
        )
        broker_count = cursor.fetchone()[0] or 0
        if broker_count > 0:
            return True
        cursor.execute(
            "SELECT COUNT(*) FROM agent_charge_requests WHERE user_id=? AND created_at >= datetime('now', '-7 days')",
            (user_id,)
        )
        agent_count = cursor.fetchone()[0] or 0
        return agent_count > 0

    def can_spin_bonus_wheel(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT spun_at FROM weekly_bonus_spins WHERE user_id = ? ORDER BY spun_at DESC LIMIT 1",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return True, None
        last_spin = datetime.strptime(str(row[0])[:19], "%Y-%m-%d %H:%M:%S")
        next_spin = last_spin + timedelta(days=7)
        now = datetime.now()
        if now >= next_spin:
            return True, None
        remaining = next_spin - now
        days = int(remaining.total_seconds() // 86400)
        hours = int((remaining.total_seconds() % 86400) // 3600)
        return False, (days, hours)

    def record_bonus_spin(self, user_id, amount_won):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT INTO weekly_bonus_spins (user_id, amount_won) VALUES (?, ?)", (user_id, amount_won))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount_won, user_id))
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                           (user_id, amount_won, "weekly_bonus_wheel", f"ربح العجلة الأسبوعية المجانية: {amount_won:.2f}$"))
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            return False

    def get_wallet_stats(self, user_id):
        cursor = self.conn.cursor()
        # إجمالي الوارد
        cursor.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND amount>0",
            (user_id,)
        )
        total_in = cursor.fetchone()[0] or 0.0
        # إجمالي الصادر
        cursor.execute(
            "SELECT COALESCE(SUM(ABS(amount)),0) FROM transactions WHERE user_id=? AND amount<0",
            (user_id,)
        )
        total_out = cursor.fetchone()[0] or 0.0
        # عمليات الإرسال
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(ABS(amount)),0) FROM transactions WHERE user_id=? AND type IN ('transfer_sent','gift_link_sent','transfer_code_sent')",
            (user_id,)
        )
        row = cursor.fetchone()
        sent_count = row[0] or 0
        sent_total = row[1] or 0.0
        # عمليات الاستلام
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type IN ('transfer_received','gift_link_received','transfer_code_received')",
            (user_id,)
        )
        row = cursor.fetchone()
        recv_count = row[0] or 0
        recv_total = row[1] or 0.0
        # عمليات الشحن
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type IN ('recharge_code','binance_deposit','stars_deposit','charge_manual','agent_charge')",
            (user_id,)
        )
        row = cursor.fetchone()
        charge_count = row[0] or 0
        charge_total = row[1] or 0.0
        # عمليات المزادات (مزايدات)
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(ABS(amount)),0) FROM transactions WHERE user_id=? AND type='auction_bid'",
            (user_id,)
        )
        row = cursor.fetchone()
        bid_count = row[0] or 0
        bid_total = row[1] or 0.0
        # مبيعات المزادات
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type='auction_sale'",
            (user_id,)
        )
        row = cursor.fetchone()
        sale_count = row[0] or 0
        sale_total = row[1] or 0.0
        # العمولات المدفوعة
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(ABS(amount)),0) FROM transactions WHERE user_id=? AND type='commission'",
            (user_id,)
        )
        row = cursor.fetchone()
        commission_count = row[0] or 0
        commission_total = row[1] or 0.0
        # الاستردادات
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND type IN ('bid_refund','starting_price_refund','refund')",
            (user_id,)
        )
        row = cursor.fetchone()
        refund_count = row[0] or 0
        refund_total = row[1] or 0.0
        # آخر عملية
        cursor.execute(
            "SELECT amount, type, description, created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        last_row = cursor.fetchone()
        last_tx = None
        if last_row:
            last_tx = {'amount': last_row[0], 'type': last_row[1], 'description': last_row[2], 'created_at': str(last_row[3])[:16]}
        # عجلة الحظ
        cursor.execute(
            "SELECT COALESCE(SUM(amount_won),0), COUNT(*) FROM lucky_wheel_spins WHERE user_id=?",
            (user_id,)
        )
        row = cursor.fetchone()
        wheel_total = row[0] or 0.0
        wheel_count = row[1] or 0
        # إجمالي عدد العمليات
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id=?", (user_id,))
        total_ops = cursor.fetchone()[0] or 0
        return {
            'total_in': total_in, 'total_out': total_out,
            'sent_count': sent_count, 'sent_total': sent_total,
            'recv_count': recv_count, 'recv_total': recv_total,
            'charge_count': charge_count, 'charge_total': charge_total,
            'bid_count': bid_count, 'bid_total': bid_total,
            'sale_count': sale_count, 'sale_total': sale_total,
            'commission_count': commission_count, 'commission_total': commission_total,
            'refund_count': refund_count, 'refund_total': refund_total,
            'wheel_total': wheel_total, 'wheel_count': wheel_count,
            'total_ops': total_ops, 'last_tx': last_tx,
        }

    def get_recent_transactions(self, user_id, limit=10):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT amount, type, description, created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            result.append({'amount': r[0], 'type': r[1], 'description': r[2], 'created_at': str(r[3])[:16]})
        return result

    def mark_commission_paid(self, auction_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE auctions SET commission_paid = 1 WHERE auction_id = ?", (auction_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error marking commission as paid: {e}")
            return False

    def create_binance_payment(self, user_id, usdt_amount, usd_amount, wallet_address):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO binance_payments (user_id, usdt_amount, usd_amount, wallet_address) VALUES (?, ?, ?, ?)",
                (user_id, usdt_amount, usd_amount, wallet_address)
            )
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating binance payment: {e}")
            return None

    def complete_binance_payment(self, pay_id, binance_tx):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "SELECT user_id, usd_amount FROM binance_payments WHERE pay_id = ? AND status = 'pending'",
                    (pay_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return False, "الدفعة غير موجودة أو مكتملة مسبقاً"
                user_id, usd_amount = row
                cursor.execute(
                    "UPDATE binance_payments SET status='completed', binance_tx=?, completed_at=CURRENT_TIMESTAMP WHERE pay_id=?",
                    (binance_tx, pay_id)
                )
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (usd_amount, user_id))
                cursor.execute(
                    "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                    (user_id, usd_amount, "binance_deposit", f"شحن عبر Binance — {usd_amount:.2f}$")
                )
                self.conn.commit()
                return True, user_id
            except Exception as e:
                self.conn.rollback()
                logger.error(f"Error completing binance payment: {e}")
                return False, str(e)

    def get_pending_binance_payments(self):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM binance_payments WHERE status='pending' ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()
        return [
            {'pay_id': r[0], 'user_id': r[1], 'usdt_amount': r[2],
             'usd_amount': r[3], 'wallet_address': r[4],
             'status': r[5], 'binance_tx': r[6], 'created_at': r[7]}
            for r in rows
        ]

    def get_all_binance_payments(self):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM binance_payments ORDER BY created_at DESC LIMIT 20"
        )
        rows = cursor.fetchall()
        return [
            {'pay_id': r[0], 'user_id': r[1], 'usdt_amount': r[2],
             'usd_amount': r[3], 'wallet_address': r[4],
             'status': r[5], 'binance_tx': r[6], 'created_at': r[7]}
            for r in rows
        ]

    # دوال نجوم تيليجرام 
    def create_stars_payment(self, user_id, stars_amount, usd_amount, invoice_payload):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO stars_payments (user_id, stars_amount, usd_amount, invoice_payload) VALUES (?, ?, ?, ?)",
                (user_id, stars_amount, usd_amount, invoice_payload)
            )
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creating stars payment: {e}")
            return None

    def complete_stars_payment(self, invoice_payload, telegram_charge_id):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "SELECT pay_id, user_id, usd_amount FROM stars_payments WHERE invoice_payload = ? AND status = 'pending'",
                    (invoice_payload,)
                )
                row = cursor.fetchone()
                if not row:
                    return False, "الدفعة غير موجودة أو مكتملة مسبقاً"
                pay_id, user_id, usd_amount = row
                cursor.execute(
                    "UPDATE stars_payments SET status='completed', telegram_charge_id=?, completed_at=CURRENT_TIMESTAMP WHERE pay_id=?",
                    (telegram_charge_id, pay_id)
                )
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (usd_amount, user_id))
                cursor.execute(
                    "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                    (user_id, usd_amount, "stars_deposit", f"شحن عبر نجوم تيليجرام — {usd_amount:.2f}$")
                )
                self.conn.commit()
                return True, (user_id, usd_amount)
            except Exception as e:
                self.conn.rollback()
                logger.error(f"Error completing stars payment: {e}")
                return False, str(e)

    def get_all_stars_payments(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM stars_payments ORDER BY created_at DESC LIMIT 20")
        rows = cursor.fetchall()
        return [
            {'pay_id': r[0], 'user_id': r[1], 'stars_amount': r[2],
             'usd_amount': r[3], 'telegram_charge_id': r[4],
             'invoice_payload': r[5], 'status': r[6], 'created_at': r[7]}
            for r in rows
        ]

    def get_setting(self, key, default=None):
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, str(value)))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error setting bot setting: {e}")
            return False

    def get_auction_duration(self):
        val = self.get_setting('auction_duration', str(DEFAULT_AUCTION_DURATION))
        try:
            return int(val)
        except:
            return DEFAULT_AUCTION_DURATION

    def ban_user(self, user_id, reason="", banned_by=None):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO banned_users (user_id, reason, banned_by) VALUES (?, ?, ?)",
                (user_id, reason, banned_by)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False

    def unban_user(self, user_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            return False

    def is_banned(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

    def get_banned_users(self):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT b.user_id, b.reason, b.banned_at, u.username, u.first_name "
            "FROM banned_users b LEFT JOIN users u ON b.user_id = u.user_id "
            "ORDER BY b.banned_at DESC"
        )
        rows = cursor.fetchall()
        return [{'user_id': r[0], 'reason': r[1], 'banned_at': r[2], 'username': r[3], 'first_name': r[4]} for r in rows]

    def search_user(self, query):
        """البحث عن مستخدم بالأيدي أو المعرف أو الاسم"""
        cursor = self.conn.cursor()
        if query.isdigit():
            cursor.execute(
                "SELECT user_id, username, first_name, last_name, balance, created_at FROM users WHERE user_id = ?",
                (int(query),)
            )
        else:
            q = query.lstrip('@').lower()
            cursor.execute(
                "SELECT user_id, username, first_name, last_name, balance, created_at FROM users "
                "WHERE LOWER(username) = ? OR LOWER(first_name) LIKE ?",
                (q, f"%{q}%")
            )
        rows = cursor.fetchall()
        return [{'user_id': r[0], 'username': r[1], 'first_name': r[2], 'last_name': r[3], 'balance': r[4], 'created_at': r[5]} for r in rows]

    def admin_set_balance(self, user_id, amount, admin_id, note=""):
        """إضافة أو خصم رصيد مباشر من الأدمن"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            desc = f"تعديل أدمن مباشر: {'+' if amount >= 0 else ''}{amount:.2f}$"
            if note:
                desc += f" - {note}"
            cursor.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, amount, "admin_adjustment", desc)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error admin_set_balance: {e}")
            return False

    # Onboarding 
    def has_completed_onboarding(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT completed FROM user_onboarding WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        return row and row[0] == 1

    def complete_onboarding(self, user_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO user_onboarding (user_id, completed, completed_at) VALUES (?,1,CURRENT_TIMESTAMP)",
                (user_id,)
            )
            cursor.execute("UPDATE users SET terms_accepted=1 WHERE user_id=?", (user_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error complete_onboarding: {e}")
            return False

    # Reports 
    def add_report(self, reported_user_id, reporter_user_id, reason=""):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO user_reports (reported_user_id, reporter_user_id, reason) VALUES (?,?,?)",
                (reported_user_id, reporter_user_id, reason)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error add_report: {e}")
            return False

    def get_user_reports(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT report_id, reporter_user_id, reason, created_at FROM user_reports WHERE reported_user_id=? ORDER BY created_at DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        return [{'report_id': r[0], 'reporter_user_id': r[1], 'reason': r[2], 'created_at': r[3]} for r in rows]

    def add_auction_report(self, auction_id, reporter_user_id, reason):
        cursor = self.conn.cursor()
        try:
            # منع التبليغ مرتين من نفس المستخدم
            cursor.execute(
                "SELECT report_id FROM auction_reports WHERE auction_id=? AND reporter_user_id=?",
                (auction_id, reporter_user_id)
            )
            if cursor.fetchone():
                return False, "لقد أبلغت عن هذا المزاد مسبقاً!"
            cursor.execute(
                "INSERT INTO auction_reports (auction_id, reporter_user_id, reason) VALUES (?,?,?)",
                (auction_id, reporter_user_id, reason)
            )
            self.conn.commit()
            return True, "تم إرسال البلاغ بنجاح"
        except Exception as e:
            logger.error(f"Error add_auction_report: {e}")
            return False, "حدث خطأ أثناء الإرسال"

    def get_auction_reports(self, auction_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT ar.report_id, ar.reporter_user_id, ar.reason, ar.created_at, u.username, u.first_name "
            "FROM auction_reports ar LEFT JOIN users u ON ar.reporter_user_id=u.user_id "
            "WHERE ar.auction_id=? ORDER BY ar.created_at DESC",
            (auction_id,)
        )
        rows = cursor.fetchall()
        return [{'report_id': r[0], 'reporter_user_id': r[1], 'reason': r[2],
                 'created_at': r[3], 'username': r[4], 'first_name': r[5]} for r in rows]

    def get_auction_report_count(self, auction_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM auction_reports WHERE auction_id=?", (auction_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def get_report_count(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_reports WHERE reported_user_id=?", (user_id,))
        return cursor.fetchone()[0] or 0

    # Verification 
    def save_verification(self, user_id, phone=None, lat=None, lon=None):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO user_verification (user_id, phone, location_lat, location_lon, verified_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                (user_id, phone, lat, lon)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error save_verification: {e}")
            return False

    def get_verification(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT phone, location_lat, location_lon, verified_at FROM user_verification WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        if row:
            return {'phone': row[0], 'lat': row[1], 'lon': row[2], 'verified_at': row[3]}
        return None

    def is_verified(self, user_id):
        v = self.get_verification(user_id)
        return v is not None and v['phone'] is not None and v['lat'] is not None

    # Extend/Reduce Auction Time 
    def extend_auction_time(self, auction_id, minutes):
        """تمديد أو تقليص وقت المزاد بعدد دقائق (سالب للتقليص)"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT ends_at FROM auctions WHERE auction_id=? AND status='active'", (auction_id,))
            row = cursor.fetchone()
            if not row:
                return False, "المزاد غير نشط أو غير موجود"
            ends_at = self.parse_datetime(row[0])
            new_ends_at = ends_at + timedelta(minutes=minutes)
            if new_ends_at <= datetime.now():
                return False, "لا يمكن تقليص الوقت لأقل من الوقت الحالي"
            cursor.execute("UPDATE auctions SET ends_at=? WHERE auction_id=?", (new_ends_at, auction_id))
            self.conn.commit()
            return True, new_ends_at
        except Exception as e:
            logger.error(f"Error extend_auction_time: {e}")
            return False, str(e)

    # طلبات السحب 
    def create_withdrawal_request(self, user_id, amount, method, details):
        cursor = self.conn.cursor()
        try:
            balance = self.get_balance(user_id)
            if balance < amount:
                return False, "رصيدك غير كافٍ", None
            # فحص لا يوجد طلب معلق مسبق
            cursor.execute(
                "SELECT COUNT(*) FROM withdrawal_requests WHERE user_id=? AND status='pending'",
                (user_id,)
            )
            if cursor.fetchone()[0] > 0:
                return False, "لديك طلب سحب قيد المعالجة بالفعل", None
            fee = round(amount * WITHDRAW_FEE_PERCENT, 4)
            net = round(amount - fee, 4)
            # خصم المبلغ مؤقتاً وتجميده
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            cursor.execute(
                "INSERT INTO withdrawal_requests (user_id, amount, method, details) VALUES (?, ?, ?, ?)",
                (user_id, amount, method, details)
            )
            req_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, -amount, "withdrawal_pending", f"طلب سحب #{req_id} — {net:.2f}$ صافي عبر {method}")
            )
            self.conn.commit()
            return True, "تم إرسال طلب السحب", req_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error create_withdrawal_request: {e}")
            return False, "حدث خطأ", None

    def get_withdrawal_by_id(self, request_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT wr.*, u.username, u.first_name FROM withdrawal_requests wr "
            "LEFT JOIN users u ON wr.user_id=u.user_id WHERE wr.request_id=?",
            (request_id,)
        )
        r = cursor.fetchone()
        if not r:
            return None
        return {
            'request_id': r[0], 'user_id': r[1], 'amount': r[2],
            'method': r[3], 'details': r[4], 'status': r[5],
            'admin_note': r[6], 'created_at': r[7], 'processed_at': r[8],
            'username': r[9], 'first_name': r[10]
        }

    def has_pending_withdrawal(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM withdrawal_requests WHERE user_id=? AND status='pending'",
            (user_id,)
        )
        return (cursor.fetchone()[0] or 0) > 0

    def approve_withdrawal(self, request_id, admin_note=""):
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT * FROM withdrawal_requests WHERE request_id = ?", (request_id,))
            row = cursor.fetchone()
            if not row or row[5] != 'pending':
                return False, "الطلب غير موجود أو تمت معالجته"
            user_id_r, amount = row[1], row[2]
            fee = round(amount * WITHDRAW_FEE_PERCENT, 4)
            net = round(amount - fee, 4)
            cursor.execute(
                "UPDATE withdrawal_requests SET status='approved', admin_note=?, processed_at=CURRENT_TIMESTAMP WHERE request_id=?",
                (admin_note, request_id)
            )
            cursor.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id_r, 0, "withdraw", f"سحب مقبول #{request_id} — {net:.2f}$ صافي عبر {row[3]}")
            )
            self.conn.commit()
            return True, {'user_id': user_id_r, 'amount': amount, 'net': net, 'method': row[3], 'details': row[4]}
        except Exception as e:
            logger.error(f"Error approve_withdrawal: {e}")
            return False, str(e)

    def reject_withdrawal(self, request_id, admin_note=""):
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT * FROM withdrawal_requests WHERE request_id = ?", (request_id,))
            row = cursor.fetchone()
            if not row or row[5] != 'pending':
                return False, "الطلب غير موجود أو تمت معالجته"
            user_id_r, amount = row[1], row[2]
            # إعادة الرصيد للمستخدم
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id_r))
            cursor.execute(
                "UPDATE withdrawal_requests SET status='rejected', admin_note=?, processed_at=CURRENT_TIMESTAMP WHERE request_id=?",
                (admin_note, request_id)
            )
            cursor.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id_r, amount, "withdrawal_refund", f"استرداد طلب سحب #{request_id} (مرفوض)")
            )
            self.conn.commit()
            return True, {'user_id': user_id_r, 'amount': amount, 'method': row[3]}
        except Exception as e:
            logger.error(f"Error reject_withdrawal: {e}")
            return False, str(e)

    def get_pending_withdrawals(self):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT wr.*, u.username, u.first_name FROM withdrawal_requests wr "
            "LEFT JOIN users u ON wr.user_id = u.user_id "
            "WHERE wr.status = 'pending' ORDER BY wr.created_at ASC"
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            result.append({
                'request_id': r[0], 'user_id': r[1], 'amount': r[2],
                'method': r[3], 'details': r[4], 'status': r[5],
                'admin_note': r[6], 'created_at': r[7], 'processed_at': r[8],
                'username': r[9], 'first_name': r[10]
            })
        return result

    def get_user_withdrawals(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM withdrawal_requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        )
        rows = cursor.fetchall()
        return [{'request_id': r[0], 'user_id': r[1], 'amount': r[2], 'method': r[3],
                 'details': r[4], 'status': r[5], 'admin_note': r[6], 'created_at': r[7]} for r in rows]

    def get_user_withdrawals_today(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM withdrawal_requests WHERE user_id = ? AND DATE(created_at) = DATE('now')",
            (user_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def add_charge_request(self, user_id, amount, method, proof):
        """تسجيل طلب شحن يدوي (زين كاش / كي كارد) بانتظار تأكيد الأدمن"""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO withdrawal_requests (user_id, amount, method, details, status) VALUES (?, ?, ?, ?, 'pending_charge')",
                (user_id, amount, method, proof)
            )
            self.conn.commit()
            return True, cursor.lastrowid
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error add_charge_request: {e}")
            return False, None

    def approve_charge_request(self, request_id):
        """قبول طلب شحن يدوي وإضافة الرصيد للمستخدم"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT * FROM withdrawal_requests WHERE request_id = ?", (request_id,))
            row = cursor.fetchone()
            if not row or row[5] != 'pending_charge':
                return False, "الطلب غير موجود أو تمت معالجته"
            user_id, amount, method = row[1], row[2], row[3]
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            cursor.execute(
                "UPDATE withdrawal_requests SET status='approved', processed_at=CURRENT_TIMESTAMP WHERE request_id=?",
                (request_id,)
            )
            cursor.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, amount, "charge_manual", f"شحن يدوي {amount:.2f}$ عبر {method} (طلب #{request_id})")
            )
            self.conn.commit()
            return True, (user_id, amount, method)
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error approve_charge_request: {e}")
            return False, str(e)

    def reject_charge_request(self, request_id, reason=""):
        """رفض طلب شحن يدوي بدون إضافة رصيد"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("SELECT * FROM withdrawal_requests WHERE request_id = ?", (request_id,))
            row = cursor.fetchone()
            if not row or row[5] != 'pending_charge':
                return False, "الطلب غير موجود أو تمت معالجته"
            user_id = row[1]
            cursor.execute(
                "UPDATE withdrawal_requests SET status='rejected', admin_note=?, processed_at=CURRENT_TIMESTAMP WHERE request_id=?",
                (reason, request_id)
            )
            self.conn.commit()
            return True, user_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error reject_charge_request: {e}")
            return False, str(e)

    # الوكلاء 
    def add_agent(self, user_id, name, description, contact, added_by):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO agents (user_id, name, description, contact, added_by, is_active) VALUES (?,?,?,?,?,1)",
                (user_id, name, description, contact, added_by)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error add_agent: {e}")
            return False

    def remove_agent(self, user_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("DELETE FROM agents WHERE user_id=?", (user_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error remove_agent: {e}")
            return False

    def get_all_agents(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT a.*, u.username, u.first_name FROM agents a LEFT JOIN users u ON a.user_id=u.user_id WHERE a.is_active=1 ORDER BY a.added_at DESC")
        rows = cursor.fetchall()
        return [{'agent_id': r[0], 'user_id': r[1], 'name': r[2], 'description': r[3],
                 'contact': r[4], 'is_active': r[5], 'added_by': r[6], 'added_at': r[7],
                 'username': r[8], 'first_name': r[9]} for r in rows]

    def is_agent(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT agent_id FROM agents WHERE user_id=? AND is_active=1", (user_id,))
        return cursor.fetchone() is not None

    def add_agent_report(self, agent_user_id, reporter_user_id, charge_code, reason):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO agent_reports (agent_user_id, reporter_user_id, charge_code, reason) VALUES (?,?,?,?)",
                (agent_user_id, reporter_user_id, charge_code, reason)
            )
            self.conn.commit()
            return True, cursor.lastrowid
        except Exception as e:
            logger.error(f"Error add_agent_report: {e}")
            return False, str(e)

    def get_agent_reports(self, status='pending'):
        cursor = self.conn.cursor()
        q = (
            "SELECT ar.*, u.username, u.first_name, a.name FROM agent_reports ar "
            "LEFT JOIN users u ON ar.reporter_user_id=u.user_id "
            "LEFT JOIN agents a ON ar.agent_user_id=a.user_id "
        )
        params = []
        if status:
            q += "WHERE ar.status=? "
            params.append(status)
        q += "ORDER BY ar.created_at DESC LIMIT 30"
        cursor.execute(q, params)
        rows = cursor.fetchall()
        return [{'report_id': r[0], 'agent_user_id': r[1], 'reporter_user_id': r[2],
                 'charge_code': r[3], 'reason': r[4], 'status': r[5], 'created_at': r[6],
                 'reporter_username': r[7], 'reporter_name': r[8], 'agent_name': r[9]} for r in rows]

    def resolve_agent_report(self, report_id):
        """يضع علامة 'تم الاطلاع' على بلاغ وكيل — يخرجه من شارة العداد المعلّق"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE agent_reports SET status='resolved' WHERE report_id=?", (report_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error resolve_agent_report: {e}")
            return False

    # الوسطاء 
    def add_broker(self, user_id, name, description, contact, added_by):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO brokers (user_id, name, description, contact, added_by, is_active) VALUES (?,?,?,?,?,1)",
                (user_id, name, description, contact, added_by)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error add_broker: {e}")
            return False

    def remove_broker(self, user_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("DELETE FROM brokers WHERE user_id=?", (user_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error remove_broker: {e}")
            return False

    def get_all_brokers(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT b.*, u.username, u.first_name FROM brokers b LEFT JOIN users u ON b.user_id=u.user_id WHERE b.is_active=1 ORDER BY b.added_at DESC")
        rows = cursor.fetchall()
        return [{'broker_id': r[0], 'user_id': r[1], 'name': r[2], 'description': r[3],
                 'contact': r[4], 'is_active': r[5], 'added_by': r[6], 'added_at': r[7],
                 'username': r[8], 'first_name': r[9]} for r in rows]

    def is_broker(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT broker_id FROM brokers WHERE user_id=? AND is_active=1", (user_id,))
        return cursor.fetchone() is not None

    # طلبات الشحن عبر الوكيل 
    def create_agent_charge_request(self, user_id, agent_user_id, amount, reason):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO agent_charge_requests (user_id, agent_user_id, amount, reason) VALUES (?,?,?,?)",
                (user_id, agent_user_id, amount, reason)
            )
            self.conn.commit()
            return True, cursor.lastrowid
        except Exception as e:
            return False, str(e)

    def get_agent_charge_requests(self, agent_user_id=None, status=None):
        cursor = self.conn.cursor()
        q = """SELECT r.*, u.username, u.first_name FROM agent_charge_requests r
               LEFT JOIN users u ON r.user_id=u.user_id WHERE 1=1"""
        params = []
        if agent_user_id:
            q += " AND r.agent_user_id=?"; params.append(agent_user_id)
        if status:
            q += " AND r.status=?"; params.append(status)
        q += " ORDER BY r.created_at DESC"
        cursor.execute(q, params)
        rows = cursor.fetchall()
        keys = ['req_id','user_id','agent_user_id','amount','reason','status','admin_note','created_at','processed_at','username','first_name']
        return [dict(zip(keys, r)) for r in rows]

    def update_agent_charge_request(self, req_id, status, admin_note=''):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                # تحقق من الحالة الحالية لتجنب التكرار
                cursor.execute("SELECT status FROM agent_charge_requests WHERE req_id=?", (req_id,))
                row = cursor.fetchone()
                if not row:
                    return False
                # لا تحديث لو أُنجز مسبقاً
                if row[0] in ('admin_approved', 'rejected') and status in ('admin_approved', 'rejected'):
                    return False
                cursor.execute(
                    "UPDATE agent_charge_requests SET status=?, admin_note=?, processed_at=CURRENT_TIMESTAMP WHERE req_id=?",
                    (status, admin_note, req_id)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"update_agent_charge_request error: {e}")
                return False

    def get_agent_charge_request_by_id(self, req_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT r.*, u.username, u.first_name FROM agent_charge_requests r LEFT JOIN users u ON r.user_id=u.user_id WHERE r.req_id=?",
            (req_id,)
        )
        r = cursor.fetchone()
        if not r: return None
        keys = ['req_id','user_id','agent_user_id','amount','reason','status','admin_note','created_at','processed_at','username','first_name']
        return dict(zip(keys, r))

    def get_agent_stats(self, agent_user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM agent_charge_requests WHERE agent_user_id=? AND status IN ('agent_approved','admin_approved')", (agent_user_id,))
        r = cursor.fetchone()
        total_req, total_charged = (r[0] or 0), (r[1] or 0.0)
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM agent_profits WHERE agent_user_id=?", (agent_user_id,))
        total_profit = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT COUNT(*) FROM agent_charge_requests WHERE agent_user_id=? AND status='pending'", (agent_user_id,))
        pending = cursor.fetchone()[0] or 0
        return {'total_req': total_req, 'total_charged': total_charged, 'total_profit': total_profit, 'pending': pending}

    def get_agent_monthly_stats(self, agent_user_id):
        """إحصائيات الشهر الحالي مقارنة بالشهر السابق للوكيل"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM agent_charge_requests WHERE agent_user_id=? "
            "AND status='admin_approved' AND strftime('%Y-%m', processed_at) = strftime('%Y-%m', 'now')",
            (agent_user_id,)
        )
        r = cursor.fetchone()
        this_month, this_month_charged = (r[0] or 0), (r[1] or 0.0)
        cursor.execute(
            "SELECT COUNT(*) FROM agent_charge_requests WHERE agent_user_id=? "
            "AND status='admin_approved' AND strftime('%Y-%m', processed_at) = strftime('%Y-%m', 'now', '-1 month')",
            (agent_user_id,)
        )
        last_month = cursor.fetchone()[0] or 0
        return {'this_month': this_month, 'last_month': last_month, 'this_month_charged': this_month_charged}

    def add_agent_profit(self, agent_user_id, req_id, amount):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT INTO agent_profits (agent_user_id, req_id, amount) VALUES (?,?,?)", (agent_user_id, req_id, amount))
            self.conn.commit()
        except Exception: pass

    # تنبيهات وبلاغات الإدارة للوكلاء (من لوحة الإدارة) 
    def add_agent_warning(self, agent_user_id, reason, issued_by, warning_type='warning'):
        """يسجّل تنبيهاً أو بلاغاً من الإدارة لوكيل معيّن"""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO agent_warnings (agent_user_id, warning_type, reason, issued_by) VALUES (?,?,?,?)",
                (agent_user_id, warning_type, reason, issued_by)
            )
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error add_agent_warning: {e}")
            return None

    def get_agent_warnings(self, agent_user_id, limit=10):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT warning_id, warning_type, reason, issued_by, created_at FROM agent_warnings "
            "WHERE agent_user_id=? ORDER BY created_at DESC LIMIT ?",
            (agent_user_id, limit)
        )
        rows = cursor.fetchall()
        return [{'warning_id': r[0], 'warning_type': r[1], 'reason': r[2],
                 'issued_by': r[3], 'created_at': r[4]} for r in rows]

    def get_agent_warning_count(self, agent_user_id, warning_type='warning'):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM agent_warnings WHERE agent_user_id=? AND warning_type=?",
            (agent_user_id, warning_type)
        )
        return cursor.fetchone()[0] or 0

    def get_agent_full_stats(self, agent_user_id):
        """تحليل شامل لعمل الوكيل: الطلبات، نسبة القبول، المبالغ المُشحَّنة، الأرباح — لوحة الإدارة"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM agent_charge_requests WHERE agent_user_id=?", (agent_user_id,))
        total = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM agent_charge_requests WHERE agent_user_id=? AND status='admin_approved'", (agent_user_id,))
        approved = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM agent_charge_requests WHERE agent_user_id=? AND status='rejected'", (agent_user_id,))
        rejected = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM agent_charge_requests WHERE agent_user_id=? AND status IN ('pending','agent_approved')", (agent_user_id,))
        pending = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM agent_charge_requests WHERE agent_user_id=? AND status='admin_approved'", (agent_user_id,))
        total_charged = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM agent_profits WHERE agent_user_id=?", (agent_user_id,))
        total_profit = cursor.fetchone()[0] or 0.0
        decided = approved + rejected
        approval_rate = (approved / decided * 100) if decided else 0.0
        return {
            'total': total, 'approved': approved, 'rejected': rejected, 'pending': pending,
            'total_charged': total_charged, 'total_profit': total_profit, 'approval_rate': approval_rate
        }

    # طلبات الوساطة 
    def create_broker_request(self, user_id, broker_user_id, service_type, details):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO broker_requests (user_id, broker_user_id, service_type, details) VALUES (?,?,?,?)",
                (user_id, broker_user_id, service_type, details)
            )
            self.conn.commit()
            return True, cursor.lastrowid
        except Exception as e:
            return False, str(e)

    def get_broker_requests(self, broker_user_id=None, status=None):
        cursor = self.conn.cursor()
        q = """SELECT r.*, u.username, u.first_name FROM broker_requests r
               LEFT JOIN users u ON r.user_id=u.user_id WHERE 1=1"""
        params = []
        if broker_user_id:
            q += " AND r.broker_user_id=?"; params.append(broker_user_id)
        if status:
            q += " AND r.status=?"; params.append(status)
        q += " ORDER BY r.created_at DESC"
        cursor.execute(q, params)
        rows = cursor.fetchall()
        keys = ['req_id','user_id','broker_user_id','service_type','details','status','admin_note','created_at','processed_at','username','first_name']
        return [dict(zip(keys, r)) for r in rows]

    def get_broker_request_by_id(self, req_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT r.*, u.username, u.first_name FROM broker_requests r LEFT JOIN users u ON r.user_id=u.user_id WHERE r.req_id=?",
            (req_id,)
        )
        r = cursor.fetchone()
        if not r: return None
        keys = ['req_id','user_id','broker_user_id','service_type','details','status','admin_note','created_at','processed_at','username','first_name']
        return dict(zip(keys, r))

    def update_broker_request(self, req_id, status, admin_note=''):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("SELECT status FROM broker_requests WHERE req_id=?", (req_id,))
                row = cursor.fetchone()
                if not row:
                    return False
                if row[0] in ('approved', 'rejected') and status in ('approved', 'rejected'):
                    return False
                cursor.execute(
                    "UPDATE broker_requests SET status=?, admin_note=?, processed_at=CURRENT_TIMESTAMP WHERE req_id=?",
                    (status, admin_note, req_id)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"update_broker_request error: {e}")
                return False

    def get_broker_stats(self, broker_user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status IN ('approved','admin_approved')", (broker_user_id,))
        total_approved = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status='pending'", (broker_user_id,))
        pending = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM broker_profits WHERE broker_user_id=?", (broker_user_id,))
        total_profit = cursor.fetchone()[0] or 0.0
        return {'total_approved': total_approved, 'pending': pending, 'total_profit': total_profit}

    def get_broker_monthly_stats(self, broker_user_id):
        """إحصائيات الشهر الحالي مقارنة بالشهر السابق للوسيط"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status IN ('approved','admin_approved') "
            "AND strftime('%Y-%m', processed_at) = strftime('%Y-%m', 'now')",
            (broker_user_id,)
        )
        this_month = cursor.fetchone()[0] or 0
        cursor.execute(
            "SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status IN ('approved','admin_approved') "
            "AND strftime('%Y-%m', processed_at) = strftime('%Y-%m', 'now', '-1 month')",
            (broker_user_id,)
        )
        last_month = cursor.fetchone()[0] or 0
        cursor.execute(
            "SELECT COALESCE(SUM(amount),0) FROM broker_profits WHERE broker_user_id=? "
            "AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')",
            (broker_user_id,)
        )
        this_month_profit = cursor.fetchone()[0] or 0.0
        return {'this_month': this_month, 'last_month': last_month, 'this_month_profit': this_month_profit}

    def add_broker_profit(self, broker_user_id, req_id, amount):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT INTO broker_profits (broker_user_id, req_id, amount) VALUES (?,?,?)", (broker_user_id, req_id, amount))
            self.conn.commit()
        except Exception: pass

    def get_bot_setting(self, key, default=None):
        """alias لـ get_setting للتوافق مع الكود القديم"""
        return self.get_setting(key, default)

    def set_bot_setting(self, key, value):
        """alias لـ set_setting للتوافق مع الكود القديم"""
        return self.set_setting(key, value)

    def is_verification_enabled(self):
        """هل الحماية (هاتف+موقع) مفعلة؟"""
        val = self.get_bot_setting('verification_enabled')
        return val != '0'

    # تقييمات الوكلاء 
    def add_agent_rating(self, agent_user_id, user_id, req_id, rating, comment=""):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO agent_ratings (agent_user_id, user_id, req_id, rating, comment) VALUES (?,?,?,?,?)",
                (agent_user_id, user_id, req_id, rating, comment)
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error add_agent_rating: {e}")
            return False

    def get_agent_rating_stats(self, agent_user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*), COALESCE(AVG(rating),0), COUNT(CASE WHEN rating=5 THEN 1 END), "
            "COUNT(CASE WHEN rating>=4 THEN 1 END) FROM agent_ratings WHERE agent_user_id=?",
            (agent_user_id,)
        )
        r = cursor.fetchone()
        return {'count': r[0] or 0, 'avg': r[1] or 0.0, 'five_star': r[2] or 0, 'positive': r[3] or 0}

    def get_agent_ratings(self, agent_user_id, limit=5):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT ar.rating, ar.comment, ar.created_at, u.first_name, u.username "
            "FROM agent_ratings ar LEFT JOIN users u ON ar.user_id=u.user_id "
            "WHERE ar.agent_user_id=? ORDER BY ar.created_at DESC LIMIT ?",
            (agent_user_id, limit)
        )
        rows = cursor.fetchall()
        return [{'rating': r[0], 'comment': r[1], 'created_at': r[2],
                 'first_name': r[3], 'username': r[4]} for r in rows]

    def has_rated_agent_req(self, user_id, req_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT rating_id FROM agent_ratings WHERE user_id=? AND req_id=?", (user_id, req_id))
        return cursor.fetchone() is not None

    # تقييمات الوسطاء 
    def add_broker_rating(self, broker_user_id, user_id, req_id, rating, comment=""):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO broker_ratings (broker_user_id, user_id, req_id, rating, comment) VALUES (?,?,?,?,?)",
                (broker_user_id, user_id, req_id, rating, comment)
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error add_broker_rating: {e}")
            return False

    def get_broker_rating_stats(self, broker_user_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*), COALESCE(AVG(rating),0), COUNT(CASE WHEN rating=5 THEN 1 END), "
            "COUNT(CASE WHEN rating>=4 THEN 1 END) FROM broker_ratings WHERE broker_user_id=?",
            (broker_user_id,)
        )
        r = cursor.fetchone()
        return {'count': r[0] or 0, 'avg': r[1] or 0.0, 'five_star': r[2] or 0, 'positive': r[3] or 0}

    def get_broker_ratings(self, broker_user_id, limit=5):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT br.rating, br.comment, br.created_at, u.first_name, u.username "
            "FROM broker_ratings br LEFT JOIN users u ON br.user_id=u.user_id "
            "WHERE br.broker_user_id=? ORDER BY br.created_at DESC LIMIT ?",
            (broker_user_id, limit)
        )
        rows = cursor.fetchall()
        return [{'rating': r[0], 'comment': r[1], 'created_at': r[2],
                 'first_name': r[3], 'username': r[4]} for r in rows]

    def has_rated_broker_req(self, user_id, req_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT rating_id FROM broker_ratings WHERE user_id=? AND req_id=?", (user_id, req_id))
        return cursor.fetchone() is not None

    def create_broker_deal(self, broker_user_id, buyer_user_id, seller_user_id, amount, description):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO broker_deals (broker_user_id, buyer_user_id, seller_user_id, amount, description) VALUES (?,?,?,?,?)",
                (broker_user_id, buyer_user_id, seller_user_id, amount, description)
            )
            self.conn.commit()
            return True, cursor.lastrowid
        except Exception as e:
            logger.error(f"Error create_broker_deal: {e}")
            return False, str(e)

    def complete_broker_deal(self, deal_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute("UPDATE broker_deals SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE deal_id=?", (deal_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error complete_broker_deal: {e}")
            return False

    def get_broker_deals(self, broker_user_id=None):
        cursor = self.conn.cursor()
        if broker_user_id:
            cursor.execute("SELECT * FROM broker_deals WHERE broker_user_id=? ORDER BY created_at DESC LIMIT 20", (broker_user_id,))
        else:
            cursor.execute("SELECT * FROM broker_deals ORDER BY created_at DESC LIMIT 30")
        rows = cursor.fetchall()
        return [{'deal_id': r[0], 'broker_user_id': r[1], 'buyer_user_id': r[2],
                 'seller_user_id': r[3], 'amount': r[4], 'description': r[5],
                 'status': r[6], 'created_at': r[7], 'completed_at': r[8]} for r in rows]

    # تنبيهات وبلاغات الإدارة للوسطاء (من لوحة الإدارة) 
    def add_broker_warning(self, broker_user_id, reason, issued_by, warning_type='warning'):
        """يسجّل تنبيهاً أو بلاغاً من الإدارة لوسيط معيّن"""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO broker_warnings (broker_user_id, warning_type, reason, issued_by) VALUES (?,?,?,?)",
                (broker_user_id, warning_type, reason, issued_by)
            )
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error add_broker_warning: {e}")
            return None

    def get_broker_warnings(self, broker_user_id, limit=10):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT warning_id, warning_type, reason, issued_by, created_at FROM broker_warnings "
            "WHERE broker_user_id=? ORDER BY created_at DESC LIMIT ?",
            (broker_user_id, limit)
        )
        rows = cursor.fetchall()
        return [{'warning_id': r[0], 'warning_type': r[1], 'reason': r[2],
                 'issued_by': r[3], 'created_at': r[4]} for r in rows]

    def get_broker_warning_count(self, broker_user_id, warning_type='warning'):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM broker_warnings WHERE broker_user_id=? AND warning_type=?",
            (broker_user_id, warning_type)
        )
        return cursor.fetchone()[0] or 0

    def get_broker_full_stats(self, broker_user_id):
        """تحليل شامل لعمل الوسيط: الطلبات، نسبة القبول، الأرباح — لاستخدام لوحة الإدارة"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=?", (broker_user_id,))
        total = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status='approved'", (broker_user_id,))
        approved = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status='rejected'", (broker_user_id,))
        rejected = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status='pending'", (broker_user_id,))
        pending = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM broker_profits WHERE broker_user_id=?", (broker_user_id,))
        total_profit = cursor.fetchone()[0] or 0.0
        decided = approved + rejected
        approval_rate = (approved / decided * 100) if decided else 0.0
        return {
            'total': total, 'approved': approved, 'rejected': rejected, 'pending': pending,
            'total_profit': total_profit, 'approval_rate': approval_rate
        }

    # ====== نظام ملصقات البوت (Bot Stickers) ======

    def add_sticker(self, event_type, file_id, added_by):
        """يضيف ملصقاً جديداً لمناسبة معينة (الأدمن فقط يستخدم هذه الدالة)"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO bot_stickers (event_type, file_id, added_by) VALUES (?, ?, ?)",
                    (event_type, file_id, added_by)
                )
                self.conn.commit()
                return True, cursor.lastrowid
            except Exception as e:
                logger.error(f"Error add_sticker: {e}")
                return False, str(e)

    def get_stickers(self, event_type, active_only=True):
        """يُعيد جميع ملصقات مناسبة معينة"""
        cursor = self.conn.cursor()
        if active_only:
            cursor.execute(
                "SELECT id, file_id FROM bot_stickers WHERE event_type=? AND is_active=1",
                (event_type,)
            )
        else:
            cursor.execute(
                "SELECT id, file_id FROM bot_stickers WHERE event_type=?",
                (event_type,)
            )
        return [{'id': r[0], 'file_id': r[1]} for r in cursor.fetchall()]

    def get_random_sticker(self, event_type):
        """يُعيد file_id لملصق عشوائي من مناسبة معينة، أو None إذا لا توجد ملصقات"""
        stickers = self.get_stickers(event_type)
        if not stickers:
            return None
        return random.choice(stickers)['file_id']

    def remove_sticker(self, sticker_id):
        """يحذف ملصقاً (حذف فعلي) أو يعطّله"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("DELETE FROM bot_stickers WHERE id=?", (sticker_id,))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error remove_sticker: {e}")
                return False

    def get_all_sticker_events(self):
        """يُعيد كل المناسبات الموجودة مع عدد ملصقات كل واحدة"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT event_type, COUNT(*) FROM bot_stickers WHERE is_active=1 GROUP BY event_type"
        )
        return [{'event_type': r[0], 'count': r[1]} for r in cursor.fetchall()]

    # ====== نظام تعلّم الذكاء الاصطناعي (AI Learning System) ======

    def log_ai_conversation(self, user_id, user_message, matched_intent=None, confidence=0.0, was_unknown=False):
        """يسجّل كل محادثة مع الذكاء الاصطناعي لتحليلها وتحسين النظام لاحقاً"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO ai_conversation_log
                       (user_id, user_message, matched_intent, confidence, was_unknown)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, user_message, matched_intent, confidence, 1 if was_unknown else 0)
                )
                self.conn.commit()
                return cursor.lastrowid
            except Exception as e:
                logger.error(f"Error log_ai_conversation: {e}")
                return None

    def set_ai_feedback(self, log_id, feedback):
        """يسجّل تقييم المستخدم (👍/👎) على رد الذكاء الاصطناعي"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "UPDATE ai_conversation_log SET feedback=? WHERE id=?",
                    (feedback, log_id)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error set_ai_feedback: {e}")
                return False

    def get_unresolved_ai_logs(self, limit=20):
        """يُعيد الأسئلة الفاشلة (غير مفهومة أو تقييمها سلبي) التي لم يراجعها الأدمن بعد"""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT id, user_id, user_message, matched_intent, confidence, feedback, created_at
               FROM ai_conversation_log
               WHERE resolved_by_admin=0 AND (was_unknown=1 OR feedback='down')
               ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        )
        rows = cursor.fetchall()
        return [{'id': r[0], 'user_id': r[1], 'user_message': r[2], 'matched_intent': r[3],
                 'confidence': r[4], 'feedback': r[5], 'created_at': r[6]} for r in rows]

    def mark_ai_log_resolved(self, log_id):
        """يعلّم سؤالاً معيناً كأنه تمت مراجعته من الأدمن"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    "UPDATE ai_conversation_log SET resolved_by_admin=1 WHERE id=?",
                    (log_id,)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error mark_ai_log_resolved: {e}")
                return False

    def add_learned_pattern(self, intent, pattern_text, added_by, source_log_id=None):
        """يضيف نمطاً جديداً تعلّمه النظام من مراجعة الأدمن لسؤال فاشل، ليُستخدم في الفهم المستقبلي"""
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO ai_learned_patterns (intent, pattern_text, added_by, source_log_id)
                       VALUES (?, ?, ?, ?)""",
                    (intent, pattern_text, added_by, source_log_id)
                )
                self.conn.commit()
                return True, cursor.lastrowid
            except Exception as e:
                logger.error(f"Error add_learned_pattern: {e}")
                return False, str(e)

    def get_learned_patterns(self):
        """يُعيد كل الأنماط المتعلَّمة مجمّعة حسب النية (intent) — تُستخدم لتوسيع محرك الفهم تلقائياً"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT intent, pattern_text FROM ai_learned_patterns")
        rows = cursor.fetchall()
        grouped = {}
        for intent, pattern in rows:
            grouped.setdefault(intent, []).append(pattern)
        return grouped

    def get_ai_stats(self):
        """إحصائيات عامة عن أداء نظام الذكاء الاصطناعي"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ai_conversation_log")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ai_conversation_log WHERE was_unknown=1")
        unknown = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ai_conversation_log WHERE feedback='up'")
        positive = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ai_conversation_log WHERE feedback='down'")
        negative = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ai_learned_patterns")
        learned = cursor.fetchone()[0]
        return {
            'total': total, 'unknown': unknown,
            'positive': positive, 'negative': negative,
            'learned_patterns': learned
        }

db = Database(DATABASE_PATH)

# ====== نظام Queue مركزي للإشعارات — يمنع flood limit ويضمن الترتيب ======
import queue as _queue

_notification_queue = _queue.Queue(maxsize=2000)

def _notification_worker():
    """worker thread يرسل الإشعارات بشكل منظم مع تجنب flood limit"""
    while True:
        try:
            task = _notification_queue.get(timeout=5)
            if task is None:
                break
            chat_id = task.get('chat_id')
            text = task.get('text', '')
            keyboard = task.get('keyboard')
            parse_mode = task.get('parse_mode', 'Markdown')
            try:
                bot.send_message(chat_id, text, reply_markup=keyboard,
                                 parse_mode=parse_mode, disable_web_page_preview=True)
            except Exception as e:
                err = str(e).lower()
                if 'flood' in err or 'too many' in err:
                    # انتظر ثم أعد الإرسال مرة واحدة
                    time.sleep(3)
                    try:
                        bot.send_message(chat_id, text, reply_markup=keyboard,
                                         parse_mode=parse_mode, disable_web_page_preview=True)
                    except Exception:
                        pass
                elif 'blocked' not in err and 'deactivated' not in err:
                    logger.warning(f"_notification_worker: فشل إرسال لـ {chat_id}: {e}")
            finally:
                _notification_queue.task_done()
            time.sleep(0.05)  # 20 رسالة/ثانية — أمان من flood
        except _queue.Empty:
            continue
        except Exception as e:
            logger.error(f"_notification_worker error: {e}")

_notif_thread = threading.Thread(target=_notification_worker, daemon=True)
_notif_thread.start()

def queue_send(chat_id, text, keyboard=None, parse_mode="Markdown"):
    """إرسال إشعار عبر الـ Queue بدل threading.Thread مباشر"""
    try:
        _notification_queue.put_nowait({
            'chat_id': chat_id, 'text': text,
            'keyboard': keyboard, 'parse_mode': parse_mode
        })
    except _queue.Full:
        logger.warning(f"queue_send: الـ Queue ممتلئة، تجاهل الإشعار لـ {chat_id}")

# ====== helpers لإرسال الإشعارات بشكل موثوق ======

def safe_send(chat_id, text, reply_markup=None, parse_mode="Markdown", retries=3):
    """إرسال رسالة مع إعادة المحاولة عند الفشل"""
    for attempt in range(retries):
        try:
            return bot.send_message(chat_id, text, reply_markup=reply_markup,
                                    parse_mode=parse_mode, disable_web_page_preview=True)
        except Exception as e:
            err = str(e).lower()
            if 'blocked' in err or 'deactivated' in err or 'not found' in err:
                logger.warning(f"safe_send: المستخدم {chat_id} لا يمكن الوصول إليه: {e}")
                return None
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                logger.error(f"safe_send failed after {retries} attempts to {chat_id}: {e}")
    return None

def notify_broker_new_request(broker_user_id, req):
    """إشعار الوسيط بطلب جديد بشكل موثوق في thread منفصل"""
    def _send():
        BROKER_SERVICE_LABELS = {
            "sell_username": "بيع يوزر", "sell_account": "بيع حساب",
            "sell_channel": "بيع قناة", "sell_group": "بيع مجموعة",
            "sell_bot": "بيع بوت", "sell_social": "بيع معرف", "buy_other": "شراء آخر"
        }
        svc = BROKER_SERVICE_LABELS.get(req.get('service_type', ''), req.get('service_type', ''))
        uname = f"@{req['username']}" if req.get('username') else (req.get('first_name') or f"ID {req['user_id']}")
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(
            types.InlineKeyboardButton(f" قبول #{req['req_id']}", callback_data=f"broker_approve_req_{req['req_id']}", style="primary"),
            types.InlineKeyboardButton(f" رفض #{req['req_id']}", callback_data=f"broker_reject_req_{req['req_id']}", style="danger")
        )
        keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوسيط", callback_data="my_broker_panel", style="primary"))
        text = (
            f" *طلب وساطة جديد #{req['req_id']}*\n\n"
            f"العميل: {uname}\n"
            f"نوع الخدمة: {svc}\n"
            f"التفاصيل: {req.get('details', '')[:200]}\n\n"
            f"⏰ {str(req.get('created_at', ''))[:16]}"
        )
        safe_send(broker_user_id, text, reply_markup=keyboard)
    threading.Thread(target=_send, daemon=True).start()

def notify_agent_new_request(agent_user_id, req):
    """إشعار الوكيل بطلب شحن جديد في thread منفصل"""
    def _send():
        uname = f"@{req['username']}" if req.get('username') else (req.get('first_name') or f"ID {req['user_id']}")
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(
            types.InlineKeyboardButton(f" قبول #{req['req_id']}", callback_data=f"agent_approve_req_{req['req_id']}", style="primary"),
            types.InlineKeyboardButton(f" رفض #{req['req_id']}", callback_data=f"agent_reject_req_{req['req_id']}", style="danger")
        )
        keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
        text = (
            f" *طلب شحن جديد #{req['req_id']}*\n\n"
            f"العميل: {uname}\n"
            f"المبلغ: {req.get('amount', 0):.2f}$\n"
            f"السبب: {req.get('reason', '')[:200]}\n\n"
            f"⏰ {str(req.get('created_at', ''))[:16]}"
        )
        safe_send(agent_user_id, text, reply_markup=keyboard)
    threading.Thread(target=_send, daemon=True).start()

# دوال تذاكر الدعم 

def db_create_ticket(user_id):
    """إنشاء تذكرة دعم جديدة للمستخدم"""
    cursor = db.conn.cursor()
    # أغلق أي تذكرة مفتوحة قديمة
    cursor.execute("UPDATE support_tickets SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE user_id=? AND status='open'", (user_id,))
    cursor.execute("INSERT INTO support_tickets (user_id, ai_history) VALUES (?, '[]')", (user_id,))
    db.conn.commit()
    return cursor.lastrowid

def db_get_open_ticket(user_id):
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM support_tickets WHERE user_id=? AND status='open' ORDER BY created_at DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return {'ticket_id': row[0], 'user_id': row[1], 'status': row[2],
            'ai_history': json.loads(row[3] or '[]'), 'summary': row[4],
            'created_at': row[5]}

def db_update_ticket_history(ticket_id, history):
    cursor = db.conn.cursor()
    cursor.execute("UPDATE support_tickets SET ai_history=? WHERE ticket_id=?", (json.dumps(history, ensure_ascii=False), ticket_id))
    db.conn.commit()

def db_close_ticket(ticket_id, summary=""):
    cursor = db.conn.cursor()
    cursor.execute("UPDATE support_tickets SET status='closed', summary=?, closed_at=CURRENT_TIMESTAMP WHERE ticket_id=?", (summary, ticket_id))
    db.conn.commit()

def db_get_all_open_tickets():
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT st.ticket_id, st.user_id, st.created_at, st.summary, u.username, u.first_name "
        "FROM support_tickets st LEFT JOIN users u ON st.user_id=u.user_id "
        "WHERE st.status='open' ORDER BY st.created_at DESC LIMIT 30"
    )
    rows = cursor.fetchall()
    return [{'ticket_id': r[0], 'user_id': r[1], 'created_at': r[2], 'summary': r[3],
             'username': r[4], 'first_name': r[5]} for r in rows]

def db_get_ticket_by_id(ticket_id):
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM support_tickets WHERE ticket_id=?", (ticket_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return {'ticket_id': row[0], 'user_id': row[1], 'status': row[2],
            'ai_history': json.loads(row[3] or '[]'), 'summary': row[4],
            'created_at': row[5]}

##############################################################################
# 
# 
# 
# 
# 
# 
#
# ذكاء اصطناعي محلي مدمج — بدون أي API خارجي
# نظام NLP عربي من الصفر مخصص لبوت المزادات
##############################################################################

class ArabicNLP:
    """محرك معالجة اللغة الطبيعية العربية من الصفر.
    يقوم بـ:
    - تطبيع النص (تشكيل، همزات، مسافات)
    - تقطيع الجمل إلى tokens
    - استخراج الكيانات (أرقام، معرّفات، روابط)
    - حساب درجة التشابه بين نصين
    - كشف النية (intent detection) بنظام أوزان
    """

    # جذور/أشكال مختلفة لكلمات متشابهة المعنى
    SYNONYMS = {
        "رصيد": ["رصيد","فلوس","مبلغ","balance","بالانس","حسابي","رصيدي","رصيده",
                     "رصيدها","گروش","كروش","نقود","دراهم","حسابك","المبلغ","الفلوس",
                     "فلوسي","فلوسه","مصاري","المصاري","باقي"],
        "شحن": ["شحن","شحنت","اشحن","شاحن","ايداع","إيداع","اضافة","إضافة",
                     "ضفت","ضيفت","دفعت","دفع","سددت","سدد","زودت","حطيت","ودّيت",
                     "ارسلت","حولت","موّلت","اشحنه","شحنه","ضيفت رصيد","حطيت فلوس"],
        "مزاد": ["مزاد","مزادي","مزاده","مزادات","المزاد","auction","مزايدة",
                     "عرض","بيع","منشور","المنشور","انشرت","انشر","الاوكشن","بيعي"],
        "مزايدة": ["مزايدة","زايدت","زايد","bid","بيد","عطيت","اعطيت","رفعت",
                     "رفع سعر","ازايد","بزايد","بيدي","حطيت بيد","عطيت سعر","رفعت سعر"],
        "تحويل": ["تحويل","حوّلت","احول","ارسل","ارسلت","transfer","ارسال",
                     "ابعث","ودّي","وديت","بعثت","بعث","ابعث فلوس","ودي له",
                     "اعطيه","اعطيته","ابعثه"],
        "هاتف": ["هاتف","تلفون","موبايل","رقم","phone","جوال","نمرة","النمرة",
                     "رقم الموبايل","رقمي","رقمك","نمرتي","نمرتك","الجوال",
                     "موبايلي","تلفوني","گوشي","number","نمبر"],
        "موقع": ["موقع","لوكيشن","location","مكاني","مكان","الموقع","gps",
                     "محلي","محلك","فين انا","وين انا","موقعي","الخريطة","map"],
        "تحقق": ["تحقق","verification","تأكيد","تحقيق","يطلب","يريد","verify",
                     "تأكيد الهوية","تسجيل","ما اكملت","اكمال","الاكمال",
                     "يريدني اتحقق","يطلب مني"],
        "تسليم": ["تسليم","سلّم","سلم","يسلم","مايسلم","ماسلم","التسليم",
                     "deliver","يعطيني","ما عطاني","ما وصلني","ما سلّمني",
                     "البضاعة","المنتج","اعطاني","يسلّم","مو يسلم","مو يعطي",
                     "ما يردني","مو يردني"],
        "حظر": ["حظر","محظور","بلوك","block","banned","موقوف","مربوط",
                     "مبلوك","ممنوع","وقفوني","حظروني","حطوني بلوك","موقوف حسابي",
                     "حسابي موقوف","مو يدخلني","ما يدخلني","ما أقدر أدخل",
                     "مو اقدر استخدم","تعلق حسابي","حسابي مربوط"],
        "عمولة": ["عمولة","كمشن","commission","خصم","يخصم","ياخذ","اخذ",
                     "يقطع","قطع","رسوم","الرسوم","يخصم من","كم ياخذ",
                     "ايش ياخذ","شو ياخذ","كم يقطع","قطعوا","خصموا"],
        "بينانس": ["بينانس","binance","usdt","تيثر","tether","كريبتو","crypto",
                     "تحويل كريبتو","عملة رقمية","bep20","trc20","erc20",
                     "تيزر","يو اس دي تي","بينانز"],
        "نجوم": ["نجوم","stars","ستارز","star","نجمة","نجمات","telegram stars",
                     "تيليجرام ستارز","نجوم تيليجرام","النجوم","الستارز"],
        "كود": ["كود","code","رمز","كوبون","coupon","voucher","كودي",
                     "الكود","كود شحن","رمز الشحن","كود خاطئ","كود ما يشتغل",
                     "شحنت بكود","ادخلت كود"],
        "فائز": ["فائز","ربحت","كسبت","ربح","فوز","winner","فزت","ما ربحت",
                     "غلبت","انا الاعلى","اعلى سعر","الاعلى","انا الرابح",
                     "ربحت المزاد","فزت بالمزاد","اعلى بيد"],
        "مرفوض": ["مرفوض","رفض","مو مقبول","مو معتمد","لم يُعتمد","مو موافق",
                     "مارفضوه","ريجكت","rejected","ما قبلوه","ما وافقوه",
                     "مو موافقين","رفضوا","ما اعتمدوه"],
        "انتظار": ["انتظار","pending","معلّق","قيد المراجعة","تحت المراجعة",
                     "ينتظر","بانتظار","مو معتمد بعد","ما اجا رد",
                     "ما وافقوا","لسه ما","لحد هسه","هسه","لهسه","هالحين"],
        "مشكلة": ["مشكلة","خطأ","error","مو شغّال","ما يشتغل","خربان","bug",
                     "مشاكل","عندي مشكله","اشكالية","مصخبر","عطلان",
                     "معطوب","ما يفتح","مو رادّ","وقع","سقط","crash","لا يعمل"],
        "محفظة": ["محفظة","wallet","حسابي","ارصدتي","الرصيد","الوالت",
                     "محفظتي","صفحة الرصيد","صفحة المحفظة"],
        "عجلة": ["عجلة","دوامة","lucky","wheel","سبين","spin","حظ","دوّار",
                     "عجلة الحظ","الدوّارة","ادور","دوّر","العجلة","lucky wheel"],
        "وكيل": ["وكيل","agent","وسيط","broker","مو امين","نصب","غش",
                     "احتيال","ضحكوا عليه","كذب","مكذوب","نصبوا عليه",
                     "غشني","خدعني","سرقني","سرق","نصّاب","مو صادق"],
        "بلاغ": ["بلاغ","بلّغت","ابلغ","report","شكوى","شكاوى","ابلغ عليه",
                     "اريد اشكو","اشكيه","اشكو","بلّغ","ابلّغ","اريد ابلغ"],
        "سعر": ["سعر","ثمن","price","كم","بكم","بكمية","بسعر كم",
                     "كم ثمنه","شقد","كمية","شقدر","شكد","بشكد","بشقد",
                     "سعر البدء","السعر","اعلى سعر","اخر سعر"],
        "مدة": ["مدة","وقت","ساعة","يوم","ينتهي","متى","امتى","duration",
                     "شقد وقت","كم وقت","متى ينتهي","لما يخلص","وقت المزاد"],
        "معرف": ["معرف","username","يوزر","يوزرنيم","اسم المستخدم","المعرف",
                     "@","يوزر نيم","هندل","handle","اليوزر","اسمك بالبوت",
                     "معرف تيليجرام","الـ username"],
        "قناة": ["قناة","channel","كانال","مجموعة","group","قروب",
                     "كروب","قناتي","مجموعتي","الكانال","الچانل","چانل"],
        "هدية": ["هدية","gift","هدايا","gifts","تيليجرام هدية",
                     "هدية تيليجرام","gift link","رابط هدية","الهدية"],
        "اشتراك": ["اشتراك","subscribe","مشترك","اشتركت","انضم","انضممت",
                     "اشترك","يطلب اشتراك","لازم اشترك","اشتراك اجباري",
                     "ما يدخلني","مو يدخلني","يطلب مني اشترك"],
        # كلمات عراقية للسبب / الاستفسار 
        "سبب": ["ليش","ليه","لماذا","شو السبب","ايش السبب","علاش",
                     "لشنو","لشنو يطلب","ليش يطلب","ليش يريد","ليش يخصم",
                     "ليش يحجز","ليش محظور","ليش ما يشتغل","ليش ما ضاف"],
        # كلمات عراقية للطريقة / الكيفية 
        "طريقة": ["كيف","طريقة","شلون","كيفية","خطوات","اشرحلي","وضح",
                     "اوضح","علمني","شكيف","گولي","گلي","بيّن","فهّمني",
                     "اريد افهم","شبيها"],
        # لم يُضف / لم يصل 
        "لم_يضف": ["ما اضيف","ما ضاف","لم يضاف","ما وصل","مو واصل",
                     "ما وصلت","لم تصل","ما جاء","ما جاي","مو جاي",
                     "ما انعكس","لم ينعكس","لهسه ما ضاف","هسه ما ضاف",
                     "بعدها ما جا","ما انضاف"],
        # رصيد محجوز 
        "محجوز": ["محجوز","مربوط","مجمّد","موقوف","ملغي","locked","frozen",
                     "مو يطلق","ما يطلق","يرجع","يرجعلي","ارجعوا","رجّعوا",
                     "ما رجع رصيدي","رصيدي مربوط","رصيدي محجوز"],
        # تأخر / بطء 
        "تأخر": ["متأخر","بطيء","تأخر","slow","ما جاء بعد","لسه","هسه",
                     "بعدين","لهسه","هالحين","هلا بعد ما","انتظرت وما"],
    }

    # ألف التعريف والحروف الزائدة للتجريد
    PREFIXES = ["ال","وال","فال","بال","كال","لل","وب","فب","كب","لب","و","ف","ب","ك","ل"]
    SUFFIXES = ["ي","ك","ه","ها","نا","كم","هم","ون","ين","ات","ة","ية","تي","تك","ته","تها"]

    def __init__(self):
        # بناء فهرس عكسي: كلمة → مجموعة المعنى
        self._word_to_group = {}
        for group, words in self.SYNONYMS.items():
            for w in words:
                self._word_to_group[w] = group

    def normalize(self, text: str) -> str:
        """تطبيع النص العربي — مع دعم اللهجة العراقية"""
        if not text:
            return ""
        text = text.strip().lower()
        # توحيد الهمزات
        text = re.sub(r'[أإآ]', 'ا', text)
        text = re.sub(r'[ؤئ]', 'ء', text)
        # حذف التشكيل
        text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
        # توحيد التاء المربوطة
        text = re.sub(r'ة', 'ه', text)
        # توحيد الحروف العراقية → عربية فصحى
        text = text.replace('گ', 'ك').replace('چ', 'ش').replace('پ', 'ب')
        text = text.replace('ڤ', 'ف').replace('ژ', 'ز')
        # توحيد الكاف بالكسرة العراقية
        text = re.sub(r'[kK]', 'ك', text)
        # توحيد Y/G للأسماء العراقية المعربة
        # توحيد ال (ال)
        text = re.sub(r'\bال', 'ال', text)
        # حذف المسافات الزائدة
        text = re.sub(r'\s+', ' ', text)
        return text

    def tokenize(self, text: str) -> list:
        """تقطيع النص إلى كلمات"""
        text = self.normalize(text)
        tokens = re.findall(r'[\u0600-\u06FF]+|[a-z0-9]+', text)
        return tokens

    def stem(self, word: str) -> str:
        """تجريد بسيط للكلمة: حذف السوابق واللواحق"""
        w = self.normalize(word)
        # حذف السوابق
        for p in sorted(self.PREFIXES, key=len, reverse=True):
            if w.startswith(p) and len(w) > len(p) + 2:
                w = w[len(p):]
                break
        # حذف اللواحق
        for s in sorted(self.SUFFIXES, key=len, reverse=True):
            if w.endswith(s) and len(w) > len(s) + 2:
                w = w[:-len(s)]
                break
        return w

    def get_semantic_group(self, word: str) -> str:
        """يعيد مجموعة المعنى للكلمة، أو None"""
        w = self.normalize(word)
        if w in self._word_to_group:
            return self._word_to_group[w]
        stemmed = self.stem(w)
        if stemmed in self._word_to_group:
            return self._word_to_group[stemmed]
        # بحث جزئي
        for key in self._word_to_group:
            if len(key) >= 3 and (w.startswith(key) or key.startswith(w)):
                return self._word_to_group[key]
        return None

    def extract_entities(self, text: str) -> dict:
        """استخراج الكيانات من النص"""
        entities = {}
        # أرقام
        nums = re.findall(r'\d+(?:\.\d+)?', text)
        if nums:
            entities['numbers'] = [float(n) for n in nums]
        # معرّف تيليجرام
        usernames = re.findall(r'@[a-zA-Z0-9_]{3,32}', text)
        if usernames:
            entities['usernames'] = usernames
        # روابط
        links = re.findall(r'https?://\S+|t\.me/\S+', text)
        if links:
            entities['links'] = links
        # رقم عملية USDT / TxHash
        txhash = re.findall(r'[0-9a-fA-F]{30,}', text)
        if txhash:
            entities['txhash'] = txhash
        # رقم هاتف
        phones = re.findall(r'(?:07\d{9}|\+964\d{10}|\+\d{10,13})', text)
        if phones:
            entities['phones'] = phones
        # ID مزاد (أرقام 6-10 خانات)
        auction_ids = re.findall(r'\b\d{6,10}\b', text)
        if auction_ids:
            entities['auction_ids'] = auction_ids
        return entities

    def semantic_tokens(self, text: str) -> set:
        """يعيد مجموعة مجموعات المعنى الموجودة في النص"""
        groups = set()
        for tok in self.tokenize(text):
            g = self.get_semantic_group(tok)
            if g:
                groups.add(g)
        return groups

    def similarity(self, text1: str, text2: str) -> float:
        """درجة التشابه الدلالي بين نصين (0.0 → 1.0)"""
        g1 = self.semantic_tokens(text1)
        g2 = self.semantic_tokens(text2)
        if not g1 and not g2:
            # تشابه حرفي
            t1 = set(self.tokenize(text1))
            t2 = set(self.tokenize(text2))
            if not t1 or not t2:
                return 0.0
            return len(t1 & t2) / len(t1 | t2)
        if not g1 or not g2:
            return 0.0
        return len(g1 & g2) / len(g1 | g2)


# قاعدة المعرفة الكاملة للبوت 

class BotKnowledgeBase:
    """قاعدة معرفة شاملة لكل شيء في البوت.
    كل entry فيها:
      - patterns: كلمات/عبارات مفتاحية تشير لهذا الموضوع
      - intent: اسم النية
      - answer: الجواب المباشر
      - followup: سؤال متابعة إذا احتجنا مزيد من التفاصيل (اختياري)
      - suggest_admin: هل نقترح إرسال للإدارة؟
    """

    ENTRIES = [
        # رصيد / شحن 
        {
            "intent": "balance_not_added_binance",
            "patterns": ["رصيد ما اضيف","رصيد لم يضاف","شحنت بينانس","دفعت usdt","ما وصل رصيد","رصيد ما وصل","binance ما ضاف","ارسلت usdt","حولت usdt","حولت بينانس","ضيفت usdt","دفعت تيثر","ارسلت تيثر","حولت تيثر","ما ضاف بعد","ارسلت من بينانس","بعثت usdt","وديت usdt","ضفت بينانس","شحنت تيثر","ما جا رصيدي","هسه ما ضاف"],
            "answer": (
                " *شحن عبر Binance / USDT*\n\n"
                "الإضافة عبر Binance *يدوية* من الأدمن وليست تلقائية.\n\n"
                "للمتابعة، أرسل للإدارة:\n"
                "• رقم العملية (TxHash)\n"
                "• المبلغ المُرسل بالـ USDT\n"
                "• وقت الإرسال التقريبي\n\n"
                "عادةً تُضاف خلال ساعات قليلة من مراجعة الأدمن."
            ),
            "suggest_admin": True,
        },
        {
            "intent": "balance_not_added_stars",
            "patterns": ["دفعت نجوم","شحنت نجوم","stars ما ضافت","نجوم ما وصلت","دفعت ستارز","ما ضاف رصيد بعد النجوم","ضيفت نجوم","النجوم ما ضافت","اشتريت نجوم","دفعت ستار","نجوم ما جت","بعد النجوم ما جا","ما انعكس رصيد النجوم"],
            "answer": (
                " *شحن عبر نجوم تيليجرام*\n\n"
                "الإضافة عبر النجوم *تلقائية وفورية* عادةً.\n\n"
                "إذا لم تُضف:\n"
                "• تأكد من اكتمال عملية الدفع في تيليجرام\n"
                "• انتظر دقيقة واحدة وراجع رصيدك\n\n"
                "إذا استمرت المشكلة أرسل للإدارة مع:\n"
                "• رقم العملية (charge_id) من تيليجرام\n"
                "• عدد النجوم المدفوعة"
            ),
            "suggest_admin": True,
        },
        {
            "intent": "balance_not_added_code",
            "patterns": ["كود ما شتغل","الكود خاطئ","كود مو صح","كود مستخدم","كود ما يقبل","كود لا يعمل","شحنت بكود","ادخلت الكود","الكود مو صح","الكود غلط","الكود ما يشتغل","كودي ما يمشي","ادخلت كود بس ما ضاف","الرمز غلط","كود مستخدم قبل"],
            "answer": (
                " *مشكلة كود الشحن*\n\n"
                "تحقق من الأمور التالية:\n"
                "الكود مكتوب بشكل صحيح (كبير/صغير مهم)\n"
                "الكود لم يُستخدم سابقاً\n"
                "الكود لم تنتهِ صلاحيته\n"
                "الكود مخصص لك وليس لحساب آخر\n\n"
                "إذا تأكدت من كل ذلك وما زال لا يعمل، أرسل الكود للإدارة."
            ),
            "suggest_admin": True,
        },
        {
            "intent": "check_balance",
            "patterns": ["كم رصيدي","شوف رصيدي","اعرف رصيدي","رصيد حسابي","balance كم","فلوسي كم","كمية رصيدي","شقد رصيدي","كم الباقي","شو رصيدي","كم عندي","شوف كم عندي"],
            "answer": (
                " *عرض الرصيد*\n\n"
                "اضغط زر *المحفظة* من القائمة الرئيسية لعرض رصيدك الحالي.\n"
                "أو اضغط زر *رصيد الحساب* في أعلى القائمة مباشرة."
            ),
            "suggest_admin": False,
        },
        {
            "intent": "recharge_how",
            "patterns": ["كيف اشحن","طريقة الشحن","اريد اشحن","شحن رصيد","كيف ادفع","طرق الدفع","كيف اضيف رصيد","شلون اشحن","شلون ادفع","كيف اضيف","طرق الشحن","اريد اضيف رصيد","شلون اضيف","طريقة الدفع"],
            "answer": (
                " *طرق شحن الرصيد*\n\n"
                " *نجوم تيليجرام* — فورية وتلقائية\n"
                " *USDT عبر Binance* — يدوية، تحتاج تأكيد الأدمن\n"
                " *كود شحن* — فوري بعد إدخال الكود\n\n"
                "اضغط *المحفظة* ← *شحن الرصيد* من القائمة الرئيسية."
            ),
            "suggest_admin": False,
        },

        # تحويل الرصيد 
        {
            "intent": "transfer_commission",
            "patterns": ["عمولة التحويل","كم يخصم التحويل","كم عمولة التحويل","ليش يخصم تحويل","ليش يقطع من التحويل","كم يقطع","يقطع كم","يخصم كم","رسوم التحويل","كمشن التحويل"],
            "answer": (
                " *عمولة التحويل بين المستخدمين*\n\n"
                "نسبة العمولة عند تحويل الرصيد: **5%** من المبلغ المُحوّل.\n\n"
                "مثال: لو حوّلت 1000$ يصل للطرف الثاني 950$.\n\n"
                "العمولة تذهب لصيانة وتطوير البوت."
            ),
            "suggest_admin": False,
        },
        {
            "intent": "transfer_how",
            "patterns": ["كيف احول","ارسل رصيد","تحويل رصيد","ابعث فلوس","طريقة التحويل","gift link","كود تحويل","شلون احول","اريد احول","ابعثله رصيد","وديله فلوس","ودي رصيد","ارسلي له","شلون ابعث"],
            "answer": (
                " *تحويل الرصيد*\n\n"
                "من *المحفظة* يمكنك:\n"
                " *تحويل برقم الأيدي* — أدخل ID المستخدم مباشرة\n"
                " *رابط هدية* — ينشئ رابطاً يستطيع أي شخص استلامه\n"
                " *كود تحويل* — كود سري يمكن إعطاؤه للمستلم\n\n"
                "ملاحظة: تُخصم عمولة 5% من كل تحويل."
            ),
            "suggest_admin": False,
        },

        # المزايدة 
        {
            "intent": "bid_insufficient_balance",
            "patterns": ["رصيد غير كافي","مو عندي رصيد","ما عندي رصيد للمزايده","insufficient","رصيدي ما يكفي","ما يقبل مزايدتي","رفض مزايدتي","رصيدي مو كافي","ما عندي كاي رصيد","رصيدي ناقص","ما يسمحلي ازايد","ما عندي فلوس كافية"],
            "answer": (
                " *رصيد غير كافي للمزايدة*\n\n"
                "يجب أن يكون رصيدك أكبر من أو يساوي سعر المزايدة.\n\n"
                "الحل: اشحن رصيدك أولاً عبر المحفظة، ثم عُد للمزايدة.\n\n"
                "لا تنسَ: الرصيد يُحجز أثناء المزاد ويُعاد لك إن خسرت."
            ),
            "suggest_admin": False,
        },
        {
            "intent": "bid_balance_locked",
            "patterns": ["رصيدي محجوز","ليش رصيدي محجوز","رصيد مربوط","مو قادر اسحب رصيدي","رصيدي موقوف","رصيدي مجمّد","ليش رصيدي مربوط","رصيدي مو يطلق","رصيدي مو يرجع","متى يرجع رصيدي","امتى يرجع","ليش ما يطلق رصيدي"],
            "answer": (
                " *الرصيد المحجوز طبيعي*\n\n"
                "عند المزايدة، يُحجز مبلغ مزايدتك تلقائياً.\n\n"
                "• إذا *خسرت* المزاد: يُعاد رصيدك فوراً بعد انتهاء المزاد\n"
                "• إذا *فزت* المزاد: يُخصم كدفعة للبائع\n\n"
                "هذا ليس خطأً، بل حماية للبائع والمشتري."
            ),
            "suggest_admin": False,
        },
        {
            "intent": "bid_cant_bid",
            "patterns": ["ما اقدر ازايد","ما يسمح لي بالمزايده","زر المزايدة ما يشتغل","لا استطيع المزايدة","مو قادر ازايد","مو يخليني ازايد","ما يقبل منيّ","زر المزايدة مو شغال","ما اقدر احط بيد","البيد ما يمشي","ما يسمحلي"],
            "answer": (
                " *تعذّر المزايدة*\n\n"
                "الأسباب المحتملة:\n"
                "المزاد انتهى أو أُغلق\n"
                "رصيدك أقل من الحد الأدنى للمزايدة\n"
                "أنت مالك هذا المزاد (لا يمكنك المزايدة على مزادك)\n"
                "حسابك محظور مؤقتاً\n\n"
                "تحقق من هذه النقاط، وإن استمرت المشكلة أرسل للإدارة."
            ),
            "suggest_admin": True,
        },
        {
            "intent": "bid_extend",
            "patterns": ["ليش يتمدد المزاد","مدة المزاد تطول","المزاد ما خلص","تمديد المزاد","ليش ما ينتهي","ليش ما يخلص المزاد","يطول وقت المزاد","المزاد يتمدد","ليش يمتد","ما ينتهي المزاد","يتأخر وقت المزاد"],
            "answer": (
                " *تمديد المزاد التلقائي*\n\n"
                "كل مزايدة جديدة تُمدّد وقت المزاد *5 دقائق* تلقائياً.\n\n"
                "هذا يمنع 'سرقة' المزاد في آخر ثانية ويضمن فرصة عادلة للجميع."
            ),
            "suggest_admin": False,
        },

        # نشر المزاد 
        {
            "intent": "auction_not_approved",
            "patterns": ["مزادي لم يعتمد","مزاد ما اعتمد","مزادي قيد المراجعه","انتظر موافقه","مو مقبول مزادي","مزادي رُفض","رُفض مزادي","مزادي مو مقبول","مزادي ما اعتمدوه","ما وافقوا على مزادي","مزادي pending","مزادي قيد الانتظار","ليش مزادي مو شايل","ما انشر مزادي"],
            "answer": (
                " *مراجعة المزاد*\n\n"
                "المزادات الجديدة تخضع لمراجعة الإدارة قبل النشر.\n\n"
                "• *قيد المراجعة*: انتظر، الإدارة ستوافق خلال ساعات قليلة\n"
                "• *مرفوض*: المزاد خالف القوانين، وتُعاد رسوم النشر\n\n"
                "أسباب الرفض الشائعة:\n"
                "— المنتج محظور أو مسروق\n"
                "— بيانات غير صحيحة\n"
                "— تكرار نشر نفس المزاد"
            ),
            "suggest_admin": False,
        },
        {
            "intent": "auction_commission",
            "patterns": ["عمولة المزاد","كم عمولة النشر","كم يخصم عند البيع","عمولة البيع","رسوم النشر","كم رسوم النشر","كم يقطع عند البيع","رسوم البيع","كم يأخذ البوت","كمشن المزاد","شقد يخصم","شقد العمولة"],
            "answer": (
                " *رسوم وعمولات المزادات*\n\n"
                "• رسوم نشر مزاد: **0.01$** (رمزية)\n"
                "• عمولة البيع: **0.5%** من سعر البيع النهائي\n\n"
                "مثال: لو بيع مزادك بـ 1000$، تُخصم 5$ عمولة.\n\n"
                "العمولات تذهب لتطوير وصيانة البوت."
            ),
            "suggest_admin": False,
        },
        {
            "intent": "auction_no_bids",
            "patterns": ["ما جاء احد على مزادي","مزادي خلص بدون مزايدين","ما احد زايد","انتهى مزادي بدون فائز","ما اشترى احد","ما زايد احد","مزادي خلص ما احد","ما احد اشترى","مزادي بلا مزايد","ما جاء عليه احد","خلص وما فيه فائز"],
            "answer": (
                " *انتهى المزاد بدون مزايدين*\n\n"
                "لا تقلق — رصيد سعر البدء يُعاد لك كاملاً تلقائياً.\n\n"
                "نصائح لزيادة فرص البيع:\n"
                "انشر رابط المزاد في مجموعاتك\n"
                "اضبط سعر بدء منخفضاً ومناسباً\n"
                "اختر وقت نشر مناسب (مساءً عادةً أفضل)\n"
                "أضف وصفاً جذاباً واضحاً للمنتج"
            ),
            "suggest_admin": False,
        },
        {
            "intent": "auction_duration",
            "patterns": ["كم مدة المزاد","متى ينتهي المزاد","مدة الافتراضيه","كم ساعة المزاد","وقت المزاد","شقد يستمر المزاد","شقد مدة المزاد","امتى ينتهي","كم يستغرق","المزاد بعد كم","ينتهي بعد كم"],
            "answer": (
                " *مدة المزاد*\n\n"
                "المدة الافتراضية للمزاد: **5 ساعات**\n\n"
                "• يمكنك تحديد مدة مختلفة عند نشر المزاد\n"
                "• كل مزايدة جديدة تُمدّد المزاد 5 دقائق إضافية\n"
                "• تُرسل تنبيهات قبل الانتهاء بـ 30 دقيقة"
            ),
            "suggest_admin": False,
        },
        {
            "intent": "auction_types",
            "patterns": ["انواع المزادات","ايش اقدر ابيع","شو اقدر انشر","ماذا يمكن بيعه","ما هي انواع المزادات","شو ينباع","شنو اقدر ابيع","اريد ابيع ايش","ايش يقبل البوت","شو يقبل","شنو يقبلون"],
            "answer": (
                " *أنواع المزادات المتاحة*\n\n"
                " *معرّف تيليجرام* — @username\n"
                " *قناة تيليجرام* — مع التحقق من الملكية\n"
                " *مجموعة تيليجرام* — مع التحقق من الملكية\n"
                " *معرّف بوت* — بوتات تيليجرام\n"
                " *هدية تيليجرام* — روابط هدايا رسمية\n"
                "معرفات تيليجرام — يوزر، قناة، مجموعة، بوت، هدية"
            ),
            "suggest_admin": False,
        },

        # التحقق من الهوية 
        {
            "intent": "verify_why_phone",
            "patterns": ["ليش تطلب هاتف","ليش رقم الهاتف","شو الهدف من الهاتف","رقم هاتفي ليش","خصوصية هاتف","هاتفي سري","ليش يطلب نمرتي","ليش يريد رقمي","لماذا يطلب الهاتف","ليش النمرة","نمرتي ليش","ليش تطلب موبايلي","شو يسوي برقمي","ليش يحتاج رقمي"],
            "answer": (
                " *لماذا نطلب رقم الهاتف؟*\n\n"
                "رقم الهاتف مطلوب لأسباب أمنية:\n\n"
                "• يربط كل حساب بشخص حقيقي واحد\n"
                "• يمنع إنشاء حسابات وهمية للتلاعب بالأسعار\n"
                "• يُستخدم *فقط* عند النزاعات من قبل الإدارة\n"
                "• يُحفظ بأمان ولا يُشارك مع أحد\n\n"
                "يُطلب *مرة واحدة فقط* طوال استخدامك للبوت."
            ),
            "suggest_admin": False,
        },
        {
            "intent": "verify_why_location",
            "patterns": ["ليش تطلب موقع","ليش location","شو تستفيد من موقعي","gps ليش","موقعي سري","خصوصية الموقع","ليش يطلب موقعي","لماذا يطلب الموقع","ليش يريد مكاني","محلي ليش","ليش يحتاج gps","شو يسوي بموقعي","ليش المكان"],
            "answer": (
                " *لماذا نطلب الموقع الجغرافي؟*\n\n"
                "• يحدد المنطقة التقريبية للبائع (مش العنوان الدقيق)\n"
                "• دليل قانوني عند الإبلاغ عن احتيال\n"
                "• يساعد في اكتشاف الأنماط المشبوهة\n\n"
                "يُؤخذ *مرة واحدة فقط* ولا يتتبع تحركاتك."
            ),
            "suggest_admin": False,
        },
        {
            "intent": "verify_how",
            "patterns": ["كيف اتحقق","كيف ارسل الهاتف","مو قادر اتحقق","التحقق ما يشتغل","كيف اكمل التحقق","ما كملت التحقق","شلون اتحقق","ما اقدر اكمل التحقق","التحقق ما يمشي","مو يسمحلي اتحقق","كيف اكمل","ما اكملت التحقق"],
            "answer": (
                " *كيفية إتمام التحقق*\n\n"
                "اضغط *نشر مزاد* من القائمة الرئيسية\n"
                "ستظهر شاشة التحقق تلقائياً\n"
                "اضغط زر *مشاركة رقم الهاتف* (يُرسل مباشرة)\n"
                "ثم اضغط *مشاركة الموقع*\n\n"
                "إذا أغلقت الشاشة: ارجع لـ 'نشر مزاد' وستعود من جديد.\n"
                "التحقق مطلوب مرة واحدة فقط."
            ),
            "suggest_admin": False,
        },

        # التسليم 
        {
            "intent": "delivery_buyer",
            "patterns": ["البائع مو يسلم","ما سلمني","فزت ومو يجاوب","الفائز ما يسلم","فزت بالمزاد ما وصلني","ما استلمت المنتج","البائع مو يرد","ما يعطيني","مو يسلمني","ربحت بس ما سلمني","فزت وما يرد","البائع اختفى","مو يجاوب البائع","ربحت وما وصلني شي"],
            "answer": (
                " *البائع لم يسلّم المنتج*\n\n"
                "إذا مرّت أكثر من **24 ساعة** من انتهاء المزاد ولم تستلم:\n\n"
                "تواصل مع البائع مباشرة أولاً\n"
                "إذا لم يستجب → أبلغ الإدارة فوراً\n\n"
                "الإدارة ستتخذ إجراءات بحق البائع وتضمن حقك.\n"
                "أرسل للإدارة: رقم المزاد + اسم المستخدم للبائع."
            ),
            "suggest_admin": True,
        },
        {
            "intent": "delivery_seller",
            "patterns": ["كيف اسلم","متى لازم اسلم","مهلة التسليم","24 ساعة تسليم","وقت التسليم","كيف اسلم للفائز","شلون اسلم","ليش لازم اسلم","متى لازم اعطيه","شو المهلة","كم عندي وقت للتسليم","كيف اعطيه","لازم اسلم بعد كم"],
            "answer": (
                " *التسليم كبائع*\n\n"
                "بعد انتهاء المزاد لديك **24 ساعة** لتسليم المنتج للفائز.\n\n"
                "خطوات التسليم:\n"
                "تواصل مع الفائز مباشرة عبر تيليجرام\n"
                "أرسل له بيانات المنتج (كلمة المرور، الأكسس، إلخ)\n"
                "احصل على تأكيده بالاستلام\n\n"
                "عدم التسليم خلال 24 ساعة = حظر فوري من البوت."
            ),
            "suggest_admin": False,
        },

        # الحظر 
        {
            "intent": "banned",
            "patterns": ["حسابي محظور","انا محظور","بلوكيت","مو قادر استخدم البوت","حسابي موقوف","ليش محظور","ايش ذنبي","حظروني","وقفوا حسابي","مبلوكيت","البوت ما يقبلني","مو يدخلني البوت","ليش حسابي موقوف","شو ذنبي","ما اقدر اشتغل","حسابي مربوط"],
            "answer": (
                " *الحساب المحظور*\n\n"
                "أسباب الحظر الشائعة:\n"
                "• عدم تسليم منتج للفائز\n"
                "• بيع منتجات مسروقة أو احتيالية\n"
                "• إدخال بيانات تحقق مزيفة\n"
                "• سلوك احتيالي موثق\n\n"
                "إذا كنت تعتقد أن الحظر خطأ، تواصل مع الإدارة مع توضيح سبب الاعتراض."
            ),
            "suggest_admin": True,
        },

        # الاشتراك الإجباري 
        {
            "intent": "subscription_required",
            "patterns": ["اشتراك اجباري","لازم اشترك","ما يدخلني","يطلب اشتراك","اشتركت بس مو يدخلني","تحقق اشتراك ما يشتغل","مو يدخلني البوت","يطلب مني اشترك","اشتركت وما يدخلني","يطلب قناة","لازم انضم","لازم اشترك بالقناة"],
            "answer": (
                " *الاشتراك الإجباري*\n\n"
                "يجب الاشتراك في القنوات المطلوبة للمتابعة.\n\n"
                "اشترك في جميع القنوات المعروضة\n"
                "اضغط زر *تحقق من الاشتراك*\n"
                "إذا لم يتحقق: تأكد من أن الاشتراك فعلاً تم ولم تغادر القناة\n\n"
                "إذا تحققت ومازال يطلب منك، أرسل للإدارة."
            ),
            "suggest_admin": False,
        },

        # عجلة الحظ 
        {
            "intent": "lucky_wheel",
            "patterns": ["عجلة الحظ","lucky wheel","دوّر العجلة","كيف العجله","جائزة العجلة","spin","دوّار","عجلة","ادور","ادور العجلة","عجلة الحظ شلون","كيف ادور","الدوّارة","اريد ادور"],
            "answer": (
                " *عجلة الحظ*\n\n"
                "عجلة الحظ تمنحك فرصة الفوز بمبالغ مختلفة!\n\n"
                "• يمكنك الدوران مرة واحدة يومياً\n"
                "• المبالغ تُضاف للرصيد فوراً عند الفوز\n"
                "• ادخل من القائمة الرئيسية ← المحفظة"
            ),
            "suggest_admin": False,
        },

        # الوكلاء والوسطاء 
        {
            "intent": "agent_scam",
            "patterns": ["الوكيل نصب","الوكيل غشني","الوكيل سرق فلوسي","مو امين الوكيل","وكيل مشكله","ابلغ عن وكيل","الوكيل خدعني","الوكيل مو صادق","الوكيل كذب","الوكيل ضحك عليه","سرق الوكيل","الوكيل نصّاب","احتجز فلوسي","ما أعاد فلوسي"],
            "answer": (
                " *بلاغ عن وكيل*\n\n"
                "إذا تعرضت لغش أو احتيال من أحد الوكلاء:\n\n"
                "توثّق المحادثة (لقطات شاشة)\n"
                "ابعث للإدارة:\n"
                "• اسم/معرف الوكيل\n"
                "• المبلغ المُحتجز\n"
                "• تفاصيل ما حدث\n\n"
                "الإدارة ستحقق فوراً وستُعاد أموالك إذا ثبتت المشكلة."
            ),
            "suggest_admin": True,
        },
        {
            "intent": "broker_how",
            "patterns": ["كيف الوسيط","ما هو الوسيط","خدمة الوساطة","ابغى وسيط","ضمان الصفقه","broker"],
            "answer": (
                " *خدمة الوسيط (Broker)*\n\n"
                "الوسيط يضمن الصفقة بين البائع والمشتري خارج المزاد.\n\n"
                "كيف يعمل:\n"
                "المشتري يحوّل المبلغ للوسيط\n"
                "البائع يسلّم المنتج\n"
                "بعد التأكيد يحوّل الوسيط المبلغ للبائع\n\n"
                "ابحث عن قائمة الوسطاء المعتمدين من لوحة التحكم."
            ),
            "suggest_admin": False,
        },

        # القوانين العامة 
        {
            "intent": "rules_general",
            "patterns": ["ما هي القوانين","اعرف القوانين","ايش القوانين","سياسة البوت","شروط الاستخدام","قوانين البوت","شنو القوانين","شو السياسة","قوانين","قانون البوت","شروط","قرأت القوانين","شنو الشروط","اريد اعرف القوانين"],
            "answer": (
                " *قوانين البوت بإيجاز*\n\n"
                " *للبائع:*\n"
                "• تسليم المنتج خلال 24 ساعة بعد البيع\n"
                "• عدم نشر منتجات مسروقة أو احتيالية\n"
                "• إدخال بيانات تحقق حقيقية\n\n"
                " *للمشتري:*\n"
                "• الرصيد يُحجز أثناء المزاد ويُعاد عند الخسارة\n"
                "• الإبلاغ خلال 24 ساعة إن لم يُسلَّم المنتج\n\n"
                " *عام:*\n"
                "• أي احتيال = حظر فوري\n"
                "• اضغط *القوانين* من القائمة لقراءة التفاصيل"
            ),
            "suggest_admin": False,
        },

        # مشاكل تقنية 
        {
            "intent": "bot_not_responding",
            "patterns": ["البوت ما يرد","البوت خربان","ما يشتغل البوت","البوت ميت","البوت واقف","مو شغال","البوت مو رادّ","البوت عطلان","البوت مصخبر","ما يجاوبني البوت","البوت crash","البوت سقط","ما يفتح البوت","البوت بطيء"],
            "answer": (
                " *البوت لا يستجيب*\n\n"
                "جرب الخطوات التالية:\n"
                "أرسل /start لإعادة تهيئة الجلسة\n"
                "انتظر 30 ثانية وأعد المحاولة\n"
                "تأكد من اتصال الإنترنت\n\n"
                "إذا استمرت المشكلة أكثر من 10 دقائق، أبلغ الإدارة."
            ),
            "suggest_admin": True,
        },
        {
            "intent": "button_not_working",
            "patterns": ["الزر ما يشتغل","ما يفتح","الزر خربان","لما اضغط ما يصير شي","زر لا يستجيب","الزر مو شغال","اضغط وما يصير","الزر ما يمشي","ما يستجيب","الزر عطلان","لما اضغط ما يفتح","مو يستجيب الزر"],
            "answer": (
                " *الزر لا يعمل*\n\n"
                "أرسل /start لإعادة تشغيل الجلسة\n"
                "إذا كانت رسالة قديمة، اطلب رسالة جديدة\n"
                "أحياناً يكون السبب ضغطاً عالياً على السيرفر — انتظر لحظة\n\n"
                "إذا استمرت المشكلة أرسل للإدارة."
            ),
            "suggest_admin": True,
        },

        # تحيات وعبارات عامة 
        {
            "intent": "greeting",
            "patterns": ["مرحبا","هلا","السلام","اهلين","هاي","hi","hello","صباح","مساء","هلو","هاي هاي","اهلا","سلام عليكم","وين انت","ابو","يا بوت","يا هلا","هلا بيك","شلونك","اشلونك","گولي"],
            "answer": (
                " *أهلاً وسهلاً!*\n\n"
                "أنا مساعد الدعم الفني لبوت المزادات.\n"
                "أعرف كل شيء عن البوت وأستطيع مساعدتك فوراً.\n\n"
                "أخبرني بمشكلتك أو سؤالك "
            ),
            "suggest_admin": False,
        },
        {
            "intent": "thanks",
            "patterns": ["شكرا","شكراً","ثانكس","thanks","مشكور","يسلمو","الله يسلمك","تسلم","شكراً جزيلاً","مليون شكر","مشكورين","الله يعطيك العافية","يعطيك العافية","بارك الله فيك","تسلم ايدك","الله يحفظك"],
            "answer": (
                " *على الرحب والسعة!*\n\n"
                "إذا عندك أي سؤال ثاني، أنا هنا دائماً."
            ),
            "suggest_admin": False,
        },
        {
            "intent": "who_are_you",
            "patterns": ["من انت","ايش انت","بوت ولا انسان","ذكاء اصطناعي","ai انت","روبوت","انت شو","انت مين","شو انت","انت ذكاء","انت بوت","انت واحد ولا بوت","انسان ولا آلة","شنو انت"],
            "answer": (
                " *أنا مساعد الدعم الفني*\n\n"
                "ذكاء اصطناعي مدمج ومبني خصيصاً لهذا البوت — لا أعتمد على أي خدمة خارجية.\n\n"
                "أعرف كل شيء عن:\n"
                "• المزادات والمزايدات\n"
                "• الرصيد والمحفظة والشحن\n"
                "• القوانين والعمولات\n"
                "• التحقق والتسليم والحظر\n"
                "• وكل تفاصيل البوت\n\n"
                "سألني بأي شيء! "
            ),
            "suggest_admin": False,
        },
    ]

    def __init__(self):
        self.nlp = ArabicNLP()
        # بناء فهرس سريع: intent → entry
        self._by_intent = {e["intent"]: e for e in self.ENTRIES}
        # دمج الأنماط المتعلَّمة من قاعدة البيانات (يضيفها الأدمن من مراجعة الأسئلة الفاشلة)
        self.reload_learned_patterns()

    def reload_learned_patterns(self):
        """يدمج الأنماط المتعلَّمة من ai_learned_patterns مع أنماط ENTRIES الأساسية.
        يُستدعى عند بدء التشغيل وعند إضافة نمط جديد من لوحة الإدمن، لتحديث الفهم فوراً
        بدون الحاجة لإعادة تشغيل البوت."""
        try:
            learned = db.get_learned_patterns()
        except Exception as e:
            logger.error(f"reload_learned_patterns: {e}")
            return
        for entry in self.ENTRIES:
            intent = entry["intent"]
            if intent in learned:
                base_patterns = set(entry.get("patterns", []))
                for p in learned[intent]:
                    if p not in base_patterns:
                        entry["patterns"].append(p)
                        base_patterns.add(p)

    def find_best_match(self, text: str, top_k: int = 1) -> list:
        """يجد أفضل إجابة لنص المستخدم.
        يعتمد على تطابق الكلمات المفتاحية مباشرةً مع أوزان.
        يعيد قائمة من (score, entry).
        """
        scores = []
        norm_text = self.nlp.normalize(text)
        user_tokens = set(self.nlp.tokenize(text))
        user_stemmed = {self.nlp.stem(t) for t in user_tokens}

        for entry in self.ENTRIES:
            best_score = 0.0

            for pattern in entry["patterns"]:
                pat_norm = self.nlp.normalize(pattern)
                pat_tokens = set(self.nlp.tokenize(pattern))
                pat_stemmed = {self.nlp.stem(t) for t in pat_tokens}

                score = 0.0

                # تطابق كامل للعبارة (أعلى درجة)
                if pat_norm == norm_text:
                    score = 1.0

                # النص يحتوي العبارة كاملة
                elif pat_norm in norm_text:
                    score = 0.9

                # تطابق كلمات بالضبط
                elif pat_tokens and pat_tokens.issubset(user_tokens):
                    score = 0.85

                # تطابق الجذور كلياً
                elif pat_stemmed and pat_stemmed.issubset(user_stemmed):
                    score = 0.80

                else:
                    # نسبة الكلمات المتطابقة (حرفياً + جذراً)
                    if pat_tokens:
                        exact_hits = len(pat_tokens & user_tokens)
                        stem_hits = len(pat_stemmed & user_stemmed)
                        total_hits = exact_hits + stem_hits * 0.8
                        coverage = total_hits / len(pat_tokens)

                        # نحتاج على الأقل نصف الكلمات متطابقة
                        if coverage >= 0.5:
                            score = coverage * 0.75
                        elif coverage >= 0.35:
                            score = coverage * 0.5

                if score > best_score:
                    best_score = score

            scores.append((best_score, entry))

        scores.sort(key=lambda x: -x[0])
        return scores[:top_k]


class LocalAIEngine:
    """محرك الذكاء الاصطناعي المحلي الكامل.
    يدير المحادثة، يتتبع السياق، ويولّد الردود.
    """
    # عتبة الثقة: أقل من هذا = لا نعرف الإجابة
    CONFIDENCE_THRESHOLD = 0.28

    def __init__(self):
        self.kb = BotKnowledgeBase()
        self.nlp = ArabicNLP()
        # ذاكرة المحادثات: {session_key: ConversationContext}
        self._sessions = {}
        self._lock = threading.Lock()

    def _get_session(self, session_key: str) -> dict:
        with self._lock:
            now = time.time()
            # تنظيف الجلسات القديمة (أكثر من ساعة)
            expired = [k for k, v in self._sessions.items()
                       if now - v.get("_last_active", now) > 3600]
            for k in expired:
                del self._sessions[k]
            if session_key not in self._sessions:
                self._sessions[session_key] = {
                    "turn": 0,
                    "last_intent": None,
                    "entities": {},
                    "unresolved_turns": 0,
                    "_last_active": now,
                }
            else:
                self._sessions[session_key]["_last_active"] = now
            return self._sessions[session_key]

    def clear_session(self, session_key: str):
        with self._lock:
            self._sessions.pop(session_key, None)

    def get_last_log_id(self, session_key: str):
        """يُعيد آخر log_id مسجَّل لهذه الجلسة (يُستخدم لربط زر التقييم 👍/👎 بالسجل الصحيح)"""
        with self._lock:
            session = self._sessions.get(session_key)
            return session.get("last_log_id") if session else None

    def _extract_context_from_history(self, history: list) -> str:
        """يجمع كل رسائل المستخدم في نص واحد للفهم السياقي"""
        user_msgs = [m["content"] for m in history if m.get("role") == "user"]
        return " ".join(user_msgs[-5:]) # آخر 5 رسائل

    def reply(self, history: list, session_key: str = "default", user_id: int = None) -> str:
        """الدالة الرئيسية: تأخذ تاريخ المحادثة وتعيد رداً.
        history = [{"role":"user"/"assistant","content":"..."}]
        كل محادثة تُسجَّل في قاعدة البيانات (إن توفّر user_id) لتغذية نظام التعلّم.
        """
        if not history:
            return "أهلاً! كيف أقدر أساعدك؟"

        session = self._get_session(session_key)
        session["turn"] += 1

        # آخر رسالة من المستخدم
        last_user_msg = ""
        for m in reversed(history):
            if m.get("role") == "user":
                last_user_msg = m["content"]
                break

        if not last_user_msg.strip():
            return "لم أفهم رسالتك، حاول مرة ثانية."

        # استخراج الكيانات من الرسالة الأخيرة
        entities = self.nlp.extract_entities(last_user_msg)
        session["entities"].update(entities)

        # نص موحّد من كامل المحادثة للفهم الأعمق
        full_context = self._extract_context_from_history(history)

        # البحث عن أفضل إجابة
        results = self.kb.find_best_match(full_context, top_k=3)
        best_score, best_entry = results[0]

        # إذا الثقة منخفضة جداً
        if best_score < self.CONFIDENCE_THRESHOLD:
            session["unresolved_turns"] += 1
            if user_id is not None:
                log_id = db.log_ai_conversation(user_id, last_user_msg, matched_intent=None,
                                                 confidence=best_score, was_unknown=True)
                session["last_log_id"] = log_id
            return self._unknown_response(session, last_user_msg)

        # تحديث حالة الجلسة
        session["last_intent"] = best_entry["intent"]
        session["unresolved_turns"] = 0

        if user_id is not None:
            log_id = db.log_ai_conversation(user_id, last_user_msg, matched_intent=best_entry["intent"],
                                             confidence=best_score, was_unknown=False)
            session["last_log_id"] = log_id

        reply_text = best_entry["answer"]

        # إضافة تفاصيل الكيانات المُستخرجة إن وجدت
        extras = self._enrich_with_entities(entities, best_entry["intent"])
        if extras:
            reply_text += f"\n\n{extras}"

        return reply_text

    def _enrich_with_entities(self, entities: dict, intent: str) -> str:
        """يضيف معلومات مخصصة بناءً على ما وجده في نص المستخدم"""
        notes = []
        if "auction_ids" in entities and "auction" in intent:
            ids = ", ".join(entities["auction_ids"][:3])
            notes.append(f"رقم المزاد الذي ذكرته: `{ids}`")
        if "txhash" in entities:
            notes.append(f"رقم العملية المُكتشف: `{entities['txhash'][0][:20]}...`")
        if "numbers" in entities and intent in ("balance_not_added_binance", "balance_not_added_stars"):
            amt = entities["numbers"][0]
            notes.append(f"المبلغ المذكور: {amt}")
        return "\n".join(notes)

    def _unknown_response(self, session: dict, user_msg: str) -> str:
        """رد عند عدم الفهم — بصيغة عربية فصيحة واضحة"""
        turns = session["unresolved_turns"]

        if turns <= 1:
            return (
                " *لم أتمكن من فهم استفسارك بدقة*\n\n"
                "يرجى إعادة صياغة سؤالك بشكل أوضح، على سبيل المثال:\n"
                "• «لم تتم إضافة رصيدي بعد الشحن»\n"
                "• «لا أستطيع المزايدة على المزاد»\n"
                "• «مزادي لم تتم الموافقة عليه»\n"
                "• «البائع لم يسلّمني بعد فوزي بالمزاد»\n\n"
                "يرجى توضيح المشكلة بالتفصيل لمساعدتك بأفضل صورة"
            )
        elif turns == 2:
            return (
                " *لم أتمكن من تحديد المشكلة بدقة*\n\n"
                "يرجى كتابة مشكلتك بوضوح أكبر، مثل:\n"
                "«قمت بشحن 10 USDT عبر Binance ولم تتم إضافة الرصيد»\n"
                "أو اضغط على زر *إرسال للإدارة* ليتولى أحد المسؤولين مساعدتك مباشرة."
            )
        else:
            return (
                "هذا الاستفسار خارج نطاق تخصصي.\n\n"
                "أستطيع المساعدة فقط في المسائل المتعلقة بالبوت والمزادات.\n"
                "يرجى الضغط على زر *إرسال للإدارة* ليتم حل المشكلة من قِبل المسؤولين."
            )

    def reply_legal(self, history: list, session_key: str = "legal_default") -> str:
        """ذكاء المستشار القانوني — يركز على شرح القوانين والسياسات.
        """
        if not history:
            return "أهلاً! اسألني عن أي قانون أو سياسة في البوت."

        last_user_msg = ""
        for m in reversed(history):
            if m.get("role") == "user":
                last_user_msg = m["content"]
                break

        full_context = self._extract_context_from_history(history)
        results = self.kb.find_best_match(full_context, top_k=1)
        best_score, best_entry = results[0]

        # للذكاء القانوني، نعطي أفضلية لـ intents معينة
        legal_intents = {
            "verify_why_phone", "verify_why_location", "rules_general",
            "auction_commission", "transfer_commission", "banned",
            "delivery_buyer", "delivery_seller", "auction_not_approved",
            "auction_types", "auction_duration", "bid_extend"
        }

        if best_score >= self.CONFIDENCE_THRESHOLD and best_entry["intent"] in legal_intents:
            return best_entry["answer"]

        # إذا لم يكن سؤالاً قانونياً بحتاً، نبحث في كامل القاعدة
        if best_score >= self.CONFIDENCE_THRESHOLD:
            # نضيف مقدمة توضيحية
            return f" *من سياسات البوت:*\n\n{best_entry['answer']}"

        # ردود احتياطية للمستشار القانوني
        legal_keywords = self.nlp.semantic_tokens(full_context)
        norm_context = self.nlp.normalize(full_context)

        if "عمولة" in legal_keywords or "رسوم" in legal_keywords or "يخصم" in norm_context or "يقطع" in norm_context:
            return (
                " *العمولات والرسوم*\n\n"
                "• نشر مزاد: 0.01$ (رمزية)\n"
                "• عمولة البيع: 0.5% من سعر البيع\n"
                "• عمولة التحويل: 5%\n\n"
                "هذه العمولات تذهب لصيانة وتطوير البوت."
            )
        if "حظر" in legal_keywords or "محظور" in norm_context or "موقوف" in norm_context:
            return (
                " *حالات الحظر الفوري*\n\n"
                "• بيع منتجات مسروقة أو احتيالية\n"
                "• عدم تسليم المنتج للفائز خلال 24 ساعة\n"
                "• إدخال بيانات تحقق مزيفة\n"
                "• أي سلوك احتيالي موثق بالبلاغات\n\n"
                "الحظر يُطبّق فوراً وبشكل دائم عند الإخلال بهذه القوانين."
            )
        if "هاتف" in legal_keywords or "نمره" in norm_context or "نمرتي" in norm_context or "رقمي" in norm_context:
            return (
                " *لماذا يطلب البوت رقم هاتفك؟*\n\n"
                "• يربط كل حساب بشخص حقيقي واحد\n"
                "• يمنع الحسابات الوهمية والتلاعب\n"
                "• يُستخدم *فقط* عند النزاعات\n"
                "• يُحفظ بأمان ولا يُشارك مع أحد\n\n"
                "يُطلب مرة واحدة فقط طوال استخدامك للبوت."
            )
        if "موقع" in legal_keywords or "لوكيشن" in norm_context or "gps" in norm_context or "مكاني" in norm_context:
            return (
                " *لماذا يطلب البوت موقعك؟*\n\n"
                "• يحدد المنطقة التقريبية فقط (وليس العنوان الدقيق)\n"
                "• دليل قانوني عند الإبلاغ عن احتيال\n"
                "• يُؤخذ مرة واحدة فقط\n"
                "• لا يتتبع تحركاتك أبداً"
            )
        if "تسليم" in legal_keywords or "يسلم" in norm_context or "ما سلم" in norm_context:
            return (
                " *قانون التسليم*\n\n"
                "• البائع لديه 24 ساعة لتسليم المنتج بعد انتهاء المزاد\n"
                "• عدم التسليم = حظر فوري من البوت\n"
                "• إذا لم يسلّمك، أبلغ الإدارة فوراً وستُستعاد حقوقك"
            )

        return (
            " *سؤالك خارج اختصاصي*\n\n"
            "أنا أشرح سياسات وقوانين البوت فقط.\n"
            "اسألني عن: العمولات، التحقق، الحظر، التسليم، أنواع المزادات، وغيرها."
        )


# إنشاء محرك الذكاء المحلي (singleton) 
_local_ai = LocalAIEngine()


def ask_claude(conversation_history, user_id=None):
    """واجهة الذكاء الاصطناعي للدعم الفني — محلي بالكامل.
    conversation_history = [{"role": "user"/"assistant", "content": "..."}]
    """
    try:
        if not conversation_history:
            return None
        # مفتاح الجلسة من أول رسالة
        session_key = f"support_{id(conversation_history)}"
        return _local_ai.reply(conversation_history, session_key, user_id=user_id)
    except Exception as e:
        logger.error(f"LocalAI error: {e}")
        return None


def get_ai_last_log_id(conversation_history):
    """يُعيد آخر log_id لمحادثة معينة — يُستخدم لربط أزرار التقييم 👍/👎 بالسجل الصحيح في قاعدة البيانات"""
    try:
        session_key = f"support_{id(conversation_history)}"
        return _local_ai.get_last_log_id(session_key)
    except Exception:
        return None


def ask_ai_legal(conversation_history):
    """واجهة الذكاء الاصطناعي للمستشار القانوني — محلي بالكامل.
    """
    try:
        if not conversation_history:
            return None
        session_key = f"legal_{id(conversation_history)}"
        return _local_ai.reply_legal(conversation_history, session_key)
    except Exception as e:
        logger.error(f"LocalAI Legal error: {e}")
        return None


def _build_manual_summary(history):
    """يبني ملخصاً نصياً من المحادثة"""
    user_msgs = [m["content"] for m in history if m.get("role") == "user"]
    if not user_msgs:
        return "لا توجد تفاصيل كافية"
    lines = [" *محادثة المستخدم مع الدعم:*\n"]
    for i, msg in enumerate(user_msgs, 1):
        lines.append(f"{i}. {msg}")
    return "\n".join(lines)


def generate_support_summary(history):
    """يولّد ملخصاً منظماً للإدارة من تاريخ المحادثة.
    """
    if not history:
        return "لا توجد تفاصيل كافية"

    user_msgs = [m["content"] for m in history if m.get("role") == "user"]
    if not user_msgs:
        return "لا توجد تفاصيل كافية"

    # استخراج الكيانات من كامل المحادثة
    full_text = " ".join(user_msgs)
    entities = _local_ai.nlp.extract_entities(full_text)

    # كشف النية الأساسية
    results = _local_ai.kb.find_best_match(full_text, top_k=1)
    best_score, best_entry = results[0]

    intent_label = best_entry["intent"].replace("_", " ") if best_score > 0.1 else "غير محدد"

    lines = [
        f" *المشكلة:* {intent_label}",
        f" *تفاصيل المستخدم:*",
    ]
    for i, msg in enumerate(user_msgs[:5], 1):
        lines.append(f" {i}. {msg}")

    if entities.get("numbers"):
        lines.append(f" *مبالغ مذكورة:* {', '.join(str(n) for n in entities['numbers'][:3])}")
    if entities.get("txhash"):
        lines.append(f" *رقم عملية:* {entities['txhash'][0][:30]}...")
    if entities.get("auction_ids"):
        lines.append(f" *أرقام مزادات:* {', '.join(entities['auction_ids'][:3])}")

    lines.append(f" *طلب المستخدم:* {user_msgs[-1]}")

    return "\n".join(lines)


# جداول قاعدة البيانات لجلسات الذكاء القانوني 
def db_create_legal_session(user_id):
    """إنشاء جلسة ذكاء قانوني جديدة"""
    cursor = db.conn.cursor()
    cursor.execute(
        "UPDATE support_tickets SET status='closed', closed_at=CURRENT_TIMESTAMP "
        "WHERE user_id=? AND status='open' AND summary LIKE 'legal_%'",
        (user_id,)
    )
    cursor.execute(
        "INSERT INTO support_tickets (user_id, ai_history, summary) VALUES (?, '[]', 'legal_session')",
        (user_id,)
    )
    db.conn.commit()
    return cursor.lastrowid

def db_get_open_legal_session(user_id):
    """جلب جلسة الذكاء القانوني المفتوحة"""
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT * FROM support_tickets WHERE user_id=? AND status='open' AND summary='legal_session' "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {'ticket_id': row[0], 'user_id': row[1], 'status': row[2],
            'ai_history': json.loads(row[3] or '[]'), 'summary': row[4],
            'created_at': row[5]}

def db_close_legal_session(ticket_id):
    cursor = db.conn.cursor()
    cursor.execute(
        "UPDATE support_tickets SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE ticket_id=?",
        (ticket_id,)
    )
    db.conn.commit()


# نص القوانين الكامل للعرض 
RULES_TEXT_FULL = f""" *قوانين وسياسات بوت المزادات*

{''*30}
 *التحقق من الهوية*
{''*30}

 *رقم الهاتف — لماذا مطلوب؟*
• يربط كل حساب بشخص حقيقي واحد
• يمنع إنشاء حسابات وهمية للتلاعب بالأسعار
• يُستخدم فقط عند النزاعات من قبل الإدارة
• يُحفظ مشفراً ولا يُشارك مع أحد
• يُطلب مرة واحدة فقط طوال استخدامك

 *الموقع الجغرافي — لماذا مطلوب؟*
• يحدد المنطقة التقريبية للبائع (ليس العنوان الدقيق)
• دليل قانوني عند الإبلاغ عن الاحتيال
• يساعد في اكتشاف الأنماط المشبوهة
• يُؤخذ مرة واحدة فقط ولا يتتبع تحركاتك

{''*30}
 *العمولات والرسوم*
{''*30}

• نشر مزاد: 0.01$ (رمزية لمنع البريد المزعج)
• عمولة البيع: 0.5% من سعر البيع النهائي
• عمولة التحويل: 5% من المبلغ المحوّل

{''*30}
 *قوانين المزادات*
{''*30}

• مدة المزاد: تُحدد عند الإنشاء (الافتراضي 5 ساعات)
• كل مزايدة تُمدد المزاد 5 دقائق تلقائياً
• تسليم المنتج للفائز: خلال 24 ساعة من انتهاء المزاد
• إن لم يأتِ مزايد: يُعاد سعر البدء للبائع كاملاً
• إن خسرت المزاد: يُعاد رصيدك فوراً

{''*30}
 *حالات الحظر الفوري*
{''*30}

• بيع منتجات مسروقة أو احتيالية
• عدم تسليم المنتج للفائز خلال 24 ساعة
• إدخال بيانات تحقق مزيفة
• أي سلوك احتيالي موثق بالبلاغات

{''*30}
 عندك سؤال؟ اضغط زر الذكاء القانوني"""


def generate_code():
    import secrets as _secrets
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" # حذف الأحرف المتشابهة (O,0,I,1)
    return "-".join("".join(_secrets.choice(chars) for _ in range(4)) for _ in range(3))

def generate_auction_id():
    """توليد auction_id فريد مع فحص التكرار في قاعدة البيانات"""
    import secrets as _secrets
    for _ in range(10):
        aid = str(_secrets.randbelow(900000) + 100000)
        if not db.get_auction_by_id(aid):
            return aid
    return str(_secrets.randbelow(90000000) + 10000000)


def is_valid_username(username):
    pattern = r'^[a-zA-Z0-9_]{5,32}$'
    return re.match(pattern, username) is not None

def normalize_telegram_link(raw: str) -> str:
    """تحويل أي شكل من أشكال رابط تيليجرام إلى الرابط الكامل"""
    raw = raw.strip()
    # أزل @ في البداية إذا وُجد
    if raw.startswith('@'):
        raw = raw[1:]
    # إذا بدأ بـ t.me أو http://t.me أضف https://
    if re.match(r'^(http://)?t\.me/', raw):
        raw = re.sub(r'^http://', 'https://', raw)
        if not raw.startswith('https://'):
            raw = 'https://' + raw
    # إذا كان معرفاً مجرداً مثل "username"أضف https://t.me/
    if re.match(r'^[a-zA-Z0-9_]{5,32}$', raw):
        raw = f'https://t.me/{raw}'
    return raw


def is_valid_telegram_link(link):
    link = normalize_telegram_link(link)
    patterns = [
        r'^https://t\.me/[a-zA-Z0-9_]{5,32}$',
        r'^https://t\.me/joinchat/[a-zA-Z0-9_-]+$',
        r'^https://t\.me/\+[a-zA-Z0-9_-]+$',
        r'^https://t\.me/gift/[0-9]+$',
        r'^https://t\.me/gift/[a-zA-Z0-9_-]+$',
        r'^https://t\.me/[a-zA-Z0-9_]{5,32}/[0-9]+$',
        r'^https://t\.me/nft/[a-zA-Z0-9_-]+$',
    ]
    for pattern in patterns:
        if re.match(pattern, link):
            return True
    return False

def verify_channel_owner(chat_id_or_username, requester_user_id):
    """يتحقق من أن المستخدم هو مالك/مشرف للقناة أو المجموعة.
    يعيد (True, chat_info) إذا كان مالكاً، أو (False, رسالة_الخطأ) إذا لم يكن.
    يحاول عدة أشكال للمعرف قبل الاستسلام.
    """
    try:
        raw = chat_id_or_username
        targets = []

        if isinstance(raw, int):
            targets = [raw]
        elif isinstance(raw, str):
            raw = raw.strip()
            if raw.startswith('https://t.me/'):
                part = raw.replace('https://t.me/', '').split('/')[0].split('?')[0]
                # روابط الدعوة الخاصة لا يمكن get_chat عليها
                if part not in ('joinchat',) and not part.startswith('+'):
                    targets.append(f"@{part}")
                    targets.append(part)
                else:
                    # رابط خاص — نحاول استخدام الرابط كاملاً مباشرةً (قد يعمل مع بعض إصدارات API)
                    targets.append(raw)
            elif raw.startswith('@'):
                targets.append(raw)
                targets.append(raw[1:])
            elif raw.lstrip('-').isdigit():
                targets.append(int(raw))
            else:
                targets.append(f"@{raw}")
                targets.append(raw)

        if not targets:
            return False, (
                "تعذر تحليل معرف القناة/المجموعة.\n\n"
                "أرسل المعرف بأحد الأشكال:\n"
                "• @username\n"
                "• https://t.me/username\n"
                "• الأيدي الرقمي للقناة"
            )

        # محاولة get_chat بكل الأشكال
        chat = None
        last_err = ""
        for t in targets:
            try:
                chat = bot.get_chat(t)
                break
            except Exception as e:
                last_err = str(e)
                logger.warning(f"verify_channel_owner get_chat({t!r}) failed: {e}")
                continue

        if chat is None:
            return False, (
                f"تعذر الوصول للقناة/المجموعة.\n\n"
                f"الأسباب المحتملة:\n"
                f"• البوت غير مضاف في القناة/المجموعة\n"
                f"• المعرف غير صحيح\n"
                f"• القناة/المجموعة خاصة والبوت ليس عضواً\n\n"
                f"الحل: أضف @{get_bot_info()['username']} كمشرف ثم أعد المحاولة.\n\n"
                f"[تفاصيل: {last_err[:120]}]"
            )

        # التحقق من عضوية البوت
        bot_id = get_bot_info()['id']
        try:
            bot_member = bot.get_chat_member(chat.id, bot_id)
            if bot_member.status not in ('administrator', 'creator'):
                return False, (
                    f"البوت عضو لكن ليس مشرفاً في:\n{chat.title}\n\n"
                    f"ارفع صلاحية البوت إلى مشرف ثم أعد المحاولة."
                )
        except Exception as e:
            err_text = str(e).lower()
            if 'not found' in err_text or 'user not found' in err_text or 'member' in err_text:
                return False, (
                    f"البوت غير موجود في:\n{chat.title}\n\n"
                    f"أضف @{get_bot_info()['username']} كمشرف في القناة/المجموعة ثم أعد المحاولة."
                )
            return False, (
                f"تعذر التحقق من صلاحيات البوت في:\n{chat.title}\n\n"
                f"تأكد من إضافة البوت كمشرف.\n[{str(e)[:100]}]"
            )

        # التحقق من ملكية المستخدم — المالك فقط (creator) مسموح له
        try:
            member = bot.get_chat_member(chat.id, requester_user_id)
        except Exception as e:
            return False, (
                f"تعذر التحقق من عضويتك في:\n{chat.title}\n\n"
                f"تأكد من أنك مالك هذه القناة/المجموعة."
            )

        if member.status == 'creator':
            return True, {'chat': chat, 'role': 'creator'}
        elif member.status == 'administrator':
            # الأدمن مرفوض — المالك فقط مسموح له
            return False, (
                f"أنت مشرف وليس **مالك** هذه القناة/المجموعة.\n\n"
                f"يُقبل فقط **المالك** لرفع المزاد.\n"
                f"القناة: {chat.title}"
            )
        else:
            return False, (
                f"أنت لست مالك هذه القناة/المجموعة.\n\n"
                f"يُقبل فقط المالك لرفع المزاد.\n"
                f"القناة: {chat.title}"
            )
    except Exception as e:
        logger.error(f"verify_channel_owner error: {e}")
        return False, f"خطأ في التحقق: {e}"



def _show_user_detail(call, target_uid, chat_id, message_id):
    """عرض تفاصيل مستخدم كاملة للأدمن"""
    u = db.get_user(target_uid)
    if not u:
        safe_answer_callback_query(call.id, "المستخدم غير موجود!")
        return
    is_banned = db.is_banned(target_uid)
    reports = db.get_user_reports(target_uid)
    report_count = len(reports)
    verification = db.get_verification(target_uid)
    stats = db.get_wallet_stats(target_uid) if hasattr(db, 'get_wallet_stats') else {}
    # معلومات الاشتراكات
    auctions = db.get_user_auctions(target_uid)
    active_count = sum(1 for a in auctions if a['status'] == 'active')
    sold_count = sum(1 for a in auctions if a['status'] == 'sold')

    text = (
        f"{''*28}\n"
        f" *تفاصيل المستخدم*\n"
        f"{''*28}\n\n"
        f"الأيدي: `{u['user_id']}`\n"
        f"المعرف: @{u['username'] if u['username'] else 'بدون معرف'}\n"
        f"الاسم: {u['first_name'] or ''} {u['last_name'] or ''}\n"
        f"الرصيد: {u['balance']:.2f}$\n"
        f"انضم: {str(u['created_at'])[:10]}\n"
        f"محظور: {'نعم' if is_banned else 'لا'}\n\n"
        f" *الإحصائيات:*\n"
        f"مزاداته: {len(auctions)} | نشط: {active_count} | مباع: {sold_count}\n"
        f"البلاغات: {report_count}\n"
    )
    if reports:
        text += f"\n*آخر بلاغ:*\n{reports[0]['reason'] or 'بدون سبب'}\n"
    if verification:
        text += f"\n الهاتف: {verification['phone'] or 'غير مُسجل'}\n"
        if verification['lat']:
            text += f"الموقع: {verification['lat']:.4f}, {verification['lon']:.4f}\n"

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("➕💰 إضافة رصيد", callback_data=f"admin_add_bal_user_{target_uid}", style="primary"),
        types.InlineKeyboardButton("➖💰 خصم رصيد", callback_data=f"admin_deduct_bal_user_{target_uid}", style="danger")
    )
    if is_banned:
        keyboard.row(types.InlineKeyboardButton("🔓 رفع الحظر", callback_data=f"admin_unban_user_detail_{target_uid}", style="primary"))
    else:
        keyboard.row(types.InlineKeyboardButton("🚫 حظر", callback_data=f"admin_ban_user_detail_{target_uid}", style="danger"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")


def _show_admin_broker_detail(call, broker_uid, chat_id, message_id):
    """عرض ملف الوسيط الكامل للأدمن: معلوماته، طلباته، تحليل عمله، وأدوات التحكم (تنبيه/بلاغ/حذف/حظر)"""
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT b.user_id, b.name, b.description, b.contact, b.is_active, b.added_at, b.added_by, "
        "u.username, u.first_name FROM brokers b LEFT JOIN users u ON b.user_id=u.user_id WHERE b.user_id=?",
        (broker_uid,)
    )
    row = cursor.fetchone()
    if not row:
        safe_answer_callback_query(call.id, "الوسيط غير موجود!", show_alert=True)
        return
    br = {
        'user_id': row[0], 'name': row[1] or '', 'description': row[2] or '',
        'contact': row[3] or '', 'is_active': row[4], 'added_at': row[5], 'added_by': row[6],
        'username': row[7], 'first_name': row[8]
    }
    is_banned = db.is_banned(broker_uid)
    stats = db.get_broker_full_stats(broker_uid)
    rating_stats = db.get_broker_rating_stats(broker_uid)
    warn_count = db.get_broker_warning_count(broker_uid, 'warning')
    recent_warnings = db.get_broker_warnings(broker_uid, limit=3)
    recent_reqs = db.get_broker_requests(broker_user_id=broker_uid)[:5]

    uname_disp = f"@{br['username']}" if br['username'] else (br['contact'] or "بدون معرف")
    name_disp = hb(br['name'] or br['first_name'] or f"وسيط {broker_uid}")

    text = f"{DIVIDER}\n🤝 {name_disp}\n{DIVIDER}\n\n"
    text += f"🆔 الأيدي: {hc(broker_uid)}\n"
    text += f"👤 المعرف: {html_escape(uname_disp)}\n"
    if br['description']:
        text += f"📝 الوصف: {html_escape(br['description'])}\n"
    text += f"📅 أُضيف: {html_escape(str(br['added_at'])[:16])}\n"
    text += f"⚡ الحالة: {'🟢 نشط' if br['is_active'] else '🔴 معطّل'}"
    if is_banned:
        text += " | 🚫 الحساب محظور"
    text += "\n"
    if warn_count > 0:
        text += f"⚠️ عدد التنبيهات السابقة: {warn_count}\n"

    if rating_stats['count'] > 0:
        avg = rating_stats['avg']
        full = int(avg)
        stars_str = "⭐" * full + ("✨" if avg - full >= 0.5 else "")
        text += f"\n{stars_str} {avg:.1f}/5 ({rating_stats['count']} تقييم)\n"
    else:
        text += "\n⭐ لا توجد تقييمات بعد\n"

    text += f"\n{DIVIDER}\n📊 {hb('تحليل العمل')}\n{DIVIDER}\n"
    text += f"إجمالي الطلبات: {stats['total']}\n"
    text += f"✅ مقبولة: {stats['approved']} | ❌ مرفوضة: {stats['rejected']} | ⏳ معلقة: {stats['pending']}\n"
    text += f"📈 نسبة القبول: {stats['approval_rate']:.0f}%\n"
    text += f"💰 إجمالي الأرباح المحققة له: {fmt_money(stats['total_profit'])}\n"

    if recent_reqs:
        text += f"\n{DIVIDER}\n📋 {hb('آخر الطلبات')}\n{DIVIDER}\n"
        status_icons = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}
        for r in recent_reqs:
            icon = status_icons.get(r['status'], '•')
            rname = r['first_name'] or (f"@{r['username']}" if r['username'] else str(r['user_id']))
            text += f"{icon} #{r['req_id']} | {html_escape(rname)} | {html_escape(str(r['created_at'])[:10])}\n"

    if recent_warnings:
        text += f"\n{DIVIDER}\n⚠️ {hb('آخر التنبيهات/البلاغات')}\n{DIVIDER}\n"
        type_label = {'warning': '⚠️ تنبيه', 'notice': '📨 بلاغ'}
        for w in recent_warnings:
            text += f"{type_label.get(w['warning_type'], '•')} ({html_escape(str(w['created_at'])[:10])}): {html_escape(w['reason'] or '')}\n"

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("📋 كل الطلبات", callback_data=f"admin_broker_reqs_{broker_uid}", style="primary"))
    keyboard.row(
        types.InlineKeyboardButton("⚠️ تنبيه", callback_data=f"admin_broker_warn_{broker_uid}", style="danger"),
        types.InlineKeyboardButton("📨 إرسال بلاغ", callback_data=f"admin_broker_notice_{broker_uid}", style="primary")
    )
    if is_banned:
        keyboard.row(types.InlineKeyboardButton("🔓 رفع حظر الحساب", callback_data=f"admin_broker_unban_{broker_uid}", style="primary"))
    else:
        keyboard.row(types.InlineKeyboardButton("🚫 حظر الحساب", callback_data=f"admin_broker_ban_{broker_uid}", style="danger"))
    keyboard.row(types.InlineKeyboardButton("🗑️ حذف الوسيط", callback_data=f"admin_broker_delete_confirm_{broker_uid}", style="danger"))
    keyboard.row(types.InlineKeyboardButton("🤝 قائمة الوسطاء", callback_data="admin_brokers", style="primary"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")


def _show_admin_agent_detail(call, agent_uid, chat_id, message_id):
    """عرض ملف الوكيل الكامل للأدمن: معلوماته، طلباته، تحليل عمله، وأدوات التحكم (تنبيه/بلاغ/حذف/حظر)"""
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT a.user_id, a.name, a.description, a.contact, a.is_active, a.added_at, a.added_by, "
        "u.username, u.first_name FROM agents a LEFT JOIN users u ON a.user_id=u.user_id WHERE a.user_id=?",
        (agent_uid,)
    )
    row = cursor.fetchone()
    if not row:
        safe_answer_callback_query(call.id, "الوكيل غير موجود!", show_alert=True)
        return
    ag = {
        'user_id': row[0], 'name': row[1] or '', 'description': row[2] or '',
        'contact': row[3] or '', 'is_active': row[4], 'added_at': row[5], 'added_by': row[6],
        'username': row[7], 'first_name': row[8]
    }
    is_banned = db.is_banned(agent_uid)
    stats = db.get_agent_full_stats(agent_uid)
    rating_stats = db.get_agent_rating_stats(agent_uid)
    warn_count = db.get_agent_warning_count(agent_uid, 'warning')
    recent_warnings = db.get_agent_warnings(agent_uid, limit=3)
    recent_reqs = db.get_agent_charge_requests(agent_user_id=agent_uid)[:5]

    uname_disp = f"@{ag['username']}" if ag['username'] else (ag['contact'] or "بدون معرف")
    name_disp = hb(ag['name'] or ag['first_name'] or f"وكيل {agent_uid}")

    text = f"{DIVIDER}\n🧑‍💼 {name_disp}\n{DIVIDER}\n\n"
    text += f"🆔 الأيدي: {hc(agent_uid)}\n"
    text += f"👤 المعرف: {html_escape(uname_disp)}\n"
    if ag['description']:
        text += f"📝 الوصف: {html_escape(ag['description'])}\n"
    text += f"📅 أُضيف: {html_escape(str(ag['added_at'])[:16])}\n"
    text += f"⚡ الحالة: {'🟢 نشط' if ag['is_active'] else '🔴 معطّل'}"
    if is_banned:
        text += " | 🚫 الحساب محظور"
    text += "\n"
    if warn_count > 0:
        text += f"⚠️ عدد التنبيهات السابقة: {warn_count}\n"

    if rating_stats['count'] > 0:
        avg = rating_stats['avg']
        full = int(avg)
        stars_str = "⭐" * full + ("✨" if avg - full >= 0.5 else "")
        text += f"\n{stars_str} {avg:.1f}/5 ({rating_stats['count']} تقييم)\n"
    else:
        text += "\n⭐ لا توجد تقييمات بعد\n"

    text += f"\n{DIVIDER}\n📊 {hb('تحليل العمل')}\n{DIVIDER}\n"
    text += f"إجمالي الطلبات: {stats['total']}\n"
    text += f"✅ مقبولة: {stats['approved']} | ❌ مرفوضة: {stats['rejected']} | ⏳ معلقة: {stats['pending']}\n"
    text += f"📈 نسبة القبول: {stats['approval_rate']:.0f}%\n"
    text += f"💵 إجمالي المبالغ المشحونة عبره: {fmt_money(stats['total_charged'])}\n"
    text += f"💰 إجمالي الأرباح المحققة له: {fmt_money(stats['total_profit'])}\n"

    if recent_reqs:
        text += f"\n{DIVIDER}\n📋 {hb('آخر الطلبات')}\n{DIVIDER}\n"
        status_icons = {'pending': '⏳', 'agent_approved': '🟡', 'admin_approved': '✅', 'rejected': '❌'}
        for r in recent_reqs:
            icon = status_icons.get(r['status'], '•')
            rname = r['first_name'] or (f"@{r['username']}" if r['username'] else str(r['user_id']))
            text += f"{icon} #{r['req_id']} | {html_escape(rname)} | {fmt_money(r['amount'])} | {html_escape(str(r['created_at'])[:10])}\n"

    if recent_warnings:
        text += f"\n{DIVIDER}\n⚠️ {hb('آخر التنبيهات/البلاغات')}\n{DIVIDER}\n"
        type_label = {'warning': '⚠️ تنبيه', 'notice': '📨 بلاغ'}
        for w in recent_warnings:
            text += f"{type_label.get(w['warning_type'], '•')} ({html_escape(str(w['created_at'])[:10])}): {html_escape(w['reason'] or '')}\n"

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("📋 كل الطلبات", callback_data=f"admin_agent_reqs_{agent_uid}", style="primary"))
    keyboard.row(
        types.InlineKeyboardButton("⚠️ تنبيه", callback_data=f"admin_agent_warn_{agent_uid}", style="danger"),
        types.InlineKeyboardButton("📨 إرسال بلاغ", callback_data=f"admin_agent_notice_{agent_uid}", style="primary")
    )
    if is_banned:
        keyboard.row(types.InlineKeyboardButton("🔓 رفع حظر الحساب", callback_data=f"admin_agent_unban_{agent_uid}", style="primary"))
    else:
        keyboard.row(types.InlineKeyboardButton("🚫 حظر الحساب", callback_data=f"admin_agent_ban_{agent_uid}", style="danger"))
    keyboard.row(types.InlineKeyboardButton("🗑️ حذف الوكيل", callback_data=f"admin_agent_delete_confirm_{agent_uid}", style="danger"))
    keyboard.row(types.InlineKeyboardButton("🧑‍💼 قائمة الوكلاء", callback_data="admin_agents", style="primary"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")


def check_subscription(user_id):
    subscribed, not_subscribed = db.check_user_subscription(user_id)
    if subscribed:
        return True, None

    keyboard = types.InlineKeyboardMarkup()
    count = len(not_subscribed)
    channels_text = (
        f" يجب الاشتراك في {'القناة التالية' if count == 1 else f'{count} قنوات'} للمتابعة:\n"
        f"{''*28}\n\n"
    )

    for i, channel in enumerate(not_subscribed, 1):
        # بناء الرابط الصحيح
        if channel['channel_username']:
            channel_link = f"https://t.me/{channel['channel_username'].lstrip('@')}"
        else:
            # قناة خاصة — نحوّل الـ ID إلى صيغة c/
            raw_id = str(channel['channel_id'])
            if raw_id.startswith('-100'):
                channel_link = f"https://t.me/c/{raw_id[4:]}"
            elif raw_id.startswith('-'):
                channel_link = f"https://t.me/c/{raw_id[1:]}"
            else:
                channel_link = f"https://t.me/c/{raw_id}"

        safe_title = (channel['channel_title'] or f'قناة {i}').strip()
        channels_text += f"{''} {i}. {safe_title}\n"
        keyboard.row(types.InlineKeyboardButton(
            f" اشترك في {safe_title}", url=channel_link
        , style="primary"))

    channels_text += f"\n{''*28}\n"
    channels_text += " بعد الاشتراك في جميع القنوات اضغط زر التحقق:"
    keyboard.row(types.InlineKeyboardButton(
        "✅ تحقق من الاشتراك", callback_data="check_subscription", style="primary"
    ))
    return False, (channels_text, keyboard)

def create_main_menu_keyboard(user_id):
    keyboard = types.InlineKeyboardMarkup()
    balance = db.get_balance(user_id)
    # ── الرصيد (دائماً في الأعلى)
    keyboard.row(types.InlineKeyboardButton(f"💰 رصيد الحساب: {balance:.2f}$", callback_data="balance", style="primary"))
    # ── المزادات (الوظيفة الأساسية)
    keyboard.row(
        premium_button("📢 نشر مزاد", custom_emoji_key="fire", callback_data="new_auction", style="primary"),
        types.InlineKeyboardButton("📋 عرض المزادات", callback_data="show_auctions", style="primary")
    )
    keyboard.row(
        types.InlineKeyboardButton("📦 مزاداتي", callback_data="my_auctions", style="primary"),
        types.InlineKeyboardButton("🙋 مزايداتي", callback_data="my_bids", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton("🔍 البحث عن مزاد", callback_data="search_auctions", style="primary"))
    # ── المالية
    keyboard.row(
        types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"),
        types.InlineKeyboardButton("📥 شحن الرصيد", callback_data="charge", style="primary")
    )
    # ── الكروت والمسابقات
    free_cards = db.get_user_free_cards_count(user_id)
    cards_label = f"🃏 كروتي ({free_cards})" if free_cards > 0 else "🃏 كروتي"
    keyboard.row(
        types.InlineKeyboardButton(cards_label, callback_data="my_cards", style="primary"),
        types.InlineKeyboardButton("🎯 المسابقات", callback_data="show_contests", style="primary")
    )
    # ── لوحة الوكيل/الوسيط (فقط لمن ينطبق عليه)
    is_ag = db.is_agent(user_id)
    is_br = db.is_broker(user_id)
    if is_ag and is_br:
        keyboard.row(
            types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"),
            types.InlineKeyboardButton("🤝 لوحة الوسيط", callback_data="my_broker_panel", style="primary")
        )
    elif is_ag:
        keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
    elif is_br:
        keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوسيط", callback_data="my_broker_panel", style="primary"))
    # ── الدعم والقوانين
    keyboard.row(
        types.InlineKeyboardButton("🛠️ دعم فني", callback_data="ai_support", style="primary"),
        types.InlineKeyboardButton("📜 القوانين", callback_data="rules", style="primary")
    )
    if user_id == OWNER_ID:
        keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard

def create_auction_type_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    types_list = list(AUCTION_TYPES.items())
    # صفوف بزرين
    for i in range(0, len(types_list) - 1, 2):
        k1, v1 = types_list[i]
        k2, v2 = types_list[i + 1]
        keyboard.row(
            types.InlineKeyboardButton(v1, callback_data=f"type_{k1}", style="primary"),
            types.InlineKeyboardButton(v2, callback_data=f"type_{k2}", style="primary")
        )
    if len(types_list) % 2 != 0:
        k, v = types_list[-1]
        keyboard.row(types.InlineKeyboardButton(v, callback_data=f"type_{k}", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
    return keyboard

def create_categories_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    categories = [
        ("usernames", "معرفات"),
        ("channels", "قنوات"),
        ("groups", "مجموعات"),
        ("bots", "بوتات"),
        ("gifts", "هدايا"),
    ]
    for i in range(0, len(categories), 2):
        row = [types.InlineKeyboardButton(n, callback_data=f"cat_{k}", style="primary") for k, n in categories[i:i+2]]
        keyboard.row(*row)
    keyboard.row(types.InlineKeyboardButton("📂 الكل", callback_data="cat_all", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
    return keyboard

def create_auction_details_keyboard(auction_id, user_id, can_refund=False, buy_now_price=0.0, is_owner=False, is_watching=False):
    keyboard = types.InlineKeyboardMarkup()
    if not is_owner:
        keyboard.row(types.InlineKeyboardButton("🔨 المزايدة الآن", callback_data=f"bid_{auction_id}", style="primary"))
        if buy_now_price and buy_now_price > 0:
            keyboard.row(types.InlineKeyboardButton(
                f" اشتري الآن بـ {buy_now_price:.2f}$",
                callback_data=f"buynow_{auction_id}", style="primary"
            ))
        watch_label = " إلغاء المتابعة" if is_watching else " تابع المزاد"
        watch_cb = f"unwatch_{auction_id}" if is_watching else f"watch_{auction_id}"
        keyboard.row(types.InlineKeyboardButton(watch_label, callback_data=watch_cb, style="primary"))
    # زر مشاركة المزاد — يفتح شاشة تيليجرام لاختيار جهات اتصال خاصة وإرسال المزاد لهم
    try:
        bot_username = get_bot_info().get('username', '')
        if bot_username:
            deep_link = f"https://t.me/{bot_username}?start=auction_{auction_id}"
            auction_info = db.get_auction_by_id(auction_id)
            title = auction_info['title'] if auction_info and auction_info.get('title') else ''
            current_price = auction_info.get('current_price') if auction_info else None
            if title and current_price:
                share_text = f"🔥 مزاد قائم الآن: {title} — السعر الحالي {fmt_money(current_price)}، لا تفوّت الفرصة!"
            elif title:
                share_text = f"🔥 مزاد قائم الآن على: {title} — شارك قبل انتهاء الوقت!"
            else:
                share_text = "🔥 مزاد حصري قائم الآن — اطّلع عليه قبل انتهاء الوقت!"
            share_url = (
                "https://t.me/share/url?url=" + urllib.parse.quote(deep_link, safe="")
                + "&text=" + urllib.parse.quote(share_text, safe="")
            )
            keyboard.row(types.InlineKeyboardButton("📤 مشاركة المزاد لشخص بالخاص", url=share_url, style="primary"))
    except Exception:
        pass
    keyboard.row(types.InlineKeyboardButton("📊 عرض المزايدات", callback_data=f"view_bids_{auction_id}", style="primary"))
    if can_refund:
        keyboard.row(types.InlineKeyboardButton("↩️💰 إرجاع الرصيد", callback_data=f"refund_bid_{auction_id}", style="danger"))
    if is_owner:
        keyboard.row(types.InlineKeyboardButton("⏱ تمديد المزاد", callback_data=f"extend_auction_{auction_id}", style="primary"))
        keyboard.row(types.InlineKeyboardButton("🔄 إعادة نشر بعد الانتهاء", callback_data=f"reauction_{auction_id}", style="primary"))
    keyboard.row(types.InlineKeyboardButton("⚠️ إبلاغ عن المزاد", callback_data=f"report_auction_{auction_id}", style="danger"))
    keyboard.row(types.InlineKeyboardButton("🗂️ للتصنيفات", callback_data="show_auctions", style="primary"))
    return keyboard

def create_admin_keyboard():
    """القائمة الرئيسية للوحة الإدارة — أقسام منظمة، كل قسم يحتوي أدواته الكاملة (تحكم كامل)"""
    keyboard = types.InlineKeyboardMarkup()

    def _count(query):
        try:
            cur = db.conn.cursor()
            cur.execute(query)
            r = cur.fetchone()
            return r[0] or 0
        except Exception:
            return 0

    def _label(base, count):
        return f"{base} ({count})" if count > 0 else base

    pending_auctions = _count("SELECT COUNT(*) FROM auctions WHERE status='pending'")
    auction_reports = _count("SELECT COUNT(*) FROM auction_reports")
    auctions_badge = pending_auctions + auction_reports

    pending_withdrawals = _count("SELECT COUNT(*) FROM withdrawal_requests WHERE status='pending'")
    pending_charges = _count("SELECT COUNT(*) FROM withdrawal_requests WHERE status='pending_charge'")
    pending_binance = _count("SELECT COUNT(*) FROM binance_payments WHERE status='pending'")
    finance_badge = pending_withdrawals + pending_charges + pending_binance

    agent_ops = _count("SELECT COUNT(*) FROM agent_pending_ops WHERE status='pending'")
    agent_charge_pending = _count("SELECT COUNT(*) FROM agent_charge_requests WHERE status IN ('pending','agent_approved')")
    agent_reports = _count("SELECT COUNT(*) FROM agent_reports WHERE status='pending'")
    broker_pending_reqs = _count("SELECT COUNT(*) FROM broker_requests WHERE status='pending'")
    partners_badge = agent_ops + agent_charge_pending + agent_reports + broker_pending_reqs

    open_tickets = _count("SELECT COUNT(*) FROM support_tickets WHERE status='open'")
    try:
        ai_stats_tmp = db.get_ai_stats()
        unresolved_count = ai_stats_tmp.get('unknown', 0) + ai_stats_tmp.get('negative', 0)
    except Exception:
        unresolved_count = 0
    content_badge = open_tickets + unresolved_count

    keyboard.row(types.InlineKeyboardButton(_label("📊 المزادات والإحصائيات", auctions_badge), callback_data="admin_cat_auctions", style="primary"))
    keyboard.row(types.InlineKeyboardButton("👥 المستخدمون", callback_data="admin_cat_users", style="primary"))
    keyboard.row(types.InlineKeyboardButton(_label("💰 المالية والمدفوعات", finance_badge), callback_data="admin_cat_finance", style="primary"))
    keyboard.row(types.InlineKeyboardButton(_label("🧑‍💼 الوكلاء والوسطاء", partners_badge), callback_data="admin_cat_partners", style="primary"))
    keyboard.row(types.InlineKeyboardButton("📡 القنوات والبث", callback_data="admin_cat_channels", style="primary"))
    keyboard.row(types.InlineKeyboardButton(_label("🎯 المسابقات والمحتوى", content_badge), callback_data="admin_cat_content", style="primary"))
    keyboard.row(types.InlineKeyboardButton("⚙️ الإعدادات العامة", callback_data="admin_cat_settings", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
    return keyboard


def create_admin_auctions_keyboard():
    keyboard = types.InlineKeyboardMarkup()

    def _c(q):
        try:
            cur = db.conn.cursor(); cur.execute(q); return cur.fetchone()[0] or 0
        except Exception:
            return 0

    pending_auctions = _c("SELECT COUNT(*) FROM auctions WHERE status='pending'")
    auction_reports = _c("SELECT COUNT(*) FROM auction_reports")
    keyboard.row(types.InlineKeyboardButton("📈 الإحصائيات", callback_data="admin_stats", style="primary"))
    keyboard.row(
        types.InlineKeyboardButton(f"⏳ المزادات المعلقة ({pending_auctions})" if pending_auctions > 0 else "⏳ المزادات المعلقة", callback_data="admin_pending", style="primary"),
        types.InlineKeyboardButton("🛡️ إدارة المزادات", callback_data="admin_manage_auctions", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton(f"🚨 بلاغات المزادات ({auction_reports})" if auction_reports > 0 else "🚨 بلاغات المزادات", callback_data="admin_auction_reports", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏆 Leaderboard البائعين", callback_data="top_sellers", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard


def create_admin_users_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("👥 المستخدمون", callback_data="admin_users", style="primary"),
        types.InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search_user", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton("🪪 تفاصيل مستخدم", callback_data="admin_user_detail", style="primary"))
    keyboard.row(
        types.InlineKeyboardButton("➕💰 إضافة رصيد", callback_data="admin_direct_add_balance", style="primary"),
        types.InlineKeyboardButton("➖💰 خصم رصيد", callback_data="admin_direct_deduct_balance", style="danger")
    )
    keyboard.row(
        types.InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban_user", style="danger"),
        types.InlineKeyboardButton("🔓 رفع الحظر", callback_data="admin_unban_user", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard


def create_admin_finance_keyboard():
    keyboard = types.InlineKeyboardMarkup()

    def _c(q):
        try:
            cur = db.conn.cursor(); cur.execute(q); return cur.fetchone()[0] or 0
        except Exception:
            return 0

    pending_binance = _c("SELECT COUNT(*) FROM binance_payments WHERE status='pending'")
    pending_withdrawals = _c("SELECT COUNT(*) FROM withdrawal_requests WHERE status='pending'")
    pending_charges = _c("SELECT COUNT(*) FROM withdrawal_requests WHERE status='pending_charge'")

    keyboard.row(
        types.InlineKeyboardButton("🎟️ إنشاء كود شحن", callback_data="create_code", style="primary"),
        types.InlineKeyboardButton("📃 عرض الأكواد", callback_data="list_codes", style="primary")
    )
    keyboard.row(
        types.InlineKeyboardButton("💳 مدفوعات Binance", callback_data="admin_binance_payments", style="primary"),
        types.InlineKeyboardButton(f"✔️💳 تأكيد Binance ({pending_binance})" if pending_binance > 0 else "✔️💳 تأكيد Binance", callback_data="admin_confirm_binance", style="primary")
    )
    keyboard.row(
        types.InlineKeyboardButton("⭐ مدفوعات النجوم", callback_data="admin_stars_payments", style="primary"),
        types.InlineKeyboardButton(f"📤 طلبات السحب ({pending_withdrawals})" if pending_withdrawals > 0 else "📤 طلبات السحب", callback_data="admin_pending_withdrawals", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton(f"📥 طلبات الشحن اليدوي ({pending_charges})" if pending_charges > 0 else "📥 طلبات الشحن اليدوي", callback_data="admin_pending_charges", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard


def create_admin_partners_keyboard():
    keyboard = types.InlineKeyboardMarkup()

    def _c(q):
        try:
            cur = db.conn.cursor(); cur.execute(q); return cur.fetchone()[0] or 0
        except Exception:
            return 0

    broker_pending = _c("SELECT COUNT(*) FROM broker_requests WHERE status='pending'")
    agent_reports_pending = _c("SELECT COUNT(*) FROM agent_reports WHERE status='pending'")
    agent_ops_pending = _c("SELECT COUNT(*) FROM agent_pending_ops WHERE status='pending'")
    agent_charge_pending = _c("SELECT COUNT(*) FROM agent_charge_requests WHERE status IN ('pending','agent_approved')")

    keyboard.row(
        types.InlineKeyboardButton("🧑‍💼 إدارة الوكلاء", callback_data="admin_agents", style="primary"),
        types.InlineKeyboardButton(f"🤝 إدارة الوسطاء ({broker_pending})" if broker_pending > 0 else "🤝 إدارة الوسطاء", callback_data="admin_brokers", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton(f"🚨 بلاغات الوكلاء ({agent_reports_pending})" if agent_reports_pending > 0 else "🚨 بلاغات الوكلاء", callback_data="admin_agent_reports", style="primary"))
    keyboard.row(types.InlineKeyboardButton(f"⏳ طلبات الوكلاء المعلقة ({agent_ops_pending})" if agent_ops_pending > 0 else "⏳ طلبات الوكلاء المعلقة", callback_data="admin_agent_pending_ops", style="primary"))
    keyboard.row(types.InlineKeyboardButton(f"📨 طلبات شحن عبر الوكلاء ({agent_charge_pending})" if agent_charge_pending > 0 else "📨 طلبات شحن عبر الوكلاء", callback_data="admin_agent_charge_pending", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard


def create_admin_channels_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("📣 بث إعلان", callback_data="admin_broadcast", style="primary"))
    keyboard.row(
        types.InlineKeyboardButton("📡 قنوات البث", callback_data="manage_broadcast_channels", style="primary"),
        types.InlineKeyboardButton("🔔 قنوات الاشتراك", callback_data="manage_subscription_channels", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton("🔄 تحديث المشتركين", callback_data="update_subscribers", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard


def create_admin_content_keyboard():
    keyboard = types.InlineKeyboardMarkup()

    def _c(q):
        try:
            cur = db.conn.cursor(); cur.execute(q); return cur.fetchone()[0] or 0
        except Exception:
            return 0

    open_tickets = _c("SELECT COUNT(*) FROM support_tickets WHERE status='open'")
    keyboard.row(types.InlineKeyboardButton("🎯 إدارة المسابقات", callback_data="admin_contests", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏷️ إدارة الملصقات", callback_data="admin_stickers", style="primary"))
    keyboard.row(types.InlineKeyboardButton(f"🎫 تذاكر الدعم ({open_tickets})" if open_tickets > 0 else "🎫 تذاكر الدعم", callback_data="admin_support_tickets", style="primary"))
    try:
        ai_stats_tmp = db.get_ai_stats()
        unresolved_count = ai_stats_tmp.get('unknown', 0) + ai_stats_tmp.get('negative', 0)
        ai_label = f"🧠 تطوير الذكاء الاصطناعي ({unresolved_count})" if unresolved_count > 0 else "🧠 تطوير الذكاء الاصطناعي"
    except Exception:
        ai_label = "🧠 تطوير الذكاء الاصطناعي"
    keyboard.row(types.InlineKeyboardButton(ai_label, callback_data="admin_ai_learning", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard


def create_admin_settings_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    duration = db.get_auction_duration()
    verify_enabled = db.is_verification_enabled()
    verify_label = "الحماية: مفعّلة " if verify_enabled else "الحماية: معطّلة "
    try:
        cur_lf = db.conn.cursor()
        cur_lf.execute("SELECT value FROM bot_settings WHERE key='listing_fee'")
        lf_row = cur_lf.fetchone()
        lf_val = float(lf_row[0]) if lf_row else 0.01
    except Exception:
        lf_val = 0.01
    keyboard.row(types.InlineKeyboardButton(f"مدة المزاد: {duration} ساعة", callback_data="admin_set_duration", style="primary"))
    keyboard.row(types.InlineKeyboardButton(f"رسوم النشر: {lf_val:.3f}$", callback_data="admin_set_listing_fee", style="primary"))
    keyboard.row(types.InlineKeyboardButton(verify_label, callback_data="admin_toggle_verification", style="primary"))
    keyboard.row(types.InlineKeyboardButton("⚙️ إعدادات العمولات", callback_data="admin_commissions", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard


def create_user_management_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("➕💰 إضافة رصيد", callback_data="admin_add_balance", style="primary"),
        types.InlineKeyboardButton("➖💰 خصم رصيد", callback_data="admin_deduct_balance", style="danger")
    )
    keyboard.row(
        types.InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="admin_list_users", style="primary"),
        types.InlineKeyboardButton("🔍 بحث مستخدم", callback_data="admin_search_user", style="primary")
    )
    keyboard.row(
        types.InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban_user", style="danger"),
        types.InlineKeyboardButton("🔓 رفع الحظر", callback_data="admin_unban_user", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard

def create_broadcast_channels_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("➕📡 إضافة قناة بث", callback_data="add_broadcast_channel", style="primary"),
        types.InlineKeyboardButton("🗑️📡 حذف قناة بث", callback_data="delete_broadcast_channel", style="danger")
    )
    keyboard.row(types.InlineKeyboardButton("📡 عرض قنوات البث", callback_data="list_broadcast_channels", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard

def create_subscription_channels_management_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("➕🔔 إضافة قناة اشتراك", callback_data="add_subscription_channel", style="primary"),
        types.InlineKeyboardButton("🗑️🔔 حذف قناة اشتراك", callback_data="delete_subscription_channel", style="danger")
    )
    keyboard.row(types.InlineKeyboardButton("🔔 عرض قنوات الاشتراك", callback_data="list_subscription_channels", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    return keyboard

def create_auctions_list_keyboard(auctions, category, platform=None):
    keyboard = types.InlineKeyboardMarkup()
    if not auctions:
        if platform:
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمنصات", callback_data=f"cat_{category}", style="primary"))
        else:
            keyboard.row(types.InlineKeyboardButton("🗂️ للتصنيفات", callback_data="show_auctions", style="primary"))
        return keyboard
    for auction in auctions[:10]:
        auction_title = auction['title'][:20] if auction['title'] else f"مزاد #{auction['auction_id']}"
        keyboard.row(types.InlineKeyboardButton(f"#{auction['auction_id']} - {auction_title}", callback_data=f"auction_details_{auction['auction_id']}", style="primary"))
    if platform:
        keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمنصات", callback_data=f"cat_{category}", style="primary"))
    else:
        keyboard.row(types.InlineKeyboardButton("🗂️ للتصنيفات", callback_data="show_auctions", style="primary"))
    return keyboard

def calculate_commission(sale_price, is_urgent=False):
    rate = URGENT_COMMISSION_RATE if is_urgent else COMMISSION_RATE
    return sale_price * rate

def calculate_transfer_commission(amount):
    return amount * TRANSFER_COMMISSION_RATE

def distribute_auction_funds(auction_id, sale_price, seller_id, buyer_id):
    try:
        # تحقق أن التوزيع لم يتم مسبقاً (حماية من double distribution)
        auction_check = db.get_auction_by_id(auction_id)
        if auction_check and auction_check.get('commission_paid'):
            logger.warning(f"distribute_auction_funds: auction #{auction_id} already distributed, skipping.")
            return None
        is_urgent = bool(auction_check.get('is_urgent')) if auction_check else False
        commission = calculate_commission(sale_price, is_urgent=is_urgent)
        seller_amount = sale_price - commission
        # كل دالة من هذي تقفل db._lock داخلياً بنفسها — لا تُستدعى من داخل with db._lock
        db.update_balance(seller_id, seller_amount)
        db.add_transaction(seller_id, seller_amount, "auction_sale", f"بيع مزاد #{auction_id}")
        db.add_revenue(auction_id, commission, "commission")
        db.mark_commission_paid(auction_id)
        return {"seller_amount": seller_amount, "commission": commission, "buyer_paid": sale_price}
    except Exception as e:
        logger.error(f"Error distributing auction funds: {e}")
        return None

def refund_starting_price_if_needed(auction_info):
    """إرجاع سعر البدء للمالك إذا انتهى المزاد بدون مزايدين"""
    starting_price = auction_info.get('starting_price', 0.0)
    if starting_price <= 0:
        return
    auction_id = auction_info['auction_id']
    # تحقق من عدم وجود transaction استرداد مسبق لهذا المزاد
    with db._lock:
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id=? AND type='starting_price_refund' AND description LIKE ?",
            (auction_info['user_id'], f"%#{auction_id}%")
        )
        already_refunded = cursor.fetchone()[0] > 0
    if already_refunded:
        return
    # كل دالة من هذي تقفل db._lock داخلياً بنفسها — لا تُستدعى من داخل with db._lock
    db.update_balance(auction_info['user_id'], starting_price)
    db.add_transaction(
        auction_info['user_id'], starting_price,
        "starting_price_refund",
        f"إرجاع سعر البدء - مزاد #{auction_id} (بدون مزايدين)"
    )
    try:
        bot.send_message(
            auction_info['user_id'],
            "\n".join([
                f"🔄 {hb('تم إرجاع سعر البدء')}",
                DIVIDER,
                f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                f"💰 {hb('المبلغ المُعاد:')} {fmt_money(starting_price)}",
                "",
                "😔 انتهى المزاد بدون أي مزايدين",
            ]),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error notifying owner of refund: {e}")

def notify_auction_watchers(auction_id, new_bidder_id, new_price):
    """إشعار متابعي المزاد عند وصول مزايدة جديدة"""
    try:
        watchers = db.get_auction_watchers(auction_id)
        auction_info = db.get_auction_by_id(auction_id)
        if not auction_info:
            return
        for wuid in watchers:
            if wuid == new_bidder_id:
                continue  # لا نُشعر من يزايد نفسه
            try:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton(
                    "🔨 المزايدة الآن", callback_data=f"bid_{auction_id}", style="primary"
                ))
                bot.send_message(
                    wuid,
                    f"🔔 {hb('مزايدة جديدة على مزاد تتابعه!')}\n\n"
                    f"📦 {html_escape(auction_info['title'])}\n"
                    f"💰 {hb('السعر الجديد:')} {fmt_money(new_price)}\n"
                    f"🆔 {hc('#' + str(auction_id))}",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception:
                pass
    except Exception as e:
        logger.error(f"notify_auction_watchers error: {e}")

def notify_outbid(auction_id, old_bidder_id, new_price):
    """إشعار المزايد السابق أن أحداً تجاوزه"""
    if not old_bidder_id:
        return
    try:
        auction_info = db.get_auction_by_id(auction_id)
        if not auction_info:
            return
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(types.InlineKeyboardButton(
            "🔥 زايد أكثر!", callback_data=f"bid_{auction_id}", style="primary"
        ))
        bot.send_message(
            old_bidder_id,
            f"⚡ {hb('تجاوزك أحدهم!')}\n\n"
            f"📦 {html_escape(auction_info['title'])}\n"
            f"💰 {hb('السعر الحالي:')} {fmt_money(new_price)}\n"
            f"⏳ لا تخسر المزاد — زايد الآن!\n"
            f"🆔 {hc('#' + str(auction_id))}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"notify_outbid error: {e}")

def check_auction_ended(auction_id):
    """يتحقق من انتهاء وقت المزاد وينهيه (بيع أو انتهاء بدون مزايدات)"""
    auction_info = db.get_auction_by_id(auction_id)
    if not auction_info or auction_info['status'] != 'active':
        return
    ends_at = db.parse_datetime(auction_info['ends_at'])
    if not ends_at:
        logger.warning(f"check_auction_ended: فشل تحليل ends_at للمزاد #{auction_id}")
        return
    if ends_at <= datetime.now():
        if auction_info['current_bidder']:
            complete_auction_sale(auction_id)
        else:
            # استخدم expire_auction التي تتحقق status='active' لمنع double expire
            if db.expire_auction(auction_id):
                refund_starting_price_if_needed(auction_info)
                try:
                    bot.send_message(
                        auction_info['user_id'],
                        "\n".join([
                            f"🏁 {hb('انتهى المزاد')}  {hc('#' + str(auction_id))}",
                            DIVIDER,
                            f"📦 {hb('المنتج:')} {html_escape(auction_info['title'])}",
                            f"🎯 {html_escape(auction_info['target'])}",
                            DIVIDER,
                            "😔 لم تتم أي مزايدة على مزادك",
                            "🔁 يمكنك نشر المزاد مرة أخرى",
                        ]),
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Error notifying auction owner: {e}")

def complete_auction_sale(auction_id):
    auction_info = db.get_auction_by_id(auction_id)
    if not auction_info or auction_info['status'] != 'active':
        return
    sold_to = auction_info['current_bidder']
    sold_price = auction_info['current_price']
    if not sold_to:
        return
    # تغيير الحالة فوراً لمنع التنفيذ المزدوج (complete_auction تقفل داخلياً بنفسها)
    if not db.complete_auction(auction_id, sold_to, sold_price):
        # ثريد آخر أنهى المزاد أولاً أو لم يعد active — لا تكرر المعالجة
        return
    distribution = distribute_auction_funds(auction_id, sold_price, auction_info['user_id'], sold_to)
    if not distribution:
        logger.error(f"Failed to distribute funds for auction #{auction_id}")
        return
    try:
        seller = db.get_user(auction_info['user_id'])
        starting_price = auction_info.get('starting_price', 0.0)
        bot.send_message(
            auction_info['user_id'],
            "\n".join([
                f"🎉 {hb('تم بيع مزادك!')}  {hc('#' + str(auction_id))}",
                DIVIDER,
                f"📦 {hb('المنتج:')} {html_escape(auction_info['title'])}",
                f"💰 {hb('سعر البيع:')} {fmt_money(sold_price)}",
                f"🆔 {hb('المشتري:')} {hc('ID ' + str(sold_to))}",
                DIVIDER,
                f"💵 {hb('تفاصيل التوزيع')}",
                hquote(
                    f"سعر البيع: {fmt_money(sold_price)}\n"
                    f"العمولة ({COMMISSION_RATE*100:.1f}%): {fmt_money(distribution['commission'])}\n"
                    f"صافي المبلغ: {fmt_money(distribution['seller_amount'])}"
                ),
                "",
                "✅ تم إضافة المبلغ إلى رصيدك",
                "📩 تواصل مع المشتري لتسليم المنتج",
            ]),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error notifying auction owner: {e}")
    buyer = db.get_user(sold_to)
    buyer_name = f"@{buyer['username']}" if buyer and buyer['username'] else f"ID {sold_to}"
    try:
        seller_contact = f"@{seller['username']}" if seller and seller['username'] else f"ID {auction_info['user_id']}"
        bot.send_message(
            sold_to,
            "\n".join([
                f"🏆 {tg_emoji('success','✅')} {hb('تهانينا! لقد فزت بالمزاد')}  {hc('#' + str(auction_id))}",
                DIVIDER,
                f"📦 {hb('المنتج:')} {html_escape(auction_info['title'])}",
                f"🎯 {hb('الهدف:')} {html_escape(auction_info['target'])}",
                f"💰 {hb('سعر الشراء:')} {fmt_money(sold_price)}",
                DIVIDER,
                f"📩 {hb('تواصل مع البائع لاستلام المنتج:')}",
                html_escape(seller_contact),
            ]),
            parse_mode="HTML"
        )
        win_sticker = db.get_random_sticker("auction_win")
        if win_sticker:
            try:
                bot.send_sticker(sold_to, win_sticker)
            except Exception as e:
                logger.warning(f"تعذر إرسال ملصق الفوز إلى {sold_to}: {e}")
    except Exception as e:
        logger.error(f"Error notifying buyer: {e}")
    try:
        bot.send_message(
            OWNER_ID,
            "\n".join([
                f"💼 {hb('تم بيع المزاد')}  {hc('#' + str(auction_id))}",
                DIVIDER,
                f"👤 {hb('البائع:')} @{html_escape(seller['username'] if seller and seller['username'] else 'مستخدم')} ({hc('ID: ' + str(auction_info['user_id']))})",
                f"👤 {hb('المشتري:')} @{html_escape(buyer['username'] if buyer and buyer['username'] else 'مستخدم')} ({hc('ID: ' + str(sold_to))})",
                f"📦 {hb('المنتج:')} {html_escape(auction_info['title'])}",
                DIVIDER,
                f"💰 {hb('سعر البيع:')} {fmt_money(sold_price)}",
                f"🧾 {hb('العمولة:')} {fmt_money(distribution['commission'])}",
                f"💵 {hb('صافي البائع:')} {fmt_money(distribution['seller_amount'])}",
            ]),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error notifying owner: {e}")
    bids = db.get_auction_bids(auction_id)
    for bid in bids:
        if bid['user_id'] != sold_to:
            db.refund_bid(bid['bid_id'])
            db.add_transaction(bid['user_id'], bid['amount'], "bid_refund", f"استرداد مزايدة مزاد #{auction_id}")
            try:
                bot.send_message(
                    bid['user_id'],
                    "\n".join([
                        f"↩️ {hb('تم استرداد مزايدتك')}",
                        DIVIDER,
                        f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                        f"💰 {hb('المبلغ المسترد:')} {fmt_money(bid['amount'])}",
                        "✅ تم إضافة المبلغ إلى رصيدك",
                        DIVIDER,
                        f"🏆 {hb('الفائز بالمنتج:')} {html_escape(buyer_name)}",
                    ]),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error notifying bidder: {e}")
    # ← طلب تقييم البائع من المشتري بعد دقيقتين
    def _send_rating_request():
        time.sleep(120)
        try:
            rating_kb = types.InlineKeyboardMarkup()
            rating_kb.row(
                types.InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_{auction_id}_5", style="primary"),
                types.InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rate_{auction_id}_4", style="primary"),
            )
            rating_kb.row(
                types.InlineKeyboardButton("⭐⭐⭐", callback_data=f"rate_{auction_id}_3", style="primary"),
                types.InlineKeyboardButton("⭐⭐", callback_data=f"rate_{auction_id}_2", style="primary"),
                types.InlineKeyboardButton("⭐", callback_data=f"rate_{auction_id}_1", style="danger"),
            )
            bot.send_message(
                sold_to,
                "\n".join([
                    f"⭐ {hb('قيّم تجربتك مع البائع!')}",
                    DIVIDER,
                    f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                    f"📦 {hb('المنتج:')} {html_escape(auction_info.get('title','') or '')}",
                    "",
                    "كيف كانت تجربتك مع البائع؟",
                ]),
                reply_markup=rating_kb, parse_mode="HTML"
            )
        except Exception:
            pass
    threading.Thread(target=_send_rating_request, daemon=True).start()
    # ← تحديث رسائل القنوات بالفائز وحذفها بعد 5 دقائق
    winner_display = buyer_name if buyer_name else f"ID {sold_to}"
    finalize_auction_broadcast(auction_id, winner_name=winner_display)

def transfer_money_between_users(from_user_id, to_user_id, amount, description=""):
    try:
        commission = calculate_transfer_commission(amount)
        net_amount = amount - commission
        with db._lock:
            from_balance = db.get_balance(from_user_id)
            if from_balance < amount:
                return False, "رصيدك غير كافي!"
            db.update_balance(from_user_id, -amount)
            db.add_transaction(from_user_id, -amount, "transfer_sent", f"تحويل إلى المستخدم {to_user_id}")
            db.update_balance(to_user_id, net_amount)
            db.add_transaction(to_user_id, net_amount, "transfer_received", f"تحويل من المستخدم {from_user_id}")
            db.add_revenue(None, commission, "transfer_commission")
            db.add_money_transfer(from_user_id, to_user_id, amount, commission, net_amount, description)
        return True, f"تم التحويل بنجاح! المبلغ المرسل: {amount:.2f}$، العمولة: {commission:.2f}$، المبلغ المستلم: {net_amount:.2f}$"
    except Exception as e:
        logger.error(f"Error transferring money: {e}")
        return False, "حدث خطأ أثناء التحويل!"

def get_subscription_channel_info(channel_id):
    try:
        chat = bot.get_chat(channel_id)
        channel_title = chat.title
        channel_username = chat.username
        try:
            member_count = bot.get_chat_member_count(channel_id)
        except:
            member_count = 0
        return {'channel_id': channel_id, 'channel_title': channel_title, 'channel_username': channel_username, 'member_count': member_count, 'success': True}
    except Exception as e:
        logger.error(f"Error getting channel info: {e}")
        return {'success': False, 'error': str(e)}

@bot.message_handler(commands=['start'])
def start_command(message):
    user = message.from_user
    # استخراج معامل الـ deep link 
    args = message.text.split(' ')
    deep_link_param = args[1] if len(args) > 1 else None

    # تسجيل المستخدم أولاً (أو تحديثه) 
    is_new_user = db.add_user(user.id, user.username, user.first_name, user.last_name)

    # إشعار المالك عند دخول مستخدم جديد 
    if is_new_user:
        try:
            total_users = len(db.get_all_users())
            owner_msg = (
                f" *مستخدم جديد انضم للبوت!*\n\n"
                f"الاسم: {user.first_name or ''} {user.last_name or ''}\n"
                f"الأيدي: `{user.id}`\n"
                f"المعرف: @{user.username if user.username else 'بدون معرف'}\n"
                f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"إجمالي المستخدمين: {total_users}"
            )
            bot.send_message(OWNER_ID, owner_msg, parse_mode="Markdown")
            db.mark_user_notified(user.id)
        except Exception as e:
            logger.error(f"Error notifying owner about new user: {e}")

    # التحقق من الاشتراك الإجباري — مع حفظ الـ deep link لإكماله بعد الاشتراك
    subscribed, sub_result = check_subscription(user.id)
    if not subscribed:
        # حفظ الـ deep link في الـ state حتى لا يضيع بعد الاشتراك
        if deep_link_param:
            db.set_user_state(user.id, "pending_deep_link", {"deep_link_param": deep_link_param})
        channels_text, sub_keyboard = sub_result
        bot.send_message(
            message.chat.id,
            f"مرحباً {user.first_name}!\n\n"
            f"يجب الاشتراك في القنوات التالية للمتابعة:\n\n"
            f"{channels_text}",
            reply_markup=sub_keyboard
        )
        return

    # معالجة رابط الإحالة
    if deep_link_param and deep_link_param.startswith('ref_'):
        referrer_id_str = deep_link_param.replace('ref_', '')
        try:
            referrer_id = int(referrer_id_str)
            if is_new_user and referrer_id != user.id:
                ok, card_number = db.register_referral(referrer_id, user.id)
                if ok:
                    # إشعار صاحب الرابط
                    referrer_info = db.get_user(referrer_id)
                    r_name = f"@{referrer_info['username']}" if referrer_info and referrer_info['username'] else f"ID {referrer_id}"
                    try:
                        bot.send_message(
                            referrer_id,
                            f" *حصلت على كارت جديد!*\n\n"
                            f"انضم مستخدم جديد عبر رابطك!\n"
                            f"رقم الكارت: `{card_number}`\n\n"
                            f"كل كارت يُشاركك في سحوبات المسابقات ",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
        except (ValueError, Exception) as e:
            logger.warning(f"[REF] خطأ في معالجة الإحالة: {e}")

    # معالجة رابط الهدية 
    if deep_link_param and deep_link_param.startswith('gift_'):
        token = deep_link_param.replace('gift_', '')
        success, result = db.use_gift_link(token, user.id)
        keyboard = create_main_menu_keyboard(user.id)
        if success:
            amount = result
            bot.send_message(message.chat.id, f"تم استلام الهدية!\n\nالمبلغ: {amount:.2f}$\nرصيدك: {db.get_balance(user.id):.2f}$", reply_markup=keyboard)
            try:
                cursor = db.conn.cursor()
                cursor.execute("SELECT from_user_id FROM gift_links WHERE token=?", (token,))
                row = cursor.fetchone()
                if row:
                    sender_id = row[0]
                    receiver_name = f"{user.first_name or ''} (@{user.username})" if user.username else f"{user.first_name or ''} [{user.id}]"
                    bot.send_message(
                        sender_id,
                        f"تم استخدام رابط هديتك!\n\n"
                        f"المبلغ: {amount:.2f}$\n"
                        f"المستلم: {receiver_name}\n"
                        f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
            except Exception as e:
                logger.error(f"Error notifying gift sender: {e}")
            try:
                receiver_name = f"{user.first_name or ''} (@{user.username})" if user.username else f"{user.first_name or ''} [{user.id}]"
                bot.send_message(
                    OWNER_ID,
                    f"استخدام رابط هدية\n\nالمبلغ: {amount:.2f}$\nالمستلم: {receiver_name}\nأيدي المستلم: {user.id}"
                )
            except Exception as e:
                logger.error(f"Error notifying owner about gift link: {e}")
        else:
            bot.send_message(message.chat.id, f"فشل: {result}", reply_markup=keyboard)
        return

    db.clear_user_state(user.id)

    # معالجة deep link مسابقة
    if deep_link_param and deep_link_param.startswith('contest_'):
        try:
            contest_id = int(deep_link_param.replace('contest_', ''))
            c = db.get_contest(contest_id)
            if not c or c['status'] not in ('active', 'scheduled'):
                keyboard = create_main_menu_keyboard(user.id)
                bot.send_message(message.chat.id, "هذه المسابقة لم تعد متاحة.", reply_markup=keyboard)
                return
            participants = db.get_contest_participants_count(contest_id)
            start_dt = db.parse_datetime(c['start_at']) if c['start_at'] else None
            time_info = ""
            if start_dt:
                diff = start_dt - datetime.now()
                if diff.total_seconds() > 0:
                    h = int(diff.total_seconds() // 3600)
                    m2 = int((diff.total_seconds() % 3600) // 60)
                    time_info = f"\n⏰ السحب بعد: {h}:{m2:02d}"
            free_cards = db.get_user_free_cards_count(user.id, contest_id=contest_id)
            text = (
                f"🏆 *{md_escape(c['name'])}*\n\n"
                f"{md_escape(c['description'] or '')}\n\n"
                f"🎁 الجائزة: *{md_escape(_prize_label(c))}*\n"
                f"👥 المشاركون: {participants}"
                f"{time_info}"
            )
            keyboard = types.InlineKeyboardMarkup()
            if c['status'] == 'active' and free_cards > 0:
                keyboard.row(types.InlineKeyboardButton(
                    f" المشاركة بـ {free_cards} كارت",
                    callback_data=f"enter_contest_{contest_id}",
                    style="primary"
                ))
            elif free_cards == 0:
                bot_info = get_bot_info()
                ref_link = f"https://t.me/{bot_info['username']}?start=ref_{user.id}"
                keyboard.row(types.InlineKeyboardButton("🔹 احصل على كروت", url=ref_link, style="primary"))
            keyboard.row(types.InlineKeyboardButton("🎯 المسابقات", callback_data="show_contests", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.send_message(message.chat.id, text, reply_markup=keyboard, parse_mode="Markdown")
            return
        except Exception as e:
            logger.error(f"contest deep link error: {e}")
            keyboard = create_main_menu_keyboard(user.id)
            bot.send_message(message.chat.id, "حدث خطأ، حاول مجدداً.", reply_markup=keyboard)
            return

    # معالجة deep link مزاد 
    if deep_link_param and deep_link_param.startswith('auction_'):
        auction_id = deep_link_param.replace('auction_', '')
        auction_info = db.get_auction_by_id(auction_id)
        if auction_info and auction_info['status'] == 'active':
            check_auction_ended(auction_id)
            auction_info = db.get_auction_by_id(auction_id)
            if auction_info and auction_info['status'] == 'active':
                ends_at = db.parse_datetime(auction_info['ends_at'])
                time_left = ends_at - datetime.now()
                if time_left.total_seconds() > 0:
                    hours_left = time_left.total_seconds() // 3600
                    minutes_left = (time_left.total_seconds() % 3600) // 60
                    user_bids = db.get_user_bids(user.id, auction_id)
                    can_refund = len(user_bids) > 0
                    text = f"تفاصيل المزاد #{auction_info['auction_id']}\n\n{auction_info['title']}\n{auction_info['target']}\nالنوع: {AUCTION_TYPES.get(auction_info['auction_type'], '')}\n"
                    if auction_info['platform']:
                        if auction_info['platform'] == "telegram":
                            text += f"المنصة: تليجرام\n"
                        else:
                            text += f"المنصة: {SOCIAL_PLATFORMS.get(auction_info['platform'], auction_info['platform'])}\n"
                    text += f"\nالسعر الحالي: {auction_info['current_price']:.2f}$\nالسعر الابتدائي: {auction_info['starting_price']:.2f}$\nعدد المزايدات: {auction_info['bids_count']}\nالمتبقي: {int(hours_left)}:{int(minutes_left):02d}\n"
                    if user_bids:
                        text += f"\nلديك {len(user_bids)} مزايدة\nأعلى مزايدة لك: {max([b['amount'] for b in user_bids]):.2f}$\n"
                    is_owner = (auction_info['user_id'] == user.id)
                    keyboard = create_auction_details_keyboard(
                        auction_id, user.id, can_refund,
                        buy_now_price=auction_info.get('buy_now_price', 0.0),
                        is_owner=is_owner
                    )
                    bot.send_message(message.chat.id, text, reply_markup=keyboard)
                    return
        keyboard = create_main_menu_keyboard(user.id)
        bot.send_message(message.chat.id, f"هذا المزاد لم يعد متاحاً أو انتهى.\n\nاختر من القائمة:", reply_markup=keyboard)
        return

    # عرض Onboarding للمستخدمين الجدد 
    if is_new_user or not db.has_completed_onboarding(user.id):
        send_onboarding_page(message.chat.id, user.id, 1)
        return

    # الصفحة الرئيسية العادية 
    balance = db.get_balance(user.id)
    active_count = len(db.get_active_auctions())
    welcome_text = (
        f"*'''  منصة المزادات الرسمية  '''*\n"
        f"\n\n"
        f"اهلاً بك، *{user.first_name}*\n\n"
        f"الرصيد:  `{balance:.2f}$`\n"
        f"المزادات النشطة:  `{active_count}`\n\n"
        f"\n"
        f"المنصة الاولى والموثوقة لبيع وشراء\n"
        f"معرفات وقنوات وبوتات وهدايا تيليجرام"
    )
    keyboard = create_main_menu_keyboard(user.id)
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=keyboard)


def _prize_label(contest):
    """يُرجع نص الجائزة للعرض: prize_description إن وُجد، وإلا المبلغ إن كان > 0، وإلا 'هدية مادية'."""
    desc = (contest.get('prize_description') or '').strip()
    amount = contest.get('prize_amount') or 0
    if desc:
        return f"{desc}" + (f" ({int(amount)}$)" if amount > 0 else "")
    if amount > 0:
        return f"{int(amount)}$"
    return "هدية مادية"

def _generate_prize_code():
    """يولّد كود جائزة من 7 أحرف وأرقام عشوائية"""
    import random as _r, string as _s
    chars = _s.ascii_uppercase + _s.digits
    return ''.join(_r.choices(chars, k=7))

_scheduled_contests = set()  # حماية من جدولة نفس المسابقة مرتين
_scheduled_contests_lock = threading.Lock()

def _schedule_contest_draw(contest_id, start_at):
    """جدولة السحب التلقائي للمسابقة في thread منفصل"""
    with _scheduled_contests_lock:
        if contest_id in _scheduled_contests:
            logger.info(f"_schedule_contest_draw: المسابقة #{contest_id} مجدولة مسبقاً، تجاهل.")
            return
        _scheduled_contests.add(contest_id)
    def _run():
        try:
            delay = (start_at - datetime.now()).total_seconds()
            if delay > 0:
                time.sleep(delay)
            c = db.get_contest(contest_id)
            if not c or c['status'] in ('cancelled', 'completed'):
                return
            cards = db.get_contest_all_cards(contest_id)
            if not cards:
                db.update_contest(contest_id, status='completed')
                # حذف رسائل القنوات بعد 5 دقائق (لا مشاركين)
                no_part_msgs = db.get_contest_channel_messages(contest_id)
                for ch_msg in no_part_msgs:
                    try:
                        bot.edit_message_text(
                            f"🏁 *انتهت المسابقة — {db.get_contest(contest_id)['name'] if db.get_contest(contest_id) else ''}*\n\n"
                            f"😔 لم يشارك أحد في هذه المسابقة.",
                            ch_msg['channel_id'], ch_msg['message_id'], parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                def _del_no_part(msgs, cid):
                    time.sleep(300)
                    for m in msgs:
                        try:
                            bot.delete_message(m['channel_id'], m['message_id'])
                        except Exception:
                            pass
                    db.delete_contest_channel_messages(cid)
                threading.Thread(target=_del_no_part, args=(list(no_part_msgs), contest_id), daemon=True).start()
                try:
                    bot.send_message(OWNER_ID, f"🏆 المسابقة #{contest_id} انتهت بدون مشاركين.")
                except Exception:
                    pass
                return
            winner_card, winner_uid = db.draw_contest_winner(contest_id)
            if not winner_card:
                return
            winner_info = db.get_user(winner_uid)
            winner_name = (f"@{winner_info['username']}" if winner_info and winner_info['username']
                           else (winner_info['first_name'] if winner_info else f"ID {winner_uid}"))
            # توليد كود الجائزة وحفظه
            prize_code = _generate_prize_code()
            db.update_contest(contest_id, winner_prize_code=prize_code)
            prize_label = _prize_label(c)
            # تحديث رسائل كل القنوات ثم حذفها بعد 5 دقائق
            contest_channel_msgs = db.get_contest_channel_messages(contest_id)
            for ch_msg in contest_channel_msgs:
                try:
                    bot.edit_message_text(
                        f"🏆 *انتهت المسابقة — {md_escape(c['name'])}*\n\n"
                        f"🎉 الفائز: {md_escape(winner_name)}\n"
                        f"🎁 الجائزة: {md_escape(prize_label)}\n"
                        f"🃏 الكارت الفائز: `{winner_card}`",
                        ch_msg['channel_id'], ch_msg['message_id'], parse_mode="Markdown"
                    )
                except Exception:
                    pass
            # حذف رسائل المسابقة من القنوات بعد 5 دقائق
            def _delete_contest_msgs(msgs, cid):
                time.sleep(300)
                for m in msgs:
                    try:
                        bot.delete_message(m['channel_id'], m['message_id'])
                    except Exception as e:
                        logger.error(f"Error deleting contest message from channel {m['channel_id']}: {e}")
                db.delete_contest_channel_messages(cid)
            threading.Thread(target=_delete_contest_msgs, args=(list(contest_channel_msgs), contest_id), daemon=True).start()
            # إشعار الفائز
            try:
                claim_kb = types.InlineKeyboardMarkup()
                claim_kb.row(types.InlineKeyboardButton(
                    "📩 مطالبة بالجائزة", callback_data=f"claim_prize_{contest_id}", style="primary"
                ))
                bot.send_message(
                    winner_uid,
                    f"🎉 *مبروك! فزت في مسابقة {md_escape(c['name'])}!*\n\n"
                    f"🃏 الكارت الفائز: `{winner_card}`\n"
                    f"🎁 الجائزة: *{md_escape(prize_label)}*\n\n"
                    f"🔑 *كود جائزتك:* `{prize_code}`\n\n"
                    f"اضغط زر المطالبة أدناه لإرسال طلبك للمالك.\n"
                    f"سيتواصل معك المالك لتسليم الجائزة بعد التحقق من الكود.",
                    parse_mode="Markdown",
                    reply_markup=claim_kb
                )
            except Exception:
                pass
            # إشعار المالك
            try:
                bot.send_message(
                    OWNER_ID,
                    f"🏆 *اكتمل سحب المسابقة #{contest_id}*\n\n"
                    f"الاسم: {md_escape(c['name'])}\n"
                    f"الفائز: {md_escape(winner_name)} (ID: `{winner_uid}`)\n"
                    f"🃏 الكارت: `{winner_card}`\n"
                    f"🎁 الجائزة: *{md_escape(prize_label)}*\n\n"
                    f"🔑 *كود جائزة الفائز:* `{prize_code}`\n\n"
                    f"انتظر مطالبة الفائز لتسليم الجائزة.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"_schedule_contest_draw _run error: {e}")
        finally:
            with _scheduled_contests_lock:
                _scheduled_contests.discard(contest_id)
    threading.Thread(target=_run, daemon=True).start()

def _restore_contest_schedulers():
    """عند تشغيل البوت: أعد جدولة المسابقات المنتظرة"""
    try:
        contests = db.get_all_contests(status='scheduled') + db.get_all_contests(status='active')
        for c in contests:
            if c['start_at']:
                start_dt = db.parse_datetime(c['start_at'])
                if start_dt and start_dt > datetime.now():
                    _schedule_contest_draw(c['contest_id'], start_dt)
    except Exception as e:
        logger.error(f"_restore_contest_schedulers: {e}")


# اكتشاف إضافة البوت لمجموعة جديدة 
@bot.my_chat_member_handler()
def handle_bot_added_to_group(update):
    """يُبلّغ الأدمن فوراً عند إضافة البوت لأي مجموعة"""
    if not update.new_chat_member:
        return
    chat = update.chat
    if chat.type not in ('group', 'supergroup'):
        return
    new_status = update.new_chat_member.status
    grp_chat_id = chat.id
    grp_title = chat.title or "مجموعة"

    if new_status in ('member', 'administrator'):
        is_admin = (new_status == 'administrator')
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(types.InlineKeyboardButton("🔹 تعيين كمجموعة وساطة", callback_data=f"set_broker_group_confirm_{grp_chat_id}", style="primary"))
        keyboard.row(types.InlineKeyboardButton("🔹 تجاهل", callback_data="admin_panel", style="primary"))
        status_icon = "مشرف" if is_admin else "عضو (ارفعه مشرفاً لتفعيل كامل الصلاحيات)"
        try:
            bot.send_message(
                OWNER_ID,
                f" *تم إضافة البوت لمجموعة!*\n\n"
                f"الاسم: *{grp_title}*\n"
                f" Chat ID: `{grp_chat_id}`\n"
                f"الصلاحية: {status_icon}\n\n"
                f"هل تريد تعيين هذه المجموعة كمجموعة الوساطة الخاصة؟",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error notifying owner of bot addition: {e}")

    elif new_status in ('kicked', 'left'):
        # البوت أُزيل من المجموعة
        saved_id = db.get_bot_setting('broker_group_id') or ''
        if saved_id and str(grp_chat_id) == saved_id:
            db.set_bot_setting('broker_group_id', '')
            db.set_bot_setting('broker_group_link', '')
            try:
                bot.send_message(
                    OWNER_ID,
                    f" *تم إزالة البوت من مجموعة الوساطة!*\n\n"
                    f" {grp_title}\n"
                    f" `{grp_chat_id}`\n\n"
                    f"تم حذف المجموعة من الإعدادات تلقائياً.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass


# معالج رسائل مجموعة الوساطة (اكتشاف تلقائي + توجيه للبوت) 
@bot.message_handler(func=lambda m: m.chat.type in ('group', 'supergroup'))
def handle_group_message(message):
    """يلتقط أي رسالة في أي مجموعة:
    1. إذا كان الأدمن في وضع waiting_broker_group_auto_detect → يحفظ chat_id ويُبلغ الأدمن
    2. إذا كانت المجموعة هي مجموعة الوساطة المحفوظة → يوجّه الرسالة للبوت الخاص تلقائياً
    """
    grp_chat_id = message.chat.id
    grp_title = message.chat.title or "مجموعة"
    sender_id = message.from_user.id if message.from_user else None

    # اكتشاف تلقائي عند إعداد مجموعة الوساطة 
    owner_state = db.get_user_state(OWNER_ID)
    if owner_state and owner_state.get('state') == 'waiting_broker_group_auto_detect':
        # تحقق من أن البوت مشرف في المجموعة
        is_admin = False
        try:
            bot_member = bot.get_chat_member(grp_chat_id, get_bot_info()['id'])
            is_admin = bot_member.status in ('administrator', 'creator')
        except Exception:
            pass

        # حفظ المجموعة
        db.set_bot_setting('broker_group_id', str(grp_chat_id))
        db.clear_user_state(OWNER_ID)

        # محاولة جلب رابط دعوة
        invite_link = ''
        if is_admin:
            try:
                invite_link = bot.export_chat_invite_link(grp_chat_id)
                db.set_bot_setting('broker_group_link', invite_link)
            except Exception:
                pass

        # إبلاغ الأدمن
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(types.InlineKeyboardButton("🔹 إعداد المجموعة", callback_data="admin_set_broker_group", style="primary"))
        keyboard.row(types.InlineKeyboardButton("🤝 إدارة الوسطاء", callback_data="admin_brokers", style="primary"))

        admin_msg = (
            f" *تم اكتشاف مجموعة الوساطة تلقائياً!*\n\n"
            f"اسم المجموعة: *{grp_title}*\n"
            f" Chat ID: `{grp_chat_id}`\n"
        )
        if is_admin:
            admin_msg += f"رابط الدعوة: {invite_link}\n\n البوت مشرف — يمكنه إدارة المجموعة."
        else:
            admin_msg += (
                "\n *البوت ليس مشرفاً بعد!*\n"
                "ارفع البوت مشرفاً في المجموعة لتفعيل كامل الصلاحيات:\n"
                "• إرسال رسائل ترحيب تلقائية\n"
                "• جلب رابط دعوة تلقائياً"
            )
        try:
            bot.send_message(OWNER_ID, admin_msg, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error notifying owner of group detection: {e}")
        return # لا نكمل

    # لا يتم توجيه رسائل المجموعة للمستخدمين


@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_state = db.get_user_state(user_id)
    if not user_state or user_state['state'] != 'waiting_phone_for_auction':
        return
    phone = message.contact.phone_number if message.contact else None
    if not phone:
        bot.send_message(chat_id, "لم يتم استقبال رقم الهاتف. حاول مجدداً.")
        return
    db.save_verification(user_id, phone=phone)
    db.set_user_state(user_id, "waiting_location_for_auction", {"phone": phone})
    # request_location يعمل فقط في ReplyKeyboardMarkup
    reply_kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    reply_kb.add(types.KeyboardButton("📍 مشاركة موقعي", request_location=True, style="primary"))
    bot.send_message(
        chat_id,
        "تم استقبال رقم هاتفك!\n\n"
        "الآن يرجى مشاركة موقعك الحالي.\n\n"
        "اضغط الزر أدناه لمشاركة الموقع.",
        reply_markup=reply_kb
    )

@bot.message_handler(content_types=['location'])
def handle_location(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_state = db.get_user_state(user_id)
    if not user_state or user_state['state'] != 'waiting_location_for_auction':
        return
    lat = message.location.latitude if message.location else None
    lon = message.location.longitude if message.location else None
    phone = user_state['data'].get('phone') if user_state.get('data') else None
    db.save_verification(user_id, phone=phone, lat=lat, lon=lon)
    db.clear_user_state(user_id)
    db.set_user_state(user_id, "choosing_auction_type")
    keyboard = create_auction_type_keyboard()
    # إزالة ReplyKeyboard أولاً ثم عرض InlineKeyboard
    bot.send_message(
        chat_id,
        "تم التحقق من هويتك بنجاح!\n\nالآن يمكنك نشر مزادك.\nاختر نوع المزاد:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.send_message(chat_id, "اختر نوع المزاد:", reply_markup=keyboard)



# 
# نظام الترحيب (Onboarding) - صفحات متعددة
# 

ONBOARDING_PAGES = {
    1: {
        "title": "مرحباً بك في منصة المزادات",
        "text": (
            "انضممت للمنصة الاولى والموثوقة في العراق\n"
            "لبيع وشراء اصول تيليجرام بالمزاد.\n\n"
            "\n\n"
            "ما الذي يمكنك بيعه وشراؤه هنا؟\n\n"
            "· معرفات تيليجرام المميزة (@username)\n"
            "· القنوات والمجموعات بأعضائها\n"
            "· معرفات البوتات (@botusername)\n"
            "· هدايا تيليجرام النادرة والمحدودة\n\n"
            "\n\n"
            "نظام مزايدة شفاف وآمن — رصيدك محجوز\n"
            "حتى اكتمال الصفقة ثم يُحرَّر فوراً."
        )
    },
    2: {
        "title": "ازرار القائمة الرئيسية",
        "text": (
            "كل زر في القائمة وظيفته:\n\n"
            "رصيد الحساب\n"
            "يعرض رصيدك الحالي بالدولار الأمريكي\n\n"
            "نشر مزاد\n"
            "ضع منتجك للبيع بالمزايدة خلال ثوانٍ\n\n"
            "عرض المزادات\n"
            "تصفح كل المزادات النشطة والمزايدة عليها\n\n"
            "مزاداتي\n"
            "تابع مزاداتك التي نشرتها ونتائجها\n\n"
            "مزايداتي\n"
            "تابع مزايداتك الحالية واسترجع رصيدك\n\n"
            "المحفظة\n"
            "شحن وتحويل وسحب وسجل كامل للمعاملات\n\n"
            "القوانين\n"
            "عرض القوانين والتحدث مع المساعد الذكي\n\n"
            "دعم فني\n"
            "تواصل مع الإدارة عند أي مشكلة"
        )
    },
    3: {
        "title": "طرق الشحن والدفع",
        "text": (
            "شحن رصيدك سهل وسريع بأكثر من طريقة:\n\n"
            "Binance — تحويل USDT\n"
            "ارسل المبلغ وارفع رقم العملية (TxHash)\n"
            "يُضاف الرصيد بعد تأكيد الإدارة\n\n"
            "نجوم تيليجرام\n"
            "دفع فوري من داخل تيليجرام مباشرة\n"
            "الرصيد يُضاف تلقائياً بدون انتظار\n\n"
            "اسياسيل\n"
            "تواصل مع المالك مباشرة لتنسيق الشحن\n\n"
            "كود الشحن\n"
            "ادخل الكود واحصل على الرصيد فوراً\n\n"
            "\n"
            "العملة: الدولار الأمريكي ($)\n"
            "ادنى رصيد للنشر: 0.01$ فقط"
        )
    },
    4: {
        "title": "لماذا نطلب رقم هاتفك؟",
        "text": (
            "عند نشر اول مزاد سيطلب البوت رقم هاتفك.\n\n"
            "الاسباب الحقيقية:\n\n"
            "1 — منع الحسابات الوهمية\n"
            "كل رقم هاتف = شخص حقيقي واحد\n"
            "يمنع التلاعب بالمزادات عبر حسابات مزيفة\n\n"
            "2 — حماية المشتري\n"
            "اي بائع محتال يمكن التعرف عليه وإبلاغ\n"
            "الجهات المختصة بحقه\n\n"
            "3 — المسؤولية القانونية\n"
            "ربط الحساب بهوية حقيقية يجعل كل بائع\n"
            "مسؤولاً عن تصرفاته امام القانون\n\n"
            "\n"
            "هذا الرقم مشفر ولا يُشارك مع أي طرف\n"
            "ولن يُطلب منك مرة ثانية ابداً."
        )
    },
    5: {
        "title": "لماذا نطلب موقعك الجغرافي؟",
        "text": (
            "بعد رقم الهاتف سيطلب البوت موقعك مرة واحدة.\n\n"
            "الاسباب:\n\n"
            "1 — تحديد المنطقة الجغرافية\n"
            "نعرف إن البائع من العراق أو خارجه\n"
            "يُسرّع حل النزاعات بشكل كبير\n\n"
            "2 — الحماية من الاحتيال الدولي\n"
            "الموقع يكشف الانماط المشبوهة ويحمي\n"
            "المشترين من عمليات النصب\n\n"
            "3 — دليل قانوني عند الإبلاغ\n"
            "إذا سُرق منك شيء يصبح الموقع دليلاً\n"
            "مهماً في التحقيق\n\n"
            "\n"
            "لا نعرف عنوانك الدقيق — فقط المنطقة.\n"
            "يُؤخذ مرة واحدة فقط ويبقى سرياً."
        )
    },
    6: {
        "title": "قوانين البيع والمزايدة",
        "text": (
            "هذه القوانين تحمي الجميع:\n\n"
            "للبائع:\n"
            "· عمولة نشر: 0.01$ (رمزية)\n"
            "· عمولة بيع: 0.5% من سعر البيع فقط\n"
            "· تسليم المنتج خلال 24 ساعة من انتهاء المزاد\n"
            "· إن لم يأتِ أي مزايد — يُعاد لك سعر البدء كاملاً\n\n"
            "للمشتري:\n"
            "· رصيدك محجوز اثناء المزايدة\n"
            "· إن خسرت المزاد — يُعاد رصيدك فوراً\n"
            "· كل مزايدة تُمدد المزاد 5 دقائق\n\n"
            "العمولات:\n"
            "· عمولة التحويل بين المستخدمين: 5%\n\n"
            "حالات الحظر الفوري:\n"
            "· بيع منتج مسروق أو احتيالي\n"
            "· عدم تسليم المنتج للفائز\n"
            "· إدخال بيانات تحقق مزيفة"
        )
    },
    7: {
        "title": "المساعد الذكي القانوني",
        "text": (
            "البوت يحتوي على مساعد ذكي متخصص.\n\n"
            "ماذا يفعل؟\n\n"
            "يجيب على أسئلتك عن القوانين بالتفصيل\n"
            "يشرح سبب كل سياسة بأسلوب واضح\n"
            "يعلّمك كيف تحمي نفسك من الاحتيال\n"
            "يوضّح حقوقك كبائع أو مشترٍ\n"
            "يجيب على: لماذا طُلب مني الهاتف؟\n\n"
            "كيف تصل إليه؟\n"
            "من القائمة الرئيسية — القوانين — دعم ذكي\n\n"
            "اسأله بأي شيء عن البوت وسياساته\n"
            "وسيجيبك فوراً بدون انتظار."
        )
    },
    8: {
        "title": "شروط الاستخدام",
        "text": (
            "بالموافقة انت تقبل ما يلي:\n\n"
            "· تقديم معلومات صحيحة وحقيقية في التحقق\n"
            "· عدم بيع منتجات مسروقة او غير قانونية\n"
            "· تسليم المنتج للمشتري خلال 24 ساعة\n"
            "· عمولة نشر المزاد: 0.01$\n"
            "· عمولة البيع: 0.5% من سعر البيع\n"
            "· عمولة التحويل: 5% من المبلغ المحوّل\n"
            "· قرار الإدارة في اي نزاع نهائي وملزم\n"
            "· البوت يحق له حفظ رقم هاتفك وموقعك\n"
            "لأغراض الأمان فقط\n\n"
            "\n"
            "المخالفون يتعرضون للحظر الفوري.\n\n"
            "إذا كان عندك اي سؤال عن هذه الشروط\n"
            "استخدم زر القوانين في القائمة للتحدث\n"
            "مع المساعد الذكي.\n\n"
            "اضغط موافق للمتابعة واستخدام البوت."
        )
    }
}

def send_onboarding_page(chat_id, user_id, page_num):
    page = ONBOARDING_PAGES.get(page_num)
    if not page:
        return
    total_pages = len(ONBOARDING_PAGES)
    text = (
        f"{''*28}\n"
        f" {page['title']}\n"
        f"{''*28}\n\n"
        f"{page['text']}\n\n"
        f"الصفحة {page_num} من {total_pages}"
    )
    keyboard = types.InlineKeyboardMarkup()
    nav_row = []
    if page_num > 1:
        nav_row.append(types.InlineKeyboardButton("⬅️ السابق", callback_data=f"onboard_page_{page_num-1}", style="primary"))
    if page_num < total_pages:
        nav_row.append(types.InlineKeyboardButton("➡️ التالي", callback_data=f"onboard_page_{page_num+1}", style="primary"))
    if nav_row:
        keyboard.row(*nav_row)
    if page_num == total_pages:
        keyboard.row(types.InlineKeyboardButton("🔹 موافق على الشروط", callback_data="onboard_accept", style="primary"))
    bot.send_message(chat_id, text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('onboard_'))
def handle_onboarding(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    try:
        if call.data.startswith('onboard_page_'):
            page_num = int(call.data.replace('onboard_page_', ''))
            page = ONBOARDING_PAGES.get(page_num)
            if not page:
                safe_answer_callback_query(call.id)
                return
            total_pages = len(ONBOARDING_PAGES)
            text = (
                f"{''*28}\n"
                f" {page['title']}\n"
                f"{''*28}\n\n"
                f"{page['text']}\n\n"
                f"الصفحة {page_num} من {total_pages}"
            )
            keyboard = types.InlineKeyboardMarkup()
            nav_row = []
            if page_num > 1:
                nav_row.append(types.InlineKeyboardButton("⬅️ السابق", callback_data=f"onboard_page_{page_num-1}", style="primary"))
            if page_num < total_pages:
                nav_row.append(types.InlineKeyboardButton("➡️ التالي", callback_data=f"onboard_page_{page_num+1}", style="primary"))
            if nav_row:
                keyboard.row(*nav_row)
            if page_num == total_pages:
                keyboard.row(types.InlineKeyboardButton("🔹 موافق على الشروط", callback_data="onboard_accept", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard)
            safe_answer_callback_query(call.id)

        elif call.data == 'onboard_accept':
            db.complete_onboarding(user_id)
            balance = db.get_balance(user_id)
            active_count = len(db.get_active_auctions())
            keyboard = create_main_menu_keyboard(user_id)
            welcome_text = (
                f"*'''  منصة المزادات الرسمية  '''*\n"
                f"\n\n"
                f"اهلاً بك، *{call.from_user.first_name}*\n\n"
                f"الرصيد:  `{balance:.2f}$`\n"
                f"المزادات النشطة:  `{active_count}`\n\n"
                f"\n"
                f"المنصة الاولى والموثوقة لبيع وشراء\n"
                f"معرفات وقنوات وبوتات وهدايا تيليجرام"
            )
            try:
                bot.edit_message_text(welcome_text, chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard)
            except Exception:
                bot.send_message(chat_id, welcome_text, parse_mode="Markdown", reply_markup=keyboard)
            safe_answer_callback_query(call.id)
    except Exception as e:
        notify_owner_button_error(call, e, user_id)
        try:
            safe_answer_callback_query(call.id, "حدث خطأ! حاول مرة أخرى.")
        except Exception:
            pass



# معالج الموافقة والرفض (نفس السابق بدون تغيير كبير)
@bot.callback_query_handler(func=lambda call: (
    (call.data.startswith('approve_') and not call.data.startswith('approve_binance_') and not call.data.startswith('approve_withdraw_')) or
    (call.data.startswith('reject_') and not call.data.startswith('reject_withdraw_'))
))
def handle_approval_rejection(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if user_id != OWNER_ID:
        safe_answer_callback_query(call.id, "هذا للمالك فقط!")
        return
    try:
        data = call.data
        if data.startswith("approve_"):
            auction_id = data[8:]
            action = "approve"
        else:
            auction_id = data[7:]
            action = "reject"
        auction_info = db.get_auction_by_id(auction_id)
        if not auction_info:
            safe_answer_callback_query(call.id, "المزاد غير موجود!")
            return
        if action == "approve":
            db.approve_auction(auction_id)
            duration = URGENT_AUCTION_DURATION if auction_info.get('is_urgent') else db.get_auction_duration()
            try:
                bot.send_message(
                    auction_info['user_id'],
                    f" *تمت الموافقة على مزادك #{auction_id}*\n\n"
                    f"{md_escape(auction_info['title'])}\n"
                    f"{md_escape(auction_info['target'])}\n"
                    f"سعر البدء: {auction_info['starting_price']:.2f}$\n"
                    f"المدة: {duration} ساعة\n\n"
                    f"تم نشره في قنوات البث\n"
                    f"يمكنك رؤيته في قائمة المزادات الحالية.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error notifying user: {e}")
            broadcast_new_auction(auction_info)
            safe_answer_callback_query(call.id, f"تمت الموافقة على المزاد #{auction_id}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(f"تمت الموافقة على المزاد #{auction_id}\n\n{auction_info['title']}\n{auction_info['target']}\n\nتم نشره في جميع قنوات البث", chat_id, message_id, reply_markup=keyboard)
        elif action == "reject":
            db.reject_auction(auction_id)
            # إعادة عمولة النشر الصحيحة (عادي=0.01$ / عاجل=0.03$) وسعر البدء إن وُجد عند الرفض
            commission_refund = URGENT_LISTING_FEE if auction_info.get('is_urgent') else 0.01
            starting_price_refund = auction_info.get('starting_price', 0.0)
            total_refund = commission_refund + starting_price_refund
            db.update_balance(auction_info['user_id'], total_refund)
            db.add_transaction(auction_info['user_id'], total_refund, "refund", f"استرداد عمولة + سعر البدء - مزاد مرفوض #{auction_id}")
            try:
                bot.send_message(auction_info['user_id'], f"تم رفض مزادك #{auction_id}\n\n{auction_info['title']}\n{auction_info['target']}\n\nتم رفض المزاد من قبل الإدارة.")
            except Exception as e:
                logger.error(f"Error notifying user: {e}")
            safe_answer_callback_query(call.id, f"تم رفض المزاد #{auction_id}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(f"تم رفض المزاد #{auction_id}\n\n{auction_info['title']}\n{auction_info['target']}\n\nتم إبلاغ المستخدم", chat_id, message_id, reply_markup=keyboard)
    except Exception as e:
        notify_owner_button_error(call, e, user_id)
        try:
            safe_answer_callback_query(call.id, "حدث خطأ!")
        except Exception:
            pass

@bot.callback_query_handler(func=lambda call: call.data in ["confirm_auction", "cancel_auction", "confirm_channel", "cancel_channel", "confirm_subscription_channel", "cancel_subscription_channel", "confirm_transfer", "cancel_transfer", "skip_description", "execute_binance_pay"])
def handle_confirmation_buttons(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    # فحص الحظر
    if user_id != OWNER_ID and db.is_banned(user_id):
        safe_answer_callback_query(call.id, "حسابك محظور من استخدام البوت.")
        return
    try:
        safe_answer_callback_query(call.id)
        if call.data == "confirm_auction":
            user_state = db.get_user_state(user_id)
            if not user_state or user_state['state'] != "confirming_auction":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            auction_data = user_state['data']
            auction_type = auction_data.get('auction_type')
            target = auction_data.get('target')
            platform = auction_data.get('platform', '')
            starting_price = float(auction_data.get('starting_price', 0.0))
            is_urgent = bool(auction_data.get('is_urgent', False))
            listing_fee = URGENT_LISTING_FEE if is_urgent else 0.01
            commission_amount = listing_fee
            total_deduct = commission_amount + starting_price
            balance = db.get_balance(user_id)
            if balance < total_deduct:
                safe_answer_callback_query(call.id, "رصيدك غير كافي!")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("📥 شحن الرصيد", callback_data="charge", style="primary"), types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                bot.edit_message_text(f"رصيدك غير كافي!\n\nرصيدك الحالي: {balance:.2f}$\nالمطلوب: {total_deduct:.2f}$\n\nيرجى شحن رصيدك أولاً.", chat_id, message_id, reply_markup=keyboard)
                return
            auction_id = auction_data.get('auction_id') or generate_auction_id()
            if not db.deduct_commission(user_id, auction_id, listing_fee=listing_fee):
                safe_answer_callback_query(call.id, "حدث خطأ في إنشاء المزاد!")
                return
            if starting_price > 0:
                db.update_balance(user_id, -starting_price)
                db.add_transaction(user_id, -starting_price, "auction_starting_price", f"سعر بدء مزاد #{auction_id}")
            if auction_type == "username" and platform:
                if platform == "telegram":
                    title = f"{AUCTION_TYPES.get(auction_type)} تليجرام - {target[:30]}"
                else:
                    title = f"{AUCTION_TYPES.get(auction_type)} - {SOCIAL_PLATFORMS.get(platform, platform)} - {target[:30]}"
            else:
                title = f"{AUCTION_TYPES.get(auction_type)} - {target[:30]}"
            if is_urgent:
                title = f"⚡ {title}"
            auction_duration = URGENT_AUCTION_DURATION if is_urgent else None
            db.add_auction(auction_id, user_id, auction_type, target, title, platform, starting_price, duration_hours=auction_duration, is_urgent=is_urgent)
            user_info = db.get_user(user_id)
            username_val = user_info['username'] if user_info else "غير معروف"
            duration = URGENT_AUCTION_DURATION if is_urgent else db.get_auction_duration()
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✅ الموافقة", callback_data=f"approve_{auction_id}", style="primary"), types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_{auction_id}", style="danger"))
            try:
                bot.send_message(
                    OWNER_ID,
                    "\n".join([
                        f"📝 {hb('طلب نشر مزاد جديد')}  {hc('#' + str(auction_id))}",
                        DIVIDER,
                        f"👤 {hb('المستخدم:')} @{html_escape(username_val if username_val else 'بدون معرف')}",
                        f"🆔 {hb('أيدي:')} {hc(user_id)}",
                        _auction_type_line({'auction_type': auction_type}),
                        f"⚡ {hb('السرعة:')} {'⚡ عاجل' if is_urgent else '🕐 عادي'}",
                        f"🌐 {hb('المنصة:')} {html_escape(SOCIAL_PLATFORMS.get(platform, platform) if platform and platform != 'telegram' else ('تليجرام' if platform == 'telegram' else 'غير محدد'))}",
                        f"🎯 {hb('الهدف:')} {html_escape(target)}",
                        DIVIDER,
                        f"💰 {hb('سعر البدء:')} {fmt_money(starting_price)}",
                        f"⏳ {hb('المدة:')} {duration} ساعة",
                        f"🕓 {hb('وقت النشر:')} {html_escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}",
                    ]),
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending to admin: {e}")
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(
                "\n".join([
                    f"✅ {hb('تم إنشاء المزاد')}  {hc('#' + str(auction_id))}",
                    DIVIDER,
                    f"💰 {hb('سعر البدء:')} {fmt_money(starting_price)}",
                    "",
                    "📨 تم إرسال طلبك للإدارة للموافقة",
                    "📢 سيتم نشره في قنوات البث عند الموافقة",
                ]),
                chat_id, message_id, reply_markup=keyboard,
                parse_mode="HTML"
            )
        elif call.data == "cancel_auction":
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text("تم إلغاء إنشاء المزاد", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "confirm_channel":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            user_state = db.get_user_state(user_id)
            if not user_state or user_state['state'] != "confirming_channel":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            channel_data = user_state['data']
            channel_id = channel_data.get('channel_id')
            channel_username = channel_data.get('channel_username')
            channel_title = channel_data.get('channel_title')
            try:
                if channel_username:
                    chat = bot.get_chat(f"@{channel_username}")
                    channel_id = chat.id
                    channel_title = chat.title
                    channel_username = chat.username
                elif channel_id:
                    chat = bot.get_chat(channel_id)
                    channel_title = chat.title
                    channel_username = chat.username
            except Exception as e:
                logger.error(f"Error getting channel info: {e}")
                safe_answer_callback_query(call.id, "لا يمكن الوصول إلى القناة!")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data="add_broadcast_channel", style="primary"))
                bot.edit_message_text(f"لا يمكن الوصول إلى القناة!\n\nتأكد من:\n1. إضافة البوت كمسؤول في القناة\n2. صحة المعرف أو الأيدي", chat_id, message_id, reply_markup=keyboard)
                return
            db.add_channel(channel_id, channel_username, channel_title, OWNER_ID)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(f"تمت إضافة القناة بنجاح!\n\n{channel_title}\n@{channel_username if channel_username else 'بدون معرف'}\n{channel_id}\n\nسيتم نشر المزادات الجديدة في هذه القناة.", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "cancel_channel":
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text("تم إلغاء إضافة القناة", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "confirm_subscription_channel":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            user_state = db.get_user_state(user_id)
            if not user_state or user_state['state'] != "confirming_subscription_channel":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            channel_data = user_state['data']
            channel_id = channel_data.get('channel_id')
            channel_username = channel_data.get('channel_username')
            channel_title = channel_data.get('channel_title')
            max_subscribers = channel_data.get('max_subscribers', 0)
            try:
                if channel_username:
                    chat = bot.get_chat(f"@{channel_username}")
                    channel_id = chat.id
                    channel_title = chat.title
                    channel_username = chat.username
                elif channel_id:
                    chat = bot.get_chat(channel_id)
                    channel_title = chat.title
                    channel_username = chat.username
                try:
                    member_count = bot.get_chat_member_count(channel_id)
                except:
                    member_count = 0
            except Exception as e:
                logger.error(f"Error getting channel info: {e}")
                safe_answer_callback_query(call.id, "لا يمكن الوصول إلى القناة!")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data="add_subscription_channel", style="primary"))
                bot.edit_message_text(f"لا يمكن الوصول إلى القناة!\n\nتأكد من:\n1. إضافة البوت كمسؤول في القناة\n2. صحة المعرف أو الأيدي", chat_id, message_id, reply_markup=keyboard)
                return
            db.add_subscription_channel(channel_id, channel_username, channel_title, OWNER_ID, max_subscribers, channel_data.get('sub_type', 'permanent'))
            db.update_subscriber_count(channel_id, member_count)
            db.clear_user_state(user_id)
            max_info = ""
            sub_type_display = ""
            if channel_data.get('sub_type') == 'paid':
                sub_type_display = f"\n نوع الاشتراك: مدفوع ({max_subscribers} اشتراك)\n تُحذف تلقائياً عند الانتهاء"
            else:
                sub_type_display = "\n نوع الاشتراك: دائم"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(f"تمت إضافة قناة الاشتراك بنجاح!\n\n{channel_title}\n@{channel_username if channel_username else 'بدون معرف'}\nالمشتركين: {member_count}{sub_type_display}\n{channel_id}\n\nسيتم طلب الاشتراك في هذه القناة من جميع المستخدمين.", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "cancel_subscription_channel":
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text("تم إلغاء إضافة قناة الاشتراك", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "confirm_transfer":
            user_state = db.get_user_state(user_id)
            if not user_state or user_state['state'] != "confirming_transfer":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            transfer_data = user_state['data']
            to_user_id = transfer_data.get('to_user_id')
            amount = transfer_data.get('amount')
            description = transfer_data.get('description', '')
            user_balance = db.get_balance(user_id)
            if user_balance < amount:
                safe_answer_callback_query(call.id, "رصيدك غير كافي!")
                return
            success, message_text = transfer_money_between_users(user_id, to_user_id, amount, description)
            if success:
                db.clear_user_state(user_id)
                new_balance = db.get_balance(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 تحويل جديد", callback_data="transfer_money", style="primary"), types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
                bot.edit_message_text(f"{message_text}\n\nرصيدك الجديد: {new_balance:.2f}$", chat_id, message_id, reply_markup=keyboard)
                try:
                    to_user = db.get_user(to_user_id)
                    if to_user:
                        to_user_balance = db.get_balance(to_user_id)
                        bot.send_message(to_user_id, f"تم استلام تحويل مالي!\n\nالمبلغ: {amount:.2f}$\nالعمولة: {calculate_transfer_commission(amount):.2f}$\nصافي المبلغ المستلم: {amount - calculate_transfer_commission(amount):.2f}$\nالمرسل: @{db.get_user(user_id)['username'] if db.get_user(user_id) and db.get_user(user_id)['username'] else 'مستخدم'}\nرصيدك الجديد: {to_user_balance:.2f}$\n\n{description if description else ''}")
                except Exception as e:
                    logger.error(f"Error notifying receiver: {e}")
            else:
                safe_answer_callback_query(call.id, message_text)
        elif call.data == "cancel_transfer":
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text("تم إلغاء عملية التحويل", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "skip_description":
            user_state = db.get_user_state(user_id)
            if not user_state or user_state['state'] != "waiting_transfer_description":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            to_user_id = (user_state.get('data') or {}).get('to_user_id')
            amount = (user_state.get('data') or {}).get('amount')
            commission = calculate_transfer_commission(amount)
            net_amount = amount - commission
            db.set_user_state(user_id, "confirming_transfer", {"to_user_id": to_user_id, "amount": amount, "description": ""})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✅ تأكيد التحويل", callback_data="confirm_transfer", style="primary"), types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_transfer", style="danger"))
            bot.edit_message_text(f"تأكيد التحويل:\n\nإلى: @{db.get_user(to_user_id)['username'] if db.get_user(to_user_id) and db.get_user(to_user_id)['username'] else 'مستخدم'}\nالمبلغ: {amount:.2f}$\nالعمولة ({TRANSFER_COMMISSION_RATE*100}%): {commission:.2f}$\nصافي المبلغ للمستلم: {net_amount:.2f}$\nالوصف: لا يوجد\n\nهل تريد تأكيد التحويل؟", chat_id, message_id, reply_markup=keyboard)

        # تنفيذ الدفع عبر Binance 
        elif call.data == "execute_binance_pay":
            if not BINANCE_ENABLED or not binance_client:
                safe_answer_callback_query(call.id, "بوابة الدفع غير متاحة!")
                return
            user_state = db.get_user_state(user_id)
            if not user_state or user_state['state'] != "confirming_binance_payment":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            pay_data = user_state['data']
            wallet = pay_data['wallet']
            usdt_amt = pay_data['usdt']
            usd_amt = pay_data['usd']
            db.clear_user_state(user_id)

            # المستخدم يُرسل USDT للبوت ← نحفظ الطلب معلقاً للمراجعة اليدوية
            # (البوت لا يسحب من حساب المستخدم — المستخدم هو من يُحوّل للبوت)
            pay_id = db.create_binance_payment(user_id, usdt_amt, usd_amt, wallet)

            # عنوان محفظة البوت (لاستقبال USDT من المستخدم)
            try:
                bot_wallet = binance_client.get_deposit_address(coin='USDT', network='TRX').get('address', 'غير متاح')
            except Exception:
                bot_wallet = "تواصل مع الدعم"

            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(
                f" *أرسل USDT للمحفظة التالية:*\n\n"
                f" *العنوان (TRC20):*\n`{bot_wallet}`\n\n"
                f"المبلغ المطلوب: *{usdt_amt} USDT*\n"
                f"سيُضاف لرصيدك: *${usd_amt:.2f}*\n\n"
                f"رقم طلبك: *#{pay_id}*\n\n"
                f"بعد الإرسال، انتظر تأكيد الإدارة خلال 30 دقيقة.\n"
                f"تأكد من إرسال USDT على شبكة TRC20 فقط.",
                chat_id, message_id,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            # إشعار المشرف
            try:
                u = db.get_user(user_id)
                name = f"@{u['username']}" if u and u['username'] else str(user_id)
                bot.send_message(
                    OWNER_ID,
                    f" *طلب شحن Binance جديد*\n\n"
                    f"المستخدم: {name} ({user_id})\n"
                    f"المبلغ: {usdt_amt} USDT → ${usd_amt:.2f}\n"
                    f"محفظة المُرسِل: `{wallet}`\n"
                    f"رقم الطلب: #{pay_id}\n\n"
                    f"بعد استلام التحويل، أكّد من لوحة الإدارة ← تأكيد دفع Binance.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    except Exception as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str or "message to edit not found" in err_str:
            pass
        else:
            notify_owner_button_error(call, e, user_id)
            try:
                safe_answer_callback_query(call.id, "حدث خطأ!")
            except:
                pass

# ====== Helper functions للـ nav_back — تعرض كل صفحة بشكل مستقل ======

def _show_wallet_page(call, user_id, chat_id, message_id):
    """عرض صفحة المحفظة — مشترك بين nav_back والـ callback العادي."""
    balance = db.get_balance(user_id)
    stats = db.get_wallet_stats(user_id)
    net = stats['total_in'] - stats['total_out']
    user_info = db.get_user(user_id)
    username = user_info['username'] if user_info and user_info['username'] else str(user_id)
    last_tx_line = ""
    if stats['last_tx']:
        TYPE_AR_SHORT = {
            'recharge_code': 'شحن-كود', 'binance_charge': 'شحن-Binance',
            'stars_charge': 'شحن-نجوم', 'asiacell_charge': 'شحن-اسياسيل',
            'lucky_wheel': 'عجلة الحظ', 'gift_link_sent': 'هدية مرسلة',
            'gift_link_received': 'هدية مستلمة', 'transfer_code_sent': 'كود صادر',
            'transfer_code_received': 'كود وارد', 'transfer_sent': 'تحويل صادر',
            'transfer_received': 'تحويل وارد', 'commission': 'عمولة',
            'bid_refund': 'استرداد', 'auction_sale': 'بيع مزاد',
            'auction_bid': 'مزايدة', 'starting_price_refund': 'استرداد بدء',
        }
        lt = stats['last_tx']
        sign = "+" if lt['amount'] > 0 else ""
        lbl = TYPE_AR_SHORT.get(lt['type'], lt['type'])
        last_tx_line = f"\n آخر عملية: {lbl} {sign}{lt['amount']:.2f}$\n {lt['created_at']}\n"
    text = (
        f"\nالمحفظة \n\n\nالمستخدم: @{username}\n"
        f"الرصيد المتاح:\n\n {balance:.2f}$ \n\n\n"
        f"الحركة المالية \n\nالوارد +{stats['total_in']:.2f}$\n"
        f"الصادر -{stats['total_out']:.2f}$\nالصافي {'+' if net >= 0 else ''}{net:.2f}$\n"
        f"إجمالي العمليات: {stats['total_ops']}\n{last_tx_line}\n"
        f"الشحن \n\nمرات الشحن {stats['charge_count']}\n"
        f"إجمالي شحن +{stats['charge_total']:.2f}$\n\n"
        f"التحويلات \n\nمرسلة {stats['sent_count']} ({stats['sent_total']:.2f}$)\n"
        f"مستلمة {stats['recv_count']} ({stats['recv_total']:.2f}$)\n\n"
        f"المزادات \n\nمزايدات {stats['bid_count']} (-{stats['bid_total']:.2f}$)\n"
        f"مبيعات {stats['sale_count']} (+{stats['sale_total']:.2f}$)\n"
        f"عمولات {stats['commission_count']} (-{stats['commission_total']:.2f}$)\n"
        f"استردادات {stats['refund_count']} (+{stats['refund_total']:.2f}$)\n\n"
        f"عجلة الحظ \n\nارباح {stats['wheel_total']:.2f}$\nدورات {stats['wheel_count']}"
    )
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("📥 شحن رصيد", callback_data="charge", style="primary"),
        types.InlineKeyboardButton("🔹 تحويل رصيد", callback_data="transfer_money", style="primary")
    )
    keyboard.row(
        types.InlineKeyboardButton("🔹 استخدام كود", callback_data="use_code", style="primary"),
        types.InlineKeyboardButton("🔹 سجل العمليات", callback_data="wallet_history", style="primary")
    )
    keyboard.row(
        types.InlineKeyboardButton("🎰 عجلة الحظ", callback_data="lucky_wheel", style="primary"),
        types.InlineKeyboardButton("📤 سحب الرصيد", callback_data="withdraw_request", style="primary")
    )
    keyboard.row(
        types.InlineKeyboardButton("🧑‍💼 الوكلاء", callback_data="show_agents", style="primary"),
        types.InlineKeyboardButton("🤝 الوسطاء", callback_data="show_brokers", style="primary")
    )
    keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    except Exception:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def _show_contests_page(call, user_id, chat_id, message_id):
    """عرض صفحة المسابقات — مشترك."""
    contests = db.get_all_contests(status='active') + db.get_all_contests(status='scheduled')
    keyboard = types.InlineKeyboardMarkup()
    free_cards = db.get_user_free_cards_count(user_id)
    cards_label = f"🃏 كروتي ({free_cards})" if free_cards > 0 else "🃏 كروتي"
    if not contests:
        text = (
            f"🎯 <b>المسابقات</b>\n\n"
            f"لا توجد مسابقات نشطة حالياً.\n\n"
            f"💡 ادعُ أصدقاءك واجمع الكروت للمشاركة في القادمة!\n"
            f"لكل صديق ينضم عبر رابطك كارت مجاني فوري 🎁"
        )
    else:
        text = f"🎯 <b>المسابقات المتاحة</b>\n\n"
        text += f"🃏 كروتك المتاحة: <b>{free_cards}</b>\n\n"
        seen = set()
        for c in contests:
            if c['contest_id'] not in seen:
                seen.add(c['contest_id'])
                status_icon = "🟢" if c['status'] == 'active' else "🔵"
                prize = _prize_label(c)
                keyboard.row(types.InlineKeyboardButton(
                    f"{status_icon} {c['name']} — 🎁 {prize}",
                    callback_data=f"contest_detail_{c['contest_id']}", style="primary"
                ))
    keyboard.row(types.InlineKeyboardButton(cards_label, callback_data="my_cards", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")


def _show_my_cards_page(call, user_id, chat_id, message_id):
    """عرض صفحة كروتي — مشترك."""
    cards = db.get_user_cards(user_id)
    free_count = db.get_user_free_cards_count(user_id)
    ref_count = len(cards)
    bot_info = get_bot_info()
    ref_link = f"https://t.me/{bot_info['username']}?start=ref_{user_id}"
    text = "\n".join([
        f"🎟️ <b>كروتي وإحالاتي</b>",
        DIVIDER,
        f"📦 <b>إجمالي الكروت:</b> {ref_count}",
        f"🆓 <b>الكروت المتاحة:</b> {free_count}",
        f"👥 <b>المستخدمون المُحالون:</b> {ref_count}",
        DIVIDER,
        f"🔗 <b>رابطك الخاص للدعوة:</b>",
        f"<code>{ref_link}</code>",
        "",
        f"💡 كل صديق ينضم عبر رابطك يمنحك <b>كارتاً مجانياً فورياً</b>، بالإضافة إلى فرصة أكبر للفوز بالمسابقات!",
    ])
    keyboard = types.InlineKeyboardMarkup()
    share_text = "🔥 وجدت أفضل منصة لمزادات الحسابات والقنوات على تيليجرام! انضم الآن واحصل على كارت مجاني:"
    share_url = (
        "https://t.me/share/url?url=" + urllib.parse.quote(ref_link, safe="")
        + "&text=" + urllib.parse.quote(share_text, safe="")
    )
    keyboard.row(types.InlineKeyboardButton("📤 مشاركة ودعوة أصدقاء", url=share_url, style="primary"))
    if cards:
        last_cards_lines = "\n".join(f"• <code>{c['card_number']}</code>" for c in cards[:5])
        text += f"\n\n🗂️ <b>آخر 5 كروت:</b>\n{last_cards_lines}"
    keyboard.row(types.InlineKeyboardButton("🎯 المسابقات", callback_data="show_contests", style="primary"))
    keyboard.row(types.InlineKeyboardButton("📋 نسخ الرابط", callback_data=f"copy_ref_link_{user_id}", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")


def _show_charge_page(call, user_id, chat_id, message_id):
    """عرض صفحة الشحن — مشترك."""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("🔹 كود شحن", callback_data="charge_code", style="primary"),
                 types.InlineKeyboardButton("🔹 Binance Pay", callback_data="charge_binance", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔹 نجوم تيليجرام", callback_data="charge_stars", style="primary"),
                 types.InlineKeyboardButton("🔹 كي كارد", callback_data="charge_kycard", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔙 المحفظة", callback_data="wallet", style="primary"))
    try:
        bot.edit_message_text("📥 <b>اختر طريقة الشحن:</b>", chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, "📥 <b>اختر طريقة الشحن:</b>", reply_markup=keyboard, parse_mode="HTML")


def _show_auctions_page(call, user_id, chat_id, message_id):
    """عرض صفحة المزادات — مشترك."""
    keyboard = create_categories_keyboard()
    try:
        bot.edit_message_text("📋 <b>تصفح المزادات</b>\n\nاختر التصنيف:", chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, "📋 <b>تصفح المزادات</b>\n\nاختر التصنيف:", reply_markup=keyboard, parse_mode="HTML")


def _show_my_auctions_page(call, user_id, chat_id, message_id):
    """عرض صفحة مزاداتي — مشترك."""
    auctions = db.get_user_auctions(user_id)
    keyboard = types.InlineKeyboardMarkup()
    if not auctions:
        text = "📦 <b>مزاداتي</b>\n\nلا توجد مزادات منشورة."
        keyboard.row(types.InlineKeyboardButton("📢 نشر مزاد جديد", callback_data="new_auction", style="primary"))
    else:
        text = f"📦 <b>مزاداتي</b> ({len(auctions)} مزاد)\n\n"
        for a in auctions[:5]:
            status_map = {'active': '🟢', 'ended': '🔴', 'cancelled': '⚫'}
            icon = status_map.get(a.get('status', ''), '⚪')
            text += f"{icon} #{a['auction_id']} — {a.get('target', '')[:30]}\n"
        keyboard.row(types.InlineKeyboardButton("📢 مزاد جديد", callback_data="new_auction", style="primary"),
                     types.InlineKeyboardButton("📋 المزادات", callback_data="show_auctions", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")


def _show_my_bids_page(call, user_id, chat_id, message_id):
    """عرض صفحة مزايداتي — مشترك."""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("📋 عرض المزادات", callback_data="show_auctions", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
    try:
        bot.edit_message_text("🙋 <b>مزايداتي</b>\n\nاختر من قائمة المزادات النشطة.", chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, "🙋 <b>مزايداتي</b>", reply_markup=keyboard, parse_mode="HTML")


def _show_admin_panel_page(call, user_id, chat_id, message_id):
    """عرض لوحة الإدارة — مشترك."""
    if user_id != OWNER_ID:
        safe_answer_callback_query(call.id, "للمالك فقط!", show_alert=True)
        return
    # نعيد تحميل لوحة الإدارة من الـ callback الأصلي
    call.data = "admin_panel"


def _show_admin_contests_page(call, user_id, chat_id, message_id):
    """عرض لوحة إدارة المسابقات — مشترك."""
    if user_id != OWNER_ID:
        safe_answer_callback_query(call.id, "للمالك فقط!", show_alert=True)
        return
    contests = db.get_all_contests()
    text = f"🎯 <b>إدارة المسابقات</b>\n\nالمجموع: {len(contests)}\n\n"
    status_ar = {'scheduled': 'قادمة', 'active': 'نشطة', 'completed': 'منتهية', 'cancelled': 'ملغاة'}
    for c in contests[:8]:
        text += f"• #{c['contest_id']} {c['name']} | {status_ar.get(c['status'], '?')} | {_prize_label(c)}\n"
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("🔹 مسابقة جديدة", callback_data="admin_new_contest", style="primary"))
    active = [c for c in contests if c['status'] in ('active', 'scheduled')]
    for c in active[:3]:
        keyboard.row(types.InlineKeyboardButton(f"⚙️ {c['name'][:20]}", callback_data=f"admin_contest_{c['contest_id']}", style="primary"))
    keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    # فحص الحظر 
    if user_id != OWNER_ID and db.is_banned(user_id):
        safe_answer_callback_query(call.id, "حسابك محظور من استخدام البوت.")
        return
    _agent_broker_callbacks = (
        call.data == "my_agent_panel" or call.data == "my_broker_panel" or
        call.data == "agent_pending_requests" or call.data == "broker_pending_requests" or
        call.data == "agent_requests_history" or call.data == "broker_requests_history" or
        call.data == "agent_detailed_stats" or call.data == "broker_detailed_stats" or
        call.data == "agent_create_code" or call.data == "agent_direct_transfer" or
        call.data.startswith("agent_approve_req_") or call.data.startswith("agent_reject_req_") or
        call.data.startswith("broker_approve_req_") or call.data.startswith("broker_reject_req_") or
        call.data.startswith("broker_report_user_")
    )
    _bypass_sub_check = (
        user_id == OWNER_ID or
        call.data in ["check_subscription", "back_to_main", "skip_description"] or
        call.data.startswith("onboard_") or
        (_agent_broker_callbacks and (db.is_agent(user_id) or db.is_broker(user_id)))
    )
    if not _bypass_sub_check:
        subscribed, result = check_subscription(user_id)
        if not subscribed:
            channels_text, keyboard = result
            safe_answer_callback_query(call.id, "يجب الاشتراك في القنوات أولاً! تحقق من رسالتك الخاصة.", show_alert=True)
            try:
                # نرسل دائمًا في الخاص مع المستخدم، وليس في مكان الزر نفسه
                # (قد يكون الزر داخل قناة عامة، فلا يصح تعديل/الكتابة هناك)
                bot.send_message(user_id, channels_text, reply_markup=keyboard)
            except Exception:
                logger.warning(f"Could not send subscription prompt privately to {user_id}")
            return
    try:
        if call.data == "back_to_main":
            db.clear_user_state(user_id)
            nav_clear(user_id)
            keyboard = create_main_menu_keyboard(user_id)
            balance = db.get_balance(user_id)
            active_count = len(db.get_active_auctions())
            welcome_text = (
                f"*'''  منصة المزادات الرسمية  '''*\n"
                f"\n\n"
                f"اهلاً بك، *{call.from_user.first_name}*\n\n"
                f"الرصيد:  `{balance:.2f}$`\n"
                f"المزادات النشطة:  `{active_count}`\n\n"
                f"\n"
                f"المنصة الاولى والموثوقة لبيع وشراء\n"
                f"معرفات وقنوات وبوتات وهدايا تيليجرام"
            )
            bot.edit_message_text(welcome_text, chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard)

        elif call.data == "nav_back":
            # نظام الرجوع الذكي — يعرف وين يروح بالضبط
            prev_page = nav_pop(user_id)
            safe_answer_callback_query(call.id)
            # محاكاة كأن المستخدم ضغط على الصفحة السابقة مباشرة
            call.data = prev_page
            # نعيد توجيه المعالجة عبر إعادة استدعاء نفس handler بـ call.data الجديد
            # نستخدم fallback بسيط: ننفذ الصفحة الصحيحة مباشرة
            if prev_page == "back_to_main" or not prev_page:
                db.clear_user_state(user_id)
                nav_clear(user_id)
                keyboard = create_main_menu_keyboard(user_id)
                balance = db.get_balance(user_id)
                active_count = len(db.get_active_auctions())
                welcome_text = (
                    f"*'''  منصة المزادات الرسمية  '''*\n"
                    f"\n\n"
                    f"اهلاً بك، *{call.from_user.first_name}*\n\n"
                    f"الرصيد:  `{balance:.2f}$`\n"
                    f"المزادات النشطة:  `{active_count}`\n\n"
                    f"\n"
                    f"المنصة الاولى والموثوقة لبيع وشراء\n"
                    f"معرفات وقنوات وبوتات وهدايا تيليجرام"
                )
                bot.edit_message_text(welcome_text, chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard)
            elif prev_page == "wallet":
                _show_wallet_page(call, user_id, chat_id, message_id)
            elif prev_page == "show_auctions":
                _show_auctions_page(call, user_id, chat_id, message_id)
            elif prev_page == "show_contests":
                _show_contests_page(call, user_id, chat_id, message_id)
            elif prev_page == "my_cards":
                _show_my_cards_page(call, user_id, chat_id, message_id)
            elif prev_page == "charge":
                _show_charge_page(call, user_id, chat_id, message_id)
            elif prev_page == "my_auctions":
                _show_my_auctions_page(call, user_id, chat_id, message_id)
            elif prev_page == "my_bids":
                _show_my_bids_page(call, user_id, chat_id, message_id)
            elif prev_page == "admin_panel":
                _show_admin_panel_page(call, user_id, chat_id, message_id)
            elif prev_page == "admin_contests":
                _show_admin_contests_page(call, user_id, chat_id, message_id)
            elif prev_page and prev_page.startswith("auction_details_"):
                # ارجع لتفاصيل المزاد المحددة — نعيد التوجيه مباشرة
                auction_id = prev_page.replace("auction_details_", "")
                auction_info = db.get_auction_by_id(auction_id)
                if auction_info and auction_info.get('status') == 'active':
                    call.data = prev_page
                    # re-dispatch: نضع الـ data الجديد ثم نستدعي handle_callback مرة أخرى
                    try:
                        handle_callback(call)
                    except Exception:
                        _show_auctions_page(call, user_id, chat_id, message_id)
                else:
                    # المزاد انتهى، روح لقائمة المزادات
                    _show_auctions_page(call, user_id, chat_id, message_id)
            else:
                # fallback: روح للرئيسية
                db.clear_user_state(user_id)
                nav_clear(user_id)
                keyboard = create_main_menu_keyboard(user_id)
                balance = db.get_balance(user_id)
                active_count = len(db.get_active_auctions())
                welcome_text = (
                    f"*'''  منصة المزادات الرسمية  '''*\n"
                    f"\n\n"
                    f"اهلاً بك، *{call.from_user.first_name}*\n\n"
                    f"الرصيد:  `{balance:.2f}$`\n"
                    f"المزادات النشطة:  `{active_count}`\n\n"
                    f"\n"
                    f"المنصة الاولى والموثوقة لبيع وشراء\n"
                    f"معرفات وقنوات وبوتات وهدايا تيليجرام"
                )
                bot.edit_message_text(welcome_text, chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard)

        elif call.data in ("auction_speed_urgent", "auction_speed_normal"):
            user_state = db.get_user_state(user_id)
            if not user_state or user_state['state'] != "waiting_auction_speed":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!", show_alert=True)
                return
            safe_answer_callback_query(call.id)
            auction_data = user_state['data'] or {}
            is_urgent = call.data == "auction_speed_urgent"
            auction_data['is_urgent'] = is_urgent
            auction_type = auction_data.get('auction_type', '')
            target = auction_data.get('target', '')
            platform = auction_data.get('platform', '')
            starting_price = float(auction_data.get('starting_price', 0.0))
            auction_id = auction_data.get('auction_id')
            db.set_user_state(user_id, "confirming_auction", auction_data)
            balance = db.get_balance(user_id)
            if is_urgent:
                duration = URGENT_AUCTION_DURATION
                listing_fee = URGENT_LISTING_FEE
                commission_pct = URGENT_COMMISSION_RATE * 100
                speed_label = "⚡ عاجل"
            else:
                duration = db.get_auction_duration()
                listing_fee = 0.01
                commission_pct = COMMISSION_RATE * 100
                speed_label = "🕐 عادي"
            text = f" *تفاصيل المزاد*\n\n"
            text += f"النوع: {AUCTION_TYPES.get(auction_type, '')}\n"
            if platform:
                if platform == "telegram":
                    text += f"المنصة: تليجرام\n"
                else:
                    text += f"المنصة: {SOCIAL_PLATFORMS.get(platform, platform)}\n"
            text += f"الهدف: {target}\n"
            text += f"الرمز: #{auction_id}\n"
            text += f"السرعة: {speed_label}\n"
            text += f"المدة: {duration} ساعة\n"
            text += f"سعر البدء: {starting_price:.2f}$\n"
            text += f"عمولة النشر: {listing_fee:.2f}$\n"
            text += f"عمولة البيع عند الإغلاق: {commission_pct:.1f}%\n"
            text += f"\nرصيدك الحالي: {balance:.2f}$\n"
            if starting_price > 0:
                text += f"سيُخصم: {starting_price + listing_fee:.2f}$ (سعر البدء + العمولة)\n"
            text += f"\nسيتم نشر المزاد في قنوات البث عند الموافقة"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✅ تأكيد النشر", callback_data="confirm_auction", style="primary"), types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_auction", style="danger"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        # المحفظة
        elif call.data == "wallet":
            safe_answer_callback_query(call.id)
            nav_push(user_id, "wallet")
            _show_wallet_page(call, user_id, chat_id, message_id)

        elif call.data == "wallet_history":
            nav_push(user_id, "wallet_history")
            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id=?", (user_id,))
            total_count = cursor.fetchone()[0] or 0
            text = f"{DIVIDER}\n📋 {hb('سجل العمليات')}\n{DIVIDER}\n\n"
            if total_count == 0:
                text += "لا توجد عمليات مسجلة بعد."
            else:
                text += f"إجمالي العمليات: {total_count}\n\nاختر نوع العمليات لعرضها:"
            keyboard = types.InlineKeyboardMarkup()
            for cat_id, cat_label, cat_types in TX_CATEGORIES:
                placeholders = ",".join("?" * len(cat_types))
                cursor.execute(f"SELECT COUNT(*) FROM transactions WHERE user_id=? AND type IN ({placeholders})", (user_id, *cat_types))
                cnt = cursor.fetchone()[0] or 0
                if cnt == 0:
                    continue
                keyboard.row(types.InlineKeyboardButton(f"{cat_label} ({cnt})", callback_data=f"wallet_history_cat_{cat_id}_0", style="primary"))
            if total_count > 0:
                keyboard.row(types.InlineKeyboardButton(f"📋 الكل ({total_count})", callback_data="wallet_history_cat_all_0", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمحفظة", callback_data="wallet", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        # ============================================================
        # طلب سحب الرصيد — واجهة كاملة
        # ============================================================
        elif call.data == "withdraw_request":
            nav_push(user_id, "withdraw_request")
            safe_answer_callback_query(call.id)
            balance = db.get_balance(user_id)
            today_count = db.get_user_withdrawals_today(user_id)
            has_pending = db.has_pending_withdrawal(user_id)
            keyboard = types.InlineKeyboardMarkup()
            if has_pending:
                keyboard.row(types.InlineKeyboardButton("📋 سجل السحوبات", callback_data="my_withdrawals", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمحفظة", callback_data="wallet", style="primary"))
                bot.edit_message_text(
                    f"🏧 {hb('طلب سحب الرصيد')}\n\n"
                    "⏳ لديك طلب سحب قيد المعالجة.\n"
                    "يرجى الانتظار حتى يتم البت فيه قبل تقديم طلب جديد.",
                    chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
                )
                return
            if balance < MIN_WITHDRAW:
                keyboard.row(types.InlineKeyboardButton("📥 شحن رصيد", callback_data="charge", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمحفظة", callback_data="wallet", style="primary"))
                bot.edit_message_text(
                    f"🏧 {hb('طلب سحب الرصيد')}\n\n"
                    f"رصيدك الحالي: {fmt_money(balance)}\n"
                    f"الحد الأدنى للسحب: {fmt_money(MIN_WITHDRAW)}\n\n"
                    "❌ رصيدك أقل من الحد الأدنى للسحب.",
                    chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
                )
                return
            if today_count >= MAX_WITHDRAWALS_PER_DAY:
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمحفظة", callback_data="wallet", style="primary"))
                bot.edit_message_text(
                    f"🏧 {hb('طلب سحب الرصيد')}\n\n"
                    f"⚠️ وصلت للحد الأقصى من طلبات السحب اليومية ({MAX_WITHDRAWALS_PER_DAY} طلبات).\n\n"
                    "حاول غداً.",
                    chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
                )
                return
            fee_text = ""
            if WITHDRAW_FEE_PERCENT > 0:
                fee_text = f"\nرسوم السحب: {WITHDRAW_FEE_PERCENT*100:.1f}%"
            keyboard.row(
                types.InlineKeyboardButton("💵 Binance USDT", callback_data="withdraw_method_binance", style="primary"),
                types.InlineKeyboardButton("📱 زين كاش", callback_data="withdraw_method_zaincash", style="primary")
            )
            keyboard.row(
                types.InlineKeyboardButton("📱 أسياسيل", callback_data="withdraw_method_asiacell", style="primary"),
                types.InlineKeyboardButton("💳 كي كارد", callback_data="withdraw_method_kycard", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("📋 سجل السحوبات", callback_data="my_withdrawals", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمحفظة", callback_data="wallet", style="primary"))
            db.set_user_state(user_id, "waiting_withdraw_method", {})
            bot.edit_message_text(
                f"🏧 {hb('طلب سحب الرصيد')}\n\n"
                f"💰 رصيدك المتاح: {hb(fmt_money(balance))}\n"
                f"📉 الحد الأدنى: {fmt_money(MIN_WITHDRAW)}"
                f"{fee_text}\n"
                f"📊 طلبات اليوم: {today_count}/{MAX_WITHDRAWALS_PER_DAY}\n\n"
                "اختر طريقة الاستلام:",
                chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
            )

        elif call.data == "my_withdrawals":
            safe_answer_callback_query(call.id)
            history = db.get_user_withdrawals(user_id)
            status_ar = {
                'pending': '⏳ قيد المعالجة',
                'approved': '✅ مقبول',
                'rejected': '❌ مرفوض'
            }
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمحفظة", callback_data="wallet", style="primary"))
            if not history:
                bot.edit_message_text(
                    f"📋 {hb('سجل السحوبات')}\n\nلا يوجد طلبات سحب بعد.",
                    chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
                )
                return
            lines = [f"📋 {hb('آخر طلبات السحب')}\n"]
            for w in history[:8]:
                st = status_ar.get(w['status'], w['status'])
                note = f" — {w['admin_note']}" if w.get('admin_note') else ""
                lines.append(f"#{w['request_id']} | {w['amount']:.2f}$ | {w['method']}\n{st}{note}\n{str(w['created_at'])[:16]}")
            bot.edit_message_text(
                "\n\n".join(lines),
                chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
            )

        elif call.data == "confirm_withdraw":
            user_state_wd = db.get_user_state(user_id)
            if not user_state_wd or user_state_wd['state'] != "confirming_withdraw":
                safe_answer_callback_query(call.id, "انتهت الجلسة!", show_alert=True)
                return
            wdata = user_state_wd['data']
            amount = wdata.get('amount', 0.0)
            method = wdata.get('method', '')
            address = wdata.get('address', '')
            balance = db.get_balance(user_id)
            if balance < amount:
                safe_answer_callback_query(call.id, "رصيدك غير كافٍ!", show_alert=True)
                db.clear_user_state(user_id)
                return
            if db.has_pending_withdrawal(user_id):
                safe_answer_callback_query(call.id, "لديك طلب سحب قيد المعالجة بالفعل!", show_alert=True)
                db.clear_user_state(user_id)
                return
            ok, msg, req_id = db.create_withdrawal_request(user_id, amount, method, address)
            db.clear_user_state(user_id)
            if not ok:
                safe_answer_callback_query(call.id, f"❌ {msg}", show_alert=True)
                return
            fee = round(amount * WITHDRAW_FEE_PERCENT, 4)
            net = round(amount - fee, 4)
            safe_answer_callback_query(call.id, "✅ تم إرسال طلب السحب!")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📋 سجل السحوبات", callback_data="my_withdrawals", style="primary"))
            keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
            fee_line = f"\nالرسوم: {fee:.2f}$ | الصافي: {net:.2f}$" if fee > 0 else ""
            bot.edit_message_text(
                f"✅ {hb('تم استلام طلب السحب!')}\n\n"
                f"🔢 رقم الطلب: #{req_id}\n"
                f"💵 المبلغ: {hb(fmt_money(amount))}{fee_line}\n"
                f"📲 طريقة الاستلام: {html_escape(method)}\n"
                f"📍 عنوان الاستلام: {hc(html_escape(address))}\n\n"
                f"⏳ سيتم معالجة طلبك خلال 24 ساعة.\n"
                f"💰 رصيدك الجديد: {fmt_money(db.get_balance(user_id))}",
                chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
            )
            # إشعار المالك
            try:
                u = db.get_user(user_id)
                name = f"@{u['username']}" if u and u['username'] else str(user_id)
                owner_kb = types.InlineKeyboardMarkup()
                owner_kb.row(
                    types.InlineKeyboardButton("✅ قبول", callback_data=f"approve_withdraw_{req_id}", style="primary"),
                    types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_withdraw_{req_id}", style="danger")
                )
                bot.send_message(
                    OWNER_ID,
                    f"🏧 *طلب سحب جديد #{req_id}*\n\n"
                    f"المستخدم: {name} (`{user_id}`)\n"
                    f"المبلغ: {amount:.2f}$"
                    + (f" | الصافي: {net:.2f}$" if fee > 0 else "") +
                    f"\nالطريقة: {method}\n"
                    f"العنوان: `{address}`\n"
                    f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    parse_mode="Markdown",
                    reply_markup=owner_kb
                )
            except Exception:
                pass


        elif call.data == "lucky_wheel":
            nav_push(user_id, "lucky_wheel")
            can_spin, remaining = db.can_spin_wheel(user_id)
            stats = db.get_wallet_stats(user_id)
            balance = db.get_balance(user_id)

            SEGS = ["0.005","0.010","0.015","0.020",
                    "0.025","0.030","0.035","0.040",
                    "0.045","0.050","0.055","0.060",
                    "0.065","0.070"]

            is_active = db.is_active_user_this_week(user_id)
            bonus_line = ""
            extra_rows = []
            if can_spin:
                extra_rows.append([types.InlineKeyboardButton("🎡 دور العجلة!", callback_data="spin_wheel", style="primary")])
            if is_active:
                can_spin_bonus, bonus_remaining = db.can_spin_bonus_wheel(user_id)
                if can_spin_bonus:
                    extra_rows.append([types.InlineKeyboardButton("🎁 الدورة الأسبوعية المجانية", callback_data="spin_bonus_wheel", style="primary")])
                    bonus_line = "\n🎁 لديك دورة أسبوعية مجانية إضافية (للمستخدمين النشطين)!"
                else:
                    d, h = bonus_remaining
                    bonus_line = f"\n🎁 الدورة الأسبوعية المجانية بعد: {d} يوم {h} ساعة"
            extra_rows.append([
                types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"),
                types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary")
            ])

            if can_spin:
                status = "✅ متاح للدوران الآن"
            else:
                h, m, s = remaining
                status = f"⏳ الوقت المتبقي: {h:02d}:{m:02d}:{s:02d}"

            text = (
                f"{DIVIDER}\n🎡 {hb('عجلة الحظ')}\n{DIVIDER}\n\n"
                f"رصيدك: {fmt_money(balance)} | {status}"
                f"{bonus_line}\n\n"
                f"الجائزة: 0.005$ — 0.070$ | مرة كل 24 ساعة\n"
                f"أرباحك من العجلة: {fmt_money(stats['wheel_total'])} | عدد الدورات: {stats['wheel_count']}"
            )
            keyboard = build_wheel_keyboard(SEGS, extra_rows=extra_rows)
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data == "spin_wheel":
            can_spin, remaining = db.can_spin_wheel(user_id)
            if not can_spin:
                h, m, s = remaining
                safe_answer_callback_query(call.id, f"انتظر {h:02d}:{m:02d}:{s:02d} قبل الدوران مجددا!", show_alert=True)
                return

            _rnd = random  # use top-level import

            SEGS = ["0.005","0.010","0.015","0.020",
                          "0.025","0.030","0.035","0.040",
                          "0.045","0.050","0.055","0.060",
                          "0.065","0.070"]
            SEG_VALUES = [round(0.005 + i*0.005, 3) for i in range(14)]
            weights = [1, 2, 3, 5, 7, 10, 12, 13, 12, 10, 8, 6, 4, 2]
            prize_idx = _rnd.choices(range(14), weights=weights, k=1)[0]
            prize = SEG_VALUES[prize_idx]

            # مسار الدوران
            total_steps = _rnd.randint(30, 45)
            pos = _rnd.randint(0, 13)
            path = []
            for _ in range(total_steps - 1):
                path.append(pos)
                pos = (pos + 1) % 14
            path.append(prize_idx)

            # تأخيرات: سريع → بطيء
            delays = []
            for i in range(total_steps):
                p = i / total_steps
                if p < 0.35: delays.append(0.07)
                elif p < 0.60: delays.append(0.13)
                elif p < 0.78: delays.append(0.22)
                elif p < 0.90: delays.append(0.38)
                else: delays.append(0.55)

            def phase(i, total):
                p = i / total
                if p < 0.35: return "تدور بسرعة..."
                elif p < 0.60: return "تتباطأ..."
                elif p < 0.80: return "تقترب..."
                elif p < 0.92: return "توشك على التوقف..."
                else: return "تتوقف..."

            prev_text = ""
            bal_now = db.get_balance(user_id)
            for step_i, active in enumerate(path):
                frame_text = (
                    f"{DIVIDER}\n🎡 عجلة الحظ — {phase(step_i, total_steps)}\n{DIVIDER}\n\n"
                    f"رصيدك: {fmt_money(bal_now)}"
                )
                spin_glyph = WHEEL_SPIN_GLYPHS[step_i % len(WHEEL_SPIN_GLYPHS)]
                frame_kb = build_wheel_keyboard(SEGS, active_idx=active, spin_glyph=spin_glyph)
                if frame_text != prev_text:
                    try:
                        bot.edit_message_text(frame_text, chat_id, message_id, reply_markup=frame_kb)
                        prev_text = frame_text
                    except Exception:
                        try:
                            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=frame_kb)
                        except Exception:
                            pass
                else:
                    try:
                        bot.edit_message_reply_markup(chat_id, message_id, reply_markup=frame_kb)
                    except Exception:
                        pass
                time.sleep(delays[step_i])

            # النتيجة
            success = db.record_spin(user_id, prize)
            if success:
                new_balance = db.get_balance(user_id)
                stats = db.get_wallet_stats(user_id)
                extra_rows = [[
                    types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"),
                    types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary")
                ]]
                keyboard = build_wheel_keyboard(SEGS, won_idx=prize_idx, extra_rows=extra_rows)
                text = (
                    f"{DIVIDER}\n🎡 عجلة الحظ — توقفت! 🎯\n{DIVIDER}\n\n"
                    f"🎉 مبروك! +{fmt_money(prize)}\n\n"
                    f"رصيدك الجديد: {fmt_money(new_balance)}\n"
                    f"مجموع أرباحك: {fmt_money(stats['wheel_total'])} | {stats['wheel_count']} دورة\n\n"
                    f"يمكنك الدوران مجدداً بعد 24 ساعة"
                )
                try:
                    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
                except Exception:
                    bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")
            else:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 حاول مجدداً", callback_data="spin_wheel", style="primary"), types.InlineKeyboardButton("🔙 رجوع", callback_data="lucky_wheel", style="primary"))
                bot.edit_message_text("حدث خطأ، حاول مجدداً.", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "spin_bonus_wheel":
            if not db.is_active_user_this_week(user_id):
                safe_answer_callback_query(call.id, "هذه الدورة للمستخدمين النشطين فقط (مزايدة/طلب وساطة/شحن خلال آخر أسبوع)!", show_alert=True)
                return
            can_spin_bonus, bonus_remaining = db.can_spin_bonus_wheel(user_id)
            if not can_spin_bonus:
                d, h = bonus_remaining
                safe_answer_callback_query(call.id, f"انتظر {d} يوم و{h} ساعة قبل الدورة الأسبوعية القادمة!", show_alert=True)
                return

            _rnd = random

            SEGS_B = ["0.020","0.040","0.060","0.080",
                      "0.100","0.120","0.140","0.160",
                      "0.180","0.200","0.220","0.240",
                      "0.260","0.280"]
            SEG_VALUES_B = [round(0.020 + i*0.020, 3) for i in range(14)]
            weights_b = [1, 2, 3, 5, 7, 10, 12, 13, 12, 10, 8, 6, 4, 2]
            prize_idx_b = _rnd.choices(range(14), weights=weights_b, k=1)[0]
            prize_b = SEG_VALUES_B[prize_idx_b]

            total_steps = _rnd.randint(30, 45)
            pos = _rnd.randint(0, 13)
            path = []
            for _ in range(total_steps - 1):
                path.append(pos)
                pos = (pos + 1) % 14
            path.append(prize_idx_b)

            delays = []
            for i in range(total_steps):
                p = i / total_steps
                if p < 0.35: delays.append(0.07)
                elif p < 0.60: delays.append(0.13)
                elif p < 0.78: delays.append(0.22)
                elif p < 0.90: delays.append(0.38)
                else: delays.append(0.55)

            def phase_b(i, total):
                p = i / total
                if p < 0.35: return "تدور بسرعة..."
                elif p < 0.60: return "تتباطأ..."
                elif p < 0.80: return "تقترب..."
                elif p < 0.92: return "توشك على التوقف..."
                else: return "تتوقف..."

            prev_text = ""
            bal_now = db.get_balance(user_id)
            for step_i, active in enumerate(path):
                frame_text = (
                    f"{DIVIDER}\n🎁 الدورة الأسبوعية المجانية — {phase_b(step_i, total_steps)}\n{DIVIDER}\n\n"
                    f"رصيدك: {fmt_money(bal_now)}"
                )
                spin_glyph = WHEEL_SPIN_GLYPHS[step_i % len(WHEEL_SPIN_GLYPHS)]
                frame_kb = build_wheel_keyboard(SEGS_B, active_idx=active, spin_glyph=spin_glyph)
                if frame_text != prev_text:
                    try:
                        bot.edit_message_text(frame_text, chat_id, message_id, reply_markup=frame_kb)
                        prev_text = frame_text
                    except Exception:
                        try:
                            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=frame_kb)
                        except Exception:
                            pass
                else:
                    try:
                        bot.edit_message_reply_markup(chat_id, message_id, reply_markup=frame_kb)
                    except Exception:
                        pass
                time.sleep(delays[step_i])

            success = db.record_bonus_spin(user_id, prize_b)
            if success:
                new_balance = db.get_balance(user_id)
                extra_rows = [[
                    types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"),
                    types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary")
                ]]
                keyboard = build_wheel_keyboard(SEGS_B, won_idx=prize_idx_b, extra_rows=extra_rows)
                text = (
                    f"{DIVIDER}\n🎁 الدورة الأسبوعية — توقفت! 🎯\n{DIVIDER}\n\n"
                    f"🎉 مبروك! +{fmt_money(prize_b)}\n\n"
                    f"رصيدك الجديد: {fmt_money(new_balance)}\n\n"
                    f"شكراً لنشاطك! دورتك الأسبوعية المجانية القادمة بعد 7 أيام"
                )
                try:
                    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
                except Exception:
                    bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")
            else:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="lucky_wheel", style="primary"))
                bot.edit_message_text("حدث خطأ، حاول مجدداً.", chat_id, message_id, reply_markup=keyboard)


        # أزرار قطاعات عجلة الحظ — لمسة تفاعلية (عرض قيمة القطاع) بدون أي تأثير على نتيجة الدوران 
        elif call.data.startswith("wheel_info_"):
            value = call.data.replace("wheel_info_", "")
            safe_answer_callback_query(call.id, f"💰 قيمة هذا القطاع: {value}$")

        elif call.data == "wheel_spin_indicator":
            safe_answer_callback_query(call.id)

        elif call.data == "transfer_money":
            nav_push(user_id, "transfer_money")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ تحويل عبر الايدي", callback_data="transfer_by_id", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 إنشاء رابط هدية", callback_data="transfer_gift_link", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 إنشاء كود تحويل", callback_data="transfer_create_code", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمحفظة", callback_data="wallet", style="primary"))
            balance = db.get_balance(user_id)
            text = (
                f"\n"
                f"تحويل رصيد \n"
                f"\n\n"
                f"رصيدك المتاح: {balance:.2f}$\n"
                f"العمولة: {TRANSFER_COMMISSION_RATE*100:.0f}%\n\n"
                f"اختر طريقة التحويل \n\n"
                f"عبر الايدي\n"
                f"تحويل مباشر لمستخدم بايديه\n\n"
                f"رابط هدية\n"
                f"رابط يحصل منه اي شخص على الرصيد\n"
                f" (يُخصم فور الإنشاء)\n\n"
                f"كود تحويل\n"
                f"كود يدخله المستلم مرة واحدة فقط\n"
                f" (يُخصم فور الإنشاء)"
            )
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)

        elif call.data == "transfer_by_id":
            db.set_user_state(user_id, "waiting_transfer_user_id")
            balance = db.get_balance(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="transfer_money", style="primary"))
            text = (
                f"\n"
                f"تحويل عبر الايدي \n"
                f"\n\n"
                f"رصيدك المتاح: {balance:.2f}$\n"
                f"العمولة: {TRANSFER_COMMISSION_RATE*100:.0f}%\n\n"
                f"ارسل ايدي المستخدم الذي تريد التحويل له:"
            )
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)

        elif call.data == "transfer_gift_link":
            db.set_user_state(user_id, "waiting_gift_link_amount")
            balance = db.get_balance(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="transfer_money", style="primary"))
            text = (
                f"\n"
                f"رابط هدية \n"
                f"\n\n"
                f"رصيدك المتاح: {balance:.2f}$\n\n"
                f"سيتم خصم المبلغ فور إنشاء الرابط.\n"
                f"الرابط صالح لمرة واحدة فقط.\n\n"
                f"ارسل المبلغ بالدولار ($):"
            )
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)

        elif call.data == "transfer_create_code":
            db.set_user_state(user_id, "waiting_transfer_code_amount")
            balance = db.get_balance(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="transfer_money", style="primary"))
            text = (
                f"\n"
                f"كود تحويل \n"
                f"\n\n"
                f"رصيدك المتاح: {balance:.2f}$\n\n"
                f"سيتم خصم المبلغ فور إنشاء الكود.\n"
                f"الكود صالح لمرة واحدة فقط.\n\n"
                f"ارسل المبلغ بالدولار ($):"
            )
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        elif call.data == "skip_location_verify":
            # الموقع إجباري — لا يمكن التخطي
            safe_answer_callback_query(call.id, "الموقع إجباري ولا يمكن تخطيه!", show_alert=True)

        # تحكم الأدمن في وقت المزاد (تمديد / تقليص) 
        elif call.data.startswith("admin_extend_auction_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            auction_id = call.data.replace("admin_extend_auction_", "")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("🔹 +15 دق", callback_data=f"admin_ext_{auction_id}_15", style="primary"),
                types.InlineKeyboardButton("🔹 +30 دق", callback_data=f"admin_ext_{auction_id}_30", style="primary"),
                types.InlineKeyboardButton("🔹 +60 دق", callback_data=f"admin_ext_{auction_id}_60", style="primary"),
            )
            keyboard.row(
                types.InlineKeyboardButton("🔹 -15 دق", callback_data=f"admin_ext_{auction_id}_-15", style="primary"),
                types.InlineKeyboardButton("🔹 -30 دق", callback_data=f"admin_ext_{auction_id}_-30", style="primary"),
                types.InlineKeyboardButton("🔹 -60 دق", callback_data=f"admin_ext_{auction_id}_-60", style="primary"),
            )
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            auction_info = db.get_auction_by_id(auction_id)
            ends_at = db.parse_datetime(auction_info['ends_at']) if auction_info else None
            remaining = ""
            if ends_at:
                diff = ends_at - datetime.now()
                if diff.total_seconds() > 0:
                    h = int(diff.total_seconds() // 3600)
                    m = int((diff.total_seconds() % 3600) // 60)
                    remaining = f"المتبقي: {h}:{m:02d}"
            bot.edit_message_text(
                f" *تحكم في وقت المزاد #{auction_id}*\n\n{remaining}\n\nاختر مقدار التمديد أو التقليص:",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data.startswith("admin_ext_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            parts = call.data.replace("admin_ext_", "").rsplit('_', 1)
            if len(parts) != 2:
                safe_answer_callback_query(call.id, "بيانات غير صحيحة")
                return
            auction_id, mins_str = parts
            minutes = int(mins_str)
            success, result = db.extend_auction_time(auction_id, minutes)
            if success:
                new_ends = result
                diff = new_ends - datetime.now()
                h = int(diff.total_seconds() // 3600)
                m = int((diff.total_seconds() % 3600) // 60)
                action = "تمديد" if minutes > 0 else "تقليص"
                safe_answer_callback_query(call.id, f"تم {action} الوقت")
                update_auction_broadcast(auction_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text(
                    f"تم {action} وقت المزاد #{auction_id}\n\n"
                    f"المتبقي الجديد: {h}:{m:02d}",
                    chat_id, message_id, reply_markup=keyboard
                )
            else:
                safe_answer_callback_query(call.id, f" {result}")

        # إدارة المستخدمين المتقدمة 
        elif call.data == "admin_user_detail":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_searching_user_detail")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.edit_message_text(
                " *بحث عن مستخدم*\n\n"
                "أرسل أحد التالي:\n"
                "• أيدي المستخدم (رقم)\n"
                "• @معرفه\n"
                "• اسمه\n\n"
                "ستظهر لك النتائج كاملة.",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data.startswith("admin_view_user_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            target_uid = int(call.data.replace("admin_view_user_", ""))
            _show_user_detail(call, target_uid, chat_id, message_id)

        elif call.data.startswith("admin_ban_user_detail_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            target_uid = int(call.data.replace("admin_ban_user_detail_", ""))
            db.ban_user(target_uid, "حظر من لوحة الإدارة", user_id)
            try:
                bot.send_message(target_uid, "تم حظر حسابك من استخدام البوت.")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم الحظر")
            _show_user_detail(call, target_uid, chat_id, message_id)

        elif call.data.startswith("admin_unban_user_detail_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            target_uid = int(call.data.replace("admin_unban_user_detail_", ""))
            db.unban_user(target_uid)
            try:
                bot.send_message(target_uid, "تم رفع الحظر عن حسابك.")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم رفع الحظر")
            _show_user_detail(call, target_uid, chat_id, message_id)

        elif call.data.startswith("admin_add_bal_user_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            target_uid = int(call.data.replace("admin_add_bal_user_", ""))
            db.set_user_state(user_id, "admin_direct_add_bal_single", {"target_uid": target_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_view_user_{target_uid}", style="danger"))
            bot.edit_message_text(
                f"أرسل المبلغ المراد إضافته للمستخدم {target_uid}:",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_deduct_bal_user_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            target_uid = int(call.data.replace("admin_deduct_bal_user_", ""))
            db.set_user_state(user_id, "admin_direct_deduct_bal_single", {"target_uid": target_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_view_user_{target_uid}", style="danger"))
            bot.edit_message_text(
                f"أرسل المبلغ المراد خصمه من المستخدم {target_uid}:",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_manage_auction_extend_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            auction_id = call.data.replace("admin_manage_auction_extend_", "")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("🔹 +15 دق", callback_data=f"admin_ext_{auction_id}_15", style="primary"),
                types.InlineKeyboardButton("🔹 +30 دق", callback_data=f"admin_ext_{auction_id}_30", style="primary"),
                types.InlineKeyboardButton("🔹 +1 ساعة", callback_data=f"admin_ext_{auction_id}_60", style="primary"),
            )
            keyboard.row(
                types.InlineKeyboardButton("🔹 -15 دق", callback_data=f"admin_ext_{auction_id}_-15", style="primary"),
                types.InlineKeyboardButton("🔹 -30 دق", callback_data=f"admin_ext_{auction_id}_-30", style="primary"),
                types.InlineKeyboardButton("🔹 -1 ساعة", callback_data=f"admin_ext_{auction_id}_-60", style="primary"),
            )
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            auction_info = db.get_auction_by_id(auction_id)
            ends_at = db.parse_datetime(auction_info['ends_at']) if auction_info else None
            remaining = ""
            if ends_at:
                diff = ends_at - datetime.now()
                if diff.total_seconds() > 0:
                    h = int(diff.total_seconds() // 3600)
                    m = int((diff.total_seconds() % 3600) // 60)
                    remaining = f"المتبقي: {h}:{m:02d}"
            bot.edit_message_text(
                f"تحكم في وقت المزاد #{auction_id}\n\n{remaining}",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("withdraw_method_") and not call.data.startswith("withdraw_method_confirm_"):
            method_key = call.data.replace("withdraw_method_", "")
            method_names = {"binance": "Binance USDT", "asiacell": "أسياسيل", "zaincash": "زين كاش", "kycard": "كي كارد", "USDT": "USDT (TRC20)", "ZainCash": "زين كاش", "Asiacell": "أسياسيل", "KyCard": "كي كارد"}
            method = method_names.get(method_key, method_key)
            safe_answer_callback_query(call.id)
            balance = db.get_balance(user_id)
            if db.has_pending_withdrawal(user_id):
                safe_answer_callback_query(call.id, "لديك طلب سحب قيد المعالجة!", show_alert=True)
                return
            hint_map = {
                "binance":   "عنوان محفظة USDT (TRC20 أو BEP20)",
                "asiacell":  "رقم هاتف أسياسيل",
                "zaincash":  "رقم هاتف زين كاش",
                "kycard":    "رقم كي كارد الخاص بك",
                "USDT":      "عنوان محفظة USDT (TRC20)",
                "ZainCash":  "رقم هاتف زين كاش",
                "Asiacell":  "رقم هاتف أسياسيل",
                "KyCard":    "رقم كي كارد الخاص بك",
            }
            hint = hint_map.get(method_key, "تفاصيل الاستلام")
            fee_text = f"\nرسوم: {WITHDRAW_FEE_PERCENT*100:.1f}% — الصافي يحسب عند التأكيد" if WITHDRAW_FEE_PERCENT > 0 else ""
            db.set_user_state(user_id, "waiting_withdraw_amount", {"method": method, "method_key": method_key, "hint": hint})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="withdraw_request", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="wallet", style="danger"))
            bot.edit_message_text(
                f"🏧 {hb('سحب الرصيد')} — {html_escape(method)}\n\n"
                f"💰 رصيدك: {hb(fmt_money(balance))}\n"
                f"📉 الحد الأدنى: {fmt_money(MIN_WITHDRAW)}"
                f"{fee_text}\n\n"
                f"أرسل المبلغ الذي تريد سحبه بالدولار:\nمثال: 10",
                chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
            )

        elif call.data == "admin_pending_withdrawals":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            safe_answer_callback_query(call.id)
            pending = db.get_pending_withdrawals()
            if not pending:
                try:
                    bot.edit_message_text(
                        "📤 *طلبات السحب المعلقة*\n\n✅ لا توجد طلبات معلقة حالياً.",
                        chat_id, message_id,
                        reply_markup=types.InlineKeyboardMarkup().row(
                            types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary")
                        ),
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                return
            summary_lines = [f"📤 *طلبات السحب المعلقة ({len(pending)})*\n"]
            for req in pending:
                name = f"@{req['username']}" if req['username'] else (req['first_name'] or f"ID {req['user_id']}")
                fee = round(req['amount'] * WITHDRAW_FEE_PERCENT, 4)
                net = round(req['amount'] - fee, 4)
                net_text = f" | صافي: {net:.2f}$" if fee > 0 else ""
                summary_lines.append(
                    f"#{req['request_id']} | {name} | {req['amount']:.2f}${net_text}\n"
                    f"{req['method']} — `{req['details']}`\n"
                    f"🕐 {str(req['created_at'])[:16]}"
                )
            try:
                bot.edit_message_text(
                    "\n\n".join(summary_lines),
                    chat_id, message_id,
                    reply_markup=types.InlineKeyboardMarkup().row(
                        types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary")
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(chat_id, "\n\n".join(summary_lines), parse_mode="Markdown")
            # إرسال كل طلب برسالة منفصلة مع أزرار القبول/الرفض
            for req in pending[:8]:
                name = f"@{req['username']}" if req['username'] else (req['first_name'] or f"ID {req['user_id']}")
                fee = round(req['amount'] * WITHDRAW_FEE_PERCENT, 4)
                net = round(req['amount'] - fee, 4)
                net_line = f"\nالصافي: {net:.2f}$" if fee > 0 else ""
                kb = types.InlineKeyboardMarkup()
                kb.row(
                    types.InlineKeyboardButton("✅ قبول", callback_data=f"approve_withdraw_{req['request_id']}", style="primary"),
                    types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_withdraw_{req['request_id']}", style="danger")
                )
                bot.send_message(
                    chat_id,
                    f"🏧 *طلب سحب #{req['request_id']}*\n\n"
                    f"👤 المستخدم: {name} (`{req['user_id']}`)\n"
                    f"💵 المبلغ: {req['amount']:.2f}${net_line}\n"
                    f"📲 الطريقة: {req['method']}\n"
                    f"📍 العنوان: `{req['details']}`\n"
                    f"🕐 التاريخ: {str(req['created_at'])[:16]}",
                    reply_markup=kb,
                    parse_mode="Markdown"
                )

        elif call.data.startswith("approve_withdraw_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            req_id = int(call.data.replace("approve_withdraw_", ""))
            ok, result = db.approve_withdrawal(req_id)
            if ok:
                target_uid = result['user_id']
                net = result['net']
                method = result['method']
                details = result['details']
                safe_answer_callback_query(call.id, f"✅ تم قبول طلب السحب #{req_id}")
                try:
                    bot.send_message(
                        target_uid,
                        f"✅ *تم قبول طلب السحب #{req_id}!*\n\n"
                        f"💵 الصافي المحول: {net:.2f}$\n"
                        f"📲 الطريقة: {method}\n"
                        f"📍 العنوان: `{details}`\n\n"
                        f"تم إرسال المبلغ. شكراً لثقتك!",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                try:
                    bot.edit_message_text(
                        f"✅ تم قبول طلب السحب #{req_id}\nالصافي: {net:.2f}$ عبر {method}",
                        chat_id, message_id
                    )
                except Exception:
                    pass
            else:
                safe_answer_callback_query(call.id, f"❌ {result}", show_alert=True)

        elif call.data.startswith("reject_withdraw_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            req_id = int(call.data.replace("reject_withdraw_", ""))
            # طلب سبب الرفض
            db.set_user_state(user_id, f"waiting_reject_withdraw_reason_{req_id}", {})
            safe_answer_callback_query(call.id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("⚡ رفض بدون سبب", callback_data=f"reject_withdraw_confirm_{req_id}_", style="danger"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="primary"))
            try:
                bot.edit_message_text(
                    f"❌ *رفض طلب السحب #{req_id}*\n\nأرسل سبب الرفض (أو اضغط رفض بدون سبب):",
                    chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(chat_id, f"أرسل سبب رفض طلب السحب #{req_id}:", reply_markup=keyboard)

        elif call.data.startswith("reject_withdraw_confirm_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            parts = call.data.replace("reject_withdraw_confirm_", "").split("_", 1)
            req_id = int(parts[0])
            reason = parts[1] if len(parts) > 1 else ""
            db.clear_user_state(user_id)
            ok, result = db.reject_withdrawal(req_id, admin_note=reason)
            if ok:
                target_uid = result['user_id']
                amount = result['amount']
                method = result['method']
                safe_answer_callback_query(call.id, f"تم رفض الطلب #{req_id} وإعادة الرصيد")
                try:
                    reason_line = f"\nالسبب: {reason}" if reason else ""
                    bot.send_message(
                        target_uid,
                        f"❌ *تم رفض طلب السحب #{req_id}*\n\n"
                        f"💵 المبلغ: {amount:.2f}$ (أُعيد لرصيدك)"
                        f"{reason_line}\n\n"
                        f"إذا كان هناك خطأ، تواصل مع الإدارة.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                try:
                    bot.edit_message_text(
                        f"❌ تم رفض طلب السحب #{req_id}\nأُعيد {amount:.2f}$ لرصيد المستخدم.",
                        chat_id, message_id
                    )
                except Exception:
                    pass
            else:
                safe_answer_callback_query(call.id, f"❌ {result}", show_alert=True)

        elif call.data == "show_agents":
            safe_answer_callback_query(call.id)
            agents = db.get_all_agents()
            keyboard = types.InlineKeyboardMarkup()
            if not agents:
                text = " *قائمة الوكلاء*\n\nلا يوجد وكلاء مسجلون حالياً.\nالوكلاء يبيعون رصيداً مباشرة للمستخدمين."
            else:
                text = " *الوكلاء المعتمدون*\n\nاختر وكيلاً للتواصل معه:"
                for ag in agents:
                    safe_name = ag['name'].replace('*','').replace('_','').replace('`','').replace('[','')
                    keyboard.row(types.InlineKeyboardButton(
                        f" {safe_name}", callback_data=f"agent_detail_{ag['user_id']}", style="primary"
                    ))
            keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("agent_detail_"):
            agent_uid = int(call.data.replace("agent_detail_", ""))
            # بحث مباشر في قاعدة البيانات بدل الاعتماد على get_all_agents فقط
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT a.user_id, a.name, a.description, a.contact, a.is_active, "
                "u.username, u.first_name "
                "FROM agents a LEFT JOIN users u ON a.user_id=u.user_id "
                "WHERE a.user_id=? AND a.is_active=1",
                (agent_uid,)
            )
            ag_row = cursor.fetchone()
            if not ag_row:
                safe_answer_callback_query(call.id, "الوكيل غير موجود!", show_alert=True)
                return
            safe_answer_callback_query(call.id)
            ag = {
                'user_id': ag_row[0], 'name': ag_row[1] or '', 'description': ag_row[2] or '',
                'contact': ag_row[3] or '', 'is_active': ag_row[4],
                'username': ag_row[5], 'first_name': ag_row[6]
            }
            safe_name = ag['name'].replace('*','').replace('_','').replace('`','').replace('[','') or f"وكيل {agent_uid}"
            safe_desc = ag['description'].replace('*','').replace('_','').replace('`','').replace('[','')
            # تحديد معلومات التواصل — أولوية: username من users، ثم contact المحفوظ
            if ag['username']:
                contact_display = f"@{ag['username']}"
                contact_url = f"https://t.me/{ag['username']}"
            elif ag['contact'] and ag['contact'].startswith('@'):
                uname_clean = ag['contact'].lstrip('@')
                contact_display = ag['contact']
                contact_url = f"https://t.me/{uname_clean}"
            elif ag['contact']:
                contact_display = ag['contact']
                contact_url = None
            else:
                contact_display = f"ID: {agent_uid}"
                contact_url = f"tg://user?id={agent_uid}"
            # إحصائيات التقييم 
            rating_stats = db.get_agent_rating_stats(agent_uid)
            cursor.execute(
                "SELECT COUNT(*) FROM agent_charge_requests WHERE agent_user_id=? AND status='admin_approved'",
                (agent_uid,)
            )
            completed_requests = cursor.fetchone()[0] or 0
            if rating_stats['count'] > 0:
                avg = rating_stats['avg']
                full = int(avg)
                stars_str = "" * full + ("" if avg - full >= 0.5 else "")
                rating_line = f"\n التقييم: {stars_str} {avg:.1f}/5 ({rating_stats['count']} تقييم)"
            else:
                rating_line = "\n التقييم: لا يوجد تقييمات بعد"
            text = (
                f" *{safe_name}*\n\n"
                f"التواصل: {contact_display}\n"
                + (f"الوصف: {safe_desc}\n" if safe_desc else "") +
                f"الطلبات المكتملة: {completed_requests}" +
                rating_line +
                "\n\nاختر ما تريد:"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📥 طلب شحن رصيد", callback_data=f"req_agent_charge_{agent_uid}", style="primary"))
            if contact_url:
                keyboard.row(types.InlineKeyboardButton(f"تواصل مع الوكيل", url=contact_url, style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 عرض التقييمات", callback_data=f"view_agent_ratings_{agent_uid}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ بلاغ على هذا الوكيل", callback_data=f"report_agent_{agent_uid}", style="danger"))
            keyboard.row(types.InlineKeyboardButton("❌ قائمة الوكلاء", callback_data="show_agents", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("req_agent_charge_"):
            agent_uid = int(call.data.replace("req_agent_charge_", ""))
            db.set_user_state(user_id, "waiting_agent_charge_reason", {"agent_uid": agent_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"agent_detail_{agent_uid}", style="danger"))
            bot.edit_message_text(
                " *طلب شحن رصيد عبر وكيل*\n\n"
                "أرسل *سبب* طلبك وكمية الرصيد التي تريدها:\n\n"
                "مثال: أريد شحن $10 لاستخدامه في المزادات",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data.startswith("report_agent_"):
            agent_uid = int(call.data.replace("report_agent_", ""))
            db.set_user_state(user_id, "waiting_agent_report_code", {"agent_uid": agent_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="show_agents", style="danger"))
            bot.edit_message_text(
                " *بلاغ على وكيل*\n\n"
                "أرسل *كود عملية الشحن* الذي أجريتها مع هذا الوكيل\n"
                "(الكود الذي أرسله لك الوكيل عند الشحن):",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data == "show_brokers":
            safe_answer_callback_query(call.id)
            brokers = db.get_all_brokers()
            keyboard = types.InlineKeyboardMarkup()
            if not brokers:
                text = " *قائمة الوسطاء*\n\nلا يوجد وسطاء مسجلون حالياً.\nالوسطاء يضمنون صفقات البيع والشراء بين الطرفين."
            else:
                text = " *الوسطاء المعتمدون*\n\nاختر وسيطاً لطلب خدمته:"
                for br in brokers:
                    safe_name = br['name'].replace('*','').replace('_','').replace('`','').replace('[','')
                    keyboard.row(types.InlineKeyboardButton(
                        f" {safe_name}", callback_data=f"broker_detail_{br['user_id']}", style="primary"
                    ))
            keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("broker_detail_"):
            broker_uid = int(call.data.replace("broker_detail_", ""))
            # بحث مباشر بدل الاعتماد على get_all_brokers
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT b.user_id, b.name, b.description, b.contact, b.is_active, "
                "u.username, u.first_name "
                "FROM brokers b LEFT JOIN users u ON b.user_id=u.user_id "
                "WHERE b.user_id=? AND b.is_active=1",
                (broker_uid,)
            )
            br_row = cursor.fetchone()
            if not br_row:
                safe_answer_callback_query(call.id, "الوسيط غير موجود!", show_alert=True)
                return
            safe_answer_callback_query(call.id)
            br = {
                'user_id': br_row[0], 'name': br_row[1] or '', 'description': br_row[2] or '',
                'contact': br_row[3] or '', 'is_active': br_row[4],
                'username': br_row[5], 'first_name': br_row[6]
            }
            safe_name = md_escape(br['name']) or f"وسيط {broker_uid}"
            safe_desc = md_escape(br['description'])
            # تحديد معلومات التواصل
            if br['username']:
                contact_display = f"@{md_escape(br['username'])}"
                contact_url = f"https://t.me/{br['username']}"
            elif br['contact'] and br['contact'].startswith('@'):
                uname_clean = br['contact'].lstrip('@')
                contact_display = br['contact']
                contact_url = f"https://t.me/{uname_clean}"
            elif br['contact']:
                contact_display = md_escape(br['contact'])
                contact_url = None
            else:
                contact_display = f"ID: {broker_uid}"
                contact_url = f"tg://user?id={broker_uid}"
            # رابط/معرف المجموعة 
            broker_group_link = db.get_bot_setting('broker_group_link') or ''
            broker_group_id_str = db.get_bot_setting('broker_group_id') or ''
            group_invite_url = broker_group_link # الرابط المحفوظ أولاً — لا نستدعي API إلا عند الضرورة
            if broker_group_id_str and not group_invite_url:
                try:
                    grp_chat_id = int(broker_group_id_str)
                    invite = bot.export_chat_invite_link(grp_chat_id)
                    if invite:
                        group_invite_url = invite
                        db.set_bot_setting('broker_group_link', invite)
                except Exception as _inv_e:
                    logger.warning(f"export_chat_invite_link failed: {_inv_e}")
            # إحصائيات التقييم 
            rating_stats = db.get_broker_rating_stats(broker_uid)
            cursor.execute(
                "SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status='approved'",
                (broker_uid,)
            )
            completed_requests = cursor.fetchone()[0] or 0
            if rating_stats['count'] > 0:
                avg = rating_stats['avg']
                full = int(avg)
                stars_str = "" * full + ("" if avg - full >= 0.5 else "")
                rating_line = f"\n التقييم: {stars_str} {avg:.1f}/5 ({rating_stats['count']} تقييم)"
            else:
                rating_line = "\n التقييم: لا يوجد تقييمات بعد"
            text = (
                f" *{safe_name}*\n\n"
                f"التواصل: {contact_display}\n"
                + (f"الوصف: {safe_desc}\n" if safe_desc else "") +
                f"الصفقات المكتملة: {completed_requests}" +
                rating_line +
                "\n\n *كيف تعمل الوساطة؟*\n"
                "• تقدم طلبك هنا داخل البوت\n"
                "• الوسيط يراجع طلبك ويوافق أو يرفض\n"
                "• بعد الموافقة تُدعى لمجموعة الوساطة الخاصة\n"
                "• الوسيط يضمن حق الطرفين في الصفقة\n"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 تقديم طلب وساطة", callback_data=f"req_broker_{broker_uid}", style="primary"))
            if contact_url:
                keyboard.row(types.InlineKeyboardButton("🔹 تواصل مع الوسيط", url=contact_url, style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 عرض التقييمات", callback_data=f"view_broker_ratings_{broker_uid}", style="primary"))
            if group_invite_url:
                keyboard.row(types.InlineKeyboardButton("❌ الانضمام لمجموعة الوساطة", url=group_invite_url, style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 قائمة الوسطاء", callback_data="show_brokers", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("req_broker_"):
            broker_uid = int(call.data.replace("req_broker_", ""))
            BROKER_SERVICE_TYPES = {
                "sell_username": "بيع يوزر / معرف",
                "sell_account": "بيع حساب تيليجرام",
                "sell_channel": "بيع قناة",
                "sell_group": "بيع مجموعة",
                "sell_bot": "بيع بوت",
                "sell_social": "بيع معرفات",
                "buy_other": "شراء منتج آخر",
            }
            db.set_user_state(user_id, "waiting_broker_service_type", {"broker_uid": broker_uid})
            keyboard = types.InlineKeyboardMarkup()
            for key, label in BROKER_SERVICE_TYPES.items():
                keyboard.row(types.InlineKeyboardButton(label, callback_data=f"broker_svc_{broker_uid}_{key}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"broker_detail_{broker_uid}", style="primary"))
            bot.edit_message_text(
                " *طلب وساطة — الخطوة 1/2*\n\nما نوع الصفقة التي تحتاج وسيطاً فيها؟",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data.startswith("broker_svc_"):
            parts = call.data.replace("broker_svc_", "").split("_", 1)
            broker_uid = int(parts[0])
            service_key = parts[1] if len(parts) > 1 else "other"
            db.set_user_state(user_id, "waiting_broker_request_details", {"broker_uid": broker_uid, "service_type": service_key})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"broker_detail_{broker_uid}", style="danger"))
            bot.edit_message_text(
                " *طلب وساطة — الخطوة 2/2*\n\n"
                "اشرح تفاصيل صفقتك:\n"
                "• ما الذي تريد بيعه أو شراءه؟\n"
                "• ما السعر المتوقع؟\n"
                "• أي معلومات تساعد الوسيط على فهم طلبك",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data == "noop_broker":
            safe_answer_callback_query(call.id, "تواصل مع الوسيط عبر المعرف المذكور في النص.", show_alert=True)

        elif call.data == "noop_agent":
            safe_answer_callback_query(call.id, "تواصل مع الوكيل عبر المعرف المذكور في النص.", show_alert=True)

        # إدارة الوكلاء (أدمن) — قائمة تفاعلية + تحكم كامل بكل وكيل 
        elif call.data == "admin_agents":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agents = db.get_all_agents()
            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM agent_charge_requests WHERE status IN ('pending','agent_approved')")
            total_pending = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COALESCE(SUM(amount),0) FROM agent_profits")
            total_profit_all = cursor.fetchone()[0] or 0.0
            text = f"{DIVIDER}\n{hb('🧑‍💼 إدارة الوكلاء')}\n{DIVIDER}\n\n"
            text += f"العدد: {len(agents)} | ⏳ طلبات معلقة: {total_pending} | 💰 إجمالي الأرباح: {fmt_money(total_profit_all)}\n\n"
            text += "اختر وكيلاً لعرض ملفه الكامل ومعلوماته وتحليل عمله، أو للتحكم به (تنبيه / بلاغ / حذف):" if agents else "لا يوجد وكلاء بعد."
            keyboard = types.InlineKeyboardMarkup()
            for ag in agents:
                rating = db.get_agent_rating_stats(ag['user_id'])
                cursor.execute("SELECT COUNT(*) FROM agent_charge_requests WHERE agent_user_id=? AND status IN ('pending','agent_approved')", (ag['user_id'],))
                pend = cursor.fetchone()[0] or 0
                label = f"🧑‍💼 {ag['name'] or ag['user_id']}"
                if rating['count'] > 0:
                    label += f" ⭐{rating['avg']:.1f}"
                if pend > 0:
                    label += f" ⏳{pend}"
                keyboard.row(types.InlineKeyboardButton(label, callback_data=f"admin_agent_detail_{ag['user_id']}", style="primary"))
            keyboard.row(
                types.InlineKeyboardButton("🔹 إضافة وكيل", callback_data="admin_add_agent", style="primary"),
                types.InlineKeyboardButton("🗑️ حذف بالأيدي", callback_data="admin_remove_agent", style="danger")
            )
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data == "admin_add_agent":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_add_agent_id")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agents", style="danger"))
            bot.edit_message_text(
                " *إضافة وكيل جديد*\n\nأرسل أيدي المستخدم الذي تريد تعيينه وكيلاً:",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data == "admin_remove_agent":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_remove_agent_id")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agents", style="danger"))
            bot.edit_message_text(
                " *حذف وكيل*\n\nأرسل أيدي الوكيل الذي تريد حذفه:",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        # ملف الوكيل الكامل للأدمن: معلوماته + طلباته + تحليل عمله + أدوات التحكم 
        elif call.data.startswith("admin_agent_detail_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agent_uid = int(call.data.replace("admin_agent_detail_", ""))
            safe_answer_callback_query(call.id)
            _show_admin_agent_detail(call, agent_uid, chat_id, message_id)

        elif call.data.startswith("admin_agent_reqs_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agent_uid = int(call.data.replace("admin_agent_reqs_", ""))
            reqs = db.get_agent_charge_requests(agent_user_id=agent_uid)[:25]
            cursor = db.conn.cursor()
            cursor.execute("SELECT name FROM agents WHERE user_id=?", (agent_uid,))
            row = cursor.fetchone()
            ag_name = row[0] if row else str(agent_uid)
            text = f"{DIVIDER}\n📋 {hb('طلبات الوكيل')} {html_escape(ag_name)}\n{DIVIDER}\n\n"
            if not reqs:
                text += "لا توجد طلبات بعد."
            else:
                status_icons = {'pending': '⏳ معلق', 'agent_approved': '🟡 بانتظار الأدمن', 'admin_approved': '✅ مكتمل', 'rejected': '❌ مرفوض'}
                for r in reqs:
                    rname = r['first_name'] or (f"@{r['username']}" if r['username'] else str(r['user_id']))
                    text += (
                        f"#{r['req_id']} | {status_icons.get(r['status'], html_escape(r['status']))}\n"
                        f"العميل: {html_escape(rname)}\n"
                        f"المبلغ: {fmt_money(r['amount'])}\n"
                        f"التاريخ: {html_escape(str(r['created_at'])[:16])}\n"
                        f"{DIVIDER}\n"
                    )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع لملف الوكيل", callback_data=f"admin_agent_detail_{agent_uid}", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data.startswith("admin_agent_warn_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agent_uid = int(call.data.replace("admin_agent_warn_", ""))
            db.set_user_state(user_id, "waiting_agent_warn_reason", {"uid": agent_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_agent_detail_{agent_uid}", style="danger"))
            bot.edit_message_text(
                "⚠️ أرسل سبب التنبيه — سيُرسل للوكيل فوراً ويُسجَّل في ملفه:",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_agent_notice_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agent_uid = int(call.data.replace("admin_agent_notice_", ""))
            db.set_user_state(user_id, "waiting_agent_notice_text", {"uid": agent_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_agent_detail_{agent_uid}", style="danger"))
            bot.edit_message_text(
                "📨 أرسل نص البلاغ/الرسالة التي تريد إرسالها للوكيل مباشرة:",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_agent_delete_confirm_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agent_uid = int(call.data.replace("admin_agent_delete_confirm_", ""))
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("✅ تأكيد الحذف", callback_data=f"admin_agent_delete_{agent_uid}", style="danger"),
                types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_agent_detail_{agent_uid}", style="primary")
            )
            bot.edit_message_text(
                "⚠️ هل أنت متأكد من حذف هذا الوكيل؟ سيفقد صلاحياته كوكيل فوراً.",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_agent_delete_") and "confirm" not in call.data:
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agent_uid = int(call.data.replace("admin_agent_delete_", ""))
            db.remove_agent(agent_uid)
            try:
                bot.send_message(agent_uid, "تم إلغاء تعيينك كوكيل من قبل الإدارة.")
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🧑‍💼 قائمة الوكلاء", callback_data="admin_agents", style="primary"))
            bot.edit_message_text("✅ تم حذف الوكيل بنجاح.", chat_id, message_id, reply_markup=keyboard)

        elif call.data.startswith("admin_agent_ban_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agent_uid = int(call.data.replace("admin_agent_ban_", ""))
            db.ban_user(agent_uid, "حظر وكيل من لوحة الإدارة", user_id)
            try:
                bot.send_message(agent_uid, "تم حظر حسابك من استخدام البوت من قبل الإدارة.")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم الحظر")
            _show_admin_agent_detail(call, agent_uid, chat_id, message_id)

        elif call.data.startswith("admin_agent_unban_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            agent_uid = int(call.data.replace("admin_agent_unban_", ""))
            db.unban_user(agent_uid)
            try:
                bot.send_message(agent_uid, "تم رفع الحظر عن حسابك.")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم رفع الحظر")
            _show_admin_agent_detail(call, agent_uid, chat_id, message_id)

        elif call.data == "admin_agent_reports":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            reports = db.get_agent_reports(status='pending')
            keyboard = types.InlineKeyboardMarkup()
            if not reports:
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("✅ لا توجد بلاغات معلقة على الوكلاء حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            text = f"{DIVIDER}\n🚨 {hb('بلاغات معلّقة على الوكلاء')}\n{DIVIDER}\n\n"
            for r in reports[:10]:
                rname = f"@{r['reporter_username']}" if r['reporter_username'] else (r['reporter_name'] or str(r['reporter_user_id']))
                text += (
                    f"#{r['report_id']}\n"
                    f"الوكيل: {html_escape(r['agent_name'] or r['agent_user_id'])}\n"
                    f"المبلِّغ: {html_escape(rname)}\n"
                    f"كود الشحن: {html_escape(r['charge_code'] or '-')}\n"
                    f"السبب: {html_escape(r['reason'] or 'لم يُذكر')}\n"
                    f"التاريخ: {html_escape(str(r['created_at'])[:16])}\n"
                    f"{DIVIDER}\n"
                )
                keyboard.row(types.InlineKeyboardButton(f"✅ تم الاطلاع #{r['report_id']}", callback_data=f"admin_resolve_agent_report_{r['report_id']}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data.startswith("admin_resolve_agent_report_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            report_id = int(call.data.replace("admin_resolve_agent_report_", ""))
            db.resolve_agent_report(report_id)
            safe_answer_callback_query(call.id, "تم وضع علامة 'تم الاطلاع' على البلاغ")
            # إعادة عرض قائمة البلاغات المعلّقة المحدّثة 
            reports = db.get_agent_reports(status='pending')
            keyboard = types.InlineKeyboardMarkup()
            if not reports:
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("✅ لا توجد بلاغات معلقة على الوكلاء حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            text = f"{DIVIDER}\n🚨 {hb('بلاغات معلّقة على الوكلاء')}\n{DIVIDER}\n\n"
            for r in reports[:10]:
                rname = f"@{r['reporter_username']}" if r['reporter_username'] else (r['reporter_name'] or str(r['reporter_user_id']))
                text += (
                    f"#{r['report_id']}\n"
                    f"الوكيل: {html_escape(r['agent_name'] or r['agent_user_id'])}\n"
                    f"المبلِّغ: {html_escape(rname)}\n"
                    f"كود الشحن: {html_escape(r['charge_code'] or '-')}\n"
                    f"السبب: {html_escape(r['reason'] or 'لم يُذكر')}\n"
                    f"التاريخ: {html_escape(str(r['created_at'])[:16])}\n"
                    f"{DIVIDER}\n"
                )
                keyboard.row(types.InlineKeyboardButton(f"✅ تم الاطلاع #{r['report_id']}", callback_data=f"admin_resolve_agent_report_{r['report_id']}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        # طلبات الشحن عبر الوكلاء — كشف احتياطي بجانب الإشعار الفوري (في حال فاته الأدمن) 
        elif call.data == "admin_agent_charge_pending":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            reqs = db.get_agent_charge_requests(status='pending') + db.get_agent_charge_requests(status='agent_approved')
            reqs.sort(key=lambda r: r['created_at'], reverse=True)
            keyboard = types.InlineKeyboardMarkup()
            if not reqs:
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("✅ لا توجد طلبات شحن عبر الوكلاء بانتظار التأكيد حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            cursor = db.conn.cursor()
            text = f"{DIVIDER}\n📨 {hb('طلبات شحن عبر الوكلاء')}\n{DIVIDER}\n\n"
            status_icons = {'pending': '⏳ بانتظار الوكيل', 'agent_approved': '🟡 بانتظار تأكيدك'}
            for r in reqs[:15]:
                rname = r['first_name'] or (f"@{r['username']}" if r['username'] else str(r['user_id']))
                cursor.execute("SELECT name FROM agents WHERE user_id=?", (r['agent_user_id'],))
                row = cursor.fetchone()
                ag_name = row[0] if row else str(r['agent_user_id'])
                text += (
                    f"#{r['req_id']} | {status_icons.get(r['status'], html_escape(r['status']))}\n"
                    f"العميل: {html_escape(rname)} | الوكيل: {html_escape(ag_name)}\n"
                    f"المبلغ: {fmt_money(r['amount'])}\n"
                    f"{DIVIDER}\n"
                )
                if r['status'] == 'agent_approved':
                    keyboard.row(
                        types.InlineKeyboardButton(f"✅ تأكيد #{r['req_id']}", callback_data=f"admin_confirm_agent_req_{r['req_id']}", style="primary"),
                        types.InlineKeyboardButton(f"❌ رفض #{r['req_id']}", callback_data=f"admin_reject_agent_req_{r['req_id']}", style="danger")
                    )
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        # إدارة الوسطاء (أدمن) — قائمة تفاعلية + تحكم كامل بكل وسيط 
        elif call.data == "admin_brokers":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            brokers = db.get_all_brokers()
            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM broker_requests WHERE status='pending'")
            total_pending = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COALESCE(SUM(amount),0) FROM broker_profits")
            total_profit_all = cursor.fetchone()[0] or 0.0
            text = f"{DIVIDER}\n{hb('🤝 إدارة الوسطاء')}\n{DIVIDER}\n\n"
            text += f"العدد: {len(brokers)} | ⏳ طلبات معلقة: {total_pending} | 💰 إجمالي الأرباح: {fmt_money(total_profit_all)}\n\n"
            text += "اختر وسيطاً لعرض ملفه الكامل ومعلوماته وتحليل عمله، أو للتحكم به (تنبيه / بلاغ / حذف):" if brokers else "لا يوجد وسطاء بعد."
            keyboard = types.InlineKeyboardMarkup()
            for br in brokers:
                rating = db.get_broker_rating_stats(br['user_id'])
                cursor.execute("SELECT COUNT(*) FROM broker_requests WHERE broker_user_id=? AND status='pending'", (br['user_id'],))
                pend = cursor.fetchone()[0] or 0
                label = f"🤝 {br['name'] or br['user_id']}"
                if rating['count'] > 0:
                    label += f" ⭐{rating['avg']:.1f}"
                if pend > 0:
                    label += f" ⏳{pend}"
                keyboard.row(types.InlineKeyboardButton(label, callback_data=f"admin_broker_detail_{br['user_id']}", style="primary"))
            keyboard.row(
                types.InlineKeyboardButton("🔹 إضافة وسيط", callback_data="admin_add_broker", style="primary"),
                types.InlineKeyboardButton("🗑️ حذف بالأيدي", callback_data="admin_remove_broker", style="danger")
            )
            keyboard.row(types.InlineKeyboardButton("🔗 رابط مجموعة الوساطة", callback_data="admin_set_broker_group", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data == "admin_add_broker":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_add_broker_id")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_brokers", style="danger"))
            bot.edit_message_text(
                " *إضافة وسيط جديد*\n\nأرسل أيدي المستخدم الذي تريد تعيينه وسيطاً:",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data == "admin_remove_broker":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_remove_broker_id")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_brokers", style="danger"))
            bot.edit_message_text(
                " *حذف وسيط*\n\nأرسل أيدي الوسيط الذي تريد حذفه:",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        # ملف الوسيط الكامل للأدمن: معلوماته + طلباته + تحليل عمله + أدوات التحكم 
        elif call.data.startswith("admin_broker_detail_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            broker_uid = int(call.data.replace("admin_broker_detail_", ""))
            safe_answer_callback_query(call.id)
            _show_admin_broker_detail(call, broker_uid, chat_id, message_id)

        elif call.data.startswith("admin_broker_reqs_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            broker_uid = int(call.data.replace("admin_broker_reqs_", ""))
            reqs = db.get_broker_requests(broker_user_id=broker_uid)[:25]
            cursor = db.conn.cursor()
            cursor.execute("SELECT name FROM brokers WHERE user_id=?", (broker_uid,))
            row = cursor.fetchone()
            br_name = row[0] if row else str(broker_uid)
            text = f"{DIVIDER}\n📋 {hb('طلبات الوسيط')} {html_escape(br_name)}\n{DIVIDER}\n\n"
            if not reqs:
                text += "لا توجد طلبات بعد."
            else:
                status_icons = {'pending': '⏳ معلق', 'approved': '✅ مقبول', 'rejected': '❌ مرفوض'}
                for r in reqs:
                    rname = r['first_name'] or (f"@{r['username']}" if r['username'] else str(r['user_id']))
                    text += (
                        f"#{r['req_id']} | {status_icons.get(r['status'], html_escape(r['status']))}\n"
                        f"العميل: {html_escape(rname)}\n"
                        f"النوع: {html_escape(r['service_type'] or '-')}\n"
                        f"التاريخ: {html_escape(str(r['created_at'])[:16])}\n"
                        f"{DIVIDER}\n"
                    )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع لملف الوسيط", callback_data=f"admin_broker_detail_{broker_uid}", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data.startswith("admin_broker_warn_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            broker_uid = int(call.data.replace("admin_broker_warn_", ""))
            db.set_user_state(user_id, "waiting_broker_warn_reason", {"uid": broker_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_broker_detail_{broker_uid}", style="danger"))
            bot.edit_message_text(
                "⚠️ أرسل سبب التنبيه — سيُرسل للوسيط فوراً ويُسجَّل في ملفه:",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_broker_notice_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            broker_uid = int(call.data.replace("admin_broker_notice_", ""))
            db.set_user_state(user_id, "waiting_broker_notice_text", {"uid": broker_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_broker_detail_{broker_uid}", style="danger"))
            bot.edit_message_text(
                "📨 أرسل نص البلاغ/الرسالة التي تريد إرسالها للوسيط مباشرة:",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_broker_delete_confirm_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            broker_uid = int(call.data.replace("admin_broker_delete_confirm_", ""))
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("✅ تأكيد الحذف", callback_data=f"admin_broker_delete_{broker_uid}", style="danger"),
                types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_broker_detail_{broker_uid}", style="primary")
            )
            bot.edit_message_text(
                "⚠️ هل أنت متأكد من حذف هذا الوسيط؟ سيفقد صلاحياته كوسيط فوراً.",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_broker_delete_") and "confirm" not in call.data:
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            broker_uid = int(call.data.replace("admin_broker_delete_", ""))
            db.remove_broker(broker_uid)
            try:
                bot.send_message(broker_uid, "تم إلغاء تعيينك كوسيط من قبل الإدارة.")
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 قائمة الوسطاء", callback_data="admin_brokers", style="primary"))
            bot.edit_message_text("✅ تم حذف الوسيط بنجاح.", chat_id, message_id, reply_markup=keyboard)

        elif call.data.startswith("admin_broker_ban_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            broker_uid = int(call.data.replace("admin_broker_ban_", ""))
            db.ban_user(broker_uid, "حظر وسيط من لوحة الإدارة", user_id)
            try:
                bot.send_message(broker_uid, "تم حظر حسابك من استخدام البوت من قبل الإدارة.")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم الحظر")
            _show_admin_broker_detail(call, broker_uid, chat_id, message_id)

        elif call.data.startswith("admin_broker_unban_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            broker_uid = int(call.data.replace("admin_broker_unban_", ""))
            db.unban_user(broker_uid)
            try:
                bot.send_message(broker_uid, "تم رفع الحظر عن حسابك.")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم رفع الحظر")
            _show_admin_broker_detail(call, broker_uid, chat_id, message_id)


        # لوحة الوكيل 
        elif call.data == "admin_toggle_verification":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            current = db.is_verification_enabled()
            new_val = '0' if current else '1'
            db.set_bot_setting('verification_enabled', new_val)
            status = "مفعّلة " if new_val == '1' else "معطّلة "
            safe_answer_callback_query(call.id, f"الحماية الآن: {status}", show_alert=True)
            try:
                keyboard = create_admin_settings_keyboard()
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
            except Exception:
                pass

        # عرض تقييمات الوكيل 
        elif call.data == "rules":
            rules_text = (
                f" *قوانين وسياسات بوت المزادات*\n\n"
                f"{''*28}\n"
                f" *التحقق من الهوية*\n"
                f"{''*28}\n\n"
                f" *رقم الهاتف — لماذا مطلوب؟*\n"
                f"• يربط كل حساب بشخص حقيقي واحد\n"
                f"• يمنع إنشاء حسابات وهمية للتلاعب بالمزادات\n"
                f"• يُستخدم فقط عند النزاعات من قبل الإدارة\n"
                f"• يُحفظ مشفراً ولا يُشارك مع أحد\n\n"
                f" *الموقع الجغرافي — لماذا مطلوب؟*\n"
                f"• يحدد المنطقة التقريبية للبائع فقط\n"
                f"• دليل قانوني عند الإبلاغ عن الاحتيال\n"
                f"• يُؤخذ مرة واحدة فقط — لا يتتبع تحركاتك\n\n"
                f"{''*28}\n"
                f" *العمولات والرسوم*\n"
                f"{''*28}\n\n"
                f"• نشر مزاد: 0.01$\n"
                f"• عمولة البيع: {COMMISSION_RATE*100:.1f}% من سعر البيع\n"
                f"• عمولة التحويل: {TRANSFER_COMMISSION_RATE*100:.0f}% من المبلغ\n\n"
                f"{''*28}\n"
                f" *قوانين المزادات*\n"
                f"{''*28}\n\n"
                f"• كل مزايدة تُمدد المزاد 5 دقائق\n"
                f"• تسليم المنتج للفائز: خلال 24 ساعة\n"
                f"• إن لم يأتِ مزايد: يُعاد سعر البدء كاملاً\n"
                f"• إن خسرت مزايدة: يُعاد رصيدك فوراً\n\n"
                f"{''*28}\n"
                f" *حالات الحظر الفوري*\n"
                f"{''*28}\n\n"
                f"• بيع منتجات مسروقة أو احتيالية\n"
                f"• عدم تسليم المنتج للفائز\n"
                f"• إدخال بيانات تحقق مزيفة\n"
                f"• أي سلوك احتيالي موثق\n\n"
                f"عندك سؤال؟ اضغط لماذا "
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 لماذا", callback_data="ai_legal", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏆 أفضل البائعين", callback_data="top_sellers", style="primary"))
            keyboard.row(types.InlineKeyboardButton("ℹ️ عن المنصة", callback_data="about_bot", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 تواصل مع الإدارة", url=f"tg://user?id={OWNER_ID}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            try:
                bot.edit_message_text(rules_text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, rules_text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "ai_legal":
            # فتح شات الذكاء القانوني
            session = db_get_open_legal_session(user_id)
            if not session:
                session_id = db_create_legal_session(user_id)
            else:
                session_id = session['ticket_id']
            db.set_user_state(user_id, f"ai_legal_chat_{session_id}")
            intro_text = (
                " *مستشار المزادات الذكي*\n\n"
                "أنا هنا للإجابة عن أي سؤال يتعلق بقوانين البوت وسياساته.\n\n"
                "على سبيل المثال، يمكنك أن تسألني:\n"
                "• لماذا يطلب البوت رقم هاتفي؟\n"
                "• لماذا يطلب موقعي الجغرافي؟\n"
                "• ما هي العمولات وكيف يتم حسابها؟\n"
                "• ماذا يحدث إذا لم يتم تسليم المنتج؟\n"
                "• كيف يُعاد رصيدي في حال خسارة المزايدة؟\n\n"
                "يرجى كتابة سؤالك الآن"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إنهاء المحادثة", callback_data=f"ai_legal_end_{session_id}", style="danger"))
            try:
                bot.edit_message_text(intro_text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, intro_text, reply_markup=keyboard, parse_mode="Markdown")
            safe_answer_callback_query(call.id)

        elif call.data.startswith("ai_legal_end_"):
            session_id = int(call.data.replace("ai_legal_end_", ""))
            db_close_legal_session(session_id)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📜 القوانين", callback_data="rules", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            try:
                bot.edit_message_text("انتهت جلسة الاستشارة.\n\nيمكنك العودة للقوانين أو الرئيسية.", chat_id, message_id, reply_markup=keyboard)
            except Exception:
                bot.send_message(chat_id, "انتهت جلسة الاستشارة.", reply_markup=keyboard)
            safe_answer_callback_query(call.id)



        elif call.data == "show_auctions":
            nav_push(user_id, "show_auctions")
            keyboard = create_categories_keyboard()
            bot.edit_message_text("اختر تصنيف المزادات:\n\n------------------------------------------", chat_id, message_id, reply_markup=keyboard)
        elif call.data.startswith("cat_"):
            category = call.data.replace("cat_", "")
            auctions = db.get_active_auctions(category)
            category_names = {"usernames": "معرفات", "channels": "قنوات", "groups": "مجموعات", "bots": "بوتات", "gifts": "هدايا", "all": "الكل"}
            if not auctions:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🗂️ للتصنيفات", callback_data="show_auctions", style="primary"), types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                bot.edit_message_text(f"لا توجد مزادات في فئة '{category_names.get(category, category)}' حالياً", chat_id, message_id, reply_markup=keyboard)
                return
            text = f"المزادات المتاحة ({category_names.get(category, category)}):\n\n------------------------------------------\n\nاختر أحد المزادات التالية:\n\n"
            keyboard = create_auctions_list_keyboard(auctions, category)
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        elif call.data == "my_auctions":
            nav_push(user_id, "my_auctions")
            auctions = db.get_user_auctions(user_id)
            if not auctions:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إنشاء مزاد جديد", callback_data="new_auction", style="primary"), types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                bot.edit_message_text("ليس لديك أي مزادات حالياً", chat_id, message_id, reply_markup=keyboard)
                return
            text = "مزاداتي:\n\n------------------------------------------\n\n"
            for auction in auctions[:10]:
                status_text = {"pending": "قيد الانتظار", "active": "نشط", "expired": "منتهي", "rejected": "مرفوض", "sold": "مباع"}
                text += f"#{auction['auction_id']}\n{auction['title']}\nأعلى مزايدة: {auction['current_price']:.2f}$\nالمزايدات: {auction['bids_count']}\n"
                if auction['status'] == "sold":
                    text += f"سعر البيع: {auction['sold_price']:.2f}$\n"
                text += f"الحالة: {status_text.get(auction['status'], auction['status'])}\n"
                if auction['status'] == "active" and auction['ends_at']:
                    ends_at = db.parse_datetime(auction['ends_at'])
                    if ends_at:
                        time_left = ends_at - datetime.now()
                        if time_left.total_seconds() > 0:
                            hours_left = time_left.total_seconds() // 3600
                            minutes_left = (time_left.total_seconds() % 3600) // 60
                            text += f"متبقي: {int(hours_left)}:{int(minutes_left):02d}\n"
                text += f"------------------------------------------\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إنشاء مزاد جديد", callback_data="new_auction", style="primary"), types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        elif call.data == "my_bids":
            nav_push(user_id, "my_bids")
            bids = db.get_user_bids(user_id)
            if not bids:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("📋 عرض المزادات", callback_data="show_auctions", style="primary"), types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                bot.edit_message_text("ليس لديك أي مزايدات حالياً", chat_id, message_id, reply_markup=keyboard)
                return
            text = "مزايداتي:\n\n------------------------------------------\n\n"
            for bid in bids[:10]:
                auction_info = db.get_auction_by_id(bid['auction_id'])
                if not auction_info:
                    continue
                text += f"#{bid['auction_id']}\n{auction_info['title']}\nمزايدتي: {bid['amount']:.2f}$\nالحالة: {auction_info['status']}\n"
                if auction_info['status'] == 'active':
                    rank = get_bid_rank(bid['auction_id'], bid['user_id'])
                    if "الأول" in rank:
                        text += f"الرتبة: المركز الأول\n"
                    elif "الثاني" in rank:
                        text += f"الرتبة: المركز الثاني\n"
                    elif "الثالث" in rank:
                        text += f"الرتبة: المركز الثالث\n"
                    else:
                        text += f"الرتبة: {rank}\n"
                text += f"{bid['bid_time'][:10] if isinstance(bid['bid_time'], str) else db.parse_datetime(bid['bid_time']).strftime('%Y-%m-%d')}\n------------------------------------------\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📋 عرض المزادات", callback_data="show_auctions", style="primary"), types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        elif call.data == "balance":
            balance = db.get_balance(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📥 شحن رصيد", callback_data="charge", style="primary"), types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(f"معلومات رصيدك\n\n------------------------------------------\n\nرصيدك الحالي: {balance:.2f}$\nعمولة نشر المزاد: 0.01$\n\nيمكنك استخدام الرصيد للمزايدة أو نشر مزادات", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "charge":
            nav_push(user_id, "charge")
            balance = db.get_balance(user_id)
            text = (
                f" <b>شحن الرصيد</b>\n\n"
                f"رصيدك الحالي: {balance:.2f}$\n\n"
                "اختر طريقة الشحن:\n\n"
                " <b>باينيس (Binance)</b> — تحويل USDT\n"
                " <b>نجوم تيليجرام</b> — دفع فوري داخل التطبيق\n"
                " <b>أسياسيل</b> — تواصل مع المالك\n"
                " <b>شحن فوري</b> — جميع طرق الشحن السريع"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 باينيس (USDT)", callback_data="binance_charge", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 نجوم تيليجرام", callback_data="stars_charge", style="primary"))
            keyboard.row(
                types.InlineKeyboardButton("🔹 أسياسيل", callback_data="charge_asiacell", style="primary"),
                types.InlineKeyboardButton("🔹 زين كاش", callback_data="charge_zaincash", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("🔹 كي كارد", callback_data="charge_kycard", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
        elif call.data == "use_code":
            db.set_user_state(user_id, "waiting_code")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="charge", style="primary"))
            bot.edit_message_text("أدخل كود الشحن:\n\nمثال: ABC-123-DEF", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "instant_charge":
            # شحن فوري: يعرض مباشرة أقسام Binance + النجوم + أسياسيل
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 باينيس (Binance USDT)", callback_data="binance_charge", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 نجوم تيليجرام (فوري)", callback_data="stars_charge", style="primary"))
            keyboard.row(
                types.InlineKeyboardButton("🔹 أسياسيل", callback_data="charge_asiacell", style="primary"),
                types.InlineKeyboardButton("🔹 زين كاش", callback_data="charge_zaincash", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("🔹 كي كارد", callback_data="charge_kycard", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(
                " *شحن فوري*\n\n"
                "اختر طريقة الشحن:\n\n"
                " *باينيس* — تحويل USDT\n"
                " *نجوم تيليجرام* — دفع فوري داخل تيليجرام\n"
                " *أسياسيل / زين كاش / كي كارد* — تحويل يدوي",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data == "charge_asiacell":
            text = (
                " <b>شحن عبر أسياسيل</b>\n\n"
                "خطوات الشحن:\n\n"
                "1⃣ حوّل المبلغ المراد شحنه إلى رقم أسياسيل الخاص بالبوت:\n"
                f"   <code>{ASIACELL_PHONE}</code>\n\n"
                "2⃣ بعد التحويل أرسل رسالة للمالك تحتوي على:\n"
                "   • رقم هاتفك الذي أرسلت منه\n"
                "   • المبلغ المُحوَّل\n"
                "   • أيدي حسابك في البوت\n"
                "   • صورة إثبات التحويل\n\n"
                f" <a href='tg://user?id={OWNER_ID}'>تواصل مع المالك</a>"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إرسال إثبات التحويل", callback_data="charge_asiacell_proof", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 تواصل مع المالك", url=f"tg://user?id={OWNER_ID}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="charge", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)

        elif call.data == "charge_asiacell_proof":
            db.set_user_state(user_id, "waiting_asiacell_amount")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_asiacell", style="danger"))
            bot.edit_message_text(
                " *شحن أسياسيل — إرسال الإثبات*\n\n"
                "أرسل المبلغ الذي حوّلته بالدولار ($):\n"
                "مثال: 10",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )
        elif call.data == "charge_zaincash":
            text = (
                " <b>شحن عبر زين كاش</b>\n\n"
                "خطوات الشحن:\n\n"
                "1⃣ حوّل المبلغ المراد شحنه إلى رقم زين كاش الخاص بالبوت:\n"
                f"   <code>{ZAIN_CASH_PHONE}</code>\n\n"
                "2⃣ بعد التحويل أرسل رسالة للمالك تحتوي على:\n"
                "   • رقم هاتفك الذي أرسلت منه\n"
                "   • المبلغ المُحوَّل\n"
                "   • أيدي حسابك في البوت\n"
                "   • صورة إثبات التحويل\n\n"
                f" <a href='tg://user?id={OWNER_ID}'>تواصل مع المالك</a>"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إرسال إثبات التحويل", callback_data="charge_zaincash_proof", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 تواصل مع المالك", url=f"tg://user?id={OWNER_ID}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="charge", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)

        elif call.data == "charge_zaincash_proof":
            db.set_user_state(user_id, "waiting_zaincash_amount")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_zaincash", style="danger"))
            bot.edit_message_text(
                " *شحن زين كاش — إرسال الإثبات*\n\n"
                "أرسل المبلغ الذي حوّلته بالدولار ($):\n"
                "مثال: 10",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data == "charge_kycard":
            text = (
                " <b>شحن عبر كي كارد</b>\n\n"
                "خطوات الشحن:\n\n"
                "1⃣ حوّل المبلغ المراد شحنه إلى كي كارد التالي:\n"
                f"   الرقم: <code>{KYCARD_NUMBER}</code>\n"
                f"   الاسم: <b>{KYCARD_NAME}</b>\n\n"
                "2⃣ بعد التحويل أرسل رسالة للمالك تحتوي على:\n"
                "   • رقم كي كارد الذي أرسلت منه\n"
                "   • المبلغ المُحوَّل\n"
                "   • أيدي حسابك في البوت\n"
                "   • صورة إثبات التحويل\n\n"
                f" <a href='tg://user?id={OWNER_ID}'>تواصل مع المالك</a>"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إرسال إثبات التحويل", callback_data="charge_kycard_proof", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 تواصل مع المالك", url=f"tg://user?id={OWNER_ID}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="charge", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)

        elif call.data == "charge_kycard_proof":
            db.set_user_state(user_id, "waiting_kycard_amount")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_kycard", style="danger"))
            bot.edit_message_text(
                " *شحن كي كارد — إرسال الإثبات*\n\n"
                "أرسل المبلغ الذي حوّلته بالدولار ($):\n"
                "مثال: 10",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data.startswith("approve_charge_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            req_id = int(call.data.replace("approve_charge_", ""))
            ok, result = db.approve_charge_request(req_id)
            if ok:
                target_uid, amount, method = result
                safe_answer_callback_query(call.id, f"✅ تم قبول الشحن #{req_id}")
                try:
                    bot.send_message(
                        target_uid,
                        f"✅ *تم قبول طلب الشحن #{req_id}!*\n\n"
                        f"المبلغ المُضاف: {amount:.2f}$\n"
                        f"الطريقة: {method}\n"
                        f"رصيدك الجديد: {db.get_balance(target_uid):.2f}$",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                try:
                    bot.edit_message_text(f"✅ تم قبول طلب الشحن #{req_id} — {amount:.2f}$", chat_id, message_id)
                except Exception:
                    pass
            else:
                safe_answer_callback_query(call.id, f"❌ {result}", show_alert=True)

        elif call.data.startswith("reject_charge_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            req_id = int(call.data.replace("reject_charge_", ""))
            db.set_user_state(user_id, f"waiting_charge_reject_reason_{req_id}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_pending_charges", style="danger"))
            try:
                bot.edit_message_text(
                    f"أرسل سبب رفض طلب الشحن #{req_id}:",
                    chat_id, message_id, reply_markup=keyboard
                )
            except Exception:
                bot.send_message(chat_id, f"أرسل سبب رفض طلب الشحن #{req_id}:", reply_markup=keyboard)

        elif call.data == "admin_pending_charges":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT wr.*, u.username, u.first_name FROM withdrawal_requests wr "
                "LEFT JOIN users u ON wr.user_id = u.user_id "
                "WHERE wr.status = 'pending_charge' ORDER BY wr.created_at ASC LIMIT 5"
            )
            rows = cursor.fetchall()
            if not rows:
                safe_answer_callback_query(call.id, "لا توجد طلبات شحن معلقة", show_alert=True)
                return
            safe_answer_callback_query(call.id)
            for r in rows:
                req_id = r[0]
                uid = r[1]
                amount = r[2]
                method = r[3]
                proof = r[4]
                created = str(r[7])[:16]
                uname = f"@{r[9]}" if r[9] else (r[10] or f"ID {uid}")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(
                    types.InlineKeyboardButton("✅ قبول", callback_data=f"approve_charge_{req_id}", style="primary"),
                    types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_charge_{req_id}", style="danger")
                )
                bot.send_message(
                    chat_id,
                    f" *طلب شحن #{req_id}*\n\n"
                    f"المستخدم: {uname} (ID: {uid})\n"
                    f"المبلغ: {amount:.2f}$\n"
                    f"الطريقة: {method}\n"
                    f"إثبات التحويل: {proof}\n"
                    f"التاريخ: {created}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )

        elif call.data == "new_auction":
            # تحقق من إتمام الـ onboarding 
            if not db.has_completed_onboarding(user_id):
                send_onboarding_page(chat_id, user_id, 1)
                safe_answer_callback_query(call.id)
                return
            # تحقق من الهوية قبل نشر أي مزاد (إذا كانت الحماية مفعلة) 
            if db.is_verification_enabled() and not db.is_verified(user_id):
                db.set_user_state(user_id, "waiting_phone_for_auction")
                # request_contact يعمل فقط في ReplyKeyboardMarkup وليس InlineKeyboard
                reply_kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                reply_kb.add(types.KeyboardButton("📱 مشاركة رقم الهاتف", request_contact=True, style="primary"))
                reply_kb.add(types.KeyboardButton("❌ إلغاء", style="danger"))
                bot.send_message(
                    chat_id,
                    " *التحقق من الهوية*\n\n"
                    "لحماية المستخدمين من عمليات الاحتيال، نطلب منك مرة واحدة فقط:\n\n"
                    "رقم هاتفك — اضغط الزر أدناه لمشاركته\n\n"
                    "معلوماتك سرية ولا تُشارك مع أحد سوى الإدارة.",
                    reply_markup=reply_kb,
                    parse_mode="Markdown"
                )
                return
            db.set_user_state(user_id, "choosing_auction_type")
            keyboard = create_auction_type_keyboard()
            bot.edit_message_text("اختر نوع المزاد:\n\nمعرف - لحساب تيليجرام\nقناة - لقناة تيليجرام\nمجموعة - لمجموعة تيليجرام\nمعرف بوت - لبوت تيليجرام\nهدية تيليجرام - لعروض الهدايا\n\nملاحظة: عند نشر مزاد بالبوت يتم نشره في قنوات البث", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "private_link":
            # ← إصلاح: معالج زر الرابط الخاص
            user_state = db.get_user_state(user_id)
            auction_type = "channel"
            if user_state and user_state.get('data'):
                auction_type = user_state['data'].get('auction_type', 'channel')
            db.set_user_state(user_id, "waiting_private_link", {"auction_type": auction_type})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"type_{auction_type}", style="primary"))
            bot.edit_message_text("🔗 إرسال الرابط الخاص", chat_id, message_id, reply_markup=keyboard)
            bot.send_message(
                chat_id, "أرسل الرابط الخاص (invite link):",
                reply_markup=types.ForceReply(selective=True)
            )
        elif call.data.startswith("type_"):
            auction_type = call.data.replace("type_", "")
            if auction_type == "username":
                db.set_user_state(user_id, "waiting_username_info", {"auction_type": "username"})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary"))
                bot.edit_message_text("📝 إرسال معرّف المزاد", chat_id, message_id, reply_markup=keyboard)
                bot.send_message(
                    chat_id, "أرسل المعرف (بدون @):",
                    reply_markup=types.ForceReply(selective=True)
                )
            else:
                db.set_user_state(user_id, f"waiting_{auction_type}_info", {"auction_type": auction_type})
                keyboard = types.InlineKeyboardMarkup()
                if auction_type in ["channel", "group"]:
                    keyboard.row(types.InlineKeyboardButton("🔹 رابط خاص", callback_data="private_link", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary"))
                type_names = {"username": "المعرف", "channel": "القناة", "group": "المجموعة", "bot": "البوت"}
                if auction_type == "gift":
                    bot.edit_message_text("🎁 إرسال رابط الهدية", chat_id, message_id, reply_markup=keyboard)
                    bot.send_message(
                        chat_id, "أرسل رابط الهدية مباشرة:",
                        reply_markup=types.ForceReply(selective=True)
                    )
                else:
                    bot.edit_message_text(f"📝 إرسال {type_names[auction_type]}", chat_id, message_id, reply_markup=keyboard)
                    bot.send_message(
                        chat_id, f"أرسل {type_names[auction_type]} (معرف بدون @ أو رابط):",
                        reply_markup=types.ForceReply(selective=True)
                    )
        elif call.data.startswith("auction_details_"):
            auction_id = call.data.replace("auction_details_", "")
            nav_push(user_id, f"auction_details_{auction_id}")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "هذا المزاد لم يعد متاحاً!")
                return
            check_auction_ended(auction_id)
            ends_at = db.parse_datetime(auction_info['ends_at'])
            if not ends_at:
                safe_answer_callback_query(call.id, "خطأ في بيانات المزاد!")
                return
            time_left = ends_at - datetime.now()
            if time_left.total_seconds() <= 0 or auction_info['status'] != 'active':
                safe_answer_callback_query(call.id, "انتهى وقت المزاد!")
                return
            hours_left = time_left.total_seconds() // 3600
            minutes_left = (time_left.total_seconds() % 3600) // 60
            user_bids = db.get_user_bids(user_id, auction_id)
            can_refund = len(user_bids) > 0

            parts = [
                f"📋 {hb('تفاصيل المزاد')}  {hc('#' + str(auction_info['auction_id']))}",
                DIVIDER,
                f"📦 {html_escape(auction_info['title'])}",
                _auction_target_line(auction_info),
                _auction_type_line(auction_info),
            ]
            platform_line = _platform_line(auction_info)
            if platform_line:
                parts.append(platform_line)
            # تقييم البائع
            seller_avg, seller_count = db.get_seller_rating(auction_info['user_id'])
            if seller_count > 0:
                stars_display = "⭐" * round(seller_avg) + f" {seller_avg}/5 ({seller_count})"
                parts.append(f"🌟 {hb('تقييم البائع:')} {stars_display}")
            parts.append(DIVIDER)
            parts.append(f"💵 {hb('السعر الحالي:')} {fmt_money(auction_info['current_price'])}")
            parts.append(f"💰 {hb('السعر الابتدائي:')} {fmt_money(auction_info['starting_price'])}")
            parts.append(f"📊 {hb('عدد المزايدات:')} {auction_info['bids_count']}")
            parts.append(f"⏳ {hb('المتبقي:')} {int(hours_left)}:{int(minutes_left):02d}")
            if user_bids:
                top_user_bid = max(bid['amount'] for bid in user_bids)
                parts.append(DIVIDER)
                parts.append(f"📌 لديك {len(user_bids)} مزايدة في هذا المزاد")
                parts.append(f"🔼 {hb('أعلى مزايدة لك:')} {fmt_money(top_user_bid)}")
            buy_now_price = auction_info.get('buy_now_price', 0.0)
            if buy_now_price and buy_now_price > 0:
                parts.append(DIVIDER)
                parts.append(f"🛒 {hb('اشتري الآن بـ')} {fmt_money(buy_now_price)} {hb('دون انتظار!')}")
            text = "\n".join(parts)

            is_owner = (auction_info['user_id'] == user_id)
            is_watching_flag = db.is_watching(auction_id, user_id)
            keyboard = create_auction_details_keyboard(
                auction_id, user_id, can_refund,
                buy_now_price=buy_now_price,
                is_owner=is_owner,
                is_watching=is_watching_flag
            )
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
        elif call.data.startswith("rate_") and not call.data.startswith("rate_confirm_") and not call.data.startswith("rate_agent_") and not call.data.startswith("rate_broker_"):
            parts = call.data.split("_")
            # rate_{auction_id}_{stars}  — auction_id قد يحتوي على _
            stars = int(parts[-1])
            auction_id = "_".join(parts[1:-1])
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "المزاد غير موجود!", show_alert=True)
                return
            if auction_info.get('sold_to') != user_id:
                safe_answer_callback_query(call.id, "التقييم متاح للمشتري فقط!", show_alert=True)
                return
            if db.has_rated(auction_id, user_id):
                safe_answer_callback_query(call.id, "لقد قيّمت هذا البائع مسبقاً!", show_alert=True)
                return
            stars_text = "⭐" * stars
            confirm_kb = types.InlineKeyboardMarkup()
            confirm_kb.row(
                types.InlineKeyboardButton(f"✅ تأكيد {stars_text}", callback_data=f"rate_confirm_{auction_id}_{stars}", style="primary"),
                types.InlineKeyboardButton("❌ إلغاء", callback_data="back_to_main", style="danger")
            )
            bot.edit_message_text(
                "\n".join([
                    f"🌟 {hb('تقييمك:')} {stars_text}",
                    "",
                    "هل تريد تأكيد التقييم؟",
                ]),
                chat_id, message_id, reply_markup=confirm_kb, parse_mode="HTML"
            )
            safe_answer_callback_query(call.id)

        elif call.data.startswith("rate_confirm_"):
            parts = call.data.split("_")
            stars = int(parts[-1])
            auction_id = "_".join(parts[2:-1])
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "المزاد غير موجود!", show_alert=True)
                return
            if db.has_rated(auction_id, user_id):
                safe_answer_callback_query(call.id, "قيّمت مسبقاً!", show_alert=True)
                return
            db.add_seller_rating(auction_id, auction_info['user_id'], user_id, stars)
            avg, count = db.get_seller_rating(auction_info['user_id'])
            safe_answer_callback_query(call.id, f"شكراً! تم تسجيل تقييمك {'⭐'*stars}", show_alert=True)
            try:
                bot.edit_message_text(
                    "\n".join([
                        f"✅ {hb('تم تسجيل تقييمك')} {'⭐'*stars}",
                        "",
                        f"🌟 {hb('تقييم البائع الآن:')} {avg}⭐ ({count} تقييم)",
                    ]),
                    chat_id, message_id,
                    reply_markup=types.InlineKeyboardMarkup().row(
                        types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary")
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            # إشعار البائع بتقييمه
            queue_send(
                auction_info['user_id'],
                "\n".join([
                    f"🌟 {hb('تقييم جديد!')}",
                    DIVIDER,
                    f"المشتري في مزاد {hc('#' + str(auction_id))} قيّمك: {'⭐'*stars}",
                    f"📊 {hb('متوسط تقييمك الآن:')} {avg}⭐ ({count} تقييم)",
                ]),
                parse_mode="HTML"
            )

        elif call.data.startswith("watch_") and not call.data.startswith("watch_list"):
            auction_id = call.data.replace("watch_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info or auction_info['status'] != 'active':
                safe_answer_callback_query(call.id, "المزاد غير نشط!", show_alert=True)
                return
            if auction_info['user_id'] == user_id:
                safe_answer_callback_query(call.id, "لا يمكنك متابعة مزادك الخاص!", show_alert=True)
                return
            added = db.watch_auction(auction_id, user_id)
            if added:
                safe_answer_callback_query(call.id, " تمت متابعة المزاد! ستصلك إشعارات عند المزايدات الجديدة.", show_alert=True)
            else:
                safe_answer_callback_query(call.id, "أنت تتابع هذا المزاد بالفعل!")
            user_bids = db.get_user_bids(user_id, auction_id)
            keyboard = create_auction_details_keyboard(
                auction_id, user_id,
                can_refund=len(user_bids) > 0,
                buy_now_price=auction_info.get('buy_now_price', 0.0),
                is_owner=(auction_info['user_id'] == user_id),
                is_watching=True
            )
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
            except Exception:
                pass

        elif call.data.startswith("unwatch_"):
            auction_id = call.data.replace("unwatch_", "")
            db.unwatch_auction(auction_id, user_id)
            safe_answer_callback_query(call.id, "تم إلغاء متابعة المزاد.")
            auction_info = db.get_auction_by_id(auction_id)
            if auction_info:
                user_bids = db.get_user_bids(user_id, auction_id)
                keyboard = create_auction_details_keyboard(
                    auction_id, user_id,
                    can_refund=len(user_bids) > 0,
                    buy_now_price=auction_info.get('buy_now_price', 0.0),
                    is_owner=(auction_info['user_id'] == user_id),
                    is_watching=False
                )
                try:
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=keyboard)
                except Exception:
                    pass

        elif call.data.startswith("buynow_"):
            auction_id = call.data.replace("buynow_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "المزاد غير موجود!", show_alert=True)
                return
            if auction_info['user_id'] == user_id:
                safe_answer_callback_query(call.id, "لا يمكنك شراء مزادك الخاص!", show_alert=True)
                return
            buy_now_price = auction_info.get('buy_now_price', 0.0)
            if not buy_now_price or buy_now_price <= 0:
                safe_answer_callback_query(call.id, "الشراء الفوري غير متاح لهذا المزاد!", show_alert=True)
                return
            check_auction_ended(auction_id)
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info or auction_info['status'] != 'active':
                safe_answer_callback_query(call.id, "انتهى وقت المزاد!", show_alert=True)
                return
            user_balance = db.get_balance(user_id)
            if user_balance < buy_now_price:
                safe_answer_callback_query(
                    call.id,
                    f"رصيدك غير كافٍ!\n\nرصيدك: {user_balance:.2f}$\nالمطلوب: {buy_now_price:.2f}$",
                    show_alert=True
                )
                return
            # تأكيد الشراء
            keyboard_confirm = types.InlineKeyboardMarkup()
            keyboard_confirm.row(
                types.InlineKeyboardButton(f"✅ تأكيد الشراء بـ {buy_now_price:.2f}$", callback_data=f"buynow_confirm_{auction_id}", style="primary"),
                types.InlineKeyboardButton("❌ إلغاء", callback_data=f"auction_details_{auction_id}", style="danger")
            )
            bot.edit_message_text(
                "\n".join([
                    f"🛒 {hb('تأكيد الشراء الفوري')}",
                    DIVIDER,
                    f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                    f"📦 {hb('المنتج:')} {html_escape(auction_info.get('title','') or '')}",
                    f"💰 {hb('السعر:')} {fmt_money(buy_now_price)}",
                    f"👛 {hb('رصيدك:')} {fmt_money(user_balance)}",
                    DIVIDER,
                    "هل تريد الشراء الآن بالسعر الكامل؟",
                ]),
                chat_id, message_id, reply_markup=keyboard_confirm, parse_mode="HTML"
            )
            safe_answer_callback_query(call.id)

        elif call.data.startswith("buynow_confirm_"):
            auction_id = call.data.replace("buynow_confirm_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "المزاد غير موجود!", show_alert=True)
                return
            success, result = db.execute_buy_now(auction_id, user_id)
            if success:
                buy_now_price = result
                safe_answer_callback_query(call.id, " تم الشراء بنجاح!", show_alert=True)
                # توزيع الأموال
                distribution = distribute_auction_funds(auction_id, buy_now_price, auction_info['user_id'], user_id)
                # إشعار البائع
                seller = db.get_user(auction_info['user_id'])
                seller_contact = f"@{seller['username']}" if seller and seller['username'] else f"ID {auction_info['user_id']}"
                try:
                    bot.send_message(
                        auction_info['user_id'],
                        "\n".join([
                            f"⚡️ {hb('تم بيع مزادك بالشراء الفوري!')}  {hc('#' + str(auction_id))}",
                            DIVIDER,
                            f"📦 {hb('المنتج:')} {html_escape(auction_info.get('title','') or '')}",
                            f"💰 {hb('سعر البيع:')} {fmt_money(buy_now_price)}",
                            f"🧾 {hb('العمولة:')} {fmt_money(distribution['commission'])} ({COMMISSION_RATE*100:.1f}%)",
                            f"💵 {hb('صافي المبلغ:')} {fmt_money(distribution['seller_amount'])}",
                            DIVIDER,
                            "📩 تواصل مع المشتري لتسليم المنتج",
                        ]),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                # إشعار المشتري
                try:
                    bot.edit_message_text(
                        "\n".join([
                            f"✅ {hb('تم الشراء بنجاح!')}",
                            DIVIDER,
                            f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                            f"📦 {hb('المنتج:')} {html_escape(auction_info.get('title','') or '')}",
                            f"💰 {hb('سعر الشراء:')} {fmt_money(buy_now_price)}",
                            f"👛 {hb('رصيدك الجديد:')} {fmt_money(db.get_balance(user_id))}",
                            DIVIDER,
                            f"📩 {hb('تواصل مع البائع لاستلام المنتج:')}",
                            html_escape(seller_contact),
                        ]),
                        chat_id, message_id, parse_mode="HTML",
                        reply_markup=types.InlineKeyboardMarkup().row(
                            types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary")
                        )
                    )
                except Exception:
                    pass
                # استرداد المزايدين الآخرين
                bids = db.get_auction_bids(auction_id)
                for bid in bids:
                    if bid['user_id'] != user_id:
                        db.refund_bid(bid['bid_id'])
                        db.add_transaction(bid['user_id'], bid['amount'], "bid_refund", f"استرداد — شراء فوري مزاد #{auction_id}")
                        queue_send(bid['user_id'],
                            "\n".join([
                                f"↩️ {hb('تم استرداد مزايدتك')}",
                                DIVIDER,
                                f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                                f"💰 {hb('المبلغ:')} {fmt_money(bid['amount'])}",
                                f"ℹ️ {hb('السبب:')} تم بيع المزاد بالشراء الفوري",
                            ]),
                            parse_mode="HTML"
                        )
                finalize_auction_broadcast(auction_id, winner_name=f"مشتري فوري")
            else:
                safe_answer_callback_query(call.id, result, show_alert=True)

        elif call.data.startswith("bid_") and not call.data.startswith("bid_confirm_") and not call.data.startswith("bid_custom_"):
            auction_id = call.data.replace("bid_", "")

            def _bid_edit(txt, kb=None):
                """تعديل الرسالة الحالية — fallback إلى send إن تعذّر."""
                try:
                    bot.edit_message_text(txt, chat_id, message_id, reply_markup=kb, parse_mode="HTML")
                except Exception:
                    bot.send_message(chat_id, txt, reply_markup=kb, parse_mode="HTML")
                safe_answer_callback_query(call.id)

            back_kb = types.InlineKeyboardMarkup()
            back_kb.row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"auction_details_{auction_id}", style="primary"))

            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                _bid_edit("⚠️ هذا المزاد لم يعد متاحاً!")
                return
            if auction_info['user_id'] == user_id:
                _bid_edit("🚫 لا يمكنك المزايدة على مزادك الخاص!", back_kb)
                return
            check_auction_ended(auction_id)
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info or auction_info['status'] != 'active':
                _bid_edit("⏰ انتهى وقت المزاد!", back_kb)
                return
            ends_at = db.parse_datetime(auction_info['ends_at'])
            time_left = (ends_at - datetime.now()).total_seconds() if ends_at else 0
            if time_left <= 0:
                _bid_edit("⏰ انتهى وقت المزاد!", back_kb)
                return
            user_balance = db.get_balance(user_id)
            current_price = auction_info['current_price']
            min_bid = round(current_price + 0.01, 2)
            if user_balance < min_bid:
                wallet_kb = types.InlineKeyboardMarkup()
                wallet_kb.row(types.InlineKeyboardButton("💳 اشحن رصيدك", callback_data="wallet", style="primary"))
                wallet_kb.row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"auction_details_{auction_id}", style="primary"))
                _bid_edit(
                    "\n".join([
                        f"⚠️ {hb('رصيدك غير كافٍ للمزايدة')}",
                        DIVIDER,
                        f"👛 {hb('رصيدك الحالي:')} {fmt_money(user_balance)}",
                        f"💰 {hb('أدنى مزايدة:')} {fmt_money(min_bid)}",
                        DIVIDER,
                        "اشحن رصيدك من المحفظة ثم عُد للمزايدة.",
                    ]),
                    wallet_kb
                )
                return
            # حساب مقترحات المزايدة الذكية بناءً على السعر الحالي
            def _smart_steps(price):
                if price < 5:      return [0.5, 1, 2, 5]
                elif price < 20:   return [1, 2, 5, 10]
                elif price < 100:  return [2, 5, 10, 25]
                elif price < 500:  return [5, 10, 25, 50]
                elif price < 2000: return [10, 25, 50, 100]
                else:              return [25, 50, 100, 250]
            steps = _smart_steps(current_price)
            hours_left = int(time_left // 3600)
            minutes_left = int((time_left % 3600) // 60)
            seconds_left = int(time_left % 60)
            time_str = f"{hours_left}س {minutes_left}د" if hours_left > 0 else f"{minutes_left}:{seconds_left:02d}"
            user_rank = get_bid_rank(auction_id, user_id)
            is_leading = auction_info.get('current_bidder') == user_id
            rank_line = (
                "🏆 " + hb("أنت الرابح حالياً!") if is_leading
                else f"🏅 {hb('رتبتك:')} {html_escape(user_rank)}" if user_rank != "لم يتم العثور"
                else "📌 لم تزايد بعد — كن الأول!"
            )
            text = "\n".join([
                f"🔥 {hb('المزايدة على')} {hc('#' + str(auction_id))}",
                html_escape(auction_info['title']),
                DIVIDER,
                f"💰 {hb('السعر الحالي:')} {fmt_money(current_price)}",
                f"👛 {hb('رصيدك:')} {fmt_money(user_balance)}",
                f"⏳ {hb('المتبقي:')} {time_str}",
                rank_line,
                DIVIDER,
                "اختر مبلغ المزايدة:",
            ])
            kb = types.InlineKeyboardMarkup()
            row_btns = []
            for step in steps:
                proposed = round(current_price + step, 2)
                if proposed <= user_balance:
                    row_btns.append(types.InlineKeyboardButton(
                        f"+{step}$ ({proposed:.2f}$)",
                        callback_data=f"bid_confirm_{auction_id}_{proposed}",
                        style="primary"
                    ))
            for i in range(0, len(row_btns), 2):
                kb.row(*row_btns[i:i+2])
            kb.row(types.InlineKeyboardButton("✏️ مبلغ مخصص", callback_data=f"bid_custom_{auction_id}", style="primary"))
            kb.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"auction_details_{auction_id}", style="danger"))
            _bid_edit(text, kb)

        elif call.data.startswith("bid_confirm_"):
            # bid_confirm_{auction_id}_{amount}
            parts = call.data.replace("bid_confirm_", "").rsplit("_", 1)
            if len(parts) != 2:
                safe_answer_callback_query(call.id, "بيانات غير صالحة!")
                return
            auction_id, bid_amount_str = parts[0], parts[1]
            try:
                bid_amount = float(bid_amount_str)
            except ValueError:
                safe_answer_callback_query(call.id, "مبلغ غير صالح!")
                return

            def _confirm_edit(txt, kb=None):
                try:
                    bot.edit_message_text(txt, chat_id, message_id, reply_markup=kb, parse_mode="HTML")
                except Exception:
                    bot.send_message(chat_id, txt, reply_markup=kb, parse_mode="HTML")
                safe_answer_callback_query(call.id)

            back_kb = types.InlineKeyboardMarkup()
            back_kb.row(
                types.InlineKeyboardButton("🔄 زايد الآن", callback_data=f"bid_{auction_id}", style="primary"),
                types.InlineKeyboardButton("🔙 رجوع", callback_data=f"auction_details_{auction_id}", style="primary")
            )

            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                _confirm_edit("⚠️ المزاد غير موجود!")
                return
            if auction_info['user_id'] == user_id:
                _confirm_edit("🚫 لا يمكنك المزايدة على مزادك!", back_kb)
                return
            check_auction_ended(auction_id)
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info or auction_info['status'] != 'active':
                _confirm_edit("⏰ انتهى وقت المزاد!", back_kb)
                return
            if bid_amount <= auction_info['current_price']:
                refresh_kb = types.InlineKeyboardMarkup()
                refresh_kb.row(
                    types.InlineKeyboardButton("🔄 زايد بالسعر الجديد", callback_data=f"bid_{auction_id}", style="primary"),
                    types.InlineKeyboardButton("❌ إلغاء", callback_data=f"auction_details_{auction_id}", style="danger")
                )
                _confirm_edit(
                    "\n".join([
                        f"⚡ {hb('تغيّر السعر!')}",
                        DIVIDER,
                        f"💰 {hb('السعر الحالي الآن:')} {fmt_money(auction_info['current_price'])}",
                        "",
                        "اضغط «زايد بالسعر الجديد» لتحديث الخيارات.",
                    ]),
                    refresh_kb
                )
                return
            user_balance = db.get_balance(user_id)
            if user_balance < bid_amount:
                wallet_kb = types.InlineKeyboardMarkup()
                wallet_kb.row(types.InlineKeyboardButton("💳 اشحن رصيدك", callback_data="wallet", style="primary"))
                wallet_kb.row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"auction_details_{auction_id}", style="primary"))
                _confirm_edit(
                    "\n".join([
                        f"⚠️ {hb('رصيدك غير كافٍ!')}",
                        DIVIDER,
                        f"👛 {hb('رصيدك:')} {fmt_money(user_balance)}",
                        f"💰 {hb('المطلوب:')} {fmt_money(bid_amount)}",
                        DIVIDER,
                        "اشحن رصيدك من المحفظة ثم عُد للمزايدة.",
                    ]),
                    wallet_kb
                )
                return
            prev_bidder = auction_info.get('current_bidder')
            # Rate Limiting: منع spam المزايدات
            if not check_bid_rate_limit(user_id):
                safe_answer_callback_query(call.id, "⚠️ تُزايد بسرعة كبيرة! انتظر ثوانٍ.", show_alert=True)
                return
            success, msg = db.add_bid(auction_id, user_id, bid_amount)
            if not success:
                err_kb = types.InlineKeyboardMarkup()
                err_kb.row(
                    types.InlineKeyboardButton("🔄 حاول مجدداً", callback_data=f"bid_{auction_id}", style="primary"),
                    types.InlineKeyboardButton("🔙 رجوع", callback_data=f"auction_details_{auction_id}", style="primary")
                )
                try:
                    bot.edit_message_text(
                        f"⚠️ {hb('تعذّرت المزايدة')}\n{DIVIDER}\n{html_escape(msg)}",
                        chat_id, message_id, reply_markup=err_kb, parse_mode="HTML"
                    )
                except Exception:
                    bot.send_message(chat_id, f"⚠️ {msg}", reply_markup=err_kb, parse_mode="HTML")
                safe_answer_callback_query(call.id)
                return
            # تحديث الرسالة للمستخدم بتأكيد فوري
            new_balance = db.get_balance(user_id)
            rank = get_bid_rank(auction_id, user_id)
            is_extended = "⏱️ تم تمديد المزاد 5 دقائق!" in msg
            confirm_text = "\n".join([
                f"✅ {hb('تمت المزايدة بنجاح!')}",
                DIVIDER,
                f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                f"💰 {hb('مبلغك:')} {fmt_money(bid_amount)}",
                f"👛 {hb('رصيدك المتبقي:')} {fmt_money(new_balance)}",
                f"🏅 {hb('رتبتك:')} {html_escape(rank)}",
            ])
            if is_extended:
                confirm_text += "\n\n⏱️ " + hb("تم تمديد المزاد 5 دقائق إضافية!")
            confirm_kb = types.InlineKeyboardMarkup()
            confirm_kb.row(types.InlineKeyboardButton("🔹 زايد أعلى", callback_data=f"bid_{auction_id}", style="primary"))
            confirm_kb.row(types.InlineKeyboardButton("🔹 تفاصيل المزاد", callback_data=f"auction_details_{auction_id}", style="primary"))
            try:
                bot.edit_message_text(confirm_text, chat_id, message_id, reply_markup=confirm_kb, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, confirm_text, reply_markup=confirm_kb, parse_mode="HTML")
            safe_answer_callback_query(call.id, f"تمت المزايدة بـ {bid_amount:.2f}$!")
            # إشعار صاحب المزاد
            try:
                owner_name = f"@{call.from_user.username}" if call.from_user.username else f"مستخدم {user_id}"
                queue_send(
                    auction_info['user_id'],
                    "\n".join([
                        f"🔔 {hb('مزايدة جديدة على مزادك!')}  {hc('#' + str(auction_id))}",
                        DIVIDER,
                        f"👤 {hb('المزايد:')} {html_escape(owner_name)}",
                        f"💰 {hb('المبلغ الجديد:')} {fmt_money(bid_amount)}",
                        f"📊 {hb('عدد المزايدات:')} {(auction_info['bids_count'] or 0) + 1}",
                    ]),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            # إشعار المالك العام
            try:
                queue_send(
                    OWNER_ID,
                    "\n".join([
                        f"🔔 {hb('مزايدة جديدة')}",
                        f"{hc('#' + str(auction_id))} — @{html_escape(call.from_user.username or user_id)} — {fmt_money(bid_amount)}",
                    ]),
                    parse_mode="HTML"
                )
            except Exception:
                pass
            # إشعار المزايد السابق (outbid)
            if prev_bidder and prev_bidder != user_id:
                try:
                    bot_info = get_bot_info()
                    deep_link = f"https://t.me/{bot_info['username']}?start=auction_{auction_id}"
                    outbid_kb = types.InlineKeyboardMarkup()
                    outbid_kb.row(types.InlineKeyboardButton("🔹 زايد الآن!", url=deep_link, style="primary"))
                    queue_send(
                        prev_bidder,
                        "\n".join([
                            f"⚠️ {hb('تم تجاوز مزايدتك!')}",
                            DIVIDER,
                            f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                            f"📦 {hb('المنتج:')} {html_escape(auction_info.get('title', '') or '')}",
                            f"💰 {hb('السعر الجديد:')} {fmt_money(bid_amount)}",
                            DIVIDER,
                            "🔥 زايد الآن لاستعادة موقعك!",
                        ]),
                        keyboard=outbid_kb,
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            # إشعار المتابعين
            try:
                watchers = db.get_auction_watchers(auction_id)
                for watcher_id in watchers:
                    if watcher_id != user_id and watcher_id != auction_info['user_id']:
                        queue_send(
                            watcher_id,
                            "\n".join([
                                f"👀 {hb('مزاد تتابعه تحرّك!')}",
                                DIVIDER,
                                f"{hc('#' + str(auction_id))} — {html_escape(auction_info.get('title','') or '')}",
                                f"💰 {hb('السعر الجديد:')} {fmt_money(bid_amount)}",
                            ]),
                            parse_mode="HTML"
                        )
            except Exception:
                pass
            update_auction_broadcast(auction_id)

        elif call.data.startswith("bid_custom_"):
            auction_id = call.data.replace("bid_custom_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "المزاد غير موجود!", show_alert=True)
                return
            check_auction_ended(auction_id)
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info or auction_info['status'] != 'active':
                safe_answer_callback_query(call.id, "انتهى وقت المزاد!", show_alert=True)
                return
            user_balance = db.get_balance(user_id)
            db.set_user_state(user_id, f"waiting_bid_{auction_id}")
            custom_kb = types.InlineKeyboardMarkup()
            custom_kb.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"auction_details_{auction_id}", style="danger"))
            custom_text = (
                f"📋 *مزايدتك على المزاد*\n\n"
                f"المزاد: #{auction_id}\n"
                f"السعر الحالي: *{auction_info['current_price']:.2f}$*\n"
                f"رصيدك: *{user_balance:.2f}$*"
            )
            try:
                bot.edit_message_text(custom_text, chat_id, message_id, reply_markup=custom_kb, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, custom_text, reply_markup=custom_kb, parse_mode="Markdown")
            bot.send_message(
                chat_id, "أدخل مبلغ مزايدتك (يجب أن يكون أعلى من السعر الحالي):",
                reply_markup=types.ForceReply(selective=True)
            )
            safe_answer_callback_query(call.id)
        elif call.data.startswith("report_auction_"):
            auction_id = call.data.replace("report_auction_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "المزاد غير موجود!")
                return
            if auction_info['user_id'] == user_id:
                safe_answer_callback_query(call.id, "لا يمكنك الإبلاغ عن مزادك!", show_alert=True)
                return
            # التحقق إن بلّغ مسبقاً
            existing = db.get_auction_reports(auction_id)
            already = any(r['reporter_user_id'] == user_id for r in existing)
            if already:
                safe_answer_callback_query(call.id, "لقد أبلغت عن هذا المزاد مسبقاً!", show_alert=True)
                return
            db.set_user_state(user_id, f"waiting_report_reason_{auction_id}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("🔹 محتوى مخالف", callback_data=f"report_reason_{auction_id}_محتوى مخالف", style="primary"),
                types.InlineKeyboardButton("🔹 احتيال/نصب", callback_data=f"report_reason_{auction_id}_احتيال أو نصب", style="primary")
            )
            keyboard.row(
                types.InlineKeyboardButton("🔹 معرف مسروق", callback_data=f"report_reason_{auction_id}_معرف مسروق", style="primary"),
                types.InlineKeyboardButton("🔹 مزاد مكرر", callback_data=f"report_reason_{auction_id}_مزاد مكرر", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("🔹 سبب آخر (اكتبه)", callback_data=f"report_reason_{auction_id}_custom", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"auction_details_{auction_id}", style="danger"))
            bot.edit_message_text(
                f" *الإبلاغ عن المزاد #{auction_id}*\n\n"
                f"المنتج: {auction_info['title']}\n\n"
                f"اختر سبب البلاغ:",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data.startswith("report_reason_"):
            # report_reason_{auction_id}_{reason}
            parts = call.data.replace("report_reason_", "").split("_", 1)
            if len(parts) < 2:
                return
            auction_id, reason = parts[0], parts[1]
            if reason == "custom":
                db.set_user_state(user_id, f"waiting_report_reason_{auction_id}")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"auction_details_{auction_id}", style="danger"))
                bot.edit_message_text(
                    " *اكتب سبب البلاغ*\n\nأرسل سبب البلاغ كرسالة نصية:",
                    chat_id, message_id,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                return
            # إرسال البلاغ مباشرة
            ok, msg = db.add_auction_report(auction_id, user_id, reason)
            db.clear_user_state(user_id)
            if ok:
                report_count = db.get_auction_report_count(auction_id)
                auction_info = db.get_auction_by_id(auction_id)
                reporter = db.get_user(user_id)
                reporter_name = f"@{reporter['username']}" if reporter and reporter['username'] else f"ID {user_id}"
                try:
                    bot.send_message(
                        OWNER_ID,
                        f" *بلاغ جديد على مزاد*\n\n"
                        f"المزاد: #{auction_id}\n"
                        f"المنتج: {auction_info['title'] if auction_info else 'غير معروف'}\n"
                        f"المُبلِّغ: {reporter_name}\n"
                        f"السبب: {reason}\n"
                        f"إجمالي البلاغات: {report_count}",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error notifying owner of auction report: {e}")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 للمزاد", callback_data=f"auction_details_{auction_id}", style="primary"))
                bot.edit_message_text(
                    " *تم إرسال البلاغ بنجاح*\n\nشكراً — سيتم مراجعته من قبل الإدارة.",
                    chat_id, message_id,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                safe_answer_callback_query(call.id, msg, show_alert=True)

        elif call.data.startswith("view_bids_"):
            auction_id = call.data.replace("view_bids_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "هذا المزاد لم يعد متاحاً!")
                return
            bids = db.get_auction_bids(auction_id)
            if not bids:
                text = f"لا توجد مزايدات على المزاد #{auction_id} بعد\n\n"
            else:
                text = f"المزايدات على المزاد #{auction_id}:\n\n"
                for i, bid in enumerate(bids[:20], 1):
                    user_name = bid['first_name'] or f"مستخدم {bid['user_id']}"
                    if bid['username']:
                        user_name = f"@{bid['username']}"
                    text += f"{i}. {user_name}\n {bid['amount']:.2f}$\n {bid['bid_time'][:16] if isinstance(bid['bid_time'], str) else db.parse_datetime(bid['bid_time']).strftime('%Y-%m-%d %H:%M')}\n"
                    if i == 1:
                        text += f"الأعلى حالياً\n"
                    text += f" --------------------\n"
            user_bids = db.get_user_bids(user_id, auction_id)
            can_refund = len(user_bids) > 0
            keyboard = create_auction_details_keyboard(auction_id, user_id, can_refund)
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        elif call.data.startswith("refund_bid_"):
            auction_id = call.data.replace("refund_bid_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "هذا المزاد لم يعد متاحاً!")
                return
            user_bids = db.get_user_bids(user_id, auction_id)
            if not user_bids:
                safe_answer_callback_query(call.id, "ليس لديك مزايدات في هذا المزاد!")
                return
            total_bids = sum([bid['amount'] for bid in user_bids])
            for bid in user_bids:
                # refund_bid يُضيف الرصيد داخلياً — لا نستدعي update_balance هنا لتجنب double refund
                if db.refund_bid(bid['bid_id']):
                    db.add_transaction(user_id, bid['amount'], "bid_refund", f"استرداد مزايدة #{bid['bid_id']} من مزاد #{auction_id}")
            if auction_info['current_bidder'] == user_id:
                other_bids = db.get_auction_bids(auction_id)
                other_bids = [b for b in other_bids if b['user_id'] != user_id]
                if other_bids:
                    highest_bid = max(other_bids, key=lambda x: x['amount'])
                    # تحديث مباشر بدون خصم رصيد أو تمديد وقت
                    cursor = db.conn.cursor()
                    cursor.execute(
                        "UPDATE auctions SET current_bidder = ?, current_price = ? WHERE auction_id = ?",
                        (highest_bid['user_id'], highest_bid['amount'], auction_id)
                    )
                    db.conn.commit()
                else:
                    cursor = db.conn.cursor()
                    cursor.execute("UPDATE auctions SET current_bidder = NULL, current_price = starting_price WHERE auction_id = ?", (auction_id,))
                    db.conn.commit()
            safe_answer_callback_query(call.id, f"تم استرداد {len(user_bids)} مزايدة بقيمة {total_bids:.2f}$!")
            keyboard = create_auction_details_keyboard(auction_id, user_id, False)
            bot.edit_message_text(f"تم استرداد جميع مزايداتك في هذا المزاد!\n\nالمجموع المسترد: {total_bids:.2f}$\nعدد المزايدات: {len(user_bids)}\n\nيمكنك الآن المزايدة مرة أخرى إذا رغبت.", chat_id, message_id, reply_markup=keyboard)
        # نظام الدعم الذكي 
        elif call.data == "ai_support":
            nav_push(user_id, "ai_support")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 فتح تذكرة دعم جديدة", callback_data="ai_support_new", style="primary"))
            existing = db_get_open_ticket(user_id)
            if existing:
                keyboard.row(types.InlineKeyboardButton("🔹 متابعة تذكرتي المفتوحة", callback_data="ai_support_continue", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            try:
                bot.edit_message_text(
                    " *مركز الدعم الفني الذكي*\n\n"
                    "مساعد الدعم سيحاول حل مشكلتك فوراً،\n"
                    "وإذا احتاج يرسلها للإدارة مباشرة.\n\n"
                    "معظم المشاكل تُحل في دقائق!",
                    chat_id, message_id,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(
                    chat_id,
                    " *مركز الدعم الفني الذكي*\n\n"
                    "مساعد الدعم سيحاول حل مشكلتك فوراً.",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )

        elif call.data == "ai_support_new":
            ticket_id = db_create_ticket(user_id)
            db.set_user_state(user_id, f"ai_support_chat_{ticket_id}", {"ticket_id": ticket_id})
            # رسالة ترحيبية ثابتة — بدون استدعاء API لتوفير الوقت
            greeting = (
                "أهلاً! أنا مساعد الدعم الفني.\n\n"
                "اختر نوع مشكلتك من الأزرار أدناه\n"
                "أو اكتب مشكلتك مباشرة بكلامك الخاص "
            )
            history = [{"role": "assistant", "content": greeting}]
            db_update_ticket_history(ticket_id, history)
            keyboard = types.InlineKeyboardMarkup()
            # أزرار اختصار للمشاكل الشائعة
            keyboard.row(
                types.InlineKeyboardButton("🔹 مشكلة رصيد", callback_data=f"support_quick_balance_{ticket_id}", style="primary"),
                types.InlineKeyboardButton("🔹 مشكلة مزاد", callback_data=f"support_quick_auction_{ticket_id}", style="primary")
            )
            keyboard.row(
                types.InlineKeyboardButton("📥 مشكلة شحن", callback_data=f"support_quick_charge_{ticket_id}", style="primary"),
                types.InlineKeyboardButton("🔹 مشكلة تحقق", callback_data=f"support_quick_verify_{ticket_id}", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("🔹 مشكلة أخرى", callback_data=f"support_quick_other_{ticket_id}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 إرسال للإدارة مباشرة", callback_data=f"ai_support_send_{ticket_id}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"ai_support_cancel_{ticket_id}", style="danger"))
            try:
                bot.edit_message_text(
                    f" *مساعد الدعم الفني*\n\n{greeting}\n\n"
                    f"_تذكرة #{ticket_id}_",
                    chat_id, message_id,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(
                    chat_id,
                    f" *مساعد الدعم الفني*\n\n{greeting}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )

        elif call.data == "ai_support_continue":
            ticket = db_get_open_ticket(user_id)
            if not ticket:
                safe_answer_callback_query(call.id, "لا توجد تذكرة مفتوحة!")
                return
            db.set_user_state(user_id, f"ai_support_chat_{ticket['ticket_id']}", {"ticket_id": ticket['ticket_id']})
            history = ticket['ai_history']
            last_ai = next((m['content'] for m in reversed(history) if m['role'] == 'assistant'), "تفضل، اكمل شرح مشكلتك.")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إرسال للإدارة", callback_data=f"ai_support_send_{ticket['ticket_id']}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء التذكرة", callback_data=f"ai_support_cancel_{ticket['ticket_id']}", style="danger"))
            bot.edit_message_text(
                f" *متابعة التذكرة #{ticket['ticket_id']}*\n\n{last_ai}",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data.startswith("support_quick_"):
            # أزرار الاختصار للمشاكل الشائعة 
            parts = call.data.replace("support_quick_", "").rsplit("_", 1)
            issue_type = parts[0]
            ticket_id = int(parts[1])
            ticket = db_get_ticket_by_id(ticket_id)
            if not ticket or ticket['user_id'] != user_id:
                safe_answer_callback_query(call.id, "التذكرة غير موجودة!")
                return
            db.set_user_state(user_id, f"ai_support_chat_{ticket_id}", {"ticket_id": ticket_id})
            # خريطة المشكلة لنص يُرسل للذكاء
            QUICK_ISSUE_MAP = {
                "balance": "عندي مشكلة في الرصيد — لم يُضف أو ناقص",
                "auction": "عندي مشكلة في المزاد — مرفوض أو لا أستطيع المزايدة",
                "charge": "عندي مشكلة في الشحن — شحنت ولم يُضف الرصيد",
                "verify": "عندي مشكلة في التحقق — طلب هاتف أو موقع ولم يكتمل",
                "other": "عندي مشكلة أخرى",
            }
            user_text = QUICK_ISSUE_MAP.get(issue_type, "عندي مشكلة")
            history = ticket['ai_history']
            history.append({"role": "user", "content": user_text})
            wait_msg = bot.send_message(chat_id, "مساعد الدعم يفكر...")
            ai_reply = ask_claude(history, user_id=user_id)
            ai_log_id = get_ai_last_log_id(history)
            if not ai_reply:
                ai_reply = (
                    "شكراً، فهمت مشكلتك.\n\n"
                    "أخبرني بتفاصيل أكثر:\n"
                    "• متى حدثت المشكلة بالضبط؟\n"
                    "• ما الخطوات التي قمت بها قبل المشكلة؟"
                )
            history.append({"role": "assistant", "content": ai_reply})
            db_update_ticket_history(ticket_id, history)
            try:
                bot.delete_message(chat_id, wait_msg.message_id)
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إرسال للإدارة", callback_data=f"ai_support_send_{ticket_id}", style="primary"))
            if ai_log_id:
                keyboard.row(
                    types.InlineKeyboardButton("👍 الرد مفيد", callback_data=f"ai_feedback_up_{ai_log_id}", style="primary"),
                    types.InlineKeyboardButton("👎 لم يساعد", callback_data=f"ai_feedback_down_{ai_log_id}", style="danger")
                )
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"ai_support_cancel_{ticket_id}", style="danger"))
            try:
                bot.edit_message_text(
                    f" *مساعد الدعم:*\n\n{ai_reply}\n\n_تذكرة #{ticket_id}_",
                    chat_id, message_id,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(
                    chat_id,
                    f" *مساعد الدعم:*\n\n{ai_reply}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            safe_answer_callback_query(call.id)

        elif call.data.startswith("ai_feedback_up_") or call.data.startswith("ai_feedback_down_"):
            # تقييم المستخدم لرد الذكاء الاصطناعي — يُغذّي نظام التعلّم لمراجعة الأدمن لاحقاً
            is_positive = call.data.startswith("ai_feedback_up_")
            log_id = int(call.data.replace("ai_feedback_up_" if is_positive else "ai_feedback_down_", ""))
            db.set_ai_feedback(log_id, "up" if is_positive else "down")
            safe_answer_callback_query(
                call.id,
                "شكراً لتقييمك!" if is_positive else "شكراً لملاحظتك، سنراجع هذا السؤال لتحسين الإجابات.",
                show_alert=False
            )

        elif call.data.startswith("ai_support_send_"):
            ticket_id = int(call.data.replace("ai_support_send_", ""))
            ticket = db_get_ticket_by_id(ticket_id)
            if not ticket or ticket['user_id'] != user_id:
                safe_answer_callback_query(call.id, "التذكرة غير موجودة!")
                return
            history = ticket['ai_history']
            if len(history) < 2:
                safe_answer_callback_query(call.id, "أخبرني بمشكلتك أولاً قبل الإرسال!")
                return
            safe_answer_callback_query(call.id, "جاري تحليل المشكلة وإرسالها...")
            # توليد ملخص
            summary = generate_support_summary(history)
            db_close_ticket(ticket_id, summary)
            db.clear_user_state(user_id)
            # إرسال للإدارة
            user_info = db.get_user(user_id)
            uname = f"@{user_info['username']}" if user_info and user_info['username'] else f"ID {user_id}"
            fname = user_info['first_name'] if user_info else ""
            try:
                keyboard_admin = types.InlineKeyboardMarkup()
                keyboard_admin.row(
                    types.InlineKeyboardButton("🔹 تم الحل", callback_data=f"support_resolved_{ticket_id}_{user_id}", style="primary"),
                    types.InlineKeyboardButton("🔹 رد على المستخدم", callback_data=f"support_reply_{ticket_id}_{user_id}", style="primary")
                )
                bot.send_message(
                    OWNER_ID,
                    f" *تذكرة دعم جديدة #{ticket_id}*\n\n"
                    f"المستخدم: {uname} ({fname})\n"
                    f"الأيدي: `{user_id}`\n"
                    f"{''*28}\n"
                    f"{summary}\n"
                    f"{''*28}\n"
                    f" {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    parse_mode="Markdown",
                    reply_markup=keyboard_admin
                )
            except Exception as e:
                logger.error(f"Error sending support ticket to admin: {e}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(
                " *تم إرسال مشكلتك للإدارة بنجاح!*\n\n"
                f"رقم التذكرة: *#{ticket_id}*\n\n"
                "سيتواصل معك المسؤول قريباً.",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data.startswith("ai_support_cancel_"):
            ticket_id = int(call.data.replace("ai_support_cancel_", ""))
            db_close_ticket(ticket_id)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            try:
                bot.edit_message_text("تم إلغاء التذكرة.", chat_id, message_id, reply_markup=keyboard)
            except Exception:
                bot.send_message(chat_id, "تم إلغاء التذكرة.", reply_markup=keyboard)

        elif call.data.startswith("ai_support_resolved_"):
            ticket_id = int(call.data.replace("ai_support_resolved_", ""))
            db_close_ticket(ticket_id, "resolved_by_ai")
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            try:
                bot.edit_message_text(
                    " *ممتاز! سعيد بمساعدتك* \n\n"
                    "إذا احتجت مساعدة مرة ثانية اضغط زر الدعم الفني.",
                    chat_id, message_id,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(chat_id, "سعيد بمساعدتك!", reply_markup=keyboard)
            safe_answer_callback_query(call.id, "تم إغلاق التذكرة")

        # ردود الإدارة على تذاكر الدعم 
        elif call.data.startswith("support_resolved_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            parts = call.data.replace("support_resolved_", "").split("_")
            ticket_id, target_uid = int(parts[0]), int(parts[1])
            safe_answer_callback_query(call.id, "تم تحديد التذكرة كمحلولة")
            try:
                bot.send_message(target_uid,
                    f" *تم حل مشكلتك!*\n\nرقم التذكرة: #{ticket_id}\nإذا احتجت مساعدة أخرى استخدم زر الدعم الفني.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=types.InlineKeyboardMarkup())
                bot.send_message(chat_id, f"تم إعلام المستخدم {target_uid} بحل تذكرته #{ticket_id}")
            except Exception:
                pass

        elif call.data.startswith("support_reply_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            parts = call.data.replace("support_reply_", "").split("_")
            ticket_id, target_uid = int(parts[0]), int(parts[1])
            db.set_user_state(user_id, "support_replying", {"ticket_id": ticket_id, "target_uid": target_uid})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.send_message(chat_id, f"اكتب ردك على المستخدم (تذكرة #{ticket_id}):", reply_markup=keyboard)

        # لوحة إدارة تذاكر الدعم 
        elif call.data == "admin_support_tickets":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            tickets = db_get_all_open_tickets()
            if not tickets:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا توجد تذاكر مفتوحة حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            text = f" *تذاكر الدعم المفتوحة ({len(tickets)})*\n\n"
            keyboard = types.InlineKeyboardMarkup()
            for t in tickets[:10]:
                name = f"@{t['username']}" if t['username'] else (t['first_name'] or f"ID {t['user_id']}")
                text += f"#{t['ticket_id']} | {name} | {str(t['created_at'])[:16]}\n"
                keyboard.row(types.InlineKeyboardButton(
                    f"#{t['ticket_id']} - {name}",
                    callback_data=f"support_reply_{t['ticket_id']}_{t['user_id']}",
                    style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "admin_panel":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            nav_push(user_id, "admin_panel")
            keyboard = create_admin_keyboard()
            try:
                s = db.get_stats()
                overview = (
                    f"🔧 لوحة الإدارة\n\n"
                    f"👥 المستخدمون: {s['total_users']} | 🆕 جديد: {s['new_users']}\n"
                    f"📦 نشط: {s['active_auctions']} | ⏳ معلق: {s['pending_auctions']} | ✅ مباع: {s['sold_auctions']}\n"
                    f"💰 الإيرادات: {fmt_money(s['total_revenue'])}\n\n"
                    f"اختر القسم المطلوب:"
                )
            except Exception:
                overview = "لوحة الإدارة\n\nاختر القسم المطلوب:"
            bot.edit_message_text(overview, chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_cat_auctions":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_admin_auctions_keyboard()
            bot.edit_message_text("📊 المزادات والإحصائيات\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_cat_users":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_admin_users_keyboard()
            bot.edit_message_text("👥 إدارة المستخدمين\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_cat_finance":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_admin_finance_keyboard()
            bot.edit_message_text("💰 المالية والمدفوعات\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_cat_partners":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_admin_partners_keyboard()
            bot.edit_message_text("🧑‍💼 الوكلاء والوسطاء\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_cat_channels":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_admin_channels_keyboard()
            bot.edit_message_text("📡 القنوات والبث\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_cat_content":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_admin_content_keyboard()
            bot.edit_message_text("🎯 المسابقات والمحتوى\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_cat_settings":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_admin_settings_keyboard()
            bot.edit_message_text("⚙️ الإعدادات العامة\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_stickers":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            STICKER_EVENTS = {
                "auction_win": "🏆 فوز بالمزاد",
                "new_auction": "📢 نشر مزاد جديد",
            }
            counts = {e['event_type']: e['count'] for e in db.get_all_sticker_events()}
            text = " *إدارة الملصقات*\n\nاختر المناسبة لعرض أو إضافة ملصقات:\n\n"
            keyboard = types.InlineKeyboardMarkup()
            for event_key, event_label in STICKER_EVENTS.items():
                cnt = counts.get(event_key, 0)
                keyboard.row(types.InlineKeyboardButton(
                    f"{event_label} ({cnt})", callback_data=f"admin_sticker_event_{event_key}", style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("admin_sticker_event_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            event_key = call.data.replace("admin_sticker_event_", "")
            stickers = db.get_stickers(event_key)
            text = f" *ملصقات هذه المناسبة*\n\nعدد الملصقات: {len(stickers)}\n\n"
            text += "اضغط *إضافة ملصق* وأرسل الملصق المطلوب مباشرة." if True else ""
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("➕ إضافة ملصق", callback_data=f"admin_sticker_add_{event_key}", style="primary"))
            for s in stickers[:10]:
                keyboard.row(types.InlineKeyboardButton(
                    f"🗑️ حذف ملصق #{s['id']}", callback_data=f"admin_sticker_del_{s['id']}_{event_key}", style="danger"
                ))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_stickers", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("admin_sticker_add_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            event_key = call.data.replace("admin_sticker_add_", "")
            db.set_user_state(user_id, "admin_waiting_sticker", {"event_type": event_key})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_sticker_event_{event_key}", style="danger"))
            bot.edit_message_text(
                "أرسل الآن الملصق المطلوب إضافته لهذه المناسبة.",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data.startswith("admin_sticker_del_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            rest = call.data.replace("admin_sticker_del_", "")
            sticker_id_str, event_key = rest.rsplit("_", 1)
            db.remove_sticker(int(sticker_id_str))
            safe_answer_callback_query(call.id, "تم حذف الملصق!")
            stickers = db.get_stickers(event_key)
            text = f" *ملصقات هذه المناسبة*\n\nعدد الملصقات: {len(stickers)}\n\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("➕ إضافة ملصق", callback_data=f"admin_sticker_add_{event_key}", style="primary"))
            for s in stickers[:10]:
                keyboard.row(types.InlineKeyboardButton(
                    f"🗑️ حذف ملصق #{s['id']}", callback_data=f"admin_sticker_del_{s['id']}_{event_key}", style="danger"
                ))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_stickers", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "admin_ai_learning":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            stats = db.get_ai_stats()
            text = (
                " *تطوير الذكاء الاصطناعي*\n\n"
                f"📊 إجمالي المحادثات: {stats['total']}\n"
                f"❓ أسئلة غير مفهومة: {stats['unknown']}\n"
                f"👍 تقييمات إيجابية: {stats['positive']}\n"
                f"👎 تقييمات سلبية: {stats['negative']}\n"
                f"🧠 أنماط مُتعلَّمة حتى الآن: {stats['learned_patterns']}\n\n"
                "راجع الأسئلة الفاشلة وأضف لها أنماطاً، ليتحسن فهم البوت تلقائياً."
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📋 مراجعة الأسئلة الفاشلة", callback_data="admin_ai_review_0", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("admin_ai_review_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            offset = int(call.data.replace("admin_ai_review_", ""))
            logs = db.get_unresolved_ai_logs(limit=50)
            if not logs:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("✅ لا توجد أسئلة فاشلة بانتظار المراجعة حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            if offset >= len(logs):
                offset = 0
            log = logs[offset]
            fb_label = {"up": "👍 إيجابي", "down": "👎 سلبي", None: "—"}.get(log['feedback'], "—")
            text = (
                f" *سؤال غير محلول ({offset + 1}/{len(logs)})*\n\n"
                f"💬 السؤال: {html_escape(log['user_message'])}\n"
                f"🎯 أقرب نية مطابقة: {log['matched_intent'] or 'لا توجد'}\n"
                f"📊 درجة الثقة: {log['confidence']:.2f}\n"
                f"تقييم المستخدم: {fb_label}\n"
                f"🕐 {str(log['created_at'])[:16]}\n\n"
                "اختر نية لربط هذا السؤال بها كنمط جديد، أو تجاهله:"
            )
            keyboard = types.InlineKeyboardMarkup()
            # أهم النيّات الشائعة لربط سريع
            common_intents = ["balance_not_added_binance", "balance_not_added_stars", "auction_pending",
                              "phone_why", "location_why", "delivery_law", "commission_question", "ban_reason"]
            for intent in common_intents:
                keyboard.row(types.InlineKeyboardButton(
                    f"➕ ربط بـ: {intent}", callback_data=f"admin_ai_link_{log['id']}_{intent}_{offset}", style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("⏭️ تجاهل (التالي)", callback_data=f"admin_ai_skip_{log['id']}_{offset}", style="primary"))
            if len(logs) > 1:
                next_offset = (offset + 1) % len(logs)
                keyboard.row(types.InlineKeyboardButton("➡️ السؤال التالي", callback_data=f"admin_ai_review_{next_offset}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("admin_ai_link_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            rest = call.data.replace("admin_ai_link_", "")
            log_id_str, intent, offset_str = rest.rsplit("_", 2)
            log_id = int(log_id_str)
            logs_all = db.get_unresolved_ai_logs(limit=50)
            target_log = next((l for l in logs_all if l['id'] == log_id), None)
            if target_log:
                db.add_learned_pattern(intent, target_log['user_message'], user_id, source_log_id=log_id)
                db.mark_ai_log_resolved(log_id)
                # تحديث محرك الفهم فوراً بدون إعادة تشغيل البوت
                try:
                    _local_ai.reload_learned_patterns()
                except Exception as e:
                    logger.error(f"reload_learned_patterns after link: {e}")
                safe_answer_callback_query(call.id, "✅ تم ربط السؤال وتحديث الفهم فوراً!")
            else:
                safe_answer_callback_query(call.id, "السؤال غير موجود (قد يكون رُوجع مسبقاً).")
            # عرض السؤال التالي تلقائياً
            logs = db.get_unresolved_ai_logs(limit=50)
            if not logs:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("✅ لا توجد أسئلة فاشلة بانتظار المراجعة حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            offset = 0
            log = logs[offset]
            fb_label = {"up": "👍 إيجابي", "down": "👎 سلبي", None: "—"}.get(log['feedback'], "—")
            text = (
                f" *سؤال غير محلول ({offset + 1}/{len(logs)})*\n\n"
                f"💬 السؤال: {html_escape(log['user_message'])}\n"
                f"🎯 أقرب نية مطابقة: {log['matched_intent'] or 'لا توجد'}\n"
                f"📊 درجة الثقة: {log['confidence']:.2f}\n"
                f"تقييم المستخدم: {fb_label}\n"
                f"🕐 {str(log['created_at'])[:16]}\n\n"
                "اختر نية لربط هذا السؤال بها كنمط جديد، أو تجاهله:"
            )
            keyboard = types.InlineKeyboardMarkup()
            common_intents = ["balance_not_added_binance", "balance_not_added_stars", "auction_pending",
                              "phone_why", "location_why", "delivery_law", "commission_question", "ban_reason"]
            for intent in common_intents:
                keyboard.row(types.InlineKeyboardButton(
                    f"➕ ربط بـ: {intent}", callback_data=f"admin_ai_link_{log['id']}_{intent}_{offset}", style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("⏭️ تجاهل (التالي)", callback_data=f"admin_ai_skip_{log['id']}_{offset}", style="primary"))
            if len(logs) > 1:
                next_offset = (offset + 1) % len(logs)
                keyboard.row(types.InlineKeyboardButton("➡️ السؤال التالي", callback_data=f"admin_ai_review_{next_offset}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("admin_ai_skip_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            rest = call.data.replace("admin_ai_skip_", "")
            log_id_str, offset_str = rest.rsplit("_", 1)
            db.mark_ai_log_resolved(int(log_id_str))
            safe_answer_callback_query(call.id, "تم التجاهل.")
            logs = db.get_unresolved_ai_logs(limit=50)
            if not logs:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("✅ لا توجد أسئلة فاشلة بانتظار المراجعة حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            offset = 0
            log = logs[offset]
            fb_label = {"up": "👍 إيجابي", "down": "👎 سلبي", None: "—"}.get(log['feedback'], "—")
            text = (
                f" *سؤال غير محلول ({offset + 1}/{len(logs)})*\n\n"
                f"💬 السؤال: {html_escape(log['user_message'])}\n"
                f"🎯 أقرب نية مطابقة: {log['matched_intent'] or 'لا توجد'}\n"
                f"📊 درجة الثقة: {log['confidence']:.2f}\n"
                f"تقييم المستخدم: {fb_label}\n"
                f"🕐 {str(log['created_at'])[:16]}\n\n"
                "اختر نية لربط هذا السؤال بها كنمط جديد، أو تجاهله:"
            )
            keyboard = types.InlineKeyboardMarkup()
            common_intents = ["balance_not_added_binance", "balance_not_added_stars", "auction_pending",
                              "phone_why", "location_why", "delivery_law", "commission_question", "ban_reason"]
            for intent in common_intents:
                keyboard.row(types.InlineKeyboardButton(
                    f"➕ ربط بـ: {intent}", callback_data=f"admin_ai_link_{log['id']}_{intent}_{offset}", style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("⏭️ تجاهل (التالي)", callback_data=f"admin_ai_skip_{log['id']}_{offset}", style="primary"))
            if len(logs) > 1:
                next_offset = (offset + 1) % len(logs)
                keyboard.row(types.InlineKeyboardButton("➡️ السؤال التالي", callback_data=f"admin_ai_review_{next_offset}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "admin_auction_reports":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            # جلب المزادات التي عليها بلاغات
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT auction_id, COUNT(*) as cnt FROM auction_reports "
                "GROUP BY auction_id ORDER BY cnt DESC LIMIT 20"
            )
            rows = cursor.fetchall()
            if not rows:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا يوجد أي بلاغات على المزادات حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            text = " *بلاغات المزادات*\n\n"
            keyboard = types.InlineKeyboardMarkup()
            for auction_id_r, cnt in rows:
                auction_info = db.get_auction_by_id(auction_id_r)
                title = auction_info['title'][:25] if auction_info else auction_id_r
                status = auction_info['status'] if auction_info else "؟"
                text += f"• #{auction_id_r} | {cnt} بلاغ | {status}\n {title}\n\n"
                keyboard.row(types.InlineKeyboardButton(
                    f"#{auction_id_r} ({cnt} بلاغ)", callback_data=f"admin_view_reports_{auction_id_r}", style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("admin_view_reports_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            auction_id = call.data.replace("admin_view_reports_", "")
            reports = db.get_auction_reports(auction_id)
            auction_info = db.get_auction_by_id(auction_id)
            if not reports:
                safe_answer_callback_query(call.id, "لا توجد بلاغات لهذا المزاد!")
                return
            text = f" *بلاغات المزاد #{auction_id}*\n"
            if auction_info:
                text += f"المنتج: {auction_info['title']}\nالحالة: {auction_info['status']}\n"
            text += f"عدد البلاغات: {len(reports)}\n{''*28}\n\n"
            for r in reports[:10]:
                name = f"@{r['username']}" if r['username'] else (r['first_name'] or f"ID {r['reporter_user_id']}")
                text += f" {name}\n {r['reason']}\n {str(r['created_at'])[:16]}\n\n"
            keyboard = types.InlineKeyboardMarkup()
            if auction_info and auction_info['status'] == 'active':
                keyboard.row(
                    types.InlineKeyboardButton("✅ موافقة (تجاهل)", callback_data=f"admin_ignore_reports_{auction_id}", style="primary"),
                    types.InlineKeyboardButton("🗑️ حذف المزاد", callback_data=f"admin_delete_reported_{auction_id}", style="danger")
                )
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للبلاغات", callback_data="admin_auction_reports", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("admin_ignore_reports_"):
            if user_id != OWNER_ID:
                return
            auction_id = call.data.replace("admin_ignore_reports_", "")
            cursor = db.conn.cursor()
            cursor.execute("DELETE FROM auction_reports WHERE auction_id=?", (auction_id,))
            db.conn.commit()
            safe_answer_callback_query(call.id, "تم تجاهل البلاغات وحذفها")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للبلاغات", callback_data="admin_auction_reports", style="primary"))
            bot.edit_message_text(f"تم تجاهل جميع بلاغات المزاد #{auction_id}.", chat_id, message_id, reply_markup=keyboard)

        elif call.data.startswith("admin_delete_reported_"):
            if user_id != OWNER_ID:
                return
            auction_id = call.data.replace("admin_delete_reported_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if auction_info:
                db.reject_auction(auction_id)
                # استرداد جميع المزايدين
                bids = db.get_auction_bids(auction_id)
                for bid in bids:
                    db.update_balance(bid['user_id'], bid['amount'])
                    db.add_transaction(bid['user_id'], bid['amount'], "bid_refund", f"استرداد — مزاد #{auction_id} محذوف بسبب بلاغ")
                    db.refund_bid(bid['bid_id'])
                    try:
                        bot.send_message(bid['user_id'], f"تم استرداد مزايدتك\n\nالمزاد #{auction_id} تم حذفه من قبل الإدارة.\nالمبلغ المسترد: {bid['amount']:.2f}$")
                    except:
                        pass
                # استرداد سعر البدء للبائع
                refund_starting_price_if_needed(auction_info)
                try:
                    bot.send_message(auction_info['user_id'], f"تم حذف مزادك #{auction_id} من قبل الإدارة بسبب بلاغات.")
                except:
                    pass
                # حذف بلاغاته
                cursor = db.conn.cursor()
                cursor.execute("DELETE FROM auction_reports WHERE auction_id=?", (auction_id,))
                db.conn.commit()
            safe_answer_callback_query(call.id, f"تم حذف المزاد #{auction_id}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(f"تم حذف المزاد #{auction_id} واسترداد جميع المزايدين.", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_stats":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            stats = db.get_stats()
            ext = db.get_extended_stats()
            banned_count = len(db.get_banned_users())

            def trend(today, yesterday):
                if yesterday == 0:
                    return f"+{today:.2f}" if today > 0 else "—"
                diff = today - yesterday
                pct = (diff / yesterday) * 100
                arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
                return f"{arrow} {abs(pct):.0f}%"

            def ascii_bar(val, max_val, width=8):
                if max_val <= 0:
                    return "░" * width
                filled = int((val / max_val) * width)
                return "█" * filled + "░" * (width - filled)

            top_bids_max = ext['top_bidders'][0][2] if ext['top_bidders'] else 1
            top_bidders_text = ""
            for i, (uid, uname, count) in enumerate(ext['top_bidders'], 1):
                bar = ascii_bar(count, top_bids_max)
                top_bidders_text += f"{i}. @{uname} [{bar}] {count}\n"

            text = (
                f"📊 *إحصائيات البوت*\n\n"
                f"👥 *المستخدمون*\n"
                f"الإجمالي: {stats['total_users']} | المحظورون: {banned_count}\n"
                f"اليوم: {ext['users_today']} (أمس: {ext['users_yesterday']})\n\n"
                f"🏷 *المزادات*\n"
                f"نشطة: {stats['active_auctions']} | معلقة: {stats['pending_auctions']} | مباعة: {stats['sold_auctions']}\n"
                f"اليوم: {ext['auctions_today']} مزاد | مبيعات اليوم: {ext['sales_today']}\n\n"
                f"💰 *الإيرادات*\n"
                f"اليوم: {ext['revenue_today']:.2f}$ {trend(ext['revenue_today'], ext['revenue_yesterday'])}\n"
                f"الأسبوع: {ext['revenue_week']:.2f}$ | الشهر: {ext['revenue_month']:.2f}$\n"
                f"الإجمالي الكلي: {stats['total_revenue']:.2f}$\n\n"
                f"📈 *قيم السوق*\n"
                f"قيمة المزادات النشطة: {stats['total_active_value']:.2f}$\n"
                f"قيمة المبيعات الكلية: {stats['total_sold_value']:.2f}$\n"
                f"إجمالي التحويلات: {stats['total_transfers']:.2f}$\n\n"
                f"📣 *القنوات*\n"
                f"قنوات البث: {stats['total_channels']} | الاشتراك: {stats['total_subscription_channels']}\n"
                f"إجمالي المشتركين: {stats['total_subscribers']}\n\n"
                f"🏆 *أكثر 5 مزايدين نشاطاً*\n"
                f"{top_bidders_text}"
                f"إجمالي المزايدات: {stats['total_bids']}"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
        elif call.data == "admin_pending":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            auctions = db.get_pending_auctions()
            if not auctions:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا توجد مزادات معلقة حالياً", chat_id, message_id, reply_markup=keyboard)
                return
            auction = auctions[0]
            user_info = db.get_user(auction['user_id'])
            username = user_info['username'] if user_info else "غير معروف"
            text = f"المزادات المعلقة:\n\n#{auction['auction_id']}\n@{username if username else 'بدون معرف'}\nأيدي المستخدم: {auction['user_id']}\nالنوع: {AUCTION_TYPES.get(auction['auction_type'], auction['auction_type'])}\nالمنصة: {SOCIAL_PLATFORMS.get(auction['platform'], auction['platform']) if auction['platform'] and auction['platform'] != 'telegram' else ('تليجرام' if auction['platform'] == 'telegram' else 'غير محدد')}\nالهدف: {auction['target']}\nالتاريخ: {auction['created_at'][:10] if isinstance(auction['created_at'], str) else db.parse_datetime(auction['created_at']).strftime('%Y-%m-%d')}\n\nاختر الإجراء:"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 قبول", callback_data=f"approve_{auction['auction_id']}", style="primary"), types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_{auction['auction_id']}", style="danger"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        elif call.data == "admin_users":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_user_management_keyboard()
            bot.edit_message_text("إدارة المستخدمين\n\nاختر الإجراء المطلوب:", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "admin_add_balance":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_user_id_for_add")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger"))
            bot.edit_message_text("أرسل أيدي المستخدم الذي تريد إضافة رصيد له:", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "admin_deduct_balance":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_user_id_for_deduct")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger"))
            bot.edit_message_text("أرسل أيدي المستخدم الذي تريد خصم رصيد منه:", chat_id, message_id, reply_markup=keyboard)
        elif call.data == "admin_list_users":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            users = db.get_all_users()
            if not users:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا توجد مستخدمين حالياً", chat_id, message_id, reply_markup=keyboard)
                return
            text = "قائمة المستخدمين:\n\n"
            for i, uid in enumerate(users[:20], 1):
                user_info = db.get_user(uid)
                if user_info:
                    text += f"{i}. @{user_info['username'] if user_info['username'] else 'بدون معرف'}\n {user_info['user_id']}\n {user_info['balance']:.2f}$\n"
                    if user_info['is_new']:
                        text += f"جديد: نعم\n"
                    text += f" --------------------\n"
            if len(users) > 20:
                text += f"\n ...و {len(users) - 20} مستخدم آخر"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 لإدارة المستخدمين", callback_data="admin_users", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        
        # الأزرار الجديدة للإدارة
        elif call.data == "manage_broadcast_channels":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_broadcast_channels_keyboard()
            bot.edit_message_text("إدارة قنوات البث (حيث يتم نشر المزادات الجديدة)\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "manage_subscription_channels":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = create_subscription_channels_management_keyboard()
            bot.edit_message_text("إدارة قنوات الاشتراك الإجباري\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "add_broadcast_channel":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_broadcast_channel_info")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_broadcast_channels", style="danger"))
            bot.edit_message_text("أرسل معرف القناة مع @ أو أيدي القناة:", chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "delete_broadcast_channel":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_channel_id_for_delete")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_broadcast_channels", style="danger"))
            bot.edit_message_text("أرسل أيدي القناة التي تريد حذفها:", chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "list_broadcast_channels":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            channels = db.get_all_channels()
            if not channels:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 للخلف", callback_data="manage_broadcast_channels", style="primary"))
                bot.edit_message_text("لا توجد قنوات بث مضافة", chat_id, message_id, reply_markup=keyboard)
                return
            text = (
                " *قنوات البث المضافة:*\n"
                "ℹ هذه القنوات للبث فقط ولا تُضاف للاشتراك الإجباري تلقائياً.\n\n"
            )
            for i, ch in enumerate(channels, 1):
                uname = f"@{ch['channel_username']}" if ch['channel_username'] else 'بدون معرف'
                text += f"{i}. {ch['channel_title']}\n   {uname}\n   `{ch['channel_id']}`\n   {str(ch['added_at'])[:10]}\n{''*20}\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 للخلف", callback_data="manage_broadcast_channels", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "add_subscription_channel":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_subscription_channel_info")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger"))
            bot.edit_message_text("إضافة قناة اشتراك إجباري\n\nأرسل معرف القناة مع @ أو أيدي القناة:", chat_id, message_id, reply_markup=keyboard)

        elif call.data.startswith("sub_type_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            sub_type = call.data.replace("sub_type_", "")
            user_state = db.get_user_state(user_id)
            if not user_state or user_state['state'] != "waiting_subscription_type":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            channel_data = user_state['data']
            if sub_type == "permanent":
                # دائم: max_subscribers = 0
                channel_data['max_subscribers'] = 0
                channel_data['sub_type'] = 'permanent'
                db.set_user_state(user_id, "confirming_subscription_channel", channel_data)
                channel_title = channel_data.get('channel_title', 'القناة')
                channel_username = channel_data.get('channel_username', '')
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(
                    types.InlineKeyboardButton("✅ تأكيد الإضافة", callback_data="confirm_subscription_channel", style="primary"),
                    types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger")
                )
                bot.edit_message_text(
                    f"تأكيد إضافة قناة الاشتراك:\n\n {channel_title}\n@{channel_username if channel_username else 'بدون معرف'}\n\n نوع الاشتراك: دائم (بلا حد)\n\nهل تريد تأكيد الإضافة؟",
                    chat_id, message_id, reply_markup=keyboard
                )
            elif sub_type == "paid":
                # مدفوع: يطلب عدد الاشتراكات
                db.set_user_state(user_id, "waiting_subscription_max_count", channel_data)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger"))
                bot.edit_message_text(
                    "اشتراك مدفوع\n\nأرسل عدد الاشتراكات المسموح بها:\n(عند الوصول للعدد ستُحذف القناة تلقائياً من الاشتراك الإجباري)",
                    chat_id, message_id, reply_markup=keyboard
                )
        
        elif call.data == "delete_subscription_channel":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_subscription_channel_id_for_delete")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger"))
            bot.edit_message_text("أرسل أيدي قناة الاشتراك التي تريد حذفها:", chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "list_subscription_channels":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            channels = db.get_subscription_channels()
            if not channels:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 للخلف", callback_data="manage_subscription_channels", style="primary"))
                bot.edit_message_text("لا توجد قنوات اشتراك إجباري", chat_id, message_id, reply_markup=keyboard)
                return
            text = "قنوات الاشتراك الإجباري:\n\n"
            for i, ch in enumerate(channels, 1):
                sub_type_label = "دائم" if ch.get('sub_type', 'permanent') == 'permanent' else f"مدفوع ({ch['max_subscribers']} اشتراك)"
                max_info = ""
                if ch.get('sub_type') == 'paid' and ch['max_subscribers'] > 0:
                    remaining = ch['max_subscribers'] - ch['subscriber_count']
                    max_info = f"\n متبقي: {remaining} من {ch['max_subscribers']}"
                text += f"{i}. {ch['channel_title']}\n @{ch['channel_username'] if ch['channel_username'] else 'بدون معرف'}\n المشتركين: {ch['subscriber_count']}\n النوع: {sub_type_label}{max_info}\n {ch['channel_id']}\n {ch['added_at'][:10]}\n --------------------\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 للخلف", callback_data="manage_subscription_channels", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "admin_set_duration":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            current = db.get_auction_duration()
            db.set_user_state(user_id, "waiting_auction_duration")
            keyboard = types.InlineKeyboardMarkup()
            # أزرار سريعة للمدد الشائعة
            keyboard.row(
                types.InlineKeyboardButton("🔹 1 ساعة", callback_data="set_dur_1", style="primary"),
                types.InlineKeyboardButton("🔹 3 ساعات", callback_data="set_dur_3", style="primary"),
                types.InlineKeyboardButton("🔹 6 ساعات", callback_data="set_dur_6", style="primary")
            )
            keyboard.row(
                types.InlineKeyboardButton("🔹 12 ساعة", callback_data="set_dur_12", style="primary"),
                types.InlineKeyboardButton("🔹 24 ساعة", callback_data="set_dur_24", style="primary"),
                types.InlineKeyboardButton("🔹 48 ساعة", callback_data="set_dur_48", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(
                f" *تحديد مدة المزاد الافتراضية*\n\n"
                f"المدة الحالية: {current} ساعة\n\n"
                f"اختر مدة من الأزرار أو أرسل رقماً (1-720 ساعة):",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data.startswith("set_dur_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            try:
                hours = int(call.data.replace("set_dur_", ""))
                db.set_setting('auction_duration', hours)
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text(
                    f"تم تحديث مدة المزاد إلى *{hours} ساعة*\n\nستُطبق على المزادات الجديدة فقط.",
                    chat_id, message_id,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                safe_answer_callback_query(call.id, f"المدة: {hours} ساعة")
            except:
                safe_answer_callback_query(call.id, "خطأ!")

        elif call.data == "update_subscribers":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            channels = db.get_subscription_channels()
            if not channels:
                safe_answer_callback_query(call.id, "لا توجد قنوات اشتراك!")
                return
            safe_answer_callback_query(call.id, "جارٍ تحديث أعداد المشتركين...")
            for channel in channels:
                try:
                    member_count = bot.get_chat_member_count(channel['channel_id'])
                    old_count = channel['subscriber_count'] or 0
                    db.update_subscriber_count(channel['channel_id'], member_count)
                    if channel['max_subscribers'] > 0 and member_count >= channel['max_subscribers']:
                        db.delete_subscription_channel(channel['channel_id'])
                        bot.send_message(OWNER_ID, f"تم حذف قناة الاشتراك المدفوعة!\n\nالقناة: {channel['channel_title']}\n@{channel['channel_username'] if channel['channel_username'] else 'بدون معرف'}\nعدد المشتركين: {member_count}/{channel['max_subscribers']}\n\nانتهت الاشتراكات المدفوعة.")
                    if member_count != old_count:
                        bot.send_message(OWNER_ID, f"تحديث عدد المشتركين في قناة {channel['channel_title']}:\n\nالعدد القديم: {old_count}\nالعدد الجديد: {member_count}\nالتغيير: {'+' if member_count > old_count else ''}{member_count - old_count}\n@{channel['channel_username'] if channel['channel_username'] else 'بدون معرف'}")
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"Error updating channel {channel['channel_id']}: {e}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 للخلف", callback_data="manage_subscription_channels", style="primary"))
            bot.edit_message_text(f"تم تحديث أعداد المشتركين لـ {len(channels)} قناة!", chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "create_code":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_code_amount")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.edit_message_text("إنشاء كود شحن جديد\n\nأرسل المبلغ بالدولار ($):", chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "list_codes":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            codes = db.get_all_recharge_codes()
            if not codes:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا توجد أكواد شحن", chat_id, message_id, reply_markup=keyboard)
                return
            text = "الأكواد المنشأة:\n\n"
            for code in codes[:10]:
                expires_at = db.parse_datetime(code['expires_at'])
                is_expired = expires_at < datetime.now() if expires_at else False
                is_used_up = code['used_count'] >= code['max_uses']
                status = "نشط"
                if not code['is_active']:
                    status = "معطل"
                elif is_expired:
                    status = "منتهي"
                elif is_used_up:
                    status = "مستنفذ"
                text += f" `{code['code']}`\n {code['amount']:.2f}$ | {code['used_count']}/{code['max_uses']} | {status}\n"
                if expires_at:
                    text += f" {expires_at.strftime('%Y-%m-%d')}\n"
                text += f"--------------------\n"
            keyboard = types.InlineKeyboardMarkup()
            # زر نسخ لكل كود (حتى 5 أكواد)
            for code in codes[:5]:
                expires_at = db.parse_datetime(code['expires_at'])
                is_expired = expires_at < datetime.now() if expires_at else False
                is_used_up = code['used_count'] >= code['max_uses']
                if code['is_active'] and not is_expired and not is_used_up:
                    keyboard.row(types.InlineKeyboardButton(
                        f" {code['code']}",
                        callback_data=f"copy_code_{code['code']}",
                        style="primary"
                    ))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
        
        elif call.data == "check_subscription":
            # مسح الكاش لإجبار تحقق حقيقي من Telegram API
            Database._sub_cache.pop(user_id, None)
            subscribed, result = check_subscription(user_id)
            if subscribed:
                is_new_user_cb = db.add_user(user_id, call.from_user.username, call.from_user.first_name, call.from_user.last_name)
                # استرجاع أي deep link معلق قبل مسح الـ state
                pending_state = db.get_user_state(user_id)
                pending_deep = None
                if pending_state and pending_state.get('state') == 'pending_deep_link':
                    pending_deep = (pending_state.get('data') or {}).get('deep_link_param')

                # معالجة رابط الإحالة المعلق — يُعالَج هنا لأن المستخدم لم يكمل /start بسبب الاشتراك
                if pending_deep and pending_deep.startswith('ref_'):
                    referrer_id_str = pending_deep.replace('ref_', '')
                    try:
                        referrer_id = int(referrer_id_str)
                        if referrer_id != user_id:
                            ok, card_number = db.register_referral(referrer_id, user_id)
                            if ok:
                                referrer_info = db.get_user(referrer_id)
                                r_name = f"@{referrer_info['username']}" if referrer_info and referrer_info['username'] else f"ID {referrer_id}"
                                try:
                                    bot.send_message(
                                        referrer_id,
                                        f" *حصلت على كارت جديد!*\n\n"
                                        f"انضم مستخدم جديد عبر رابطك!\n"
                                        f"رقم الكارت: `{card_number}`\n\n"
                                        f"كل كارت يُشاركك في سحوبات المسابقات ",
                                        parse_mode="Markdown"
                                    )
                                except Exception:
                                    pass
                    except (ValueError, Exception) as e:
                        logger.warning(f"[REF-CB] خطأ في معالجة الإحالة المعلقة: {e}")
                    pending_deep = None  # لا تكمل deep link الـ ref كـ navigation

                db.clear_user_state(user_id)

                # إذا في deep link معلق — أكمل منه مباشرةً
                if pending_deep and pending_deep.startswith('auction_'):
                    auction_id = pending_deep.replace('auction_', '')
                    auction_info = db.get_auction_by_id(auction_id)
                    if auction_info and auction_info['status'] == 'active':
                        check_auction_ended(auction_id)
                        auction_info = db.get_auction_by_id(auction_id)
                    if auction_info and auction_info['status'] == 'active':
                        ends_at = db.parse_datetime(auction_info['ends_at'])
                        time_left = ends_at - datetime.now()
                        if time_left.total_seconds() > 0:
                            hours_left = time_left.total_seconds() // 3600
                            minutes_left = (time_left.total_seconds() % 3600) // 60
                            user_bids = db.get_user_bids(user_id, auction_id)
                            can_refund = len(user_bids) > 0
                            text = f"تفاصيل المزاد #{auction_info['auction_id']}\n\n{auction_info['title']}\n{auction_info['target']}\nالنوع: {AUCTION_TYPES.get(auction_info['auction_type'], '')}\n"
                            if auction_info['platform']:
                                if auction_info['platform'] == "telegram":
                                    text += "المنصة: تليجرام\n"
                                else:
                                    text += f"المنصة: {SOCIAL_PLATFORMS.get(auction_info['platform'], auction_info['platform'])}\n"
                            text += f"\nالسعر الحالي: {auction_info['current_price']:.2f}$\nالسعر الابتدائي: {auction_info['starting_price']:.2f}$\nعدد المزايدات: {auction_info['bids_count']}\nالمتبقي: {int(hours_left)}:{int(minutes_left):02d}\n"
                            if user_bids:
                                text += f"\nلديك {len(user_bids)} مزايدة\nأعلى مزايدة لك: {max([b['amount'] for b in user_bids]):.2f}$\n"
                            kbd = create_auction_details_keyboard(auction_id, user_id, can_refund)
                            try:
                                bot.edit_message_text(text, chat_id, message_id, reply_markup=kbd)
                            except Exception:
                                bot.send_message(chat_id, text, reply_markup=kbd)
                            return
                    # المزاد انتهى أو غير موجود
                    keyboard = create_main_menu_keyboard(user_id)
                    try:
                        bot.edit_message_text("هذا المزاد لم يعد متاحاً أو انتهى.\n\nاختر من القائمة:", chat_id, message_id, reply_markup=keyboard)
                    except Exception:
                        bot.send_message(chat_id, "هذا المزاد لم يعد متاحاً أو انتهى.\n\nاختر من القائمة:", reply_markup=keyboard)
                    return

                elif pending_deep and pending_deep.startswith('contest_'):
                    try:
                        contest_id = int(pending_deep.replace('contest_', ''))
                        c = db.get_contest(contest_id)
                        if c and c['status'] in ('active', 'scheduled'):
                            participants = db.get_contest_participants_count(contest_id)
                            free_cards = db.get_user_free_cards_count(user_id, contest_id=contest_id)
                            text = f"🏆 *{md_escape(c['name'])}*\n\n{md_escape(c['description'] or '')}\n\n🎁 الجائزة: *{md_escape(_prize_label(c))}*\n👥 المشاركون: {participants}"
                            keyboard = types.InlineKeyboardMarkup()
                            if c['status'] == 'active' and free_cards > 0:
                                keyboard.row(types.InlineKeyboardButton(f" المشاركة بـ {free_cards} كارت", callback_data=f"enter_contest_{contest_id}", style="primary"))
                            keyboard.row(types.InlineKeyboardButton("🎯 المسابقات", callback_data="show_contests", style="primary"))
                            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                            try:
                                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
                            except Exception:
                                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")
                            return
                    except Exception as e:
                        logger.error(f"pending contest deep link error: {e}")

                # لا يوجد deep link معلق — عرض الصفحة الرئيسية
                balance = db.get_balance(user_id)
                keyboard = create_main_menu_keyboard(user_id)
                try:
                    bot.edit_message_text(
                        f"تم التحقق من اشتراكك!\n\nمرحباً {call.from_user.first_name}!\nرصيدك الحالي: {balance:.2f}$\n\nاختر من القائمة:",
                        chat_id, message_id, reply_markup=keyboard
                    )
                except Exception:
                    bot.send_message(chat_id, f"تم التحقق من اشتراكك!\n\nمرحباً {call.from_user.first_name}!\nرصيدك الحالي: {balance:.2f}$\n\nاختر من القائمة:", reply_markup=keyboard)
            else:
                channels_text, keyboard = result
                safe_answer_callback_query(call.id, "لم تشترك بعد في جميع القنوات!")
                bot.edit_message_text(channels_text, chat_id, message_id, reply_markup=keyboard)
        
        elif call.data == "admin_broadcast":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_broadcast")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.edit_message_text("أرسل الرسالة التي تريد بثها:\nيمكنك استخدام HTML للتصميم\n\nملاحظة: سيتم إرسال الرسالة لجميع المستخدمين", chat_id, message_id, reply_markup=keyboard)
        
        # 
        # بوابة الدفع عبر Binance 
        # 
        elif call.data == "binance_charge":
            if not BINANCE_ENABLED:
                safe_answer_callback_query(call.id, "بوابة الدفع غير متاحة حالياً!")
                return
            live_rate = get_usdt_rate()
            keyboard = types.InlineKeyboardMarkup()
            for plan_key, plan in CHARGE_PLANS.items():
                usd_val = plan['usdt']  # 1 USDT = $1
                keyboard.row(types.InlineKeyboardButton(
                    f" {plan['label']}",
                    callback_data=f"binance_plan_{plan_key}",
                    style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="charge", style="primary"))
            bot.edit_message_text(
                f" *شحن الرصيد عبر Binance*\n\n"
                f"سعر USDT الحالي: *{live_rate:.2f}$*\n"
                f"_(سعر السوق مع خصم {USDT_DISCOUNT_RATE*100:.2f}%)_\n\n"
                f"اختر المبلغ الذي تريد شحنه:",
                chat_id, message_id,
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        elif call.data.startswith("binance_plan_"):
            plan_key = call.data.replace("binance_plan_", "")
            plan = CHARGE_PLANS.get(plan_key)
            if not plan:
                safe_answer_callback_query(call.id, "خطة غير صالحة!")
                return
            live_rate = get_usdt_rate()
            usd_val = plan['usdt']  # 1 USDT = $1
            db.set_user_state(user_id, "waiting_binance_wallet", {
                "plan_key": plan_key,
                "usdt": plan['usdt'],
                "usd": usd_val,
                "rate": live_rate
            })
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="binance_charge", style="danger"))
            bot.edit_message_text(
                f" *تفاصيل الشحن عبر Binance*\n\n"
                f"المبلغ: *{plan['usdt']} USDT*\n"
                f"سعر USDT: *{live_rate:.2f}$*\n"
                f"يُضاف لرصيدك: *${usd_val:.2f}*\n\n"
                f"أرسل عنوان محفظتك (TRC20 أو BEP20)\n"
                f"حتى يتم التحقق من التحويل الصادر منها:",
                chat_id, message_id,
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        # تأكيد دفع يدوي من المشرف 
        elif call.data == "admin_confirm_binance":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            payments = db.get_pending_binance_payments()
            if not payments:
                safe_answer_callback_query(call.id, "لا توجد مدفوعات معلقة")
                return
            keyboard = types.InlineKeyboardMarkup()
            for p in payments[:8]:
                u = db.get_user(p['user_id'])
                name = u['first_name'] if u else str(p['user_id'])
                keyboard.row(types.InlineKeyboardButton(
                    f"#{p['pay_id']} | {p['usdt_amount']} USDT | {name}",
                    callback_data=f"approve_binance_{p['pay_id']}",
                    style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(
                " *المدفوعات المعلقة — اختر لتأكيد:*",
                chat_id, message_id,
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        elif call.data.startswith("approve_binance_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            pay_id = int(call.data.replace("approve_binance_", ""))
            success, result = db.complete_binance_payment(pay_id)
            if success:
                credited_user_id = result
                user_info = db.get_user(credited_user_id)
                new_balance = db.get_balance(credited_user_id)
                try:
                    bot.send_message(
                        credited_user_id,
                        f" *تم تأكيد شحن رصيدك!*\n\n"
                        f"رصيدك الجديد: {new_balance:.2f}$",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text(
                    f"تم تأكيد الدفعة #{pay_id} وإضافة الرصيد للمستخدم {credited_user_id}",
                    chat_id, message_id, reply_markup=keyboard
                )
            else:
                safe_answer_callback_query(call.id, f"فشل: {result}")

        # سجل مدفوعات Binance (مشرف) 
        elif call.data == "admin_binance_payments":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            payments = db.get_all_binance_payments()
            if not payments:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا توجد مدفوعات بعد", chat_id, message_id, reply_markup=keyboard)
                return
            text = " *آخر مدفوعات Binance:*\n\n"
            status_ar = {'pending': ' معلق', 'completed': ' مكتمل', 'failed': ' فشل'}
            for p in payments[:12]:
                text += (
                    f"#{p['pay_id']} | {p['usdt_amount']} USDT → {p['usd_amount']:.2f}$\n"
                    f"المستخدم: {p['user_id']} | {status_ar.get(p['status'], p['status'])}\n"
                    f" {str(p['created_at'])[:16]}\n"
                    f"\n"
                )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard)

        # 
        # بوابة الدفع عبر نجوم تيليجرام 
        # 
        elif call.data == "stars_charge":
            keyboard = types.InlineKeyboardMarkup()
            for plan_key, plan in STARS_PLANS.items():
                usd_val = plan['stars'] * STAR_TO_USD_RATE
                keyboard.row(types.InlineKeyboardButton(
                    f"{plan['label']}",
                    callback_data=f"stars_plan_{plan_key}",
                    style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="charge", style="primary"))
            bot.edit_message_text(
                f" *شحن الرصيد عبر نجوم تيليجرام*\n\n"
                f"سعر الصرف: 1 نجمة = ${STAR_TO_USD_RATE:.3f}\n\n"
                f"الدفع فوري وآمن عبر تيليجرام مباشرة\n\n"
                f"اختر عدد النجوم التي تريد شحنها:",
                chat_id, message_id,
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        elif call.data.startswith("stars_plan_"):
            plan_key = call.data.replace("stars_plan_", "")
            plan = STARS_PLANS.get(plan_key)
            if not plan:
                safe_answer_callback_query(call.id, "خطة غير صالحة!")
                return
            usd_val = plan['stars'] * STAR_TO_USD_RATE
            import uuid
            payload = f"stars_{user_id}_{plan_key}_{uuid.uuid4().hex[:8]}"
            # سجّل الدفعة مسبقاً
            db.create_stars_payment(user_id, plan['stars'], usd_val, payload)
            from telebot.types import LabeledPrice
            bot.send_invoice(
                chat_id=chat_id,
                title="شحن رصيد البوت",
                description=f"شحن {plan['stars']} نجمة = ${usd_val:.2f} يُضاف فوراً لرصيدك",
                invoice_payload=payload,
                provider_token="", # فارغ للنجوم XTR
                currency="XTR",
                prices=[LabeledPrice(label=plan['label'], amount=plan['stars'])]
            )
            safe_answer_callback_query(call.id)

        # سجل مدفوعات النجوم (مشرف) 
        elif call.data == "admin_stars_payments":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            payments = db.get_all_stars_payments()
            if not payments:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا توجد مدفوعات نجوم بعد", chat_id, message_id, reply_markup=keyboard)
                return
            text = " *آخر مدفوعات النجوم:*\n\n"
            status_ar = {'pending': ' معلق', 'completed': ' مكتمل'}
            for p in payments[:12]:
                text += (
                    f"#{p['pay_id']} | {p['stars_amount']} → {p['usd_amount']:.2f}$\n"
                    f"المستخدم: {p['user_id']} | {status_ar.get(p['status'], p['status'])}\n"
                    f" {str(p['created_at'])[:16]}\n"
                    f"\n"
                )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard)

        elif call.data == "admin_direct_add_balance":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_direct_add_bal")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.edit_message_text(
                "إضافة رصيد مباشر\n\nأرسل:\nأيدي_المستخدم المبلغ السبب\n\nمثال:\n123456789 500 هدية ترحيب\n\nأو بدون سبب:\n123456789 500",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data == "admin_direct_deduct_balance":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_direct_deduct_bal")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.edit_message_text(
                "خصم رصيد مباشر\n\nأرسل:\nأيدي_المستخدم المبلغ السبب\n\nمثال:\n123456789 200 مخالفة\n\nأو بدون سبب:\n123456789 200",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data == "admin_search_user":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_searching_user")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.edit_message_text(
                "البحث عن مستخدم\n\nأرسل الأيدي أو المعرف (@username) أو جزء من الاسم:",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data == "admin_ban_user":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_banning_user")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.edit_message_text(
                "حظر مستخدم\n\nأرسل:\nأيدي_المستخدم السبب\n\nمثال:\n123456789 احتيال\n\nأو بدون سبب:\n123456789",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data == "admin_unban_user":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_unbanning_user")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            # عرض قائمة المحظورين
            banned = db.get_banned_users()
            if banned:
                text = "رفع حظر مستخدم\n\nالمحظورون حالياً:\n\n"
                for b in banned[:10]:
                    name = f"@{b['username']}" if b['username'] else (b['first_name'] or str(b['user_id']))
                    text += f"- {name} | {b['user_id']}\n السبب: {b['reason'] or 'غير محدد'}\n"
                text += "\nأرسل أيدي المستخدم لرفع الحظر عنه:"
            else:
                text = "رفع حظر مستخدم\n\nلا يوجد مستخدمون محظورون حالياً.\n\nأرسل أيدي المستخدم لرفع الحظر عنه:"
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_manage_auctions":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 المزادات النشطة", callback_data="admin_list_active_auctions", style="primary"))
            keyboard.row(types.InlineKeyboardButton("⏳ المزادات المعلقة", callback_data="admin_pending", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 المزادات المباعة", callback_data="admin_list_sold_auctions", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ حذف / إلغاء مزاد", callback_data="admin_cancel_auction_input", style="danger"))
            keyboard.row(types.InlineKeyboardButton("🔹 تمديد/تقليص مزاد", callback_data="admin_extend_auction_input", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text("إدارة المزادات\n\nاختر الإجراء:", chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_extend_auction_input":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            # عرض قائمة المزادات النشطة مع أزرار تمديد
            auctions = db.get_active_auctions("all")
            if not auctions:
                safe_answer_callback_query(call.id, "لا توجد مزادات نشطة!")
                return
            keyboard = types.InlineKeyboardMarkup()
            for a in auctions[:8]:
                ends_at = db.parse_datetime(a['ends_at'])
                diff = ends_at - datetime.now()
                h = max(0, int(diff.total_seconds() // 3600))
                m = max(0, int((diff.total_seconds() % 3600) // 60))
                keyboard.row(types.InlineKeyboardButton(
                    f"#{a['auction_id']} | {a['title'][:20]} | {h}:{m:02d}",
                    callback_data=f"admin_manage_auction_extend_{a['auction_id']}",
                    style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔹 للإدارة", callback_data="admin_manage_auctions", style="primary"))
            bot.edit_message_text(
                " *اختر المزاد لتعديل وقته:*",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data == "admin_list_active_auctions":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            auctions = db.get_active_auctions("all")
            if not auctions:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا توجد مزادات نشطة حالياً", chat_id, message_id, reply_markup=keyboard)
                return
            text = f"المزادات النشطة ({len(auctions)}):\n\n"
            for a in auctions[:15]:
                ends_at = db.parse_datetime(a['ends_at'])
                time_left = ends_at - datetime.now()
                hours_left = max(0, int(time_left.total_seconds() // 3600))
                mins_left = max(0, int((time_left.total_seconds() % 3600) // 60))
                text += f"#{a['auction_id']} | {a['title'][:25]}\nالسعر: {a['current_price']:.3f} | المزايدات: {a['bids_count']} | متبقي: {hours_left}:{mins_left:02d}\n----\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_list_sold_auctions":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            cursor = db.conn.cursor()
            cursor.execute("SELECT * FROM auctions WHERE status='sold' ORDER BY sold_at DESC LIMIT 15")
            rows = cursor.fetchall()
            if not rows:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("لا توجد مزادات مباعة بعد", chat_id, message_id, reply_markup=keyboard)
                return
            text = "آخر المزادات المباعة:\n\n"
            for r in rows:
                text += f"#{r[0]} | {r[3][:25]}\nسعر البيع: {r[17]:.3f} | البائع: {r[1]} | المشتري: {r[15]}\n----\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)

        elif call.data == "admin_cancel_auction_input":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_cancelling_auction")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_manage_auctions", style="danger"))
            bot.edit_message_text(
                "إلغاء مزاد\n\nأرسل رقم المزاد الذي تريد إلغاءه:\nسيتم استرداد مزايدات جميع المشاركين",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data == "admin_commissions":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            commission_pct = float(db.get_setting('commission_rate', str(COMMISSION_RATE)) or COMMISSION_RATE) * 100
            transfer_pct = float(db.get_setting('transfer_commission_rate', str(TRANSFER_COMMISSION_RATE)) or TRANSFER_COMMISSION_RATE) * 100
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✏️ تعديل عمولة البيع", callback_data="admin_set_commission", style="primary"))
            keyboard.row(types.InlineKeyboardButton("✏️ تعديل عمولة التحويل", callback_data="admin_set_transfer_commission", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(
                f"إعدادات العمولات\n\nعمولة البيع الحالية: {commission_pct:.2f}%\nعمولة التحويل الحالية: {transfer_pct:.2f}%\n\nاختر ما تريد تعديله:",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data == "admin_set_commission":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_setting_commission")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_commissions", style="danger"))
            bot.edit_message_text(
                "تعديل عمولة البيع\n\nأرسل النسبة المئوية الجديدة (مثال: 0.5 تعني 0.5%):",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data == "admin_set_transfer_commission":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_setting_transfer_commission")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_commissions", style="danger"))
            bot.edit_message_text(
                "تعديل عمولة التحويل\n\nأرسل النسبة المئوية الجديدة (مثال: 5 تعني 5%):",
                chat_id, message_id, reply_markup=keyboard
            )

        elif call.data == "my_agent_panel":
            nav_push(user_id, "my_agent_panel")
            try:
                if not db.is_agent(user_id):
                    safe_answer_callback_query(call.id, "أنت لست وكيلاً مسجلاً!", show_alert=True)
                    return
                safe_answer_callback_query(call.id)
                try:
                    stats = db.get_agent_stats(user_id)
                except Exception:
                    stats = {'total_req': 0, 'total_charged': 0.0, 'total_profit': 0.0, 'pending': 0}
                try:
                    rating_stats = db.get_agent_rating_stats(user_id)
                except Exception:
                    rating_stats = {'count': 0, 'avg': 0.0}
                cur2 = db.conn.cursor()
                cur2.execute("SELECT name, description, contact FROM agents WHERE user_id=?", (user_id,))
                ag_row = cur2.fetchone()
                ag_name = ag_row[0] if ag_row and ag_row[0] else str(user_id)
                ag_desc = ag_row[1] if ag_row and ag_row[1] else ""
                ag_contact = ag_row[2] if ag_row and ag_row[2] else "—"
                if rating_stats.get("count", 0) > 0:
                    avg = rating_stats["avg"]
                    stars_str = "" * int(avg) + ("" if avg - int(avg) >= 0.5 else "")
                    rating_line = f"التقييم: {stars_str} {avg:.1f}/5 ({rating_stats['count']} تقييم)"
                else:
                    rating_line = "لا يوجد تقييمات بعد"
                try:
                    pending_reqs = db.get_agent_charge_requests(agent_user_id=user_id, status="pending")
                    pending_count = len(pending_reqs)
                except Exception:
                    pending_count = 0
                text = (
                    f" *لوحة الوكيل*\n\n"
                    f"الاسم: {md_escape(ag_name)}\n"
                    f"التواصل: {md_escape(ag_contact)}\n"
                    + (f"الوصف: {md_escape(ag_desc)}\n" if ag_desc else "") +
                    f"{rating_line}\n\n"
                    f"الإحصائيات \n"
                    f"الطلبات المكتملة: {stats['total_req']}\n"
                    f"إجمالي الشحن: {stats['total_charged']:.2f}$\n"
                    f"طلبات معلقة: {pending_count}"
                )
                keyboard = types.InlineKeyboardMarkup()
                if pending_count > 0:
                    keyboard.row(types.InlineKeyboardButton(
                        f"الطلبات المعلقة ({pending_count})", callback_data="agent_pending_requests", style="primary"))
                keyboard.row(
                    types.InlineKeyboardButton("🎟️ إنشاء كود شحن", callback_data="agent_create_code", style="primary"),
                    types.InlineKeyboardButton("🔹 تحويل مباشر", callback_data="agent_direct_transfer", style="primary")
                )
                keyboard.row(types.InlineKeyboardButton("🔹 سجل الطلبات", callback_data="agent_requests_history", style="primary"))
                keyboard.row(types.InlineKeyboardButton("📊 إحصائيات مفصلة", callback_data="agent_detailed_stats", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                try:
                    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
                except Exception:
                    bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")
            except Exception as e_panel:
                logger.error(f"my_agent_panel error: {e_panel}")
                safe_answer_callback_query(call.id, "حدث خطأ، حاول مجدداً!", show_alert=True)

        elif call.data == "agent_pending_requests":
            if not db.is_agent(user_id):
                safe_answer_callback_query(call.id, "أنت لست وكيلاً!")
                return
            reqs = db.get_agent_charge_requests(agent_user_id=user_id, status="pending")
            if not reqs:
                safe_answer_callback_query(call.id, "لا توجد طلبات معلقة!", show_alert=True)
                return
            keyboard = types.InlineKeyboardMarkup()
            text = f" *الطلبات المعلقة ({len(reqs)})*\n\n"
            for r in reqs[:8]:
                uname = f"@{r['username']}" if r['username'] else (r['first_name'] or f"ID {r['user_id']}")
                text += f"#{r['req_id']} | {uname} | {r['amount']:.2f}$\n{md_escape(r['reason'][:50])}\n\n"
                keyboard.row(
                    types.InlineKeyboardButton(f" #{r['req_id']}", callback_data=f"agent_approve_req_{r['req_id']}", style="primary"),
                    types.InlineKeyboardButton(f" #{r['req_id']}", callback_data=f"agent_reject_req_{r['req_id']}", style="danger")
                )
            keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "agent_requests_history":
            if not db.is_agent(user_id):
                safe_answer_callback_query(call.id, "أنت لست وكيلاً!")
                return
            reqs = db.get_agent_charge_requests(agent_user_id=user_id)
            if not reqs:
                safe_answer_callback_query(call.id, "لا يوجد سجل طلبات بعد!", show_alert=True)
                return
            status_ar = {"pending": "", "agent_approved": "بانتظار الأدمن", "admin_approved": "مكتمل", "rejected": "مرفوض"}
            text = f" *سجل آخر الطلبات*\n\n"
            for r in reqs[:10]:
                uname = f"@{r['username']}" if r['username'] else f"ID {r['user_id']}"
                st = status_ar.get(r['status'], r['status'])
                text += f"#{r['req_id']} | {uname} | {r['amount']:.2f}$ | {st}\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "agent_detailed_stats":
            if not db.is_agent(user_id):
                safe_answer_callback_query(call.id, "أنت لست وكيلاً!", show_alert=True)
                return
            safe_answer_callback_query(call.id)
            try:
                m_stats = db.get_agent_monthly_stats(user_id)
            except Exception:
                m_stats = {'this_month': 0, 'last_month': 0, 'this_month_charged': 0.0}
            this_m = m_stats['this_month']
            last_m = m_stats['last_month']
            if last_m > 0:
                diff_pct = round(((this_m - last_m) / last_m) * 100)
                trend = f"📈 +{diff_pct}%" if diff_pct >= 0 else f"📉 {diff_pct}%"
            else:
                trend = "📈 جديد" if this_m > 0 else "—"
            try:
                rating_stats = db.get_agent_rating_stats(user_id)
            except Exception:
                rating_stats = {'count': 0, 'avg': 0.0}
            text = (
                f" *الإحصائيات المفصلة*\n\n"
                f"الشهر الحالي:\n"
                f"  • طلبات مكتملة: {this_m}\n"
                f"  • إجمالي الشحن هذا الشهر: {m_stats['this_month_charged']:.2f}$\n"
                f"  • الشهر السابق: {last_m}\n"
                f"  • نسبة التغيّر: {trend}\n\n"
                f"التقييم العام:\n"
                f"  • عدد التقييمات: {rating_stats.get('count', 0)}\n"
                f"  • المتوسط: {rating_stats.get('avg', 0.0):.1f}/5\n"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "agent_create_code":
            if not db.is_agent(user_id):
                safe_answer_callback_query(call.id, "أنت لست وكيلاً!")
                return
            balance = db.get_balance(user_id)
            if balance < 1:
                safe_answer_callback_query(call.id, "رصيدك غير كافٍ لإنشاء كود!", show_alert=True)
                return
            db.set_user_state(user_id, "agent_creating_code")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="my_agent_panel", style="danger"))
            bot.edit_message_text(
                f" *إنشاء كود شحن*\n\nرصيدك: {balance:.2f}$\n\nأرسل قيمة الكود بالدولار:",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data == "agent_direct_transfer":
            if not db.is_agent(user_id):
                safe_answer_callback_query(call.id, "أنت لست وكيلاً!")
                return
            db.set_user_state(user_id, "agent_direct_transfer_id")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="my_agent_panel", style="danger"))
            bot.edit_message_text(
                " *تحويل مباشر*\n\nأرسل أيدي المستخدم الذي تريد تحويل رصيد له:",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        # لوحة الوسيط 
        elif call.data == "my_broker_panel":
            nav_push(user_id, "my_broker_panel")
            try:
                if not db.is_broker(user_id):
                    safe_answer_callback_query(call.id, "أنت لست وسيطاً مسجلاً!", show_alert=True)
                    return
                safe_answer_callback_query(call.id)
                try:
                    stats = db.get_broker_stats(user_id)
                except Exception:
                    stats = {'total_approved': 0, 'pending': 0, 'total_profit': 0.0}
                try:
                    rating_stats = db.get_broker_rating_stats(user_id)
                except Exception:
                    rating_stats = {'count': 0, 'avg': 0.0}
                cur2 = db.conn.cursor()
                cur2.execute("SELECT name, description, contact FROM brokers WHERE user_id=?", (user_id,))
                br_row = cur2.fetchone()
                br_name = br_row[0] if br_row and br_row[0] else str(user_id)
                br_desc = br_row[1] if br_row and br_row[1] else ""
                br_contact = br_row[2] if br_row and br_row[2] else "—"
                if rating_stats.get("count", 0) > 0:
                    avg = rating_stats["avg"]
                    stars_str = "" * int(avg) + ("" if avg - int(avg) >= 0.5 else "")
                    rating_line = f"التقييم: {stars_str} {avg:.1f}/5 ({rating_stats['count']} تقييم)"
                else:
                    rating_line = "لا يوجد تقييمات بعد"
                try:
                    pending_reqs = db.get_broker_requests(broker_user_id=user_id, status="pending")
                    pending_count = len(pending_reqs)
                except Exception:
                    pending_count = 0
                group_link = ""
                try:
                    group_link = db.get_bot_setting("broker_group_link") or ""
                except Exception:
                    pass
                group_line = f"\n رابط المجموعة: {group_link}" if group_link else ""
                text = (
                    f" *لوحة الوسيط*\n\n"
                    f"الاسم: {md_escape(br_name)}\n"
                    f"التواصل: {md_escape(br_contact)}\n"
                    + (f"الوصف: {md_escape(br_desc)}\n" if br_desc else "") +
                    f"{rating_line}{group_line}\n\n"
                    f"الإحصائيات \n"
                    f"الصفقات المكتملة: {stats['total_approved']}\n"
                    f"طلبات معلقة: {pending_count}"
                )
                keyboard = types.InlineKeyboardMarkup()
                if pending_count > 0:
                    keyboard.row(types.InlineKeyboardButton(
                        f"الطلبات المعلقة ({pending_count})", callback_data="broker_pending_requests", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔹 سجل الطلبات", callback_data="broker_requests_history", style="primary"))
                keyboard.row(types.InlineKeyboardButton("📊 إحصائيات مفصلة", callback_data="broker_detailed_stats", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                try:
                    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
                except Exception:
                    bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")
            except Exception as e_panel:
                logger.error(f"my_broker_panel error: {e_panel}")
                safe_answer_callback_query(call.id, "حدث خطأ، حاول مجدداً!", show_alert=True)

        elif call.data == "broker_pending_requests":
            if not db.is_broker(user_id):
                safe_answer_callback_query(call.id, "أنت لست وسيطاً!")
                return
            reqs = db.get_broker_requests(broker_user_id=user_id, status="pending")
            if not reqs:
                safe_answer_callback_query(call.id, "لا توجد طلبات معلقة!", show_alert=True)
                return
            BROKER_SERVICE_LABELS = {
                "sell_username": "بيع يوزر", "sell_account": "بيع حساب",
                "sell_channel": "بيع قناة", "sell_group": "بيع مجموعة",
                "sell_bot": "بيع بوت", "sell_social": "بيع معرف", "buy_other": "شراء آخر"
            }
            keyboard = types.InlineKeyboardMarkup()
            text = f" *طلبات الوساطة المعلقة ({len(reqs)})*\n\n"
            for r in reqs[:6]:
                uname = f"@{r['username']}" if r['username'] else (r['first_name'] or f"ID {r['user_id']}")
                safe_uname = uname.replace('_', '\\_')
                svc = BROKER_SERVICE_LABELS.get(r['service_type'], r['service_type'])
                safe_details = r['details'][:60].replace('*', '').replace('_', '').replace('`', '').replace('[', '')
                text += f"#{r['req_id']} | {safe_uname} | {svc}\n{safe_details}\n\n"
                keyboard.row(
                    types.InlineKeyboardButton(f"قبول #{r['req_id']}", callback_data=f"broker_approve_req_{r['req_id']}", style="primary"),
                    types.InlineKeyboardButton(f"رفض #{r['req_id']}", callback_data=f"broker_reject_req_{r['req_id']}", style="danger")
                )
                keyboard.row(types.InlineKeyboardButton(f"بلاغ #{r['req_id']}", callback_data=f"broker_report_user_{r['req_id']}", style="danger"))
            keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوسيط", callback_data="my_broker_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "broker_requests_history":
            if not db.is_broker(user_id):
                safe_answer_callback_query(call.id, "أنت لست وسيطاً!")
                return
            reqs = db.get_broker_requests(broker_user_id=user_id)
            if not reqs:
                safe_answer_callback_query(call.id, "لا يوجد سجل طلبات بعد!", show_alert=True)
                return
            status_ar = {"pending": "معلق", "approved": "مقبول", "rejected": "مرفوض"}
            text = f" *سجل آخر طلبات الوساطة*\n\n"
            for r in reqs[:10]:
                uname = f"@{r['username']}" if r['username'] else f"ID {r['user_id']}"
                safe_uname = uname.replace('_', '\\_')
                st = status_ar.get(r['status'], r['status'])
                text += f"#{r['req_id']} | {safe_uname} | {st}\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوسيط", callback_data="my_broker_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "broker_detailed_stats":
            if not db.is_broker(user_id):
                safe_answer_callback_query(call.id, "أنت لست وسيطاً!", show_alert=True)
                return
            safe_answer_callback_query(call.id)
            try:
                m_stats = db.get_broker_monthly_stats(user_id)
            except Exception:
                m_stats = {'this_month': 0, 'last_month': 0, 'this_month_profit': 0.0}
            this_m = m_stats['this_month']
            last_m = m_stats['last_month']
            if last_m > 0:
                diff_pct = round(((this_m - last_m) / last_m) * 100)
                trend = f"📈 +{diff_pct}%" if diff_pct >= 0 else f"📉 {diff_pct}%"
            else:
                trend = "📈 جديد" if this_m > 0 else "—"
            try:
                rating_stats = db.get_broker_rating_stats(user_id)
            except Exception:
                rating_stats = {'count': 0, 'avg': 0.0}
            text = (
                f" *الإحصائيات المفصلة*\n\n"
                f"الشهر الحالي:\n"
                f"  • صفقات مكتملة: {this_m}\n"
                f"  • الشهر السابق: {last_m}\n"
                f"  • نسبة التغيّر: {trend}\n\n"
                f"التقييم العام:\n"
                f"  • عدد التقييمات: {rating_stats.get('count', 0)}\n"
                f"  • المتوسط: {rating_stats.get('avg', 0.0):.1f}/5\n"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوسيط", callback_data="my_broker_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        elif call.data.startswith("copy_code_"):
            code_val = call.data.replace("copy_code_", "")
            safe_answer_callback_query(call.id, f"الكود: {code_val}", show_alert=True)

        # عرض تقييمات الوكيل 
        elif call.data.startswith("view_agent_ratings_"):
            agent_uid = int(call.data.replace("view_agent_ratings_", ""))
            rating_stats = db.get_agent_rating_stats(agent_uid)
            ratings = db.get_agent_ratings(agent_uid, limit=5)
            cursor = db.conn.cursor()
            cursor.execute("SELECT name FROM agents WHERE user_id=?", (agent_uid,))
            ag_row = cursor.fetchone()
            ag_name = ag_row[0] if ag_row else f"وكيل {agent_uid}"
            if rating_stats["count"] == 0:
                text = f" *تقييمات {ag_name}*\n\nلا توجد تقييمات بعد."
            else:
                avg = rating_stats["avg"]
                full = int(avg)
                stars_str = "" * full + ("" if avg - full >= 0.5 else "")
                text = f" *تقييمات {ag_name}*\n\n{stars_str} {avg:.1f}/5 ({rating_stats['count']} تقييم)\n\n"
                for r in ratings:
                    name = r["first_name"] or (f"@{r['username']}" if r["username"] else "مستخدم")
                    stars = "" * r["rating"]
                    text += f"• {name}: {stars}\n"
                    if r["comment"]:
                        text += f" {r['comment']}\n"
                    text += "\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للوكيل", callback_data=f"agent_detail_{agent_uid}", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        # عرض تقييمات الوسيط 
        elif call.data.startswith("view_broker_ratings_"):
            broker_uid = int(call.data.replace("view_broker_ratings_", ""))
            rating_stats = db.get_broker_rating_stats(broker_uid)
            ratings = db.get_broker_ratings(broker_uid, limit=5)
            cursor = db.conn.cursor()
            cursor.execute("SELECT name FROM brokers WHERE user_id=?", (broker_uid,))
            br_row = cursor.fetchone()
            br_name = br_row[0] if br_row else f"وسيط {broker_uid}"
            if rating_stats["count"] == 0:
                text = f" *تقييمات {br_name}*\n\nلا توجد تقييمات بعد."
            else:
                avg = rating_stats["avg"]
                full = int(avg)
                stars_str = "" * full + ("" if avg - full >= 0.5 else "")
                text = f" *تقييمات {br_name}*\n\n{stars_str} {avg:.1f}/5 ({rating_stats['count']} تقييم)\n\n"
                for r in ratings:
                    name = r["first_name"] or (f"@{r['username']}" if r["username"] else "مستخدم")
                    stars = "" * r["rating"]
                    text += f"• {name}: {stars}\n"
                    if r["comment"]:
                        text += f" {r['comment']}\n"
                    text += "\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للوسيط", callback_data=f"broker_detail_{broker_uid}", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")

        # تأكيد تعيين مجموعة الوساطة 
        elif call.data.startswith("set_broker_group_confirm_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            try:
                grp_id = int(call.data.replace("set_broker_group_confirm_", ""))
                db.set_bot_setting("broker_group_id", str(grp_id))
                invite_link = ""
                try:
                    invite_link = bot.export_chat_invite_link(grp_id)
                    db.set_bot_setting("broker_group_link", invite_link)
                except Exception:
                    pass
                safe_answer_callback_query(call.id, "تم تعيين مجموعة الوساطة!")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🤝 إدارة الوسطاء", callback_data="admin_brokers", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                link_line = f"\nرابط الدعوة: {invite_link}" if invite_link else ""
                bot.edit_message_text(
                    f" *تم تعيين مجموعة الوساطة!*\n\nالـ Chat ID: `{grp_id}`{link_line}",
                    chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
                )
            except Exception as e:
                safe_answer_callback_query(call.id, f"خطأ: {e}", show_alert=True)

        # تخطي وصف الوكيل 
        elif call.data == "skip_agent_desc":
            if user_id != OWNER_ID: return
            user_state_now = db.get_user_state(user_id)
            if not user_state_now or user_state_now["state"] != "waiting_add_agent_desc":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            data = user_state_now.get("data", {}) or {}
            db.add_agent(data["uid"], data["name"], "", data["contact"], OWNER_ID)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🧑‍💼 إدارة الوكلاء", callback_data="admin_agents", style="primary"))
            bot.edit_message_text(
                f" *تم إضافة الوكيل!*\n\nالاسم: {md_escape(data['name'])}\nالتواصل: {md_escape(data['contact'])}",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )
            try:
                bot.send_message(data["uid"], "تم تعيينك وكيلاً في البوت!")
            except Exception:
                pass

        # إعداد مجموعة الوساطة يدوياً 
        elif call.data == "admin_set_broker_group":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            saved_id = db.get_bot_setting('broker_group_id') or ''
            saved_link = db.get_bot_setting('broker_group_link') or ''
            db.set_user_state(user_id, "waiting_broker_group_id")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 اكتشاف تلقائي", callback_data="admin_broker_group_auto", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            current_info = ""
            if saved_id:
                current_info = f"\nالمجموعة الحالية: `{saved_id}`"
                if saved_link:
                    current_info += f"\nرابط الدعوة: {saved_link}"
            bot.edit_message_text(
                f" *إعداد مجموعة الوساطة*\n\n"
                f"أرسل Chat ID للمجموعة (رقم سالب مثل: -1001234567890){current_info}\n\n"
                f"أو اضغط 'اكتشاف تلقائي' ثم أرسل أي رسالة في المجموعة.",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif call.data == "admin_broker_group_auto":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            db.set_user_state(user_id, "waiting_broker_group_auto_detect")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
            bot.edit_message_text(
                " *اكتشاف تلقائي لمجموعة الوساطة*\n\n"
                "الآن أرسل أي رسالة في المجموعة التي تريد تعيينها\n"
                "وسيتم اكتشافها تلقائياً.",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        # تخطي وصف الوسيط 
        elif call.data == "skip_broker_desc":
            if user_id != OWNER_ID: return
            user_state_now = db.get_user_state(user_id)
            if not user_state_now or user_state_now["state"] != "waiting_add_broker_desc":
                safe_answer_callback_query(call.id, "انتهت صلاحية الطلب!")
                return
            data = user_state_now.get("data", {}) or {}
            db.add_broker(data["uid"], data["name"], "", data["contact"], OWNER_ID)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 إدارة الوسطاء", callback_data="admin_brokers", style="primary"))
            bot.edit_message_text(
                f" *تم إضافة الوسيط!*\n\nالاسم: {md_escape(data['name'])}\nالتواصل: {md_escape(data['contact'])}",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )
            try:
                bot.send_message(data["uid"], "تم تعيينك وسيطاً في البوت!")
            except Exception:
                pass

        # موافقة/رفض الوكيل على طلب شحن 
        elif call.data.startswith("agent_approve_req_"):
            if not db.is_agent(user_id):
                safe_answer_callback_query(call.id, "أنت لست وكيلاً!", show_alert=True)
                return
            req_id = int(call.data.replace("agent_approve_req_", ""))
            req = db.get_agent_charge_request_by_id(req_id)
            if not req:
                safe_answer_callback_query(call.id, "الطلب غير موجود!")
                return
            if req["agent_user_id"] != user_id:
                safe_answer_callback_query(call.id, "هذا الطلب ليس لك!", show_alert=True)
                return
            keyboard_admin = types.InlineKeyboardMarkup()
            keyboard_admin.row(
                types.InlineKeyboardButton("✅ تأكيد وإضافة الرصيد", callback_data=f"admin_confirm_agent_req_{req_id}", style="primary"),
                types.InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_agent_req_{req_id}", style="danger")
            )
            try:
                bot.send_message(
                    OWNER_ID,
                    f" *وافق وكيل على طلب شحن!*\n\nالطلب: #{req_id}\nالعميل: ID {req['user_id']}\nالوكيل: ID {req['agent_user_id']}\nالمبلغ: {req['amount']:.2f}$\nالسبب: {req['reason']}\n\nهل تؤكد إضافة الرصيد للعميل؟",
                    reply_markup=keyboard_admin, parse_mode="Markdown"
                )
            except Exception:
                pass
            db.update_agent_charge_request(req_id, "agent_approved", "وافق الوكيل")
            safe_answer_callback_query(call.id, "تم إرسال للأدمن للتأكيد")
            try:
                bot.edit_message_text(f" *وافقت على الطلب #{req_id}*\n\nبانتظار تأكيد الأدمن.", chat_id, message_id, parse_mode="Markdown")
            except Exception:
                pass

        elif call.data.startswith("agent_reject_req_"):
            if not db.is_agent(user_id):
                safe_answer_callback_query(call.id, "أنت لست وكيلاً!", show_alert=True)
                return
            req_id = int(call.data.replace("agent_reject_req_", ""))
            req = db.get_agent_charge_request_by_id(req_id)
            if not req:
                safe_answer_callback_query(call.id, "الطلب غير موجود!")
                return
            if req["agent_user_id"] != user_id:
                safe_answer_callback_query(call.id, "هذا الطلب ليس لك!", show_alert=True)
                return
            db.update_agent_charge_request(req_id, "rejected", "رفض الوكيل")
            try:
                bot.send_message(req["user_id"], f"تم رفض طلب الشحن #{req_id} من الوكيل.", parse_mode="Markdown")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم الرفض")
            try:
                bot.edit_message_text(f"تم رفض الطلب #{req_id}.", chat_id, message_id)
            except Exception:
                pass

        # تأكيد الأدمن لطلب شحن الوكيل 
        elif call.data.startswith("admin_confirm_agent_req_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            req_id = int(call.data.replace("admin_confirm_agent_req_", ""))
            req = db.get_agent_charge_request_by_id(req_id)
            if not req or req["status"] == "admin_approved":
                safe_answer_callback_query(call.id, "تمت معالجته مسبقاً!")
                return
            db.update_balance(req["user_id"], req["amount"])
            db.add_transaction(req["user_id"], req["amount"], "agent_charge", f"شحن عبر وكيل - طلب #{req_id}")
            db.update_agent_charge_request(req_id, "admin_approved", "أكده الأدمن")
            db.add_agent_profit(req["agent_user_id"], req_id, 0)
            new_bal = db.get_balance(req["user_id"])
            keyboard_rate = types.InlineKeyboardMarkup()
            keyboard_rate.row(
                types.InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_agent_{req['agent_user_id']}_{req_id}_5", style="primary"),
                types.InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rate_agent_{req['agent_user_id']}_{req_id}_4", style="primary")
            )
            keyboard_rate.row(
                types.InlineKeyboardButton("⭐⭐⭐", callback_data=f"rate_agent_{req['agent_user_id']}_{req_id}_3", style="primary"),
                types.InlineKeyboardButton("⭐⭐", callback_data=f"rate_agent_{req['agent_user_id']}_{req_id}_2", style="primary")
            )
            keyboard_rate.row(
                types.InlineKeyboardButton("⭐", callback_data=f"rate_agent_{req['agent_user_id']}_{req_id}_1", style="danger")
            )
            try:
                bot.send_message(req["user_id"],
                    f" *تم شحن رصيدك!*\n\nالمبلغ: {req['amount']:.2f}$\nرصيدك الجديد: {new_bal:.2f}$\n\nبواسطة الوكيل - طلب #{req_id}\n\nقيّم الوكيل بعد انتهاء الصفقة:",
                    reply_markup=keyboard_rate, parse_mode="Markdown"
                )
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم إضافة الرصيد")
            try:
                bot.edit_message_text(f"تم تأكيد طلب #{req_id} وإضافة {req['amount']:.2f}$ للمستخدم {req['user_id']}.", chat_id, message_id)
            except Exception:
                pass

        elif call.data.startswith("admin_reject_agent_req_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            req_id = int(call.data.replace("admin_reject_agent_req_", ""))
            req = db.get_agent_charge_request_by_id(req_id)
            if not req:
                safe_answer_callback_query(call.id, "الطلب غير موجود!")
                return
            db.update_agent_charge_request(req_id, "rejected", "رفض الأدمن")
            try:
                bot.send_message(req["user_id"], f"تم رفض طلب الشحن #{req_id} من الإدارة.")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم الرفض")
            try:
                bot.edit_message_text(f"تم رفض الطلب #{req_id}.", chat_id, message_id)
            except Exception:
                pass

        # موافقة/رفض الوسيط على طلب وساطة 
        elif call.data.startswith("broker_approve_req_"):
            if not db.is_broker(user_id):
                safe_answer_callback_query(call.id, "أنت لست وسيطاً!", show_alert=True)
                return
            req_id = int(call.data.replace("broker_approve_req_", ""))
            req = db.get_broker_request_by_id(req_id)
            if not req:
                safe_answer_callback_query(call.id, "الطلب غير موجود!")
                return
            if req["broker_user_id"] != user_id:
                safe_answer_callback_query(call.id, "هذا الطلب ليس لك!", show_alert=True)
                return
            # منع التكرار — update_broker_request يرفض لو معالج مسبقاً
            updated = db.update_broker_request(req_id, "approved", "وافق الوسيط")
            if not updated:
                safe_answer_callback_query(call.id, "تمت معالجة هذا الطلب مسبقاً!", show_alert=True)
                return
            db.add_broker_profit(req["broker_user_id"], req_id, 0)
            # إنشاء رابط دعوة شخصي لهذا المستخدم فقط (expire بعد 15 دقيقة، use_count=1)
            broker_group_link = ""
            broker_group_id_str = db.get_bot_setting("broker_group_id") or ""
            invite_link_error = ""
            if broker_group_id_str:
                try:
                    grp_chat_id_tmp = int(broker_group_id_str)
                    link_obj = bot.create_chat_invite_link(
                        grp_chat_id_tmp,
                        expire_date=int(time.time()) + 900,  # 15 دقيقة
                        member_limit=1
                    )
                    broker_group_link = link_obj.invite_link
                except Exception as e_inv:
                    invite_link_error = str(e_inv)
                    logger.error(f"broker_approve_req: فشل إنشاء رابط الدعوة للمجموعة {broker_group_id_str}: {e_inv}")
            else:
                invite_link_error = "broker_group_id غير مضبوط في الإعدادات"
                logger.warning("broker_approve_req: broker_group_id فارغ — لم يتم إنشاء رابط دعوة")
            cursor_b = db.conn.cursor()
            cursor_b.execute(
                "SELECT u.username FROM brokers b LEFT JOIN users u ON b.user_id=u.user_id WHERE b.user_id=?",
                (req["broker_user_id"],)
            )
            br_row = cursor_b.fetchone()
            br_contact = f"@{md_escape(br_row[0])}" if br_row and br_row[0] else f"ID: {req['broker_user_id']}"
            keyboard_user = types.InlineKeyboardMarkup()
            if broker_group_link:
                keyboard_user.row(types.InlineKeyboardButton("🔹 انضم لمجموعة الوساطة", url=broker_group_link, style="primary"))
                msg_text = (
                    f" *وافق الوسيط على طلبك!*\n\n"
                    f"رقم الطلب: #{req_id}\n\n"
                    f"انضم لمجموعة الوساطة للتواصل مع الوسيط مباشرة\n\n"
                    f"*الرابط صالح لمرة واحدة فقط ولمدة 15 دقيقة*\n"
                    f"ادخل المجموعة الآن قبل انتهاء الرابط."
                )
            else:
                keyboard_user.row(types.InlineKeyboardButton("🔹 تواصل مع الوسيط", url=f"tg://user?id={req['broker_user_id']}", style="primary"))
                msg_text = (
                    f" *وافق الوسيط على طلبك!*\n\n"
                    f"رقم الطلب: #{req_id}\n\n"
                    f"تواصل مع الوسيط مباشرة: {br_contact}"
                )
            keyboard_user.row(
                types.InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_broker_{req['broker_user_id']}_{req_id}_5", style="primary"),
                types.InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rate_broker_{req['broker_user_id']}_{req_id}_4", style="primary")
            )
            keyboard_user.row(
                types.InlineKeyboardButton("⭐⭐⭐", callback_data=f"rate_broker_{req['broker_user_id']}_{req_id}_3", style="primary"),
                types.InlineKeyboardButton("⭐⭐", callback_data=f"rate_broker_{req['broker_user_id']}_{req_id}_2", style="primary")
            )
            keyboard_user.row(
                types.InlineKeyboardButton("⭐", callback_data=f"rate_broker_{req['broker_user_id']}_{req_id}_1", style="danger")
            )
            msg_text += "\n\nقيّم الوسيط بعد انتهاء الصفقة:"
            send_result = safe_send(req["user_id"], msg_text, reply_markup=keyboard_user)
            if send_result:
                broker_notif = f" وافقت على طلب #{req_id}. تم إرسال الرابط للعميل ({15} دقيقة)."
            else:
                broker_notif = f" وافقت على طلب #{req_id}، لكن تعذّر إرسال الإشعار للعميل (ربما حجب البوت)."
            # إشعار الأدمن لو فشل إنشاء الرابط
            if invite_link_error and not broker_group_link:
                try:
                    bot.send_message(
                        OWNER_ID,
                        f"⚠️ *تحذير: فشل إنشاء رابط الدعوة*\n\n"
                        f"الطلب: #{req_id}\n"
                        f"السبب: {md_escape(invite_link_error)}\n\n"
                        f"تأكد أن البوت مشرف في مجموعة الوساطة وأن broker\\_group\\_id صحيح.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            safe_answer_callback_query(call.id, "✅ تم الموافقة وإبلاغ العميل")
            try:
                bot.edit_message_text(broker_notif, chat_id, message_id)
            except Exception:
                pass

        elif call.data.startswith("broker_reject_req_"):
            if not db.is_broker(user_id):
                safe_answer_callback_query(call.id, "أنت لست وسيطاً!", show_alert=True)
                return
            req_id = int(call.data.replace("broker_reject_req_", ""))
            req = db.get_broker_request_by_id(req_id)
            if not req:
                safe_answer_callback_query(call.id, "الطلب غير موجود!")
                return
            if req["broker_user_id"] != user_id:
                safe_answer_callback_query(call.id, "هذا الطلب ليس لك!", show_alert=True)
                return
            db.update_broker_request(req_id, "rejected", "رفض الوسيط")
            try:
                bot.send_message(req["user_id"], f" *تم رفض طلب الوساطة #{req_id}.*\n\nيمكنك اختيار وسيط آخر.", parse_mode="Markdown")
            except Exception:
                pass
            safe_answer_callback_query(call.id, "تم الرفض")
            try:
                bot.edit_message_text(f"تم رفض الطلب #{req_id}.", chat_id, message_id)
            except Exception:
                pass

        # بلاغ من الوسيط على مستخدم 
        elif call.data.startswith("broker_report_user_"):
            if not db.is_broker(user_id):
                safe_answer_callback_query(call.id, "أنت لست وسيطاً!", show_alert=True)
                return
            req_id = int(call.data.replace("broker_report_user_", ""))
            req = db.get_broker_request_by_id(req_id)
            if not req:
                safe_answer_callback_query(call.id, "الطلب غير موجود!")
                return
            if req["broker_user_id"] != user_id:
                safe_answer_callback_query(call.id, "هذا الطلب ليس لك!", show_alert=True)
                return
            db.add_report(req["user_id"], user_id, f"بلاغ من وسيط على طلب #{req_id}")
            safe_answer_callback_query(call.id, "تم إرسال البلاغ للإدارة", show_alert=True)
            try:
                bot.send_message(OWNER_ID, f" *بلاغ من وسيط!*\n\nالوسيط: ID {user_id}\nالمستخدم: ID {req['user_id']}\nطلب #{req_id}", parse_mode="Markdown")
            except Exception:
                pass

        # تأكيد/رفض تحويل وكيل مباشر 
        elif call.data.startswith("admin_approve_agent_op_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            try:
                op_id = int(call.data.replace("admin_approve_agent_op_", ""))
            except ValueError:
                safe_answer_callback_query(call.id, "بيانات غير صحيحة!")
                return
            op = db.get_agent_pending_op(op_id)
            if not op:
                safe_answer_callback_query(call.id, "العملية غير موجودة!", show_alert=True)
                return
            if op['status'] != 'pending':
                safe_answer_callback_query(call.id, f"العملية {op['status']} بالفعل!", show_alert=True)
                return
            agent_id = op['agent_id']
            amount = op['amount']
            agent_balance = db.get_balance(agent_id)
            if agent_balance < amount:
                safe_answer_callback_query(call.id, f"رصيد الوكيل غير كافٍ! ({agent_balance:.2f}$ < {amount:.2f}$)", show_alert=True)
                return

            if op['op_type'] == 'code':
                # إنشاء الكود الفعلي وخصم الرصيد
                code = op['code']
                with db._lock:
                    db.conn.execute(
                        "INSERT OR IGNORE INTO recharge_codes (code, amount, max_uses, created_by) VALUES (?,?,1,?)",
                        (code, amount, agent_id)
                    )
                    db.conn.commit()
                db.update_balance(agent_id, -amount)
                db.add_transaction(agent_id, -amount, 'agent_code_create', f"إنشاء كود شحن {code}")
                db.resolve_agent_pending_op(op_id, 'approved')
                # إشعار الوكيل
                try:
                    keyboard_agent = types.InlineKeyboardMarkup()
                    keyboard_agent.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
                    bot.send_message(
                        agent_id,
                        f"✅ *تمت الموافقة على إنشاء الكود!*\n\n"
                        f"الكود: `{code}`\n"
                        f"القيمة: {amount:.2f}$\n"
                        f"رصيدك الجديد: {db.get_balance(agent_id):.2f}$\n\n"
                        f"أرسل هذا الكود لعميلك.",
                        reply_markup=keyboard_agent, parse_mode="Markdown"
                    )
                except Exception:
                    pass
                safe_answer_callback_query(call.id, "✅ تمت الموافقة وإنشاء الكود")
                try:
                    bot.edit_message_text(
                        f"✅ تمت الموافقة\n\nالكود: {code} | {amount:.2f}$ | وكيل {agent_id}",
                        chat_id, message_id
                    )
                except Exception:
                    pass

            elif op['op_type'] == 'transfer':
                target_uid = op['target_uid']
                # خصم من الوكيل وإضافة للمستلم
                db.update_balance(agent_id, -amount)
                db.update_balance(target_uid, amount)
                db.add_transaction(agent_id, -amount, 'agent_transfer_out', f"تحويل مباشر إلى {target_uid}")
                db.add_transaction(target_uid, amount, 'agent_transfer', f"تحويل مباشر من وكيل {agent_id}")
                db.resolve_agent_pending_op(op_id, 'approved')
                target_user = db.get_user(target_uid)
                uname = f"@{target_user['username']}" if target_user and target_user['username'] else str(target_uid)
                # إشعار المستلم
                try:
                    bot.send_message(
                        target_uid,
                        f"💰 *تم استلام تحويل!*\n\n"
                        f"المبلغ: {amount:.2f}$\n"
                        f"رصيدك الجديد: {db.get_balance(target_uid):.2f}$",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                # إشعار الوكيل
                try:
                    bot.send_message(
                        agent_id,
                        f"✅ *تمت الموافقة على التحويل!*\n\n"
                        f"المستلم: {md_escape(uname)}\n"
                        f"المبلغ: {amount:.2f}$\n"
                        f"رصيدك الجديد: {db.get_balance(agent_id):.2f}$",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                safe_answer_callback_query(call.id, "✅ تم التحويل")
                try:
                    bot.edit_message_text(
                        f"✅ تم التحويل\n\n{amount:.2f}$ → {uname} ({target_uid})\nمن وكيل {agent_id}",
                        chat_id, message_id
                    )
                except Exception:
                    pass

        elif call.data.startswith("admin_reject_agent_op_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            try:
                op_id = int(call.data.replace("admin_reject_agent_op_", ""))
            except ValueError:
                safe_answer_callback_query(call.id, "بيانات غير صحيحة!")
                return
            op = db.get_agent_pending_op(op_id)
            if not op:
                safe_answer_callback_query(call.id, "العملية غير موجودة!", show_alert=True)
                return
            if op['status'] != 'pending':
                safe_answer_callback_query(call.id, f"العملية {op['status']} بالفعل!", show_alert=True)
                return
            db.resolve_agent_pending_op(op_id, 'rejected', admin_note='رُفض من الإدارة')
            op_label = "إنشاء الكود" if op['op_type'] == 'code' else "التحويل المباشر"
            # إشعار الوكيل
            try:
                kb_ag = types.InlineKeyboardMarkup()
                kb_ag.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
                bot.send_message(
                    op['agent_id'],
                    f"❌ *تم رفض طلب {op_label}*\n\n"
                    f"المبلغ: {op['amount']:.2f}$\n\n"
                    f"تواصل مع الإدارة لمعرفة السبب.",
                    reply_markup=kb_ag, parse_mode="Markdown"
                )
            except Exception:
                pass
            safe_answer_callback_query(call.id, "❌ تم الرفض")
            try:
                bot.edit_message_text(
                    f"❌ تم رفض طلب {op_label} من وكيل {op['agent_id']} | {op['amount']:.2f}$",
                    chat_id, message_id
                )
            except Exception:
                pass

        # ← handlers قديمة — محوّلة للنظام الجديد (pending_ops)
        elif call.data == "admin_agent_pending_ops":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            cursor_ops = db.conn.cursor()
            cursor_ops.execute(
                "SELECT op_id, op_type, agent_id, target_uid, amount, code, created_at "
                "FROM agent_pending_ops WHERE status='pending' ORDER BY created_at ASC"
            )
            ops = cursor_ops.fetchall()
            if not ops:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text("✅ لا توجد طلبات وكلاء معلقة حالياً.", chat_id, message_id, reply_markup=keyboard)
                return
            text = f"⏳ *طلبات الوكلاء المعلقة ({len(ops)})*\n\n"
            keyboard = types.InlineKeyboardMarkup()
            for op in ops:
                op_id, op_type, agent_id, target_uid, amount, code, created_at = op
                agents_list = db.get_all_agents()
                ag = next((a for a in agents_list if a['user_id'] == agent_id), None)
                ag_name = ag['name'] if ag else str(agent_id)
                created_str = str(created_at)[:16] if created_at else "?"
                if op_type == 'code':
                    text += (
                        f"🔐 #{op_id} — كود شحن\n"
                        f"الوكيل: {md_escape(ag_name)} (`{agent_id}`)\n"
                        f"القيمة: *{amount:.2f}$* | الكود: `{code or '?'}`\n"
                        f"وقت الطلب: {created_str}\n\n"
                    )
                else:
                    target_user = db.get_user(target_uid)
                    t_name = f"@{target_user['username']}" if target_user and target_user['username'] else str(target_uid)
                    text += (
                        f"💸 #{op_id} — تحويل مباشر\n"
                        f"الوكيل: {md_escape(ag_name)} (`{agent_id}`)\n"
                        f"المستلم: {md_escape(t_name)} (`{target_uid}`)\n"
                        f"المبلغ: *{amount:.2f}$*\n"
                        f"وقت الطلب: {created_str}\n\n"
                    )
                keyboard.row(
                    types.InlineKeyboardButton(f"✅ #{op_id}", callback_data=f"admin_approve_agent_op_{op_id}", style="primary"),
                    types.InlineKeyboardButton(f"❌ رفض #{op_id}", callback_data=f"admin_reject_agent_op_reason_{op_id}", style="danger"),
                    types.InlineKeyboardButton(f"⛔ فوري #{op_id}", callback_data=f"admin_reject_agent_op_{op_id}", style="danger"),
                )
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            safe_answer_callback_query(call.id)
        elif call.data.startswith("admin_approve_agent_transfer_"):
            safe_answer_callback_query(call.id, "⚠️ هذا الطلب قديم — استخدم لوحة طلبات الوكلاء", show_alert=True)

        elif call.data.startswith("admin_reject_agent_transfer_"):
            safe_answer_callback_query(call.id, "⚠️ هذا الطلب قديم — استخدم لوحة طلبات الوكلاء", show_alert=True)

        # رفض مع سبب — الأدمن يكتب السبب
        elif call.data.startswith("admin_reject_agent_op_reason_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            try:
                op_id = int(call.data.replace("admin_reject_agent_op_reason_", ""))
            except ValueError:
                safe_answer_callback_query(call.id, "بيانات غير صحيحة!")
                return
            op = db.get_agent_pending_op(op_id)
            if not op or op['status'] != 'pending':
                safe_answer_callback_query(call.id, "العملية غير موجودة أو منتهية!", show_alert=True)
                return
            db.set_user_state(user_id, f"admin_reject_reason_{op_id}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ رفض بدون سبب", callback_data=f"admin_reject_agent_op_{op_id}", style="danger"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agent_pending_ops", style="primary"))
            op_label = "إنشاء كود" if op['op_type'] == 'code' else "تحويل مباشر"
            bot.edit_message_text(
                f"❌ *رفض طلب {op_label}*\n\n"
                f"الوكيل: `{op['agent_id']}`\n"
                f"المبلغ: {op['amount']:.2f}$\n\n"
                f"أرسل سبب الرفض (سيُرسل للوكيل):",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )
            safe_answer_callback_query(call.id)

        # تقييم الوكيل 
        elif call.data.startswith("rate_agent_"):
            parts = call.data.replace("rate_agent_", "").split("_")
            if len(parts) < 3:
                safe_answer_callback_query(call.id, "بيانات غير صحيحة!")
                return
            agent_uid_r, req_id_r, stars = int(parts[0]), int(parts[1]), int(parts[2])
            if db.has_rated_agent_req(user_id, req_id_r):
                safe_answer_callback_query(call.id, "لقد قيّمت مسبقاً!", show_alert=True)
                return
            db.add_agent_rating(agent_uid_r, user_id, req_id_r, stars)
            if stars < 4:
                db.set_user_state(user_id, "waiting_agent_rating_comment", {"agent_uid": agent_uid_r, "req_id": req_id_r})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 تخطي التعليق", callback_data=f"agent_detail_{agent_uid_r}", style="primary"))
                try:
                    bot.edit_message_text(f"{'' * stars} شكراً!\n\nأرسل تعليقاً (اختياري):", chat_id, message_id, reply_markup=keyboard)
                except Exception:
                    bot.send_message(chat_id, f"{'' * stars} شكراً!", reply_markup=keyboard)
            else:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع للوكيل", callback_data=f"agent_detail_{agent_uid_r}", style="primary"))
                try:
                    bot.edit_message_text(f"{'' * stars} شكراً على تقييمك!", chat_id, message_id, reply_markup=keyboard)
                except Exception:
                    bot.send_message(chat_id, f"{'' * stars} شكراً!", reply_markup=keyboard)
            safe_answer_callback_query(call.id, f"تم التقييم بـ {stars} نجوم")

        # تقييم الوسيط 
        elif call.data.startswith("rate_broker_"):
            parts = call.data.replace("rate_broker_", "").split("_")
            if len(parts) < 3:
                safe_answer_callback_query(call.id, "بيانات غير صحيحة!")
                return
            broker_uid_r, req_id_r, stars = int(parts[0]), int(parts[1]), int(parts[2])
            if db.has_rated_broker_req(user_id, req_id_r):
                safe_answer_callback_query(call.id, "لقد قيّمت مسبقاً!", show_alert=True)
                return
            db.add_broker_rating(broker_uid_r, user_id, req_id_r, stars)
            if stars < 4:
                db.set_user_state(user_id, "waiting_broker_rating_comment", {"broker_uid": broker_uid_r, "req_id": req_id_r})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 تخطي التعليق", callback_data=f"broker_detail_{broker_uid_r}", style="primary"))
                try:
                    bot.edit_message_text(f"{'' * stars} شكراً!\n\nأرسل تعليقاً (اختياري):", chat_id, message_id, reply_markup=keyboard)
                except Exception:
                    bot.send_message(chat_id, f"{'' * stars} شكراً!", reply_markup=keyboard)
            else:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع للوسيط", callback_data=f"broker_detail_{broker_uid_r}", style="primary"))
                try:
                    bot.edit_message_text(f"{'' * stars} شكراً على تقييمك!", chat_id, message_id, reply_markup=keyboard)
                except Exception:
                    bot.send_message(chat_id, f"{'' * stars} شكراً!", reply_markup=keyboard)
            safe_answer_callback_query(call.id, f"تم التقييم بـ {stars} نجوم")

        elif call.data == "my_cards":
            safe_answer_callback_query(call.id)
            nav_push(user_id, "my_cards")
            cards = db.get_user_cards(user_id)
            free_count = db.get_user_free_cards_count(user_id)
            ref_count = db.get_user_referral_count(user_id)
            bot_info = get_bot_info()
            ref_link = f"https://t.me/{bot_info['username']}?start=ref_{user_id}"
            # بناء نص منظم مع HTML
            text_lines = [
                f"🎟️ {hb('كروتي وإحالاتي')}",
                DIVIDER,
                f"📦 {hb('إجمالي الكروت:')} {len(cards)}",
                f"🆓 {hb('الكروت المتاحة للمسابقات:')} <b>{free_count}</b>",
                f"👥 {hb('المستخدمون المُحالون:')} {ref_count}",
                DIVIDER,
                f"🔗 {hb('رابطك الخاص للدعوة:')}",
                hc(ref_link),
                "",
                "💡 كل صديق ينضم عبر رابطك يمنحك <b>كارتاً مجانياً فورياً</b>",
                "مما يزيد فرصك في الفوز بالمسابقات! 🎯",
            ]
            text = "\n".join(text_lines)
            keyboard = types.InlineKeyboardMarkup()
            share_text = "🔥 وجدت أفضل منصة لمزادات الحسابات والقنوات على تيليجرام! انضم الآن واحصل على كارت مجاني:"
            share_url = (
                "https://t.me/share/url?url=" + urllib.parse.quote(ref_link, safe="")
                + "&text=" + urllib.parse.quote(share_text, safe="")
            )
            keyboard.row(types.InlineKeyboardButton("📤 مشاركة ودعوة أصدقاء", url=share_url, style="primary"))
            if cards:
                last_cards_lines = "\n".join(f"• {hc(c['card_number'])}" for c in cards[:5])
                text += f"\n\n🗂️ {hb('آخر 5 كروت:')}\n{last_cards_lines}"
            # صف: مسابقات + نسخ الرابط
            keyboard.row(
                types.InlineKeyboardButton("🎯 المسابقات", callback_data="show_contests", style="primary"),
                types.InlineKeyboardButton("📋 نسخ الرابط", callback_data=f"copy_ref_link_{user_id}", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")


        elif call.data.startswith("copy_ref_link_"):
            ref_uid = call.data.replace("copy_ref_link_", "")
            bot_info = get_bot_info()
            ref_link = f"https://t.me/{bot_info['username']}?start=ref_{ref_uid}"
            safe_answer_callback_query(call.id, f"رابطك: {ref_link}", show_alert=True)

        elif call.data == "show_contests":
            safe_answer_callback_query(call.id)
            nav_push(user_id, "show_contests")
            contests_active = db.get_all_contests(status='active')
            contests_sched = db.get_all_contests(status='scheduled')
            contests = contests_active + contests_sched
            free_cards = db.get_user_free_cards_count(user_id)
            cards_label = f"🃏 كروتي ({free_cards})" if free_cards > 0 else "🃏 كروتي"
            keyboard = types.InlineKeyboardMarkup()
            if not contests:
                text = (
                    "🎯 <b>المسابقات</b>\n\n"
                    "لا توجد مسابقات نشطة حالياً.\n\n"
                    "💡 ادعُ أصدقاءك واجمع الكروت للمشاركة في القادمة!\n"
                    "لكل صديق ينضم عبر رابطك كارت مجاني فوري 🎁"
                )
            else:
                text = (
                    "🎯 <b>المسابقات المتاحة</b>\n\n"
                    f"🃏 كروتك المتاحة: <b>{free_cards}</b>\n\n"
                    "اختر مسابقة للمشاركة:\n"
                )
                seen = set()
                for c in contests:
                    if c['contest_id'] not in seen:
                        seen.add(c['contest_id'])
                        status_icon = "🟢" if c['status'] == 'active' else "🔵"
                        prize = _prize_label(c)
                        keyboard.row(types.InlineKeyboardButton(
                            f"{status_icon} {c['name']} — 🎁 {prize}",
                            callback_data=f"contest_detail_{c['contest_id']}", style="primary"
                        ))
            keyboard.row(types.InlineKeyboardButton(cards_label, callback_data="my_cards", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data.startswith("contest_detail_"):
            safe_answer_callback_query(call.id)
            contest_id = int(call.data.replace("contest_detail_", ""))
            c = db.get_contest(contest_id)
            if not c:
                safe_answer_callback_query(call.id, "المسابقة غير موجودة!", show_alert=True)
                return
            if call.message.chat.type != 'private':
                safe_answer_callback_query(call.id, "افتح البوت للمشاركة!", show_alert=True)
                return
            participants = db.get_contest_participants_count(contest_id)
            all_cards_count = len(db.get_contest_all_cards(contest_id))
            free_cards = db.get_user_free_cards_count(user_id, contest_id=contest_id)
            # حساب احتمالية الفوز
            user_cards_in = db.get_user_free_cards_count(user_id)  # كروت الشخص الكلية
            win_chance = ""
            if all_cards_count > 0 and user_cards_in > 0:
                pct = min(100.0, (user_cards_in / max(all_cards_count + user_cards_in, 1)) * 100)
                win_chance = f"🎰 احتمالية فوزك: ≈ {pct:.1f}%\n"
            start_dt = db.parse_datetime(c['start_at']) if c['start_at'] else None
            time_info = ""
            if start_dt:
                diff = start_dt - datetime.now()
                if diff.total_seconds() > 0:
                    h = int(diff.total_seconds() // 3600)
                    m = int((diff.total_seconds() % 3600) // 60)
                    time_info = f"⏰ السحب بعد: {h}:{m:02d}\n"
                else:
                    time_info = "⏰ السحب قريباً...\n"
            status_ar = {'scheduled': '🔵 قادمة', 'active': '🟢 نشطة', 'completed': '🔴 منتهية', 'cancelled': '⚫ ملغاة'}
            prize_label = _prize_label(c)
            text = (
                f"🏆 <b>{c['name']}</b>\n\n"
                f"{c['description'] or ''}\n\n"
                f"🎁 الجائزة: <b>{prize_label}</b>\n"
                f"👥 المشاركون: {participants}\n"
                f"🃏 الكروت المشاركة: {all_cards_count}\n"
                f"📌 الحالة: {status_ar.get(c['status'], c['status'])}\n"
                f"{time_info}"
                f"{win_chance}\n"
                f"🃏 كروتك المتاحة: <b>{free_cards}</b>"
            )
            keyboard = types.InlineKeyboardMarkup()
            if c['status'] in ('active', 'scheduled') and free_cards > 0:
                keyboard.row(types.InlineKeyboardButton(
                    f"🎯 المشاركة بـ {free_cards} كارت", callback_data=f"enter_contest_{contest_id}", style="primary"
                ))
            elif free_cards == 0 and c['status'] in ('active', 'scheduled'):
                bot_info = get_bot_info()
                ref_link = f"https://t.me/{bot_info['username']}?start=ref_{user_id}"
                keyboard.row(types.InlineKeyboardButton("🃏 احصل على كروت مجانية", url=ref_link, style="primary"))
            keyboard.row(
                types.InlineKeyboardButton("🎯 المسابقات", callback_data="show_contests", style="primary"),
                types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary")
            )
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data.startswith("enter_contest_"):
            if call.message.chat.type != 'private':
                safe_answer_callback_query(call.id, "افتح البوت للمشاركة!", show_alert=True)
                return
            contest_id = int(call.data.replace("enter_contest_", ""))
            c = db.get_contest(contest_id)
            if not c or c['status'] not in ('active', 'scheduled'):
                safe_answer_callback_query(call.id, "المسابقة لم تعد متاحة!", show_alert=True)
                return
            ok, cards_used = db.enter_contest(contest_id, user_id)
            if ok:
                participants = db.get_contest_participants_count(contest_id)
                def _update_contest_msg(cid, count):
                    try:
                        c2 = db.get_contest(cid)
                        if not c2:
                            return
                        txt = (
                            f"🏆 *{md_escape(c2['name'])}*\n\n"
                            f"{md_escape(c2['description'] or '')}\n\n"
                            f"🎁 الجائزة: *{md_escape(_prize_label(c2))}*\n"
                            f"👥 المشاركون: {count}\n"
                        )
                        if c2['start_at']:
                            diff = db.parse_datetime(c2['start_at']) - datetime.now()
                            if diff.total_seconds() > 0:
                                h = int(diff.total_seconds() // 3600)
                                m2 = int((diff.total_seconds() % 3600) // 60)
                                txt += f"⏰ السحب بعد: {h}:{m2:02d}\n"
                        kb = types.InlineKeyboardMarkup()
                        _bu = get_bot_info().get('username', 'bot')
                        kb.row(types.InlineKeyboardButton("🏆 المشاركة في المسابقة", url=f"https://t.me/{_bu}?start=contest_{cid}"))
                        for ch_msg in db.get_contest_channel_messages(cid):
                            try:
                                bot.edit_message_text(txt, ch_msg['channel_id'], ch_msg['message_id'], reply_markup=kb, parse_mode="Markdown")
                            except Exception:
                                pass
                    except Exception:
                        pass
                threading.Thread(target=_update_contest_msg, args=(contest_id, participants), daemon=True).start()
                safe_answer_callback_query(call.id, f"✅ شاركت بـ {cards_used} كارت!", show_alert=True)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(
                    types.InlineKeyboardButton("🎯 المسابقات", callback_data="show_contests", style="primary"),
                    types.InlineKeyboardButton("🃏 كروتي", callback_data="my_cards", style="primary")
                )
                keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                try:
                    bot.edit_message_text(
                        f"✅ <b>تم تسجيل مشاركتك!</b>\n\n"
                        f"المسابقة: {c['name']}\n"
                        f"الكروت المشاركة: <b>{cards_used}</b>\n"
                        f"إجمالي المشاركين الآن: {participants}\n\n"
                        f"بالتوفيق! 🍀",
                        chat_id, message_id, reply_markup=keyboard, parse_mode="HTML"
                    )
                except Exception:
                    bot.send_message(chat_id, f"✅ تم تسجيل {cards_used} كارت في المسابقة!", reply_markup=keyboard)
            else:
                safe_answer_callback_query(call.id, "لا تملك كروت متاحة أو شاركت مسبقاً!", show_alert=True)

        # إدارة المسابقات (أدمن) 
        elif call.data == "admin_contest_in_1min":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            user_state_now = db.get_user_state(user_id)
            if not user_state_now or user_state_now['state'] != 'admin_contest_step4':
                safe_answer_callback_query(call.id, "انتهت الجلسة!")
                return
            start_at = datetime.now() + timedelta(minutes=1)
            data = (user_state_now.get('data') or {})
            ok, contest_id = db.create_contest(
                data.get('name', 'مسابقة'), data.get('description', ''),
                data.get('prize', 0), start_at, user_id,
                prize_description=data.get('prize_description', '')
            )
            db.clear_user_state(user_id)
            if ok:
                _schedule_contest_draw(contest_id, start_at)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إدارة المسابقة", callback_data=f"admin_contest_{contest_id}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔹 نشر الآن", callback_data=f"admin_publish_contest_{contest_id}", style="primary"))
                safe_answer_callback_query(call.id, f" تم إنشاء المسابقة #{contest_id}")
                try:
                    bot.edit_message_text(
                        f" *تم إنشاء المسابقة #{contest_id}!*\n\nالسحب بعد دقيقة واحدة.",
                        chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
                    )
                except Exception:
                    pass

        elif call.data == "admin_contest_in_1h":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            user_state_now = db.get_user_state(user_id)
            if not user_state_now or user_state_now['state'] != 'admin_contest_step4':
                safe_answer_callback_query(call.id, "انتهت الجلسة!")
                return
            start_at = datetime.now() + timedelta(hours=1)
            data = (user_state_now.get('data') or {})
            ok, contest_id = db.create_contest(
                data.get('name', 'مسابقة'), data.get('description', ''),
                data.get('prize', 0), start_at, user_id,
                prize_description=data.get('prize_description', '')
            )
            db.clear_user_state(user_id)
            if ok:
                _schedule_contest_draw(contest_id, start_at)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إدارة المسابقة", callback_data=f"admin_contest_{contest_id}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔹 نشر الآن", callback_data=f"admin_publish_contest_{contest_id}", style="primary"))
                safe_answer_callback_query(call.id, f" تم إنشاء المسابقة #{contest_id}")
                try:
                    bot.edit_message_text(
                        f" *تم إنشاء المسابقة #{contest_id}!*\n\nالسحب بعد ساعة.",
                        chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
                    )
                except Exception:
                    pass

        elif call.data == "admin_contests":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا للمالك فقط!")
                return
            nav_push(user_id, "admin_contests")
            contests = db.get_all_contests()
            status_ar = {'scheduled': '🔵 قادمة', 'active': '🟢 نشطة', 'completed': '🔴 منتهية', 'cancelled': '⚫ ملغاة'}
            text = f"🎯 <b>إدارة المسابقات</b>\n\nالمجموع: {len(contests)}\n\n"
            for c in contests[:8]:
                participants = db.get_contest_participants_count(c['contest_id'])
                text += f"• #{c['contest_id']} <b>{c['name']}</b>\n  {status_ar.get(c['status'],'?')} | 🎁 {_prize_label(c)} | 👥 {participants}\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("➕ مسابقة جديدة", callback_data="admin_new_contest", style="primary"))
            active = [c for c in contests if c['status'] in ('active', 'scheduled')]
            for c in active[:4]:
                participants = db.get_contest_participants_count(c['contest_id'])
                icon = "🟢" if c['status'] == 'active' else "🔵"
                keyboard.row(types.InlineKeyboardButton(
                    f"{icon} #{c['contest_id']} {c['name'][:18]} ({participants}👥)",
                    callback_data=f"admin_contest_{c['contest_id']}", style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data == "admin_new_contest":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            db.set_user_state(user_id, "admin_contest_step1")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_contests", style="danger"))
            bot.edit_message_text(
                "🏆 *مسابقة جديدة — الخطوة 1/5*\n\nأرسل *اسم* المسابقة:",
                chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
            )

        elif call.data.startswith("admin_contest_") and call.data.replace("admin_contest_", "").isdigit():
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            contest_id = int(call.data.replace("admin_contest_", ""))
            c = db.get_contest(contest_id)
            if not c:
                safe_answer_callback_query(call.id, "غير موجود!")
                return
            participants = db.get_contest_participants_count(contest_id)
            cards_count = len(db.get_contest_all_cards(contest_id))
            status_ar = {'scheduled': '🔵 قادمة', 'active': '🟢 نشطة', 'completed': '🔴 منتهية', 'cancelled': '⚫ ملغاة'}
            time_info = ""
            if c['start_at']:
                try:
                    diff = db.parse_datetime(c['start_at']) - datetime.now()
                    if diff.total_seconds() > 0:
                        h = int(diff.total_seconds() // 3600)
                        m = int((diff.total_seconds() % 3600) // 60)
                        time_info = f"\n⏰ السحب بعد: {h}:{m:02d}"
                    else:
                        time_info = "\n⏰ السحب قريباً جداً..."
                except Exception:
                    time_info = f"\n📅 {str(c['start_at'])[:16]}"
            text = (
                f"🏆 <b>إدارة المسابقة #{contest_id}</b>\n\n"
                f"📌 الاسم: <b>{c['name']}</b>\n"
                f"🎁 الجائزة: <b>{_prize_label(c)}</b>\n"
                f"📋 الوصف: {c.get('description') or '—'}\n"
                f"📌 الحالة: {status_ar.get(c['status'], c['status'])}\n"
                f"👥 المشاركون: <b>{participants}</b>\n"
                f"🃏 الكروت المشاركة: <b>{cards_count}</b>"
                f"{time_info}"
            )
            keyboard = types.InlineKeyboardMarkup()
            if c['status'] in ('scheduled', 'active'):
                keyboard.row(types.InlineKeyboardButton("📤 تشغيل السحب الآن", callback_data=f"admin_draw_contest_{contest_id}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("📣 نشر في القناة", callback_data=f"admin_publish_contest_{contest_id}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء المسابقة", callback_data=f"admin_cancel_contest_{contest_id}", style="danger"))
            keyboard.row(types.InlineKeyboardButton("🔙 إدارة المسابقات", callback_data="admin_contests", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        elif call.data.startswith("admin_draw_contest_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            contest_id = int(call.data.replace("admin_draw_contest_", ""))
            c = db.get_contest(contest_id)
            if not c:
                safe_answer_callback_query(call.id, "غير موجود!")
                return
            cards = db.get_contest_all_cards(contest_id)
            if not cards:
                safe_answer_callback_query(call.id, "لا توجد كروت مشاركة!", show_alert=True)
                return
            safe_answer_callback_query(call.id, "جارٍ السحب...")
            # عرض الكروت بشكل عشوائي ثم الفائز
            def _do_draw():
                try:
                    import random as _r
                    # قراءة المسابقة من DB للحصول على بيانات محدثة
                    c_fresh = db.get_contest(contest_id)
                    if not c_fresh or c_fresh['status'] == 'completed':
                        bot.send_message(chat_id, "⚠️ المسابقة اكتملت مسبقاً أو غير موجودة.")
                        return
                    # بناء نص الكروت المشاركة (عرض عشوائي)
                    all_numbers = [card['card_number'] for card in cards]
                    _r.shuffle(all_numbers)
                    preview_lines = "\n".join([f"🃏 {n}" for n in all_numbers[:15]])
                    if len(all_numbers) > 15:
                        preview_lines += f"\n... و{len(all_numbers)-15} كارت آخر"
                    msg = bot.send_message(
                        chat_id,
                        f"🎰 *جارٍ السحب...*\n\nالكروت المشاركة ({len(all_numbers)}):\n{preview_lines}",
                        parse_mode="Markdown"
                    )
                    time.sleep(3)
                    winner_card, winner_uid = db.draw_contest_winner(contest_id)
                    if not winner_card:
                        bot.edit_message_text("❌ فشل السحب!", chat_id, msg.message_id)
                        return
                    winner_info = db.get_user(winner_uid)
                    winner_name = (f"@{winner_info['username']}" if winner_info and winner_info['username']
                                   else (winner_info['first_name'] if winner_info else f"ID {winner_uid}"))
                    # توليد كود الجائزة وحفظه
                    prize_code = _generate_prize_code()
                    db.update_contest(contest_id, winner_prize_code=prize_code)
                    prize_label = _prize_label(c_fresh)
                    result_text = (
                        f"🏆 *نتيجة السحب — {c_fresh['name']}*\n\n"
                        f"{'─'*24}\n"
                        f"🃏 *الكارت الفائز:*\n`{winner_card}`\n\n"
                        f"🎉 *الفائز: {winner_name}*\n"
                        f"🎁 *الجائزة: {prize_label}*\n"
                        f"{'─'*24}\n\n"
                        f"🔑 كود الجائزة: `{prize_code}`\n\n"
                        f"تم إرسال الكود للفائز ✅"
                    )
                    try:
                        bot.edit_message_text(result_text, chat_id, msg.message_id, parse_mode="Markdown")
                    except Exception:
                        bot.send_message(chat_id, result_text, parse_mode="Markdown")
                    # تحديث رسائل كل القنوات
                    for ch_msg in db.get_contest_channel_messages(contest_id):
                        try:
                            bot.edit_message_text(
                                f"🏆 *انتهت المسابقة — {md_escape(c_fresh['name'])}*\n\n"
                                f"🎉 الفائز: {md_escape(winner_name)}\n"
                                f"🎁 الجائزة: {md_escape(prize_label)}\n"
                                f"🃏 الكارت الفائز: `{winner_card}`",
                                ch_msg['channel_id'], ch_msg['message_id'], parse_mode="Markdown"
                            )
                        except Exception:
                            pass
                    # إشعار الفائز
                    try:
                        claim_kb = types.InlineKeyboardMarkup()
                        claim_kb.row(types.InlineKeyboardButton(
                            "📩 مطالبة بالجائزة", callback_data=f"claim_prize_{contest_id}", style="primary"
                        ))
                        bot.send_message(
                            winner_uid,
                            f"🎉 *مبروك! فزت في مسابقة {md_escape(c_fresh['name'])}!*\n\n"
                            f"🃏 الكارت الفائز: `{winner_card}`\n"
                            f"🎁 الجائزة: *{md_escape(prize_label)}*\n\n"
                            f"🔑 *كود جائزتك:* `{prize_code}`\n\n"
                            f"اضغط زر المطالبة أدناه لإرسال طلبك للمالك.\n"
                            f"سيتواصل معك المالك لتسليم الجائزة بعد التحقق من الكود.",
                            parse_mode="Markdown",
                            reply_markup=claim_kb
                        )
                    except Exception:
                        pass
                except Exception as ex:
                    logger.error(f"_do_draw error: {ex}")
            threading.Thread(target=_do_draw, daemon=True).start()

        elif call.data.startswith("admin_publish_contest_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            contest_id = int(call.data.replace("admin_publish_contest_", ""))
            c = db.get_contest(contest_id)
            if not c:
                safe_answer_callback_query(call.id, "غير موجود!")
                return
            channels = db.get_all_channels()
            if not channels:
                safe_answer_callback_query(call.id, "لا توجد قنوات بث!", show_alert=True)
                return
            participants = db.get_contest_participants_count(contest_id)
            start_dt = db.parse_datetime(c['start_at']) if c['start_at'] else None
            time_info = ""
            if start_dt:
                diff = start_dt - datetime.now()
                if diff.total_seconds() > 0:
                    h = int(diff.total_seconds() // 3600)
                    m2 = int((diff.total_seconds() % 3600) // 60)
                    time_info = f"⏰ السحب بعد: {h}:{m2:02d}\n"
            contest_text = (
                f"🏆 *{md_escape(c['name'])}*\n\n"
                f"{md_escape(c['description'] or '')}\n\n"
                f"🎁 الجائزة: *{md_escape(_prize_label(c))}*\n"
                f"👥 المشاركون: {participants}\n"
                f"{time_info}"
            )
            bot_username = get_bot_info().get('username', 'bot')
            deep_link = f"https://t.me/{bot_username}?start=contest_{contest_id}"
            kb = types.InlineKeyboardMarkup()
            kb.row(types.InlineKeyboardButton("📤 المشاركة في المسابقة", url=deep_link))
            def _publish():
                for ch in channels:
                    try:
                        sent = bot.send_message(ch['channel_id'], contest_text, reply_markup=kb, parse_mode="Markdown")
                        db.save_contest_message(contest_id, ch['channel_id'], sent.message_id)
                        db.update_contest(contest_id, status='active')
                        time.sleep(0.5)
                    except Exception as ex:
                        logger.error(f"publish_contest to {ch['channel_id']}: {ex}")
            threading.Thread(target=_publish, daemon=True).start()
            safe_answer_callback_query(call.id, " جارٍ نشر المسابقة في القنوات!")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إدارة المسابقة", callback_data=f"admin_contest_{contest_id}", style="primary"))
            try:
                bot.edit_message_text(f" تم نشر المسابقة في القنوات!", chat_id, message_id, reply_markup=keyboard)
            except Exception:
                pass

        elif call.data.startswith("admin_cancel_contest_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            contest_id = int(call.data.replace("admin_cancel_contest_", ""))
            db.update_contest(contest_id, status='cancelled')
            safe_answer_callback_query(call.id, "تم إلغاء المسابقة")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🎯 إدارة المسابقات", callback_data="admin_contests", style="primary"))
            try:
                bot.edit_message_text(f" تم إلغاء المسابقة #{contest_id}", chat_id, message_id, reply_markup=keyboard)
            except Exception:
                pass

        elif call.data == "admin_contest_skip_prize":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            user_state_now = db.get_user_state(user_id)
            if not user_state_now or user_state_now['state'] != 'admin_contest_step3':
                safe_answer_callback_query(call.id, "انتهت الجلسة!")
                return
            data = (user_state_now.get('data') or {})
            data['prize'] = 0  # بدون مبلغ مالي
            db.set_user_state(user_id, "admin_contest_step3b", data)
            safe_answer_callback_query(call.id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✏️ تحديد الجائزة — ماذا يحصل الفائز؟", callback_data="admin_contest_write_prize_desc", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_contests", style="danger"))
            try:
                bot.edit_message_text(
                    "⏭ تم تخطي المبلغ المالي.\n\n"
                    "*الخطوة 4/5:* حدد ماذا يحصل الفائز\n\n"
                    "اضغط الزر أدناه لكتابة وصف الجائزة:\n"
                    "_(مثال: هاتف، ساعة، بطاقة شحن...)_",
                    chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(chat_id, "✏️ *أرسل وصف الجائزة:*", reply_markup=keyboard, parse_mode="Markdown")

        elif call.data == "admin_contest_write_prize_desc":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            user_state_now = db.get_user_state(user_id)
            valid_states = ('admin_contest_step3b', 'admin_contest_step3')
            if not user_state_now or user_state_now['state'] not in valid_states:
                safe_answer_callback_query(call.id, "❌ انتهت الجلسة، ابدأ من جديد.")
                return
            # إذا كانت الحالة step3 (لم يُرسل مبلغ بعد) نضع prize=0 ونكمل
            if user_state_now['state'] == 'admin_contest_step3':
                data = (user_state_now.get('data') or {})
                data['prize'] = 0
                db.set_user_state(user_id, "admin_contest_step3b", data)
            safe_answer_callback_query(call.id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_contests", style="danger"))
            try:
                bot.edit_message_text(
                    "✏️ *أرسل وصف الجائزة:*\n\n"
                    "مثال: كود شحن لشبكة زين، أو رصيد خارجي، أو هدية مادية...\n"
                    "هذا الوصف سيظهر للفائز عند الإعلان عن نتيجة السحب.",
                    chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
                )
            except Exception:
                bot.send_message(
                    chat_id,
                    "✏️ *أرسل وصف الجائزة:*",
                    reply_markup=keyboard, parse_mode="Markdown"
                )

        elif call.data.startswith("claim_prize_"):
            contest_id = int(call.data.replace("claim_prize_", ""))
            c = db.get_contest(contest_id)
            if not c:
                safe_answer_callback_query(call.id, "المسابقة غير موجودة!", show_alert=True)
                return
            if c.get('winner_user_id') != user_id:
                safe_answer_callback_query(call.id, "أنت لست الفائز في هذه المسابقة!", show_alert=True)
                return
            prize_code = c.get('winner_prize_code') or ''
            prize_label = _prize_label(c)
            winner_info = db.get_user(user_id)
            winner_name = (f"@{winner_info['username']}" if winner_info and winner_info['username']
                           else (winner_info['first_name'] if winner_info else f"ID {user_id}"))
            claim_text_user = (
                f"📩 *تم إرسال طلب مطالبتك بالجائزة!*\n\n"
                f"📌 رقم المسابقة: *#{contest_id}*\n"
                f"🏷 اسم المسابقة: {md_escape(c['name'])}\n"
                f"🎁 الجائزة: *{md_escape(prize_label)}*\n"
                f"🔑 كودك: `{prize_code}`\n\n"
                f"تم إرسال طلبك للمالك.\n"
                f"سيتواصل معك قريباً لتسليم الجائزة بعد التحقق من الكود."
            )
            claim_text_owner = (
                f"📩 *مطالبة بجائزة مسابقة!*\n\n"
                f"📌 رقم المسابقة: *#{contest_id}*\n"
                f"🏷 اسم المسابقة: {md_escape(c['name'])}\n"
                f"👤 الفائز: {md_escape(winner_name)} (ID: `{user_id}`)\n"
                f"🎁 الجائزة: *{md_escape(prize_label)}*\n"
                f"🔑 كود الجائزة: `{prize_code}`\n\n"
                f"الفائز يطالب بجائزته — تواصل معه وتحقق من الكود ثم سلّم الجائزة."
            )
            safe_answer_callback_query(call.id, "✅ تم إرسال طلب المطالبة!")
            try:
                bot.send_message(chat_id, claim_text_user, parse_mode="Markdown")
            except Exception:
                pass
            try:
                bot.send_message(OWNER_ID, claim_text_owner, parse_mode="Markdown")
            except Exception:
                pass


        elif call.data == "admin_set_listing_fee":
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            safe_answer_callback_query(call.id)
            try:
                cur_lf2 = db.conn.cursor()
                cur_lf2.execute("SELECT value FROM bot_settings WHERE key='listing_fee'")
                lf_row2 = cur_lf2.fetchone()
                current_fee = float(lf_row2[0]) if lf_row2 else 0.01
            except Exception:
                current_fee = 0.01
            db.set_user_state(user_id, "admin_setting_listing_fee")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("🔹 0.01$", callback_data="set_lf_0.01", style="primary"),
                types.InlineKeyboardButton("🔹 0.05$", callback_data="set_lf_0.05", style="primary"),
                types.InlineKeyboardButton("🔹 0.10$", callback_data="set_lf_0.10", style="primary")
            )
            keyboard.row(
                types.InlineKeyboardButton("🔹 0.25$", callback_data="set_lf_0.25", style="primary"),
                types.InlineKeyboardButton("🔹 0.50$", callback_data="set_lf_0.50", style="primary"),
                types.InlineKeyboardButton("🔹 1.00$", callback_data="set_lf_1.00", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.edit_message_text(
                f"💲 {hb('رسوم نشر المزاد')}\n\n"
                f"الرسوم الحالية: {hb(f'{current_fee:.3f}$')}\n\n"
                "اختر قيمة من الأزرار أو أرسل رقماً (0 - 10):",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        elif call.data.startswith("set_lf_"):
            if user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "للمالك فقط!")
                return
            try:
                fee_val = float(call.data.replace("set_lf_", ""))
                cur_lf3 = db.conn.cursor()
                cur_lf3.execute("INSERT OR REPLACE INTO bot_settings (key,value) VALUES ('listing_fee',?)", (str(fee_val),))
                db.conn.commit()
                db.clear_user_state(user_id)
                safe_answer_callback_query(call.id, f"✅ رسوم النشر: {fee_val:.3f}$")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.edit_message_text(
                    f"✅ تم تحديث رسوم النشر إلى {hb(f'{fee_val:.3f}$')}\n\nستُطبق على المزادات الجديدة.",
                    chat_id, message_id,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception:
                safe_answer_callback_query(call.id, "خطأ!")

        # ============================================================
        # ميزات جديدة — بحث المزادات
        # ============================================================
        elif call.data == "search_auctions":
            safe_answer_callback_query(call.id)
            db.set_user_state(user_id, "searching_auctions")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(
                f"🔍 {hb('البحث عن مزاد')}\n\n"
                "أرسل جزء من اسم المزاد أو المعرّف (@username):\n\n"
                "مثال: t.me/example أو @username أو كلمة من الاسم",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        # ============================================================
        # تمديد المزاد من قبل البائع
        # ============================================================
        elif call.data.startswith("extend_auction_"):
            auction_id = call.data.replace("extend_auction_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "المزاد غير موجود!", show_alert=True)
                return
            if auction_info['user_id'] != user_id and user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا مزادك فقط!", show_alert=True)
                return
            if auction_info['status'] != 'active':
                safe_answer_callback_query(call.id, "المزاد غير نشط!", show_alert=True)
                return
            balance = db.get_balance(user_id)
            # رسوم التمديد: 0.05$ لكل 24 ساعة إضافية
            EXTEND_FEE_PER_24H = 0.05
            safe_answer_callback_query(call.id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton(f"24 ساعة — {EXTEND_FEE_PER_24H:.2f}$", callback_data=f"do_extend_{auction_id}_24", style="primary"),
                types.InlineKeyboardButton(f"48 ساعة — {EXTEND_FEE_PER_24H*2:.2f}$", callback_data=f"do_extend_{auction_id}_48", style="primary")
            )
            keyboard.row(
                types.InlineKeyboardButton(f"72 ساعة — {EXTEND_FEE_PER_24H*3:.2f}$", callback_data=f"do_extend_{auction_id}_72", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"auction_details_{auction_id}", style="danger"))
            bot.edit_message_text(
                f"⏱ {hb('تمديد المزاد')}  {hc('#' + str(auction_id))}\n\n"
                f"رصيدك: {fmt_money(balance)}\n"
                f"رسوم التمديد: {EXTEND_FEE_PER_24H:.2f}$ لكل 24 ساعة\n\n"
                "اختر مدة التمديد:",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        elif call.data.startswith("do_extend_"):
            parts = call.data.replace("do_extend_", "").rsplit("_", 1)
            auction_id = parts[0]
            hours = int(parts[1])
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info or auction_info['status'] != 'active':
                safe_answer_callback_query(call.id, "المزاد غير نشط!", show_alert=True)
                return
            if auction_info['user_id'] != user_id and user_id != OWNER_ID:
                safe_answer_callback_query(call.id, "هذا مزادك فقط!", show_alert=True)
                return
            EXTEND_FEE_PER_24H = 0.05
            fee = EXTEND_FEE_PER_24H * (hours / 24)
            balance = db.get_balance(user_id)
            if balance < fee:
                safe_answer_callback_query(call.id, f"رصيدك غير كافٍ! المطلوب: {fee:.2f}$", show_alert=True)
                return
            # خصم الرسوم وتمديد المزاد
            db.update_balance(user_id, -fee)
            db.add_transaction(user_id, -fee, "commission", f"رسوم تمديد مزاد #{auction_id} — {hours}h")
            db.add_revenue(auction_id, fee, "extension_fee")
            with db._lock:
                c = db.conn.cursor()
                c.execute(
                    f"UPDATE auctions SET ends_at = datetime(ends_at, '+{hours} hours') WHERE auction_id=? AND status='active'",
                    (auction_id,)
                )
                db.conn.commit()
            safe_answer_callback_query(call.id, f"✅ تم تمديد المزاد {hours} ساعة!")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 تفاصيل المزاد", callback_data=f"auction_details_{auction_id}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(
                f"✅ {hb('تم تمديد المزاد!')}\n\n"
                f"المزاد: {hc('#' + str(auction_id))}\n"
                f"التمديد: {hours} ساعة\n"
                f"الرسوم: {fmt_money(fee)}\n"
                f"رصيدك الجديد: {fmt_money(db.get_balance(user_id))}",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        # ============================================================
        # إعادة نشر مزاد منتهي
        # ============================================================
        elif call.data.startswith("reauction_"):
            auction_id = call.data.replace("reauction_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                safe_answer_callback_query(call.id, "المزاد غير موجود!", show_alert=True)
                return
            if auction_info['user_id'] != user_id:
                safe_answer_callback_query(call.id, "هذا مزادك فقط!", show_alert=True)
                return
            if auction_info['status'] not in ('expired', 'rejected'):
                safe_answer_callback_query(call.id, "يمكن إعادة نشر المزادات المنتهية أو المرفوضة فقط!", show_alert=True)
                return
            safe_answer_callback_query(call.id)
            balance = db.get_balance(user_id)
            starting_price = auction_info.get('starting_price', 0.0)
            listing_fee = 0.01
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✅ تأكيد إعادة النشر", callback_data=f"confirm_reauction_{auction_id}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="my_auctions", style="danger"))
            bot.edit_message_text(
                f"🔄 {hb('إعادة نشر المزاد')}\n\n"
                f"📦 {html_escape(auction_info['title'])}\n"
                f"🎯 {html_escape(auction_info['target'])}\n"
                f"💰 سعر البدء: {fmt_money(starting_price)}\n"
                f"📋 رسوم النشر: {fmt_money(listing_fee)}\n"
                f"💵 رصيدك: {fmt_money(balance)}\n\n"
                f"سيُعاد نشر المزاد بنفس البيانات للموافقة.",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        elif call.data.startswith("confirm_reauction_"):
            auction_id = call.data.replace("confirm_reauction_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info or auction_info['user_id'] != user_id:
                safe_answer_callback_query(call.id, "خطأ!", show_alert=True)
                return
            balance = db.get_balance(user_id)
            starting_price = auction_info.get('starting_price', 0.0)
            listing_fee = 0.01
            total_deduct = starting_price + listing_fee
            if balance < total_deduct:
                safe_answer_callback_query(call.id, f"رصيدك غير كافٍ! المطلوب: {total_deduct:.2f}$", show_alert=True)
                return
            # إنشاء مزاد جديد بنفس البيانات
            new_auction_id = generate_auction_id()
            duration = db.get_auction_duration()
            with db._lock:
                c = db.conn.cursor()
                c.execute(
                    """INSERT INTO auctions (auction_id, user_id, auction_type, title, target, description,
                    starting_price, current_price, status, duration_hours, platform, is_urgent)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (new_auction_id, user_id, auction_info['auction_type'], auction_info['title'],
                     auction_info['target'], auction_info.get('description', ''),
                     starting_price, starting_price, 'pending', duration,
                     auction_info.get('platform', ''), auction_info.get('is_urgent', 0))
                )
                db.conn.commit()
            # خصم الرسوم
            if starting_price > 0:
                db.update_balance(user_id, -starting_price)
                db.add_transaction(user_id, -starting_price, "auction_bid", f"سعر بدء مزاد جديد #{new_auction_id}")
            db.update_balance(user_id, -listing_fee)
            db.add_transaction(user_id, -listing_fee, "commission", f"رسوم نشر مزاد #{new_auction_id}")
            safe_answer_callback_query(call.id, "✅ تم إرسال المزاد للمراجعة!")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📦 مزاداتي", callback_data="my_auctions", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(
                f"✅ {hb('تم إرسال المزاد للمراجعة!')}\n\n"
                f"رقم المزاد الجديد: {hc('#' + str(new_auction_id))}\n"
                f"سيتم نشره بعد موافقة الإدارة.",
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            # إشعار المالك
            try:
                u = db.get_user(user_id)
                name = f"@{u['username']}" if u and u['username'] else str(user_id)
                bot.send_message(
                    OWNER_ID,
                    f"📋 *مزاد معاد نشره للمراجعة*\n\n"
                    f"المستخدم: {name} ({user_id})\n"
                    f"المزاد الجديد: #{new_auction_id}\n"
                    f"أصل المزاد: #{auction_id}\n"
                    f"النوع: {AUCTION_TYPES.get(auction_info['auction_type'], '')}\n"
                    f"الهدف: {auction_info['target']}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        # ============================================================
        # قائمة أفضل البائعين Leaderboard
        # ============================================================
        elif call.data == "top_sellers":
            safe_answer_callback_query(call.id)
            cursor_lb = db.conn.cursor()
            cursor_lb.execute("""
                SELECT a.user_id, u.username, u.first_name,
                    COUNT(DISTINCT a.auction_id) as sold_count,
                    COALESCE(AVG(sr.rating), 0) as avg_rating,
                    COUNT(sr.rating_id) as rating_count
                FROM auctions a
                LEFT JOIN users u ON a.user_id = u.user_id
                LEFT JOIN seller_ratings sr ON a.user_id = sr.seller_id
                WHERE a.status = 'sold'
                GROUP BY a.user_id
                ORDER BY avg_rating DESC, sold_count DESC
                LIMIT 10
            """)
            rows = cursor_lb.fetchall()
            if not rows:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                bot.edit_message_text("لا توجد بيانات بعد.", chat_id, message_id, reply_markup=keyboard)
                return
            medals = ["🥇", "🥈", "🥉"]
            lines = [f"🏆 {hb('أفضل البائعين')}\n"]
            for i, row in enumerate(rows):
                uid, uname, fname, sold_count, avg_rating, rating_count = row
                medal = medals[i] if i < 3 else f"{i+1}."
                name = f"@{uname}" if uname else (fname or f"ID {uid}")
                stars = "⭐" * round(avg_rating) if avg_rating > 0 else "—"
                rating_str = f"{avg_rating:.1f}/5 ({rating_count})" if rating_count > 0 else "لا تقييمات"
                lines.append(f"{medal} {html_escape(name)}\n   مبيعات: {sold_count} | التقييم: {stars} {rating_str}")
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📋 عرض المزادات", callback_data="show_auctions", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text(
                "\n".join(lines),
                chat_id, message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        # ============================================================
        # سجل العمليات المُصنَّف — عرض مُقسَّم حسب نوع العملية مع تصفّح صفحات 
        # ============================================================
        elif call.data.startswith("wallet_history_cat_"):
            safe_answer_callback_query(call.id)
            rest = call.data.replace("wallet_history_cat_", "")
            cat_id, page_str = rest.rsplit("_", 1)
            try:
                page = int(page_str)
            except ValueError:
                page = 0
            PER_PAGE = 10
            offset = page * PER_PAGE

            cat_map = {c[0]: (c[1], c[2]) for c in TX_CATEGORIES}
            cursor_wh = db.conn.cursor()
            if cat_id == "all":
                cat_label = "📋 الكل"
                cursor_wh.execute(
                    "SELECT amount, type, created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (user_id, PER_PAGE + 1, offset)
                )
            else:
                cat_label, cat_types = cat_map.get(cat_id, ("📋 العمليات", []))
                placeholders = ",".join("?" * len(cat_types))
                cursor_wh.execute(
                    f"SELECT amount, type, created_at FROM transactions WHERE user_id=? AND type IN ({placeholders}) ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (user_id, *cat_types, PER_PAGE + 1, offset)
                )
            rows_wh = cursor_wh.fetchall()
            has_next = len(rows_wh) > PER_PAGE
            txs = rows_wh[:PER_PAGE]

            if not txs:
                if page > 0:
                    safe_answer_callback_query(call.id, "لا توجد عمليات أخرى!", show_alert=True)
                    return
                text = f"{DIVIDER}\n{hb(cat_label)}\n{DIVIDER}\n\nلا توجد عمليات في هذا التصنيف."
            else:
                lines = [f"{DIVIDER}\n{hb(cat_label)} — {hi(f'صفحة {page+1}')}\n{DIVIDER}\n"]
                for amount, ttype, created in txs:
                    sign = "+" if amount > 0 else ""
                    label = TX_TYPE_LABELS.get(ttype, ttype)
                    date = str(created).replace('T', ' ')[:16]
                    lines.append(f"🔹 {html_escape(label)}\n{sign}{amount:.2f}$ | {html_escape(date)}\n")
                text = "\n".join(lines)

            keyboard = types.InlineKeyboardMarkup()
            nav_row = []
            if page > 0:
                nav_row.append(types.InlineKeyboardButton("◀ السابق", callback_data=f"wallet_history_cat_{cat_id}_{page-1}", style="primary"))
            if has_next:
                nav_row.append(types.InlineKeyboardButton("التالي ▶", callback_data=f"wallet_history_cat_{cat_id}_{page+1}", style="primary"))
            if nav_row:
                keyboard.row(*nav_row)
            keyboard.row(types.InlineKeyboardButton("🔖 التصنيفات", callback_data="wallet_history", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع للمحفظة", callback_data="wallet", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        # ============================================================
        # إشعار المتابعين عند المزايدة — معالج داخلي (يُستدعى من add_bid)
        # ============================================================
        elif call.data == "top_sellers_leaderboard":
            # إعادة توجيه
            safe_answer_callback_query(call.id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏆 أفضل البائعين", callback_data="top_sellers", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.edit_message_text("اختر:", chat_id, message_id, reply_markup=keyboard)

        # ============================================================
        # الـ Leaderboard في الكيبورد الرئيسي
        # ============================================================
        elif call.data == "about_bot":
            safe_answer_callback_query(call.id)
            duration = db.get_auction_duration()
            active_count = len(db.get_active_auctions())
            text = (
                f"ℹ️ {hb('عن المنصة')}\n\n"
                f"{DIVIDER}\n"
                f"🏷 {hb('منصة المزادات')} هي الوجهة الأولى لبيع وشراء:\n"
                f"• معرفات تيليجرام (@username)\n"
                f"• قنوات ومجموعات تيليجرام\n"
                f"• بوتات تيليجرام\n"
                f"• هدايا تيليجرام الرقمية\n\n"
                f"{DIVIDER}\n"
                f"⚙️ {hb('كيف تعمل المنصة؟')}\n\n"
                f"1️⃣ البائع ينشر مزاده ويحدد سعر البداية\n"
                f"2️⃣ المزاد يُراجع من الإدارة ثم يُنشر في القنوات\n"
                f"3️⃣ المزايدون يتنافسون لمدة {duration} ساعة\n"
                f"4️⃣ الفائز يتواصل مع البائع لاستلام المنتج\n\n"
                f"{DIVIDER}\n"
                f"💰 {hb('الرسوم والعمولات')}\n\n"
                f"• رسوم نشر المزاد: 0.01$\n"
                f"• عمولة البيع: {COMMISSION_RATE*100:.1f}% من سعر البيع النهائي\n"
                f"• مزاد عاجل (ساعة): عمولة {URGENT_COMMISSION_RATE*100:.0f}%\n"
                f"• عمولة التحويل بين المستخدمين: {TRANSFER_COMMISSION_RATE*100:.0f}%\n\n"
                f"{DIVIDER}\n"
                f"🛡 {hb('الضمانات')}\n\n"
                f"• إذا لم يُسلَّم المنتج: إبلاغ فوري للإدارة\n"
                f"• إذا خسرت المزايدة: يُعاد رصيدك فوراً\n"
                f"• إذا لم يأتِ مزايد: يُعاد سعر البداية للبائع\n\n"
                f"📊 المزادات النشطة حالياً: {hb(str(active_count))}"
            )
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("📋 عرض المزادات", callback_data="show_auctions", style="primary"),
                types.InlineKeyboardButton("📜 القوانين", callback_data="rules", style="primary")
            )
            keyboard.row(types.InlineKeyboardButton("🏆 أفضل البائعين", callback_data="top_sellers", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")

        else:
            logger.warning(f"Unknown callback data: {call.data}")
            try:
                safe_answer_callback_query(call.id, "زر غير معروف!")
            except Exception:
                pass
    except Exception as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str or "message to edit not found" in err_str:
            try:
                safe_answer_callback_query(call.id)
            except Exception:
                pass
        else:
            tb = traceback.format_exc()
            logger.error(f"Error handling callback '{call.data}': {e}\n{tb}")
            try:
                safe_answer_callback_query(call.id, "حدث خطأ! حاول مرة أخرى.")
            except Exception:
                pass
            notify_owner_button_error(call, e, user_id)

def get_bid_rank(auction_id, user_id):
    bids = db.get_auction_bids(auction_id)
    sorted_bids = sorted(bids, key=lambda x: x['amount'], reverse=True)
    for i, bid in enumerate(sorted_bids, 1):
        if bid['user_id'] == user_id:
            if i == 1:
                return "المركز الأول"
            elif i == 2:
                return "المركز الثاني"
            elif i == 3:
                return "المركز الثالث"
            else:
                return f"المركز {i}"
    return "لم يتم العثور"

@bot.message_handler(content_types=['sticker'], func=lambda message: message.chat.type == 'private')
def handle_admin_sticker_upload(message):
    """يستقبل الملصق الذي يرسله الأدمن لربطه بمناسبة معينة (فوز، مزاد جديد...)"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id != OWNER_ID:
        return
    user_state = db.get_user_state(user_id)
    if not user_state or user_state.get('state') != 'admin_waiting_sticker':
        return
    data = user_state.get('data', {}) or {}
    event_type = data.get('event_type')
    if not event_type:
        bot.send_message(chat_id, "حدث خطأ، حاول مجدداً من لوحة الإدارة.")
        db.clear_user_state(user_id)
        return
    file_id = message.sticker.file_id
    ok, _ = db.add_sticker(event_type, file_id, user_id)
    db.clear_user_state(user_id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("🔙 رجوع لإدارة الملصقات", callback_data=f"admin_sticker_event_{event_type}", style="primary"))
    if ok:
        bot.send_message(chat_id, "✅ تم إضافة الملصق بنجاح لهذه المناسبة.", reply_markup=keyboard)
    else:
        bot.send_message(chat_id, "فشل حفظ الملصق، حاول مجدداً.", reply_markup=keyboard)


@bot.message_handler(func=lambda message: message.chat.type == 'private')
def handle_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    # فحص الحظر 
    if user_id != OWNER_ID and db.is_banned(user_id):
        bot.send_message(chat_id, "حسابك محظور من استخدام البوت.")
        return
    if user_id != OWNER_ID and not (db.is_agent(user_id) or db.is_broker(user_id)):
        subscribed, result = check_subscription(user_id)
        if not subscribed:
            channels_text, keyboard = result
            bot.send_message(chat_id, channels_text, reply_markup=keyboard)
            return
    is_new_user = db.add_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    if is_new_user:
        try:
            bot.send_message(OWNER_ID, f"مستخدم جديد انضم للبوت!\n\n المستخدم: {message.from_user.first_name} {f'({message.from_user.last_name})' if message.from_user.last_name else ''}\n الأيدي: {user_id}\n المعرف: @{message.from_user.username if message.from_user.username else 'بدون معرف'}\n التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n العدد الإجمالي للمستخدمين الآن: {len(db.get_all_users())}")
            db.mark_user_notified(user_id)
        except Exception as e:
            logger.error(f"Error notifying owner: {e}")
    user_state = db.get_user_state(user_id)

    # معالجة أزرار ReplyKeyboard للتحقق 
    if message.text and message.text.strip() in ["إلغاء", "cancel", "Cancel"]:
        if user_state and user_state['state'] in ["waiting_phone_for_auction", "waiting_location_for_auction"]:
            db.clear_user_state(user_id)
            keyboard = create_main_menu_keyboard(user_id)
            bot.send_message(chat_id, "تم الإلغاء.", reply_markup=types.ReplyKeyboardRemove())
            bot.send_message(chat_id, "اختر من القائمة:", reply_markup=keyboard)
            return

    if not user_state:
        text = message.text.strip().lower() if message.text else ""

        # ردود ذكية على النص الحر 
        INTENTS = {
            # رصيد
            "balance": ["رصيد", "balance", "كم رصيدي", "كم عندي", "ميزاني", "حسابي"],
            # شحن
            "charge": ["شحن", "اشحن", "charge", "ضيف رصيد", "اضافة رصيد", "بنس", "binance", "نجوم", "stars", "اسياسيل", "asiacell"],
            # تحويل
            "transfer_money": ["تحويل", "حول", "ارسل رصيد", "بعث", "transfer", "ارسال"],
            # كود
            "use_code": ["كود", "code", "استخدم كود", "ادخل كود", "عندي كود"],
            # عجلة
            "lucky_wheel": ["عجلة", "wheel", "حظ", "لف", "دور", "spin"],
            # مزادات
            "show_auctions": ["مزاد", "مزادات", "auction", "شوف", "عرض", "شراء", "بيع"],
            # نشر مزاد
            "new_auction": ["نشر", "بيع", "اضف مزاد", "مزاد جديد", "إنشاء مزاد"],
            # مزاداتي
            "my_auctions": ["مزاداتي", "مزاداتك", "اعمالي", "نشراتي"],
            # مزايداتي
            "my_bids": ["مزايداتي", "مزايداتك", "مزايدتي"],
            # بحث
            "search_auctions": ["بحث", "search", "دور", "فتش", "ابحث", "أبحث"],
            # محفظة
            "wallet": ["محفظة", "wallet", "احصائيات", "سجل", "عمليات"],
            # مساعدة
            "help": ["مساعدة", "help", "ساعدني", "كيف", "ايش", "وش", "شلون", "كيفية"],
            # قوانين
            "rules": ["قوانين", "rules", "شروط", "سياسة"],
        }

        QUICK_REPLIES = {
            "balance": lambda: (
                f"رصيدك الحالي: {db.get_balance(user_id):.2f}$",
                types.InlineKeyboardMarkup().row(
                    types.InlineKeyboardButton("📥 شحن رصيد", callback_data="charge", style="primary"),
                    types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary")
                )
            ),
            "help": lambda: (
                "يمكنني مساعدتك في:\n\n"
                "رصيدي — لمعرفة رصيدك\n"
                "شحن — لشحن رصيدك\n"
                "تحويل — لتحويل رصيد لمستخدم\n"
                "كود — لاستخدام كود شحن او تحويل\n"
                "عجلة — لتدوير عجلة الحظ\n"
                "مزادات — لعرض المزادات\n"
                "محفظة — لاحصائياتك الكاملة\n\n"
                "او استخدم القائمة:",
                create_main_menu_keyboard(user_id)
            ),
        }

        # البحث عن Intent 
        matched = None
        for intent, keywords in INTENTS.items():
            if any(kw in text for kw in keywords):
                matched = intent
                break

        if matched == "balance":
            reply_text, reply_kb = QUICK_REPLIES["balance"]()
            bot.send_message(chat_id, reply_text, reply_markup=reply_kb)
        elif matched == "help":
            reply_text, reply_kb = QUICK_REPLIES["help"]()
            bot.send_message(chat_id, reply_text, reply_markup=reply_kb)
        elif matched in ["charge", "transfer_money", "use_code", "lucky_wheel",
                         "show_auctions", "new_auction", "my_auctions", "my_bids",
                         "wallet", "rules", "search_auctions"]:
            # فتح الصفحة المقابلة مباشرة
            ACTION_MSGS = {
                "charge": "فتح صفحة الشحن:",
                "transfer_money":"فتح صفحة التحويل:",
                "use_code": "فتح صفحة استخدام الكود:",
                "lucky_wheel": "فتح عجلة الحظ:",
                "show_auctions": "فتح قائمة المزادات:",
                "new_auction": "فتح نشر مزاد جديد:",
                "my_auctions": "فتح مزاداتك:",
                "my_bids": "فتح مزايداتك:",
                "wallet": "فتح المحفظة:",
                "rules": "فتح القوانين:",
                "search_auctions": "فتح البحث:",
            }
            shortcut_kb = types.InlineKeyboardMarkup()
            shortcut_kb.row(types.InlineKeyboardButton(ACTION_MSGS[matched].replace(":", "").replace("فتح ", ""), callback_data=matched, style="primary"))
            shortcut_kb.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.send_message(chat_id, ACTION_MSGS[matched], reply_markup=shortcut_kb)
        else:
            # لا يوجد تطابق — القائمة مع رسالة لطيفة
            balance = db.get_balance(user_id)
            keyboard = create_main_menu_keyboard(user_id)
            bot.send_message(
                chat_id,
                f"مرحباً {message.from_user.first_name}!\n\n"
                f"رصيدك: {balance:.2f}$\n\n"
                f"اكتب 'مساعدة' لمعرفة ما يمكنني فعله، او اختر من القائمة:",
                reply_markup=keyboard
            )
        return
    state = user_state['state']
    try:
        if state in ["waiting_username_info", "waiting_channel_info", "waiting_group_info", "waiting_bot_info", "waiting_gift_info"]:
            auction_type = None
            platform = None
            if state == "waiting_username_info":
                auction_type = "username"
            elif state == "waiting_channel_info":
                auction_type = "channel"
            elif state == "waiting_group_info":
                auction_type = "group"
            elif state == "waiting_bot_info":
                auction_type = "bot"
            elif state == "waiting_gift_info":
                auction_type = "gift"
            elif state.startswith("waiting_username_"):
                auction_type = "username"
            if not auction_type:
                bot.send_message(chat_id, "خطأ في نوع المزاد!")
                db.clear_user_state(user_id)
                return
            target = message.text.strip()

            # تطبيع الرابط وقبول الأشكال المختصرة 
            if auction_type == "gift":
                target = normalize_telegram_link(target)
                if not is_valid_telegram_link(target):
                    bot.send_message(
                        chat_id,
                        "رابط الهدية غير صالح!\n\n"
                        "الأشكال المقبولة:\n"
                        "• t.me/gift/123456\n"
                        "• https://t.me/gift/abc\n"
                        "• t.me/nft/BigYear-3605",
                        reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary"))
                    )
                    return
            else:
                if auction_type == "username":
                    # قبول username بدون @ أو مع @
                    raw_target = target.lstrip('@')
                    if not is_valid_username(raw_target):
                        bot.send_message(chat_id, "المعرف غير صالح!\n\nأرسل معرفاً صحيحاً مثال: username", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary")))
                        return
                    target = f"@{raw_target}"
                else:
                    # قناة / مجموعة / بوت — قبول t.me/user أو @user أو username
                    normalized = normalize_telegram_link(target)
                    if normalized.startswith('https://t.me/'):
                        if not is_valid_telegram_link(normalized):
                            bot.send_message(chat_id, "الرابط غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary")))
                            return
                        # استخرج المعرف من الرابط
                        part = normalized.replace('https://t.me/', '').split('/')[0].split('?')[0]
                        if part and not part.startswith('+') and part != 'joinchat':
                            target = f"@{part}"
                        else:
                            target = normalized # رابط خاص
                    else:
                        raw_target = target.lstrip('@')
                        if is_valid_username(raw_target):
                            target = f"@{raw_target}"
                        else:
                            bot.send_message(chat_id, "المعرف غير صالح!\n\nأرسل معرفاً أو رابطاً صحيحاً\nمثال: username أو t.me/username", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary")))
                            return

            # ===== التحقق من الملكية للقنوات والمجموعات (المالك فقط) =====
            if auction_type in ("channel", "group"):
                verify_msg = bot.send_message(
                    chat_id,
                    f"جاري التحقق من ملكيتك لـ {target}...\n\n"
                    f"ملاحظة: يُقبل فقط **مالك** القناة/المجموعة، لا يُقبل الأدمن.\n"
                    f"تأكد من أن البوت مضاف كمشرف في القناة/المجموعة."
                )
                is_owner, verify_result = verify_channel_owner(target, user_id)
                try:
                    bot.delete_message(chat_id, verify_msg.message_id)
                except Exception:
                    pass
                if not is_owner:
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data=f"type_{auction_type}", style="primary"))
                    keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary"))
                    bot.send_message(
                        chat_id,
                        f"فشل التحقق من الملكية\n\n{verify_result}",
                        reply_markup=keyboard
                    )
                    return
                # تأكيد الملكية — creator فقط
                bot.send_message(
                    chat_id,
                    f"تم التحقق من ملكيتك\n\n"
                    f"القناة/المجموعة: {verify_result['chat'].title}\n"
                    f"صلاحيتك: مالك\n\n"
                    f"يمكنك المتابعة لرفع المزاد."
                )
            # =================================================

            auction_id = generate_auction_id()
            auction_data = {"auction_type": auction_type, "target": target, "platform": platform, "auction_id": auction_id}
            db.set_user_state(user_id, "waiting_starting_price", auction_data)
            balance = db.get_balance(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_auction", style="danger"))
            bot.send_message(
                chat_id,
                f" *أدخل سعر بدء المزاد*\n\n"
                f"رصيدك الحالي: {balance:.2f}$\n\n"
                f"أرسل السعر الابتدائي للمزاد بالدولار ($), أو اكتب إلغاء للتراجع:",
                reply_markup=types.ForceReply(selective=True),
                parse_mode="Markdown"
            )
        elif state == "waiting_private_link":
            private_link = message.text.strip()
            if not is_valid_telegram_link(private_link):
                bot.send_message(chat_id, "رابط غير صالح!\n\nرجاءً أرسل رابط تيليجرام صحيح", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary")))
                return
            auction_id = generate_auction_id()
            link_auction_type = user_state['data'].get('auction_type', 'channel') if user_state.get('data') else 'channel'

            if link_auction_type in ("channel", "group"):
                is_invite_link = (
                    re.search(r't\.me/\+', private_link) or
                    'joinchat' in private_link
                )
                if is_invite_link:
                    # رابط دعوة خاص — لا يمكن get_chat عليه مباشرة
                    # نحتاج الـ chat_id الحقيقي: نطلب forward رسالة من القناة
                    auction_data = {"auction_type": link_auction_type, "target": private_link, "auction_id": auction_id}
                    db.set_user_state(user_id, "waiting_forward_verify", auction_data)
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="new_auction", style="danger"))
                    bot.send_message(
                        chat_id,
                        f" *التحقق من ملكية الرابط الخاص*\n\n"
                        f"رابط الدعوة الخاص لا يمكن التحقق منه مباشرة.\n\n"
                        f"للتحقق من ملكيتك، قم بما يلي:\n"
                        f"1⃣ افتح القناة/المجموعة\n"
                        f"2⃣ اختر أي رسالة فيها\n"
                        f"3⃣ اضغط forward (إعادة توجيه) وأرسلها *هنا في البوت*\n\n"
                        f"يجب أن تكون مشرفاً أو مالكاً فيها حتى يتم قبول المزاد.",
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )
                    return
                else:
                    # رابط عادي — تحقق مباشر
                    verify_msg = bot.send_message(
                        chat_id,
                        f"جاري التحقق من ملكيتك...\n\n"
                        f"تأكد من أن البوت مضاف كمشرف في القناة/المجموعة."
                    )
                    is_owner, verify_result = verify_channel_owner(private_link, user_id)
                    try:
                        bot.delete_message(chat_id, verify_msg.message_id)
                    except Exception:
                        pass
                    if not is_owner:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data=f"type_{link_auction_type}", style="primary"))
                        keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary"))
                        bot.send_message(chat_id, f"فشل التحقق من الملكية\n\n{verify_result}", reply_markup=keyboard)
                        return
                    role_ar = "مالك" if verify_result['role'] == 'creator' else "مشرف"
                    bot.send_message(
                        chat_id,
                        f"تم التحقق من ملكيتك\n\n"
                        f"القناة/المجموعة: {verify_result['chat'].title}\n"
                        f"صلاحيتك: {role_ar}\n\n"
                        f"يمكنك المتابعة لرفع المزاد."
                    )

            auction_data = {"auction_type": link_auction_type, "target": private_link, "auction_id": auction_id}
            db.set_user_state(user_id, "waiting_starting_price", auction_data)
            balance = db.get_balance(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_auction", style="danger"))
            bot.send_message(
                chat_id,
                f" *أدخل سعر بدء المزاد*\n\n"
                f"رصيدك الحالي: {balance:.2f}$\n\n"
                f"أرسل السعر الابتدائي للمزاد بالدولار ($), أو اكتب إلغاء للتراجع:",
                reply_markup=types.ForceReply(selective=True),
                parse_mode="Markdown"
            )

        elif state == "waiting_forward_verify":
            # التحقق من ملكية القناة الخاصة عبر forward رسالة
            auction_data = user_state.get('data', {}) or {}
            private_link = auction_data.get('target', '')
            link_auction_type = auction_data.get('auction_type', 'channel')
            auction_id = auction_data.get('auction_id', generate_auction_id())

            # استخراج chat_id من الـ forward
            fwd_chat = None
            if message.forward_from_chat:
                fwd_chat = message.forward_from_chat
            elif message.forward_origin and hasattr(message.forward_origin, 'chat'):
                fwd_chat = message.forward_origin.chat

            if not fwd_chat:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="new_auction", style="danger"))
                bot.send_message(
                    chat_id,
                    "لم يتم اكتشاف forward من قناة أو مجموعة.\n\n"
                    "تأكد من أنك تضغط forward على رسالة من القناة/المجموعة وليس مجرد نسخ النص.\n\n"
                    "أرسل الـ forward مرة أخرى:",
                    reply_markup=keyboard
                )
                return

            fwd_id = fwd_chat.id

            # التحقق من صلاحية البوت في القناة
            try:
                bot_member = bot.get_chat_member(fwd_id, get_bot_info()['id'])
                if bot_member.status not in ('administrator', 'creator'):
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data=f"type_{link_auction_type}", style="primary"))
                    bot.send_message(
                        chat_id,
                        f"البوت موجود في {fwd_chat.title} لكنه ليس مشرفاً.\n\n"
                        f"ارفع صلاحية البوت إلى مشرف ثم أعد المحاولة.",
                        reply_markup=keyboard
                    )
                    return
            except Exception as e:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data=f"type_{link_auction_type}", style="primary"))
                bot.send_message(
                    chat_id,
                    f"البوت غير موجود في {fwd_chat.title}.\n\n"
                    f"أضف @{get_bot_info()['username']} كمشرف في القناة/المجموعة ثم أعد المحاولة.",
                    reply_markup=keyboard
                )
                return

            # التحقق من صلاحية المستخدم في القناة
            try:
                member = bot.get_chat_member(fwd_id, user_id)
            except Exception:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data=f"type_{link_auction_type}", style="primary"))
                bot.send_message(
                    chat_id,
                    f"تعذر التحقق من عضويتك في {fwd_chat.title}.\n\n"
                    f"تأكد من أنك عضو فيها.",
                    reply_markup=keyboard
                )
                return

            if member.status not in ('creator', 'administrator'):
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data="new_auction", style="primary"))
                bot.send_message(
                    chat_id,
                    f"أنت لست مالك أو مشرف في {fwd_chat.title}.\n\n"
                    f"فقط المالك أو المشرفون يمكنهم رفع مزاد على هذه القناة/المجموعة.",
                    reply_markup=keyboard
                )
                return

            role_ar = "مالك" if member.status == 'creator' else "مشرف"
            bot.send_message(
                chat_id,
                f"تم التحقق من ملكيتك\n\n"
                f"القناة/المجموعة: {fwd_chat.title}\n"
                f"الأيدي: {fwd_id}\n"
                f"صلاحيتك: {role_ar}\n\n"
                f"يمكنك المتابعة لرفع المزاد."
            )

            # تحديث الـ target بالأيدي الحقيقي (أكثر موثوقية من الرابط)
            auction_data['auction_id'] = auction_id
            db.set_user_state(user_id, "waiting_starting_price", auction_data)
            balance = db.get_balance(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_auction", style="danger"))
            bot.send_message(
                chat_id,
                f" *أدخل سعر بدء المزاد*\n\n"
                f"رصيدك الحالي: {balance:.2f}$\n\n"
                f"أرسل السعر الابتدائي للمزاد بالدولار ($), أو اكتب إلغاء للتراجع:",
                reply_markup=types.ForceReply(selective=True),
                parse_mode="Markdown"
            )

        elif state == "choosing_username_type":
            db.clear_user_state(user_id)
            keyboard = create_main_menu_keyboard(user_id)
            bot.send_message(chat_id, "يرجى اختيار نوع من الأزرار أعلاه", reply_markup=keyboard)
        elif state == "waiting_starting_price":
            try:
                starting_price = float(message.text.strip())
                if starting_price < 0:
                    bot.send_message(chat_id, "السعر يجب أن يكون صفر أو أكبر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_auction", style="danger")))
                    return
                balance = db.get_balance(user_id)
                if starting_price > 0 and balance < starting_price + 0.01:
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.row(types.InlineKeyboardButton("📥 شحن الرصيد", callback_data="charge", style="primary"), types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_auction", style="danger"))
                    bot.send_message(chat_id, f" *رصيدك غير كافٍ!*\n\nرصيدك: {balance:.2f}$\nالمطلوب (سعر البدء + عمولة): {starting_price + 0.01:.2f}$", reply_markup=keyboard, parse_mode="Markdown")
                    return
                # حفظ سعر البدء وانتقل لمرحلة اختيار نوع المزاد
                auction_data = user_state['data'] or {}
                auction_data['starting_price'] = starting_price
                auction_type = auction_data.get('auction_type', '')
                target = auction_data.get('target', '')
                auction_id = auction_data.get('auction_id', generate_auction_id())
                auction_data['auction_id'] = auction_id
                db.set_user_state(user_id, "waiting_auction_speed", auction_data)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton(
                    f"⚡ مزاد عاجل (ساعة واحدة، عمولة {URGENT_COMMISSION_RATE*100:.0f}%)",
                    callback_data="auction_speed_urgent", style="primary"))
                keyboard.row(types.InlineKeyboardButton(
                    f"🕐 مزاد عادي ({db.get_auction_duration()} ساعات، عمولة {COMMISSION_RATE*100:.1f}%)",
                    callback_data="auction_speed_normal", style="primary"))
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_auction", style="danger"))
                bot.send_message(
                    chat_id,
                    " *اختر نوع المزاد*\n\n"
                    "⚡ *عاجل*: يدوم ساعة واحدة فقط، مناسب لمن يريد بيع سريع. عمولة أعلى مقابل سرعة الانتشار.\n"
                    "🕐 *عادي*: المدة الافتراضية، عمولة أقل.",
                    reply_markup=keyboard, parse_mode="Markdown"
                )
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! أرسل رقماً صحيحاً مثل: 500 أو 1000.500", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_auction", style="danger")))
        elif state.startswith("waiting_bid_"):
            auction_id = state.replace("waiting_bid_", "")
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                bot.send_message(chat_id, "هذا المزاد لم يعد متاحاً!")
                db.clear_user_state(user_id)
                return
            # تحقق من انتهاء المزاد أولاً
            check_auction_ended(auction_id)
            # أعد قراءة بيانات المزاد بعد الفحص (الحالة قد تغيّرت)
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info or auction_info['status'] != 'active':
                bot.send_message(chat_id, "⏰ انتهى المزاد ولم تعد المزايدة متاحة!")
                db.clear_user_state(user_id)
                return
            try:
                bid_amount = float(message.text.strip())
                if bid_amount <= auction_info['current_price']:
                    bot.send_message(chat_id, f"يجب أن يكون سعر مزايدتك أعلى من السعر الحالي!\n\nالسعر الحالي: {auction_info['current_price']:.2f}$", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"auction_details_{auction_id}", style="primary")))
                    return
                success, msg = db.add_bid(auction_id, user_id, bid_amount)
                if not success:
                    bot.send_message(chat_id, msg, reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"auction_details_{auction_id}", style="primary")))
                    return
                db.clear_user_state(user_id)
                # إشعار صاحب المزاد عبر Queue
                try:
                    owner_name = f"@{message.from_user.username}" if message.from_user.username else f"مستخدم {user_id}"
                    queue_send(
                        auction_info['user_id'],
                        "\n".join([
                            f"🔔 {hb('مزايدة جديدة على مزادك!')}  {hc('#' + str(auction_id))}",
                            DIVIDER,
                            f"👤 {hb('المزايد:')} {html_escape(owner_name)}",
                            f"💰 {hb('المبلغ الجديد:')} {fmt_money(bid_amount)}",
                            f"📊 {hb('عدد المزايدات:')} {(auction_info['bids_count'] or 0) + 1}",
                        ]),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                # إشعار المالك العام عبر Queue (بدون flood)
                try:
                    queue_send(
                        OWNER_ID,
                        "\n".join([
                            f"🔔 {hb('مزايدة جديدة')}",
                            f"{hc('#' + str(auction_id))} — @{html_escape(message.from_user.username or user_id)} — {fmt_money(bid_amount)}",
                        ]),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                # إشعار المزايد السابق (outbid) بشكل واضح عبر Queue
                if auction_info['current_bidder'] and auction_info['current_bidder'] != user_id:
                    try:
                        bot_info = get_bot_info()
                        deep_link = f"https://t.me/{bot_info['username']}?start=auction_{auction_id}"
                        outbid_kb = types.InlineKeyboardMarkup()
                        outbid_kb.row(types.InlineKeyboardButton(
                            "🔹 زايد الآن قبل فوات الأوان!",
                            url=deep_link, style="primary"
                        ))
                        queue_send(
                            auction_info['current_bidder'],
                            "\n".join([
                                f"⚠️ {hb('تم تجاوز مزايدتك!')}",
                                DIVIDER,
                                f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                                f"📦 {hb('المنتج:')} {html_escape(auction_info.get('title', '') or '')}",
                                f"💰 {hb('السعر الجديد:')} {fmt_money(bid_amount)}",
                                DIVIDER,
                                "🔥 زايد الآن لاستعادة موقعك الأول!",
                            ]),
                            keyboard=outbid_kb,
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                # إشعار متابعي المزاد (Watchers) عبر Queue
                try:
                    watchers = db.get_auction_watchers(auction_id)
                    for watcher_id in watchers:
                        if watcher_id != user_id and watcher_id != auction_info['user_id']:
                            queue_send(
                                watcher_id,
                                "\n".join([
                                    f"👀 {hb('مزاد تتابعه تحرّك!')}",
                                    DIVIDER,
                                    f"{hc('#' + str(auction_id))} — {html_escape(auction_info.get('title','') or '')}",
                                    f"💰 {hb('السعر الجديد:')} {fmt_money(bid_amount)}",
                                ]),
                                parse_mode="HTML"
                            )
                except Exception:
                    pass
                user_bids = db.get_user_bids(user_id, auction_id)
                can_refund = len(user_bids) > 0
                is_watching_now = db.is_watching(auction_id, user_id)
                keyboard = create_auction_details_keyboard(
                    auction_id, user_id, can_refund,
                    buy_now_price=auction_info.get('buy_now_price', 0.0),
                    is_owner=False,
                    is_watching=is_watching_now
                )
                bot.send_message(
                    chat_id,
                    "\n".join([
                        f"✅ {hb('تمت المزايدة بنجاح!')}",
                        DIVIDER,
                        f"🆔 {hb('المزاد:')} {hc('#' + str(auction_id))}",
                        f"💰 {hb('مبلغك:')} {fmt_money(bid_amount)}",
                        f"👛 {hb('رصيدك الجديد:')} {fmt_money(db.get_balance(user_id))}",
                        f"🏅 {hb('رتبتك:')} {html_escape(get_bid_rank(auction_id, user_id))}",
                    ]),
                    reply_markup=keyboard, parse_mode="HTML"
                )
                # ← تحديث رسائل القنوات بالسعر الجديد وأعلى 3 مزايدين
                update_auction_broadcast(auction_id)
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! أرسل رقماً صحيحاً.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"auction_details_{auction_id}", style="primary")))

        elif state == "waiting_asiacell_amount":
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "مبلغ غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_asiacell", style="danger")))
                    return
                db.set_user_state(user_id, "waiting_asiacell_proof", {"amount": amount})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_asiacell", style="danger"))
                bot.send_message(
                    chat_id,
                    f"💰 *شحن {amount:.2f}$ عبر أسياسيل*\n\n"
                    f"الآن أرسل صورة أو رقم العملية كإثبات للتحويل:",
                    reply_markup=keyboard, parse_mode="Markdown"
                )
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_asiacell", style="danger")))

        elif state == "waiting_asiacell_proof":
            proof = message.text.strip() if message.text else ""
            if message.photo:
                proof = f"[صورة] file_id:{message.photo[-1].file_id}"
            if not proof:
                bot.send_message(chat_id, "أرسل إثبات التحويل (نص أو صورة).")
                return
            charge_data = user_state.get('data', {}) or {}
            amount = charge_data.get('amount', 0)
            ok, req_id = db.add_charge_request(user_id, amount, "أسياسيل", proof)
            db.clear_user_state(user_id)
            if ok:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
                bot.send_message(
                    chat_id,
                    f"✅ *تم إرسال طلب الشحن #{req_id}*\n\n"
                    f"المبلغ: {amount:.2f}$\n"
                    f"الطريقة: أسياسيل\n\n"
                    f"سيتم مراجعته وإضافة الرصيد خلال وقت قصير.",
                    reply_markup=keyboard, parse_mode="Markdown"
                )
                try:
                    u = db.get_user(user_id)
                    name = f"@{u['username']}" if u and u['username'] else str(user_id)
                    keyboard_admin = types.InlineKeyboardMarkup()
                    keyboard_admin.row(
                        types.InlineKeyboardButton("✅ قبول", callback_data=f"approve_charge_{req_id}", style="primary"),
                        types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_charge_{req_id}", style="danger")
                    )
                    bot.send_message(
                        OWNER_ID,
                        f" *طلب شحن جديد #{req_id}*\n\n"
                        f"المستخدم: {name} (ID: {user_id})\n"
                        f"المبلغ: {amount:.2f}$\n"
                        f"الطريقة: أسياسيل\n"
                        f"الإثبات: {proof}",
                        reply_markup=keyboard_admin, parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                bot.send_message(chat_id, "حدث خطأ، حاول مجدداً.")

        elif state == "waiting_zaincash_amount":
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "مبلغ غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_zaincash", style="danger")))
                    return
                db.set_user_state(user_id, "waiting_zaincash_proof", {"amount": amount})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_zaincash", style="danger"))
                bot.send_message(
                    chat_id,
                    f"💰 *شحن {amount:.2f}$ عبر زين كاش*\n\n"
                    f"الآن أرسل صورة أو رقم العملية كإثبات للتحويل:",
                    reply_markup=keyboard, parse_mode="Markdown"
                )
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_zaincash", style="danger")))

        elif state == "waiting_zaincash_proof":
            proof = message.text.strip() if message.text else ""
            if message.photo:
                proof = f"[صورة] file_id:{message.photo[-1].file_id}"
            if not proof:
                bot.send_message(chat_id, "أرسل إثبات التحويل (نص أو صورة).")
                return
            charge_data = user_state.get('data', {}) or {}
            amount = charge_data.get('amount', 0)
            ok, req_id = db.add_charge_request(user_id, amount, "زين كاش", proof)
            db.clear_user_state(user_id)
            if ok:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
                bot.send_message(
                    chat_id,
                    f"✅ *تم إرسال طلب الشحن #{req_id}*\n\n"
                    f"المبلغ: {amount:.2f}$\n"
                    f"الطريقة: زين كاش\n\n"
                    f"سيتم مراجعته وإضافة الرصيد خلال وقت قصير.",
                    reply_markup=keyboard, parse_mode="Markdown"
                )
                try:
                    u = db.get_user(user_id)
                    name = f"@{u['username']}" if u and u['username'] else str(user_id)
                    keyboard_admin = types.InlineKeyboardMarkup()
                    keyboard_admin.row(
                        types.InlineKeyboardButton("✅ قبول", callback_data=f"approve_charge_{req_id}", style="primary"),
                        types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_charge_{req_id}", style="danger")
                    )
                    bot.send_message(
                        OWNER_ID,
                        f" *طلب شحن جديد #{req_id}*\n\n"
                        f"المستخدم: {name} (ID: {user_id})\n"
                        f"المبلغ: {amount:.2f}$\n"
                        f"الطريقة: زين كاش\n"
                        f"الإثبات: {proof}",
                        reply_markup=keyboard_admin, parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                bot.send_message(chat_id, "حدث خطأ، حاول مجدداً.")

        elif state == "waiting_kycard_amount":
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "مبلغ غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_kycard", style="danger")))
                    return
                db.set_user_state(user_id, "waiting_kycard_proof", {"amount": amount})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_kycard", style="danger"))
                bot.send_message(
                    chat_id,
                    f"💰 *شحن {amount:.2f}$ عبر كي كارد*\n\n"
                    f"الآن أرسل صورة أو رقم العملية كإثبات للتحويل:",
                    reply_markup=keyboard, parse_mode="Markdown"
                )
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="charge_kycard", style="danger")))

        elif state == "waiting_kycard_proof":
            proof = message.text.strip() if message.text else ""
            if message.photo:
                proof = f"[صورة] file_id:{message.photo[-1].file_id}"
            if not proof:
                bot.send_message(chat_id, "أرسل إثبات التحويل (نص أو صورة).")
                return
            charge_data = user_state.get('data', {}) or {}
            amount = charge_data.get('amount', 0)
            ok, req_id = db.add_charge_request(user_id, amount, "كي كارد", proof)
            db.clear_user_state(user_id)
            if ok:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
                bot.send_message(
                    chat_id,
                    f"✅ *تم إرسال طلب الشحن #{req_id}*\n\n"
                    f"المبلغ: {amount:.2f}$\n"
                    f"الطريقة: كي كارد\n\n"
                    f"سيتم مراجعته وإضافة الرصيد خلال وقت قصير.",
                    reply_markup=keyboard, parse_mode="Markdown"
                )
                try:
                    u = db.get_user(user_id)
                    name = f"@{u['username']}" if u and u['username'] else str(user_id)
                    keyboard_admin = types.InlineKeyboardMarkup()
                    keyboard_admin.row(
                        types.InlineKeyboardButton("✅ قبول", callback_data=f"approve_charge_{req_id}", style="primary"),
                        types.InlineKeyboardButton("❌ رفض", callback_data=f"reject_charge_{req_id}", style="danger")
                    )
                    bot.send_message(
                        OWNER_ID,
                        f" *طلب شحن جديد #{req_id}*\n\n"
                        f"المستخدم: {name} (ID: {user_id})\n"
                        f"المبلغ: {amount:.2f}$\n"
                        f"الطريقة: كي كارد\n"
                        f"الإثبات: {proof}",
                        reply_markup=keyboard_admin, parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                bot.send_message(chat_id, "حدث خطأ، حاول مجدداً.")

        elif state.startswith("waiting_charge_reject_reason_"):
            req_id = int(state.replace("waiting_charge_reject_reason_", ""))
            reason = message.text.strip() if message.text else "لم يُحدد سبب"
            db.clear_user_state(user_id)
            ok, result = db.reject_charge_request(req_id, reason)
            if ok:
                target_uid = result
                bot.send_message(chat_id, f"❌ تم رفض طلب الشحن #{req_id}.")
                try:
                    bot.send_message(
                        target_uid,
                        f"❌ *تم رفض طلب الشحن #{req_id}*\n\n"
                        f"السبب: {reason}\n\n"
                        f"إذا كان هناك خطأ، تواصل مع المالك.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                bot.send_message(chat_id, f"خطأ: {result}")

        elif state == "waiting_withdraw_amount":
            try:
                amount = float(message.text.strip().replace(",", ""))
                balance = db.get_balance(user_id)
                withdraw_data = (user_state.get('data') or {})
                method = withdraw_data.get('method', '')
                hint = withdraw_data.get('hint', 'تفاصيل الاستلام')
                cancel_kb = types.InlineKeyboardMarkup()
                cancel_kb.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="wallet", style="danger"))
                if amount < MIN_WITHDRAW:
                    bot.send_message(chat_id, f"❌ الحد الأدنى للسحب {MIN_WITHDRAW}$.", reply_markup=cancel_kb)
                    return
                if amount > balance:
                    bot.send_message(chat_id, f"❌ رصيدك غير كافٍ!\n\nرصيدك: {balance:.2f}$\nالمطلوب: {amount:.2f}$", reply_markup=cancel_kb)
                    return
                fee = round(amount * WITHDRAW_FEE_PERCENT, 4)
                net = round(amount - fee, 4)
                fee_line = f"\nالرسوم: {fee:.2f}$ | الصافي: {net:.2f}$" if fee > 0 else ""
                db.set_user_state(user_id, "waiting_withdraw_details", {"amount": amount, "method": method, "hint": hint})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="wallet", style="danger"))
                bot.send_message(
                    chat_id,
                    f"💵 *طلب سحب {amount:.2f}$*{fee_line}\n"
                    f"📲 الطريقة: {method}\n\n"
                    f"أرسل {hint}:",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except ValueError:
                cancel_kb = types.InlineKeyboardMarkup()
                cancel_kb.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="wallet", style="danger"))
                bot.send_message(chat_id, "❌ مبلغ غير صالح! أرسل رقماً مثل: 10", reply_markup=cancel_kb)

        elif state == "waiting_withdraw_details":
            details = message.text.strip()
            if not details:
                bot.send_message(chat_id, "أرسل تفاصيل الاستلام (عنوان المحفظة أو رقم الهاتف).")
                return
            withdraw_data = (user_state.get('data') or {})
            amount = withdraw_data.get('amount', 0)
            method = withdraw_data.get('method', '')
            fee = round(amount * WITHDRAW_FEE_PERCENT, 4)
            net = round(amount - fee, 4)
            fee_line = f"\nالرسوم: {fee:.2f}$ | الصافي: {net:.2f}$" if fee > 0 else ""
            # عرض تأكيد قبل الإرسال
            db.set_user_state(user_id, "confirming_withdraw", {"amount": amount, "method": method, "address": details})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("✅ تأكيد السحب", callback_data="confirm_withdraw", style="primary"),
                types.InlineKeyboardButton("❌ إلغاء", callback_data="wallet", style="danger")
            )
            bot.send_message(
                chat_id,
                f"🏧 *تأكيد طلب السحب*\n\n"
                f"💵 المبلغ: {amount:.2f}${fee_line}\n"
                f"📲 الطريقة: {method}\n"
                f"📍 العنوان: `{details}`\n\n"
                f"هل تريد تأكيد الطلب؟",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif state.startswith("waiting_reject_withdraw_reason_"):
            req_id = int(state.replace("waiting_reject_withdraw_reason_", ""))
            reason = message.text.strip() if message.text else ""
            db.clear_user_state(user_id)
            ok, result = db.reject_withdrawal(req_id, admin_note=reason)
            if ok:
                target_uid = result['user_id']
                amount = result['amount']
                method = result['method']
                reason_line = f"\nالسبب: {reason}" if reason else ""
                try:
                    bot.send_message(
                        target_uid,
                        f"❌ *تم رفض طلب السحب #{req_id}*\n\n"
                        f"💵 المبلغ: {amount:.2f}$ (أُعيد لرصيدك)"
                        f"{reason_line}\n\n"
                        f"إذا كان هناك خطأ تواصل مع الإدارة.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                bot.send_message(
                    chat_id,
                    f"❌ تم رفض طلب السحب #{req_id} وإعادة {amount:.2f}$ لرصيد المستخدم.",
                    reply_markup=types.InlineKeyboardMarkup().row(
                        types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary")
                    )
                )
            else:
                bot.send_message(chat_id, f"❌ خطأ: {result}")

        elif state.startswith("waiting_report_reason_"):
            auction_id = state.replace("waiting_report_reason_", "")
            reason = message.text.strip() if message.text else ""
            if not reason:
                bot.send_message(chat_id, "يرجى كتابة سبب البلاغ.")
                return
            if len(reason) > 300:
                bot.send_message(chat_id, "السبب طويل جداً (أقصاه 300 حرف).")
                return
            ok, msg_result = db.add_auction_report(auction_id, user_id, reason)
            db.clear_user_state(user_id)
            if ok:
                auction_info = db.get_auction_by_id(auction_id)
                report_count = db.get_auction_report_count(auction_id)
                reporter = db.get_user(user_id)
                reporter_name = f"@{reporter['username']}" if reporter and reporter['username'] else f"ID {user_id}"
                try:
                    bot.send_message(
                        OWNER_ID,
                        f" *بلاغ جديد على مزاد*\n\n"
                        f"المزاد: #{auction_id}\n"
                        f"المنتج: {auction_info['title'] if auction_info else 'غير معروف'}\n"
                        f"المُبلِّغ: {reporter_name}\n"
                        f"السبب: {reason}\n"
                        f"إجمالي البلاغات: {report_count}",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error notifying owner of auction report: {e}")
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 للمزاد", callback_data=f"auction_details_{auction_id}", style="primary"))
                bot.send_message(
                    chat_id,
                    " *تم إرسال البلاغ بنجاح*\n\nشكراً — سيتم مراجعته من قبل الإدارة.",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                bot.send_message(chat_id, f" {msg_result}")

        elif state == "waiting_broadcast_channel_info":
            if user_id != OWNER_ID:
                return
            channel_input = message.text.strip()
            if channel_input.startswith("@"):
                channel_username = channel_input[1:]
                channel_id = None
            elif channel_input.isdigit() or (channel_input.startswith("-") and channel_input[1:].isdigit()):
                channel_id = int(channel_input)
                channel_username = None
            else:
                bot.send_message(chat_id, "أدخل معرف القناة مع @ أو أيدي القناة", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_broadcast_channels", style="danger")))
                return
            channel_data = {"channel_id": channel_id, "channel_username": channel_username, "channel_title": "قناة غير معروفة"}
            db.set_user_state(user_id, "confirming_channel", channel_data)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✅ تأكيد الإضافة", callback_data="confirm_channel", style="primary"), types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_channel", style="danger"))
            bot.send_message(chat_id, f"تفاصيل القناة:\n\nالمعرف: @{channel_username if channel_username else 'غير معروف'}\nالأيدي: {channel_id if channel_id else 'غير معروف'}\nالعنوان: قناة غير معروفة\n\nهل تريد إضافة هذه القناة؟", reply_markup=keyboard)
        elif state == "waiting_subscription_channel_info":
            if user_id != OWNER_ID:
                return
            channel_input = message.text.strip()
            if channel_input.startswith("@"):
                channel_username = channel_input[1:]
                channel_id = None
            elif channel_input.isdigit() or (channel_input.startswith("-") and channel_input[1:].isdigit()):
                channel_id = int(channel_input)
                channel_username = None
            else:
                bot.send_message(chat_id, "أدخل معرف القناة مع @ أو أيدي القناة", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger")))
                return
            channel_data = {"channel_id": channel_id, "channel_username": channel_username, "channel_title": "قناة غير معروفة"}
            db.set_user_state(user_id, "waiting_subscription_type", channel_data)
            keyboard = types.InlineKeyboardMarkup()
            # الاشتراك المدفوع هو المحدد افتراضياً (يظهر أولاً وبعلامة )
            keyboard.row(types.InlineKeyboardButton("🔹 اشتراك مدفوع", callback_data="sub_type_paid", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 دائم", callback_data="sub_type_permanent", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger"))
            display_id = f"@{channel_username}" if channel_username else str(channel_id)
            bot.send_message(
                chat_id,
                f"تم استلام معرف القناة: {display_id}\n\nاختر نوع الاشتراك:\n\n اشتراك مدفوع — تحدد عدد الاشتراكات، وعند انتهائها تُحذف القناة تلقائياً\n دائم — بلا حد للاشتراكات",
                reply_markup=keyboard
            )
        elif state == "waiting_subscription_max_count":
            if user_id != OWNER_ID:
                return
            try:
                max_subscribers = int(message.text.strip())
                if max_subscribers <= 0:
                    bot.send_message(chat_id, "يجب أن يكون العدد أكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger")))
                    return
                channel_data = user_state['data']
                channel_data['max_subscribers'] = max_subscribers
                channel_data['sub_type'] = 'paid'
                db.set_user_state(user_id, "confirming_subscription_channel", channel_data)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(
                    types.InlineKeyboardButton("✅ تأكيد الإضافة", callback_data="confirm_subscription_channel", style="primary"),
                    types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_subscription_channel", style="danger")
                )
                channel_username = channel_data.get('channel_username', '')
                bot.send_message(
                    chat_id,
                    f"تأكيد إضافة قناة الاشتراك:\n\n @{channel_username if channel_username else 'بدون معرف'}\n\n نوع الاشتراك: مدفوع\n عدد الاشتراكات: {max_subscribers}\n القناة تُحذف تلقائياً عند انتهاء الاشتراكات\n\nهل تريد تأكيد الإضافة؟",
                    reply_markup=keyboard
                )
            except ValueError:
                bot.send_message(chat_id, "عدد غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger")))
        elif state == "waiting_binance_wallet":
            wallet = message.text.strip()
            if len(wallet) < 20:
                bot.send_message(chat_id, "عنوان المحفظة غير صحيح، أعد المحاولة.",
                    reply_markup=types.InlineKeyboardMarkup().row(
                        types.InlineKeyboardButton("❌ إلغاء", callback_data="binance_charge", style="danger")
                    ))
                return
            plan_data = user_state['data']
            usdt_amt = plan_data['usdt']
            usd_amt = plan_data['usd']
            live_rate = 1.0  # 1 USDT = $1
            db.set_user_state(user_id, "confirming_binance_payment", {
                "wallet": wallet, "usdt": usdt_amt, "usd": usd_amt
            })
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("✅ تأكيد الدفع", callback_data="execute_binance_pay", style="primary"),
                types.InlineKeyboardButton("❌ إلغاء", callback_data="binance_charge", style="danger")
            )
            bot.send_message(
                chat_id,
                f" *تأكيد عملية الشحن*\n\n"
                f"المبلغ: *{usdt_amt} USDT*\n"
                f"سعر USDT: *{live_rate:.2f}$*\n"
                f"يُضاف لرصيدك: *${usd_amt:.2f}*\n"
                f"المحفظة: `{wallet}`\n\n"
                f"سيتم سحب المبلغ من محفظتك فوراً.",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

        elif state == "waiting_transfer_user_id":
            try:
                to_user_id = int(message.text.strip())
                if to_user_id == user_id:
                    bot.send_message(chat_id, "لا يمكنك التحويل لنفسك!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع للتحويل", callback_data="transfer_by_id", style="primary")))
                    return
                to_user = db.get_user(to_user_id)
                if not to_user:
                    bot.send_message(chat_id, "المستخدم غير موجود!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data="transfer_money", style="primary")))
                    return
                db.set_user_state(user_id, "waiting_transfer_amount", {"to_user_id": to_user_id})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="back_to_main", style="danger"))
                bot.send_message(chat_id, f"المستخدم: @{to_user['username'] if to_user['username'] else 'بدون معرف'}\nرصيدك الحالي: ${db.get_balance(user_id):.2f}\n\nأرسل المبلغ الذي تريد تحويله بالدولار ($):\nالعمولة: {TRANSFER_COMMISSION_RATE*100}%", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح! أرسل أيدي صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data="transfer_money", style="primary")))
        elif state == "waiting_transfer_amount":
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "المبلغ يجب أن يكون أكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="back_to_main", style="danger")))
                    return
                to_user_id = (user_state.get('data') or {}).get('to_user_id')
                user_balance = db.get_balance(user_id)
                if user_balance < amount:
                    bot.send_message(chat_id, f"رصيدك غير كافي!\n\nرصيدك الحالي: {user_balance:.2f}$\nالمبلغ المطلوب: {amount:.2f}$", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("📥 شحن رصيد", callback_data="charge", style="primary"), types.InlineKeyboardButton("🔙 رجوع للتحويل", callback_data="transfer_by_id", style="primary")))
                    return
                commission = calculate_transfer_commission(amount)
                net_amount = amount - commission
                db.set_user_state(user_id, "waiting_transfer_description", {"to_user_id": to_user_id, "amount": amount})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 تخطي", callback_data="skip_description", style="primary"))
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="back_to_main", style="danger"))
                bot.send_message(chat_id, f"تفاصيل التحويل:\n\nإلى: @{db.get_user(to_user_id)['username'] if db.get_user(to_user_id) and db.get_user(to_user_id)['username'] else 'مستخدم'}\nالمبلغ: {amount:.2f}$\nالعمولة ({TRANSFER_COMMISSION_RATE*100}%): {commission:.2f}$\nصافي المبلغ للمستلم: {net_amount:.2f}$\n\nأرسل وصف للتحويل (اختياري):", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="back_to_main", style="danger")))
        elif state == "waiting_transfer_description":
            description = message.text.strip()
            to_user_id = (user_state.get('data') or {}).get('to_user_id')
            amount = (user_state.get('data') or {}).get('amount')
            commission = calculate_transfer_commission(amount)
            net_amount = amount - commission
            db.set_user_state(user_id, "confirming_transfer", {"to_user_id": to_user_id, "amount": amount, "description": description})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✅ تأكيد التحويل", callback_data="confirm_transfer", style="primary"), types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_transfer", style="danger"))
            bot.send_message(chat_id, f"تأكيد التحويل:\n\nإلى: @{db.get_user(to_user_id)['username'] if db.get_user(to_user_id) and db.get_user(to_user_id)['username'] else 'مستخدم'}\nالمبلغ: {amount:.2f}$\nالعمولة ({TRANSFER_COMMISSION_RATE*100}%): {commission:.2f}$\nصافي المبلغ للمستلم: {net_amount:.2f}$\nالوصف: {description if description else 'لا يوجد'}\n\nهل تريد تأكيد التحويل؟", reply_markup=keyboard)
        elif state == "waiting_user_id_for_add":
            if user_id != OWNER_ID:
                return
            try:
                target_user_id = int(message.text.strip())
                target_user = db.get_user(target_user_id)
                if not target_user:
                    bot.send_message(chat_id, "المستخدم غير موجود!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
                    return
                db.set_user_state(user_id, "waiting_amount_for_add", {"user_id": target_user_id})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger"))
                bot.send_message(chat_id, f"المستخدم: @{target_user['username'] if target_user['username'] else 'بدون معرف'}\nالرصيد الحالي: ${target_user['balance']:.2f}\n\nأرسل المبلغ الذي تريد إضافته بالدولار ($):", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح! أرسل أيدي صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
        elif state == "waiting_amount_for_add":
            if user_id != OWNER_ID:
                return
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "المبلغ يجب أن يكون أكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
                    return
                target_user_id = (user_state.get('data') or {}).get('user_id')
                target_user = db.get_user(target_user_id)
                db.update_balance(target_user_id, amount)
                db.add_transaction(target_user_id, amount, "admin_add", f"إضافة رصيد من الإدارة")
                new_balance = db.get_balance(target_user_id)
                try:
                    bot.send_message(target_user_id, f"تم إضافة رصيد لحسابك!\n\nالتفاصيل:\nالمبلغ المضاف: {amount:.2f}$\nالرصيد الجديد: {new_balance:.2f}$\nبواسطة: الإدارة")
                except Exception as e:
                    logger.error(f"Error notifying user: {e}")
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 لإدارة المستخدمين", callback_data="admin_users", style="primary"))
                bot.send_message(chat_id, f"تمت إضافة الرصيد بنجاح!\n\nالمستخدم: @{target_user['username'] if target_user['username'] else 'بدون معرف'}\nالمبلغ المضاف: {amount:.2f}$\nالرصيد الجديد: {new_balance:.2f}$", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
        elif state == "waiting_user_id_for_deduct":
            if user_id != OWNER_ID:
                return
            try:
                target_user_id = int(message.text.strip())
                target_user = db.get_user(target_user_id)
                if not target_user:
                    bot.send_message(chat_id, "المستخدم غير موجود!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
                    return
                db.set_user_state(user_id, "waiting_amount_for_deduct", {"user_id": target_user_id})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger"))
                bot.send_message(chat_id, f"المستخدم: @{target_user['username'] if target_user['username'] else 'بدون معرف'}\nالرصيد الحالي: ${target_user['balance']:.2f}\n\nأرسل المبلغ الذي تريد خصمه بالدولار ($):", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح! أرسل أيدي صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
        elif state == "waiting_amount_for_deduct":
            if user_id != OWNER_ID:
                return
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "المبلغ يجب أن يكون أكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
                    return
                target_user_id = (user_state.get('data') or {}).get('user_id')
                target_user = db.get_user(target_user_id)
                current_balance = target_user['balance']
                if current_balance < amount:
                    bot.send_message(chat_id, f"رصيد المستخدم غير كافي!\nالرصيد الحالي: {current_balance:.2f}$\nالمبلغ المطلوب: {amount:.2f}$", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
                    return
                db.update_balance(target_user_id, -amount)
                db.add_transaction(target_user_id, -amount, "admin_deduct", f"خصم رصيد من الإدارة")
                new_balance = db.get_balance(target_user_id)
                try:
                    bot.send_message(target_user_id, f"تم خصم رصيد من حسابك!\n\nالتفاصيل:\nالمبلغ المخصوم: {amount:.2f}$\nالرصيد الجديد: {new_balance:.2f}$\nبواسطة: الإدارة")
                except Exception as e:
                    logger.error(f"Error notifying user: {e}")
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 لإدارة المستخدمين", callback_data="admin_users", style="primary"))
                bot.send_message(chat_id, f"تم خصم الرصيد بنجاح!\n\nالمستخدم: @{target_user['username'] if target_user['username'] else 'بدون معرف'}\nالمبلغ المخصوم: {amount:.2f}$\nالرصيد الجديد: {new_balance:.2f}$", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_users", style="danger")))
        elif state == "admin_direct_add_bal_single":
            if user_id != OWNER_ID:
                return
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "المبلغ يجب أن يكون أكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                target_uid = (user_state.get('data') or {}).get('target_uid')
                db.update_balance(target_uid, amount)
                db.add_transaction(target_uid, amount, "admin_add", "إضافة رصيد من الإدارة")
                new_balance = db.get_balance(target_uid)
                try:
                    bot.send_message(target_uid, f"تم إضافة {amount:.2f}$ لرصيدك!\nرصيدك الجديد: {new_balance:.2f}$")
                except Exception:
                    pass
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, f"تمت إضافة {amount:.2f}$ للمستخدم {target_uid}\nالرصيد الجديد: {new_balance:.2f}$", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))

        elif state == "admin_direct_deduct_bal_single":
            if user_id != OWNER_ID:
                return
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "المبلغ يجب أن يكون أكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                target_uid = (user_state.get('data') or {}).get('target_uid')
                current_balance = db.get_balance(target_uid)
                if current_balance < amount:
                    bot.send_message(chat_id, f"رصيد المستخدم غير كافٍ!\nالرصيد الحالي: {current_balance:.2f}$", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                db.update_balance(target_uid, -amount)
                db.add_transaction(target_uid, -amount, "admin_deduct", "خصم رصيد من الإدارة")
                new_balance = db.get_balance(target_uid)
                try:
                    bot.send_message(target_uid, f"تم خصم {amount:.2f}$ من رصيدك!\nرصيدك الجديد: {new_balance:.2f}$")
                except Exception:
                    pass
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, f"تم خصم {amount:.2f}$ من المستخدم {target_uid}\nالرصيد الجديد: {new_balance:.2f}$", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))

        elif state == "waiting_broadcast":
            if user_id != OWNER_ID:
                return
            message_text = message.text
            users = db.get_all_users()
            bot.send_message(chat_id, f"جارٍ إرسال البث لـ {len(users)} مستخدم...")
            success_count = 0
            failed_count = 0
            for uid in users:
                try:
                    bot.send_message(uid, message_text, parse_mode="HTML", disable_web_page_preview=True)
                    success_count += 1
                    time.sleep(0.1)
                except Exception as e:
                    failed_count += 1
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.send_message(chat_id, f"تم إكمال البث:\n\nتم بنجاح: {success_count}\nفشل: {failed_count}\nالمجموع: {len(users)}", reply_markup=keyboard)
        elif state == "waiting_channel_id_for_delete":
            if user_id != OWNER_ID:
                return
            try:
                channel_id = int(message.text.strip())
                cursor = db.conn.cursor()
                cursor.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
                db.conn.commit()
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("📡 لإدارة قنوات البث", callback_data="manage_broadcast_channels", style="primary"))
                bot.send_message(chat_id, f"تم حذف القناة بنجاح!\n\nأيدي القناة: {channel_id}", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح! أرسل أيدي صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_broadcast_channels", style="danger")))
        elif state == "waiting_subscription_channel_id_for_delete":
            if user_id != OWNER_ID:
                return
            try:
                channel_id = int(message.text.strip())
                cursor = db.conn.cursor()
                cursor.execute("DELETE FROM subscription_channels WHERE channel_id = ?", (channel_id,))
                db.conn.commit()
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔔 لإدارة قنوات الاشتراك", callback_data="manage_subscription_channels", style="primary"))
                bot.send_message(chat_id, f"تم حذف قناة الاشتراك بنجاح!\n\nأيدي القناة: {channel_id}", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح! أرسل أيدي صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="manage_subscription_channels", style="danger")))
        elif state == "waiting_code":
            code = message.text.strip().upper()
            success_tc, result_tc = db.use_transfer_code(code, user_id)
            if success_tc:
                new_balance = db.get_balance(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"), types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                bot.send_message(chat_id, f"تم استخدام كود التحويل!\n\nالمبلغ المضاف: {result_tc:.2f}$\nرصيدك الجديد: {new_balance:.2f}$", reply_markup=keyboard)
                # إشعار صاحب الكود
                try:
                    cursor = db.conn.cursor()
                    cursor.execute("SELECT from_user_id FROM transfer_codes WHERE code=?", (code,))
                    row = cursor.fetchone()
                    if row:
                        sender_id = row[0]
                        user_info_r = db.get_user(user_id)
                        r_name = f"{user_info_r['first_name'] or ''} (@{user_info_r['username']})" if user_info_r and user_info_r['username'] else f"[{user_id}]"
                        bot.send_message(
                            sender_id,
                            f"تم استخدام كود التحويل الخاص بك!\n\n"
                            f"الكود: {code}\n"
                            f"المبلغ: {result_tc:.2f}$\n"
                            f"المستلم: {r_name}\n"
                            f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                except Exception as e:
                    logger.error(f"Error notifying transfer code sender: {e}")
                # إشعار المالك
                try:
                    user_info_r = db.get_user(user_id)
                    r_name = f"{user_info_r['first_name'] or ''} (@{user_info_r['username']})" if user_info_r and user_info_r['username'] else f"[{user_id}]"
                    bot.send_message(
                        OWNER_ID,
                        f"استخدام كود تحويل\n\n"
                        f"الكود: {code}\n"
                        f"المبلغ: {result_tc:.2f}$\n"
                        f"المستلم: {r_name} [{user_id}]\n"
                        f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                except Exception as e:
                    logger.error(f"Error notifying owner about transfer code: {e}")
                db.clear_user_state(user_id)
                return
            code_info = db.get_recharge_code(code)
            if not code_info:
                bot.send_message(chat_id, "الكود غير صالح او منتهي الصلاحية!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data="use_code", style="primary"), types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary")))
                return
            success, msg = db.use_recharge_code(code_info['code_id'], user_id)
            if success:
                new_balance = db.get_balance(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"), types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                bot.send_message(chat_id, f"{msg}\n\nرصيدك الجديد: {new_balance:.2f}$", reply_markup=keyboard)
            else:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data="use_code", style="primary"), types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
                bot.send_message(chat_id, f"فشل استخدام الكود: {msg}", reply_markup=keyboard)
            db.clear_user_state(user_id)

        elif state == "waiting_gift_link_amount":
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "المبلغ يجب ان يكون اكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="transfer_money", style="danger")))
                    return
                balance = db.get_balance(user_id)
                if balance < amount:
                    bot.send_message(chat_id, f"رصيدك غير كاف!\n\nرصيدك: {balance:.2f}$\nالمطلوب: {amount:.2f}$", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("📥 شحن رصيد", callback_data="charge", style="primary"), types.InlineKeyboardButton("🔙 رجوع", callback_data="transfer_money", style="primary")))
                    return
                success, msg, token = db.create_gift_link(user_id, amount)
                db.clear_user_state(user_id)
                if success:
                    bot_info = get_bot_info()
                    gift_url = f"https://t.me/{bot_info['username']}?start=gift_{token}"
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.row(types.InlineKeyboardButton("📤 مشاركة الرابط", url=f"https://t.me/share/url?url={gift_url}&text=هدية+لك+بقيمة+${amount:.2f}", style="primary"))
                    keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
                    bot.send_message(chat_id,
                        f"تم إنشاء رابط الهدية!\n\nالمبلغ: {amount:.2f}$\nالرابط:\n{gift_url}\n\nالرابط صالح لمرة واحدة فقط\nرصيدك الجديد: {db.get_balance(user_id):.2f}$",
                        reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, f"فشل إنشاء الرابط: {msg}", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="transfer_money", style="primary")))
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! ارسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="transfer_money", style="danger")))

        elif state == "waiting_transfer_code_amount":
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "المبلغ يجب ان يكون اكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="transfer_money", style="danger")))
                    return
                balance = db.get_balance(user_id)
                if balance < amount:
                    bot.send_message(chat_id, f"رصيدك غير كاف!\n\nرصيدك: {balance:.2f}$\nالمطلوب: {amount:.2f}$", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("📥 شحن رصيد", callback_data="charge", style="primary"), types.InlineKeyboardButton("🔙 رجوع", callback_data="transfer_money", style="primary")))
                    return
                success, msg, code = db.create_transfer_code(user_id, amount)
                db.clear_user_state(user_id)
                if success:
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
                    bot.send_message(chat_id,
                        f"تم إنشاء كود التحويل!\n\nالمبلغ: {amount:.2f}$\nالكود:\n{code}\n\nالكود صالح لمرة واحدة فقط\nرصيدك الجديد: {db.get_balance(user_id):.2f}$",
                        reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, f"فشل إنشاء الكود: {msg}", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="transfer_money", style="primary")))
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! ارسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="transfer_money", style="danger")))

        elif state == "waiting_auction_duration":
            if user_id != OWNER_ID:
                return
            try:
                hours = int(message.text.strip())
                if hours < 1 or hours > 720:
                    bot.send_message(chat_id, "المدة يجب أن تكون بين 1 و720 ساعة!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                db.set_setting('auction_duration', hours)
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, f"تم تحديث مدة المزاد إلى *{hours} ساعة*\n\nستُطبق على المزادات الجديدة فقط.", reply_markup=keyboard, parse_mode="Markdown")
            except ValueError:
                bot.send_message(chat_id, "أدخل رقماً صحيحاً!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
        elif state.startswith("admin_reject_reason_"):
            if user_id != OWNER_ID:
                db.clear_user_state(user_id)
                return
            try:
                op_id = int(state.replace("admin_reject_reason_", ""))
            except ValueError:
                db.clear_user_state(user_id)
                return
            reason = message.text.strip() if message.text else "لم يُحدد سبب"
            op = db.get_agent_pending_op(op_id)
            if not op or op['status'] != 'pending':
                bot.send_message(chat_id, "العملية غير موجودة أو تمت معالجتها بالفعل!")
                db.clear_user_state(user_id)
                return
            db.resolve_agent_pending_op(op_id, 'rejected', admin_note=reason)
            op_label = "إنشاء الكود" if op['op_type'] == 'code' else "التحويل المباشر"
            # إشعار الوكيل بالسبب
            try:
                kb_agent = types.InlineKeyboardMarkup()
                kb_agent.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
                bot.send_message(
                    op['agent_id'],
                    f"❌ *تم رفض طلب {op_label}*\n\n"
                    f"المبلغ: {op['amount']:.2f}$\n"
                    f"السبب: {md_escape(reason)}\n\n"
                    f"تواصل مع الإدارة إذا كان لديك استفسار.",
                    reply_markup=kb_agent, parse_mode="Markdown"
                )
            except Exception:
                pass
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ طلبات الوكلاء", callback_data="admin_agent_pending_ops", style="primary"))
            bot.send_message(
                chat_id,
                f"✅ تم رفض الطلب #{op_id} مع إرسال السبب للوكيل.\n\nالسبب: {md_escape(reason)}",
                reply_markup=keyboard, parse_mode="Markdown"
            )

        elif state == "waiting_code_amount":
            if user_id != OWNER_ID:
                return
            try:
                amount = float(message.text.strip())
                if amount <= 0:
                    bot.send_message(chat_id, "المبلغ يجب أن يكون أكبر من صفر!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                db.set_user_state(user_id, "waiting_code_max_uses", {"amount": amount})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
                bot.send_message(chat_id, f"المبلغ: {amount:.2f}$\n\nأرسل عدد المستخدمين الذين يستخدمون الكود (1-100):", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "مبلغ غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
        elif state == "waiting_code_max_uses":
            if user_id != OWNER_ID:
                return
            try:
                max_uses = int(message.text.strip())
                if max_uses < 1 or max_uses > 100:
                    bot.send_message(chat_id, "عدد المستخدمين يجب أن يكون بين 1 و 100!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                amount = (user_state.get('data') or {}).get('amount')
                db.set_user_state(user_id, "waiting_code_expires_days", {"amount": amount, "max_uses": max_uses})
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger"))
                bot.send_message(chat_id, f"المبلغ: {amount:.2f}$\nعدد المستخدمين: {max_uses}\n\nأرسل عدد الأيام لانتهاء الصلاحية (1-365):", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "عدد غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
        elif state == "waiting_code_expires_days":
            if user_id != OWNER_ID:
                return
            try:
                expires_days = int(message.text.strip())
                if expires_days < 1 or expires_days > 365:
                    bot.send_message(chat_id, "عدد الأيام يجب أن يكون بين 1 و 365!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                amount = (user_state.get('data') or {}).get('amount')
                max_uses = (user_state.get('data') or {}).get('max_uses')
                code = db.create_recharge_code(amount, max_uses, expires_days, OWNER_ID)
                if not code:
                    bot.send_message(chat_id, "فشل إنشاء الكود! حاول مرة أخرى.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔹 إعادة المحاولة", callback_data="create_code", style="primary")))
                    return
                db.clear_user_state(user_id)
                expires_date = datetime.now() + timedelta(days=expires_days)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("📋 نسخ الكود", callback_data=f"copy_code_{code}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(
                    chat_id,
                    f" *تم إنشاء كود الشحن بنجاح!*\n\n"
                    f"الكود: `{code}`\n"
                    f"المبلغ: {amount:.2f}$\n"
                    f"عدد المستخدمين: {max_uses}\n"
                    f"ينتهي في: {expires_date.strftime('%Y-%m-%d')}\n\n"
                    f"اضغط على الكود أعلاه لنسخه، أو اضغط زر النسخ",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            except ValueError:
                bot.send_message(chat_id, "عدد غير صالح! أرسل رقم صحيح.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
        # 
        # حالات لوحة الإدارة الجديدة 
        # 
        elif state == "admin_direct_add_bal":
            if user_id != OWNER_ID:
                return
            try:
                parts = message.text.strip().split(None, 2)
                if len(parts) < 2:
                    raise ValueError()
                target_uid = int(parts[0])
                amount = float(parts[1])
                note = parts[2] if len(parts) > 2 else ""
                target_user = db.get_user(target_uid)
                if not target_user:
                    bot.send_message(chat_id, "المستخدم غير موجود!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                db.admin_set_balance(target_uid, amount, user_id, note)
                new_balance = db.get_balance(target_uid)
                db.clear_user_state(user_id)
                try:
                    bot.send_message(target_uid, f"تم إضافة رصيد لحسابك!\nالمبلغ: {amount:.2f}$\nالرصيد الجديد: {new_balance:.2f}$\n{('السبب: ' + note) if note else ''}")
                except Exception:
                    pass
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                name = f"@{target_user['username']}" if target_user['username'] else str(target_uid)
                bot.send_message(chat_id, f"تمت إضافة {amount:.2f}$ للمستخدم {name}\nالرصيد الجديد: {new_balance:.2f}$", reply_markup=keyboard)
            except (ValueError, IndexError):
                bot.send_message(chat_id, "صيغة غير صحيحة!\n\nمثال: 123456789 500 هدية", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))

        elif state == "admin_direct_deduct_bal":
            if user_id != OWNER_ID:
                return
            try:
                parts = message.text.strip().split(None, 2)
                if len(parts) < 2:
                    raise ValueError()
                target_uid = int(parts[0])
                amount = float(parts[1])
                note = parts[2] if len(parts) > 2 else ""
                target_user = db.get_user(target_uid)
                if not target_user:
                    bot.send_message(chat_id, "المستخدم غير موجود!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                current_bal = db.get_balance(target_uid)
                if current_bal < amount:
                    bot.send_message(chat_id, f"رصيد المستخدم غير كافٍ!\nالرصيد الحالي: {current_bal:.2f}$", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                db.admin_set_balance(target_uid, -amount, user_id, note)
                new_balance = db.get_balance(target_uid)
                db.clear_user_state(user_id)
                try:
                    bot.send_message(target_uid, f"تم خصم رصيد من حسابك.\nالمبلغ: {amount:.2f}$\nالرصيد الجديد: {new_balance:.2f}$\n{('السبب: ' + note) if note else ''}")
                except Exception:
                    pass
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                name = f"@{target_user['username']}" if target_user['username'] else str(target_uid)
                bot.send_message(chat_id, f"تم خصم {amount:.2f}$ من {name}\nالرصيد الجديد: {new_balance:.2f}$", reply_markup=keyboard)
            except (ValueError, IndexError):
                bot.send_message(chat_id, "صيغة غير صحيحة!\n\nمثال: 123456789 200 مخالفة", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))

        elif state == "admin_searching_user":
            if user_id != OWNER_ID:
                return
            query = message.text.strip()
            results = db.search_user(query)
            db.clear_user_state(user_id)
            if not results:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔍 بحث مجدداً", callback_data="admin_search_user", style="primary"), types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, "لم يتم العثور على مستخدم بهذا البحث.", reply_markup=keyboard)
                return
            text = f"نتائج البحث ({len(results)}):\n\n"
            for u in results[:10]:
                name = f"@{u['username']}" if u['username'] else (u['first_name'] or "بدون اسم")
                is_banned_label = " | محظور" if db.is_banned(u['user_id']) else ""
                text += f"ID: {u['user_id']}\nالاسم: {name}{is_banned_label}\nالرصيد: {u['balance']:.2f}$\nتاريخ الانضمام: {str(u['created_at'])[:10]}\n----\n"
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔍 بحث مجدداً", callback_data="admin_search_user", style="primary"), types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.send_message(chat_id, text, reply_markup=keyboard)

        elif state == "admin_banning_user":
            if user_id != OWNER_ID:
                return
            parts = message.text.strip().split(None, 1)
            try:
                target_uid = int(parts[0])
                reason = parts[1] if len(parts) > 1 else ""
                db.ban_user(target_uid, reason, user_id)
                db.clear_user_state(user_id)
                target_user = db.get_user(target_uid)
                name = f"@{target_user['username']}" if target_user and target_user['username'] else str(target_uid)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, f"تم حظر المستخدم {name}\n{('السبب: ' + reason) if reason else ''}", reply_markup=keyboard)
                try:
                    bot.send_message(target_uid, "تم حظر حسابك من استخدام البوت.")
                except Exception:
                    pass
            except (ValueError, IndexError):
                bot.send_message(chat_id, "أيدي غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))

        elif state == "admin_unbanning_user":
            if user_id != OWNER_ID:
                return
            try:
                target_uid = int(message.text.strip())
                if not db.is_banned(target_uid):
                    bot.send_message(chat_id, "هذا المستخدم ليس محظوراً.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary")))
                    db.clear_user_state(user_id)
                    return
                db.unban_user(target_uid)
                db.clear_user_state(user_id)
                target_user = db.get_user(target_uid)
                name = f"@{target_user['username']}" if target_user and target_user['username'] else str(target_uid)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, f"تم رفع الحظر عن المستخدم {name}", reply_markup=keyboard)
                try:
                    bot.send_message(target_uid, "تم رفع الحظر عن حسابك. يمكنك استخدام البوت الآن.")
                except Exception:
                    pass
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))

        elif state == "admin_cancelling_auction":
            if user_id != OWNER_ID:
                return
            auction_id = message.text.strip()
            auction_info = db.get_auction_by_id(auction_id)
            if not auction_info:
                bot.send_message(chat_id, "المزاد غير موجود!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary")))
                db.clear_user_state(user_id)
                return
            bids = db.get_auction_bids(auction_id)
            refunded = 0
            for bid in bids:
                if db.refund_bid(bid['bid_id']):
                    db.add_transaction(bid['user_id'], bid['amount'], "bid_refund", f"استرداد - إلغاء مزاد #{auction_id} من الإدارة")
                    try:
                        bot.send_message(bid['user_id'], f"تم استرداد مزايدتك في المزاد #{auction_id}\nالمبلغ: {bid['amount']:.2f}$\nسبب: إلغاء المزاد من الإدارة")
                    except Exception:
                        pass
                    refunded += 1
            db.expire_auction(auction_id)
            # ← استرداد سعر البدء للبائع (كان ناقص: المزاد يُلغى لكن سعر البدء يضيع)
            refund_starting_price_if_needed(auction_info)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.send_message(chat_id, f"تم إلغاء المزاد #{auction_id}\nعدد المزايدات المستردة: {refunded}", reply_markup=keyboard)
            try:
                starting_price = auction_info.get('starting_price', 0.0)
                extra_note = f"\nتم استرداد سعر البدء: {starting_price:.2f}$" if starting_price > 0 else ""
                bot.send_message(auction_info['user_id'], f"تم إلغاء مزادك #{auction_id} من الإدارة.{extra_note}")
            except Exception:
                pass

        elif state == "admin_setting_listing_fee":
            if user_id != OWNER_ID:
                return
            try:
                fee_val = float(message.text.strip())
                if fee_val < 0 or fee_val > 10:
                    bot.send_message(chat_id, "القيمة يجب أن تكون بين 0 و 10!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))
                    return
                cur_lf4 = db.conn.cursor()
                cur_lf4.execute("INSERT OR REPLACE INTO bot_settings (key,value) VALUES ('listing_fee',?)", (str(fee_val),))
                db.conn.commit()
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, f"✅ تم تحديث رسوم النشر إلى {fee_val:.3f}$", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أرسل رقماً صحيحاً!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel", style="danger")))

        elif state == "admin_setting_commission":
            if user_id != OWNER_ID:
                return
            try:
                pct = float(message.text.strip())
                if pct < 0 or pct > 50:
                    bot.send_message(chat_id, "النسبة يجب أن تكون بين 0 و 50!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_commissions", style="danger")))
                    return
                db.set_setting('commission_rate', pct / 100)
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("⚙️ إعدادات العمولات", callback_data="admin_commissions", style="primary"))
                bot.send_message(chat_id, f"تم تحديث عمولة البيع إلى {pct}%\n(ستُطبق على المزادات الجديدة)", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "قيمة غير صالحة!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_commissions", style="danger")))

        elif state == "searching_auctions":
            query = message.text.strip()
            db.clear_user_state(user_id)
            if not query:
                bot.send_message(chat_id, "أرسل كلمة للبحث.", reply_markup=create_main_menu_keyboard(user_id))
                return
            # البحث في قاعدة البيانات
            cursor_sr = db.conn.cursor()
            cursor_sr.execute("""
                SELECT * FROM auctions
                WHERE status='active' AND (
                    LOWER(title) LIKE ? OR
                    LOWER(target) LIKE ? OR
                    LOWER(description) LIKE ?
                )
                ORDER BY created_at DESC LIMIT 15
            """, (f"%{query.lower()}%", f"%{query.lower()}%", f"%{query.lower()}%"))
            rows_sr = cursor_sr.fetchall()
            cols = [d[0] for d in cursor_sr.description]
            auctions_found = [dict(zip(cols, r)) for r in rows_sr]
            keyboard = types.InlineKeyboardMarkup()
            if not auctions_found:
                keyboard.row(types.InlineKeyboardButton("🔍 بحث مجدداً", callback_data="search_auctions", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔹 عرض كل المزادات", callback_data="show_auctions", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
                bot.send_message(
                    chat_id,
                    f"🔍 لم أجد نتائج لـ \"{html_escape(query)}\"\n\nحاول بكلمة مختلفة.",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
            lines = [f"🔍 {hb('نتائج البحث:')} {html_escape(query)}\n{DIVIDER}"]
            for a in auctions_found:
                type_label = AUCTION_TYPES.get(a['auction_type'], a['auction_type'])
                lines.append(
                    f"• {hb(html_escape(a['title']))} — {hc('#' + str(a['auction_id']))}\n"
                    f"  {type_label} | {fmt_money(a['current_price'])}"
                )
                keyboard.row(types.InlineKeyboardButton(
                    f"#{a['auction_id']} — {a['title'][:30]}",
                    callback_data=f"auction_details_{a['auction_id']}",
                    style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔍 بحث مجدداً", callback_data="search_auctions", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.send_message(
                chat_id,
                "\n".join(lines),
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        # حالة طلب السحب
        elif state == "waiting_withdraw_address":
            address = message.text.strip()
            wdata = (user_state.get('data') or {})
            amount = wdata.get('amount', 0.0)
            method = wdata.get('method', 'USDT')
            balance = db.get_balance(user_id)
            if balance < amount:
                bot.send_message(chat_id, "رصيدك غير كافٍ!", reply_markup=create_main_menu_keyboard(user_id))
                db.clear_user_state(user_id)
                return
            db.set_user_state(user_id, "confirming_withdraw", {"amount": amount, "method": method, "address": address})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("✅ تأكيد السحب", callback_data="confirm_withdraw", style="primary"),
                types.InlineKeyboardButton("❌ إلغاء", callback_data="wallet", style="danger")
            )
            bot.send_message(
                chat_id,
                f"🏧 {hb('تأكيد طلب السحب')}\n\n"
                f"المبلغ: {fmt_money(amount)}\n"
                f"طريقة الاستلام: {html_escape(method)}\n"
                f"عنوان/رقم الاستلام: {hc(html_escape(address))}\n\n"
                "هل تريد تأكيد الطلب؟",
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        elif state == "waiting_withdraw_amount":
            try:
                amount = float(message.text.strip())
                if amount < MIN_WITHDRAW:
                    bot.send_message(chat_id, f"الحد الأدنى للسحب: {fmt_money(MIN_WITHDRAW)}", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="withdraw_request", style="primary")))
                    return
                balance = db.get_balance(user_id)
                if balance < amount:
                    bot.send_message(chat_id, f"رصيدك ({fmt_money(balance)}) غير كافٍ!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="withdraw_request", style="primary")))
                    return
                wdata = (user_state.get('data') or {})
                wdata['amount'] = amount
                db.set_user_state(user_id, "waiting_withdraw_address", wdata)
                method = wdata.get('method', 'USDT')
                placeholder = "مثال: TXxxx... (محفظة USDT TRC20)" if "USDT" in method else "مثال: 07XXXXXXXX"
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="wallet", style="danger"))
                bot.send_message(
                    chat_id,
                    f"💳 أرسل {html_escape(method)} الذي تريد الاستلام عليه:\n\n{placeholder}",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except ValueError:
                bot.send_message(chat_id, "أرسل رقماً صحيحاً!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="wallet", style="danger")))

        # حالات جديدة 
        elif state == "admin_searching_user_detail":
            if user_id != OWNER_ID:
                return
            query = message.text.strip()
            results = db.search_user(query)
            db.clear_user_state(user_id)
            if not results:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔍 بحث مجدداً", callback_data="admin_user_detail", style="primary"), types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, "لم يتم العثور على مستخدم.", reply_markup=keyboard)
                return
            if len(results) == 1:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 عرض التفاصيل", callback_data=f"admin_view_user_{results[0]['user_id']}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                u = results[0]
                banned_label = "محظور" if db.is_banned(u['user_id']) else ""
                text = (f"تم العثور على مستخدم:\n\n"
                        f" `{u['user_id']}`\n"
                        f" @{u['username'] or 'بدون معرف'}{banned_label}\n"
                        f" {u['first_name'] or ''}\n"
                        f" {u['balance']:.2f}$")
                bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")
                return
            keyboard = types.InlineKeyboardMarkup()
            for u in results[:8]:
                name = f"@{u['username']}" if u['username'] else (u['first_name'] or f"ID {u['user_id']}")
                banned_label = " " if db.is_banned(u['user_id']) else ""
                keyboard.row(types.InlineKeyboardButton(
                    f"{name}{banned_label} | {u['balance']:.1f}$",
                    callback_data=f"admin_view_user_{u['user_id']}",
                    style="primary"
                ))
            keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
            bot.send_message(chat_id, f"نتائج البحث ({len(results)}):", reply_markup=keyboard)

        # حالات الوكلاء والوسطاء 
        elif state == "waiting_agent_report_code":
            charge_code = message.text.strip()
            agent_uid = user_state['data'].get('agent_uid') if user_state.get('data') else None
            if not agent_uid:
                db.clear_user_state(user_id)
                bot.send_message(chat_id, "انتهت الجلسة.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="show_agents", style="primary")))
                return
            db.set_user_state(user_id, "waiting_agent_report_reason", {"agent_uid": agent_uid, "charge_code": charge_code})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="show_agents", style="danger"))
            bot.send_message(chat_id, f"كود العملية: `{charge_code}`\n\nاكتب سبب البلاغ:", reply_markup=keyboard, parse_mode="Markdown")

        elif state == "waiting_agent_report_reason":
            reason = message.text.strip()
            data = user_state.get('data', {}) or {}
            agent_uid = data.get('agent_uid')
            charge_code = data.get('charge_code', '')
            if not agent_uid:
                db.clear_user_state(user_id)
                bot.send_message(chat_id, "انتهت الجلسة.", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="wallet", style="primary")))
                return
            ok, result = db.add_agent_report(agent_uid, user_id, charge_code, reason)
            db.clear_user_state(user_id)
            if ok:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("👛 المحفظة", callback_data="wallet", style="primary"))
                bot.send_message(chat_id, " *تم إرسال البلاغ بنجاح*\n\nسيتم مراجعته من الإدارة.", reply_markup=keyboard, parse_mode="Markdown")
                try:
                    agents = db.get_all_agents()
                    ag_name = next((a['name'] for a in agents if a['user_id'] == agent_uid), str(agent_uid))
                    reporter = db.get_user(user_id)
                    r_name = f"@{reporter['username']}" if reporter and reporter['username'] else str(user_id)
                    bot.send_message(OWNER_ID, f" *بلاغ على وكيل!*\n\nالوكيل: {ag_name} (ID: {agent_uid})\nالمبلِّغ: {r_name}\nكود الشحن: {charge_code}\nالسبب: {reason}", parse_mode="Markdown")
                except Exception:
                    pass
            else:
                bot.send_message(chat_id, f"فشل الإرسال: {result}", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("🔙 رجوع", callback_data="wallet", style="primary")))

        elif state == "waiting_add_agent_id":
            if user_id != OWNER_ID: return
            try:
                target_uid = int(message.text.strip())
                target_user = db.get_user(target_uid)
                # نسمح بالإضافة حتى لو المستخدم لم يسجل في البوت بعد
                if not target_user:
                    # نسجّله مؤقتاً بدون بيانات
                    db.conn.execute(
                        "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                        (target_uid, None, f"user_{target_uid}")
                    )
                    db.conn.commit()
                    target_user = db.get_user(target_uid)
                db.set_user_state(user_id, "waiting_add_agent_name", {"uid": target_uid})
                uname = f"@{target_user['username']}" if target_user and target_user['username'] else str(target_uid)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agents", style="danger"))
                bot.send_message(chat_id, f"المستخدم: {uname}\n\nأرسل اسم الوكيل:", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agents", style="danger")))

        elif state == "waiting_add_agent_name":
            if user_id != OWNER_ID: return
            name = message.text.strip()
            data = user_state.get('data', {}) or {}
            db.set_user_state(user_id, "waiting_add_agent_contact", {"uid": data.get('uid'), "name": name})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agents", style="danger"))
            bot.send_message(chat_id, f"الاسم: {name}\n\nأرسل طريقة التواصل (@username أو رقم):", reply_markup=keyboard)

        elif state == "waiting_add_agent_contact":
            if user_id != OWNER_ID: return
            contact = message.text.strip()
            data = user_state.get('data', {}) or {}
            db.set_user_state(user_id, "waiting_add_agent_desc", {"uid": data.get('uid'), "name": data.get('name'), "contact": contact})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 تخطي", callback_data="skip_agent_desc", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agents", style="danger"))
            bot.send_message(chat_id, "أرسل وصفاً مختصراً (اختياري):", reply_markup=keyboard)

        elif state == "waiting_add_agent_desc":
            if user_id != OWNER_ID: return
            desc = message.text.strip()
            data = user_state.get('data', {}) or {}
            db.add_agent(data['uid'], data['name'], desc, data['contact'], OWNER_ID)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🧑‍💼 إدارة الوكلاء", callback_data="admin_agents", style="primary"))
            bot.send_message(chat_id, f" *تم إضافة الوكيل!*\n\nالاسم: {md_escape(data['name'])}\nالوصف: {md_escape(desc)}\nالتواصل: {md_escape(data['contact'])}", reply_markup=keyboard, parse_mode="Markdown")
            try:
                bot.send_message(data['uid'], "تم تعيينك وكيلاً في البوت!\nستظهر معلوماتك للمستخدمين في قسم الوكلاء.")
            except Exception:
                pass

        elif state == "waiting_remove_agent_id":
            if user_id != OWNER_ID: return
            try:
                target_uid = int(message.text.strip())
                if not db.is_agent(target_uid):
                    bot.send_message(chat_id, "هذا المستخدم ليس وكيلاً!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agents", style="danger")))
                    return
                db.remove_agent(target_uid)
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🧑‍💼 إدارة الوكلاء", callback_data="admin_agents", style="primary"))
                bot.send_message(chat_id, "تم حذف الوكيل.", reply_markup=keyboard)
                try: bot.send_message(target_uid, "تم إلغاء تعيينك كوكيل.")
                except Exception: pass
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_agents", style="danger")))

        # تنبيه إداري لوكيل — يُسجَّل في ملفه ويُرسَل له مباشرة 
        elif state == "waiting_agent_warn_reason":
            if user_id != OWNER_ID: return
            data = user_state.get('data', {}) or {}
            agent_uid = data.get('uid')
            db.clear_user_state(user_id)
            if not agent_uid:
                bot.send_message(chat_id, "انتهت الجلسة.")
                return
            reason = message.text.strip()
            db.add_agent_warning(agent_uid, reason, user_id, warning_type='warning')
            try:
                bot.send_message(chat_id=agent_uid, text=f"⚠️ تنبيه من الإدارة\n\n{reason}\n\nيرجى الالتزام بقوانين الوكالة لتجنب إجراءات أشد.")
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع لملف الوكيل", callback_data=f"admin_agent_detail_{agent_uid}", style="primary"))
            bot.send_message(chat_id, "✅ تم إرسال التنبيه للوكيل وتسجيله في ملفه.", reply_markup=keyboard)

        # بلاغ/رسالة إدارية مباشرة لوكيل — يُسجَّل في ملفه ويُرسَل له 
        elif state == "waiting_agent_notice_text":
            if user_id != OWNER_ID: return
            data = user_state.get('data', {}) or {}
            agent_uid = data.get('uid')
            db.clear_user_state(user_id)
            if not agent_uid:
                bot.send_message(chat_id, "انتهت الجلسة.")
                return
            notice_text = message.text.strip()
            db.add_agent_warning(agent_uid, notice_text, user_id, warning_type='notice')
            try:
                bot.send_message(chat_id=agent_uid, text=f"📨 رسالة من الإدارة\n\n{notice_text}")
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع لملف الوكيل", callback_data=f"admin_agent_detail_{agent_uid}", style="primary"))
            bot.send_message(chat_id, "✅ تم إرسال البلاغ للوكيل وتسجيله في ملفه.", reply_markup=keyboard)


            try:
                target_uid = int(message.text.strip())
                target_user = db.get_user(target_uid)
                # نسمح بالإضافة حتى لو المستخدم لم يسجل في البوت بعد
                if not target_user:
                    db.conn.execute(
                        "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                        (target_uid, None, f"user_{target_uid}")
                    )
                    db.conn.commit()
                    target_user = db.get_user(target_uid)
                db.set_user_state(user_id, "waiting_add_broker_name", {"uid": target_uid})
                uname = f"@{target_user['username']}" if target_user and target_user['username'] else str(target_uid)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_brokers", style="danger"))
                bot.send_message(chat_id, f"المستخدم: {uname}\n\nأرسل اسم الوسيط:", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_brokers", style="danger")))

        elif state == "waiting_add_broker_name":
            if user_id != OWNER_ID: return
            name = message.text.strip()
            data = user_state.get('data', {}) or {}
            db.set_user_state(user_id, "waiting_add_broker_contact", {"uid": data.get('uid'), "name": name})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_brokers", style="danger"))
            bot.send_message(chat_id, f"الاسم: {name}\n\nأرسل طريقة التواصل (@username):", reply_markup=keyboard)

        elif state == "waiting_add_broker_contact":
            if user_id != OWNER_ID: return
            contact = message.text.strip()
            data = user_state.get('data', {}) or {}
            db.set_user_state(user_id, "waiting_add_broker_desc", {"uid": data.get('uid'), "name": data.get('name'), "contact": contact})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 تخطي", callback_data="skip_broker_desc", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_brokers", style="danger"))
            bot.send_message(chat_id, "أرسل وصفاً مختصراً (اختياري):", reply_markup=keyboard)

        elif state == "waiting_add_broker_desc":
            if user_id != OWNER_ID: return
            desc = message.text.strip()
            data = user_state.get('data', {}) or {}
            db.add_broker(data['uid'], data['name'], desc, data['contact'], OWNER_ID)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 إدارة الوسطاء", callback_data="admin_brokers", style="primary"))
            bot.send_message(chat_id, f" *تم إضافة الوسيط!*\n\nالاسم: {md_escape(data['name'])}\nالوصف: {md_escape(desc)}\nالتواصل: {md_escape(data['contact'])}", reply_markup=keyboard, parse_mode="Markdown")
            try:
                bot.send_message(data['uid'], "تم تعيينك وسيطاً في البوت!\nمهمتك: ضمان حق الطرفين في عمليات البيع والشراء.")
            except Exception:
                pass

        elif state == "waiting_remove_broker_id":
            if user_id != OWNER_ID: return
            try:
                target_uid = int(message.text.strip())
                if not db.is_broker(target_uid):
                    bot.send_message(chat_id, "هذا المستخدم ليس وسيطاً!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_brokers", style="danger")))
                    return
                db.remove_broker(target_uid)
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🤝 إدارة الوسطاء", callback_data="admin_brokers", style="primary"))
                bot.send_message(chat_id, "تم حذف الوسيط.", reply_markup=keyboard)
                try: bot.send_message(target_uid, "تم إلغاء تعيينك كوسيط.")
                except Exception: pass
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح!", reply_markup=types.InlineKeyboardMarkup().row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_brokers", style="danger")))

        # تنبيه إداري لوسيط — يُسجَّل في ملفه ويُرسَل له مباشرة 
        elif state == "waiting_broker_warn_reason":
            if user_id != OWNER_ID: return
            data = user_state.get('data', {}) or {}
            broker_uid = data.get('uid')
            db.clear_user_state(user_id)
            if not broker_uid:
                bot.send_message(chat_id, "انتهت الجلسة.")
                return
            reason = message.text.strip()
            db.add_broker_warning(broker_uid, reason, user_id, warning_type='warning')
            try:
                bot.send_message(chat_id=broker_uid, text=f"⚠️ تنبيه من الإدارة\n\n{reason}\n\nيرجى الالتزام بقوانين الوساطة لتجنب إجراءات أشد.")
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع لملف الوسيط", callback_data=f"admin_broker_detail_{broker_uid}", style="primary"))
            bot.send_message(chat_id, "✅ تم إرسال التنبيه للوسيط وتسجيله في ملفه.", reply_markup=keyboard)

        # بلاغ/رسالة إدارية مباشرة لوسيط — يُسجَّل في ملفه ويُرسَل له 
        elif state == "waiting_broker_notice_text":
            if user_id != OWNER_ID: return
            data = user_state.get('data', {}) or {}
            broker_uid = data.get('uid')
            db.clear_user_state(user_id)
            if not broker_uid:
                bot.send_message(chat_id, "انتهت الجلسة.")
                return
            notice_text = message.text.strip()
            db.add_broker_warning(broker_uid, notice_text, user_id, warning_type='notice')
            try:
                bot.send_message(chat_id=broker_uid, text=f"📨 رسالة من الإدارة\n\n{notice_text}")
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع لملف الوسيط", callback_data=f"admin_broker_detail_{broker_uid}", style="primary"))
            bot.send_message(chat_id, "✅ تم إرسال البلاغ للوسيط وتسجيله في ملفه.", reply_markup=keyboard)

        # طلب شحن عبر وكيل: السبب + الكمية 
        elif state == "waiting_agent_charge_reason":
            data = user_state.get('data', {}) or {}
            agent_uid = data.get('agent_uid')
            if not agent_uid:
                db.clear_user_state(user_id)
                bot.send_message(chat_id, "انتهت الجلسة.")
                return
            db.set_user_state(user_id, "waiting_agent_charge_amount", {"agent_uid": agent_uid, "reason": message.text.strip()})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"agent_detail_{agent_uid}", style="danger"))
            bot.send_message(chat_id, " *كم مبلغ الشحن الذي تريده؟*\n\nأرسل المبلغ بالدولار الأمريكي\nمثال: 5000", reply_markup=keyboard, parse_mode="Markdown")

        elif state == "waiting_agent_charge_amount":
            data = user_state.get('data', {}) or {}
            agent_uid = data.get('agent_uid')
            reason = data.get('reason', '')
            try:
                amount = float(message.text.strip().replace(',', ''))
                if amount <= 0:
                    raise ValueError
            except ValueError:
                bot.send_message(chat_id, "أدخل مبلغاً صحيحاً بالدولار.")
                return
            ok, req_id = db.create_agent_charge_request(user_id, agent_uid, amount, reason)
            db.clear_user_state(user_id)
            if ok:
                agents_list = db.get_all_agents()
                ag = next((a for a in agents_list if a['user_id'] == agent_uid), None)
                ag_name = ag['name'] if ag else str(agent_uid)
                req_data = db.get_agent_charge_request_by_id(req_id)
                if req_data:
                    notify_agent_new_request(agent_uid, req_data)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ قائمة الوكلاء", callback_data="show_agents", style="primary"))
                bot.send_message(chat_id, f" *تم إرسال طلبك للوكيل {ag_name}!*\n\nالمبلغ: {amount:.2f}$\nسيصلك رد قريباً.", reply_markup=keyboard, parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "فشل إرسال الطلب، حاول مجدداً.")

        # طلب وساطة: اختيار نوع الخدمة (نصي — احتياطي لو ضاع الكيبورد)
        elif state == "waiting_broker_service_type":
            data = user_state.get('data', {}) or {}
            broker_uid = data.get('broker_uid')
            if not broker_uid:
                db.clear_user_state(user_id)
                bot.send_message(chat_id, "انتهت الجلسة.",
                    reply_markup=types.InlineKeyboardMarkup().row(
                        types.InlineKeyboardButton("🔹 قائمة الوسطاء", callback_data="show_brokers", style="primary")))
                return
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔙 رجوع", callback_data=f"broker_detail_{broker_uid}", style="danger"))
            bot.send_message(chat_id, "اختر نوع الصفقة من الأزرار أعلاه.", reply_markup=keyboard)

        # طلب وساطة: تفاصيل الصفقة 
        elif state == "waiting_broker_request_details":
            data = user_state.get('data', {}) or {}
            broker_uid = data.get('broker_uid')
            service_type = data.get('service_type', 'other')
            details = message.text.strip()
            if not broker_uid:
                db.clear_user_state(user_id)
                bot.send_message(chat_id, "انتهت الجلسة.")
                return
            ok, req_id = db.create_broker_request(user_id, broker_uid, service_type, details)
            db.clear_user_state(user_id)
            if ok:
                brokers_list = db.get_all_brokers()
                br = next((b for b in brokers_list if b['user_id'] == broker_uid), None)
                br_name = br['name'] if br else str(broker_uid)
                req_data = db.get_broker_request_by_id(req_id)
                if req_data:
                    notify_broker_new_request(broker_uid, req_data)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 قائمة الوسطاء", callback_data="show_brokers", style="primary"))
                bot.send_message(chat_id, f" *تم إرسال طلبك للوسيط {br_name}!*\n\nسيصلك رد قريباً.", reply_markup=keyboard, parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "فشل إرسال الطلب، حاول مجدداً.")

        # رابط مجموعة الوساطة 
        # حالات إنشاء المسابقة (أدمن)
        elif state == "admin_contest_step1":
            if user_id != OWNER_ID: return
            name = message.text.strip()[:100]
            db.set_user_state(user_id, "admin_contest_step2", {"name": name})
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_contests", style="danger"))
            bot.send_message(chat_id, f"✅ الاسم: *{name}*\n\n*الخطوة 2/5:* أرسل وصف المسابقة:", reply_markup=keyboard, parse_mode="Markdown")

        elif state == "admin_contest_step2":
            if user_id != OWNER_ID: return
            desc = message.text.strip()[:500]
            data = (user_state.get('data') or {})
            data['description'] = desc
            db.set_user_state(user_id, "admin_contest_step3", data)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("⏭ تخطي (هدية مادية فقط)", callback_data="admin_contest_skip_prize", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_contests", style="danger"))
            bot.send_message(
                chat_id,
                f"✅ الوصف: {desc[:60]}...\n\n"
                f"*الخطوة 3/5:* مبلغ الجائزة بالدولار _(اختياري)_\n\n"
                f"أرسل رقماً إذا كانت الجائزة مالية، أو اضغط *تخطي* إذا كانت هدية مادية فقط:",
                reply_markup=keyboard, parse_mode="Markdown"
            )

        elif state == "admin_contest_step3":
            if user_id != OWNER_ID: return
            raw_prize = message.text.strip().replace(',', '')
            try:
                prize_amount = float(raw_prize)
                if prize_amount < 0:
                    raise ValueError
            except ValueError:
                bot.send_message(chat_id, "❌ أرسل رقماً صحيحاً فقط!\nمثال: `5000`\n\nأو اضغط *تخطي* إذا كانت هدية مادية.", parse_mode="Markdown")
                return
            data = (user_state.get('data') or {})
            data['prize'] = prize_amount
            db.set_user_state(user_id, "admin_contest_step3b", data)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("✏️ تحديد الجائزة — ماذا يحصل الفائز؟", callback_data="admin_contest_write_prize_desc", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_contests", style="danger"))
            bot.send_message(
                chat_id,
                f"✅ المبلغ: *{prize_amount:.2f}$*\n\n"
                f"*الخطوة 4/5:* حدد ماذا يحصل الفائز\n\n"
                f"اضغط الزر أدناه لكتابة وصف الجائزة:\n"
                f"_(مثال: كود شحن زين، رصيد خارجي، هدية مادية...)_",
                reply_markup=keyboard, parse_mode="Markdown"
            )

        elif state == "admin_contest_step3b":
            if user_id != OWNER_ID: return
            prize_desc = message.text.strip()[:300]
            data = (user_state.get('data') or {})
            data['prize_description'] = prize_desc
            db.set_user_state(user_id, "admin_contest_step4", data)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 دقيقة واحدة من الآن", callback_data="admin_contest_in_1min", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 ساعة من الآن", callback_data="admin_contest_in_1h", style="primary"))
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_contests", style="danger"))
            bot.send_message(
                chat_id,
                f"🎁 وصف الجائزة: {prize_desc[:80]}\n\n"
                f"*الخطوة 5/5:* متى يبدأ السحب؟\n\n"
                f"أرسل الوقت بالصيغة: `YYYY-MM-DD HH:MM`\nمثال: `{datetime.now().strftime('%Y-%m-%d')} 20:00`\n\n"
                f"أو اضغط أحد الأزرار أدناه:",
                reply_markup=keyboard, parse_mode="Markdown"
            )

        elif state == "admin_contest_step4":
            if user_id != OWNER_ID: return
            raw = message.text.strip()
            try:
                start_at = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            except ValueError:
                bot.send_message(chat_id, "صيغة غير صحيحة!\nاستخدم: `YYYY-MM-DD HH:MM`", parse_mode="Markdown")
                return
            data = (user_state.get('data') or {})
            ok, contest_id = db.create_contest(
                data.get('name', 'مسابقة'), data.get('description', ''),
                data.get('prize', 0), start_at, user_id,
                prize_description=data.get('prize_description', '')
            )
            db.clear_user_state(user_id)
            if ok:
                _schedule_contest_draw(contest_id, start_at)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔹 إدارة المسابقة", callback_data=f"admin_contest_{contest_id}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔹 نشر الآن", callback_data=f"admin_publish_contest_{contest_id}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🎯 إدارة المسابقات", callback_data="admin_contests", style="primary"))
                bot.send_message(
                    chat_id,
                    f"✅ *تم إنشاء المسابقة #{contest_id}!*\n\n"
                    f"الاسم: {md_escape(data.get('name', ''))}\n"
                    f"الجائزة: {md_escape(data.get('prize_description') or str(int(data.get('prize', 0))) + '$')}\n"
                    f"السحب في: {start_at.strftime('%Y-%m-%d %H:%M')}",
                    reply_markup=keyboard, parse_mode="Markdown"
                )
            else:
                bot.send_message(chat_id, f" فشل الإنشاء: {contest_id}")

        elif state == "waiting_broker_group_id":
            if user_id != OWNER_ID: return
            raw = message.text.strip()
            try:
                grp_id = int(raw)
                db.set_bot_setting('broker_group_id', str(grp_id))
                invite_link = ""
                try:
                    invite_link = bot.export_chat_invite_link(grp_id)
                    db.set_bot_setting('broker_group_link', invite_link)
                except Exception:
                    pass
                db.clear_user_state(user_id)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🤝 إدارة الوسطاء", callback_data="admin_brokers", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                link_line = f"\nرابط الدعوة: {invite_link}" if invite_link else ""
                bot.send_message(chat_id, f" *تم حفظ مجموعة الوساطة!*\n\nالـ Chat ID: `{grp_id}`{link_line}", reply_markup=keyboard, parse_mode="Markdown")
            except ValueError:
                bot.send_message(chat_id, "يجب أن يكون Chat ID رقماً مثل: -1001234567890")

        elif state == "waiting_broker_group_link":
            if user_id != OWNER_ID: return
            link = message.text.strip()
            db.set_bot_setting('broker_group_link', link)
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 إعداد المجموعة", callback_data="admin_set_broker_group", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🤝 إدارة الوسطاء", callback_data="admin_brokers", style="primary"))
            bot.send_message(chat_id, f" *تم حفظ رابط مجموعة الوساطة:*\n{link}", reply_markup=keyboard, parse_mode="Markdown")

        # تعليق تقييم الوكيل 
        elif state == "waiting_agent_rating_comment":
            data = db.get_user_state(user_id)
            st_data = data['data'] if data else {}
            agent_uid_r = st_data.get('agent_uid')
            req_id_r = st_data.get('req_id')
            comment = message.text.strip()[:300]
            if agent_uid_r and req_id_r:
                # تحديث التعليق في التقييم الموجود
                try:
                    db.conn.execute(
                        "UPDATE agent_ratings SET comment=? WHERE user_id=? AND req_id=?",
                        (comment, user_id, req_id_r)
                    )
                    db.conn.commit()
                except Exception as e:
                    logger.error(f"Error updating agent rating comment: {e}")
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 عرض الوكيل", callback_data=f"agent_detail_{agent_uid_r}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.send_message(chat_id, " *شكراً! تم حفظ تقييمك وتعليقك.*", reply_markup=keyboard, parse_mode="Markdown")

        # تعليق تقييم الوسيط 
        elif state == "waiting_broker_rating_comment":
            data = db.get_user_state(user_id)
            st_data = data['data'] if data else {}
            broker_uid_r = st_data.get('broker_uid')
            req_id_r = st_data.get('req_id')
            comment = message.text.strip()[:300]
            if broker_uid_r and req_id_r:
                try:
                    db.conn.execute(
                        "UPDATE broker_ratings SET comment=? WHERE user_id=? AND req_id=?",
                        (comment, user_id, req_id_r)
                    )
                    db.conn.commit()
                except Exception as e:
                    logger.error(f"Error updating broker rating comment: {e}")
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🔹 عرض الوسيط", callback_data=f"broker_detail_{broker_uid_r}", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))
            bot.send_message(chat_id, " *شكراً! تم حفظ تقييمك وتعليقك.*", reply_markup=keyboard, parse_mode="Markdown")

        # إنشاء كود شحن من لوحة الوكيل 
        elif state == "agent_creating_code":
            if not db.is_agent(user_id):
                db.clear_user_state(user_id)
                return
            try:
                amount = float(message.text.strip().replace(',', ''))
                if amount <= 0: raise ValueError
            except ValueError:
                bot.send_message(chat_id, "أدخل مبلغاً صحيحاً.")
                return
            balance = db.get_balance(user_id)
            if balance < amount:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="my_agent_panel", style="danger"))
                bot.send_message(chat_id, f"رصيدك غير كافٍ!\n\nرصيدك: {balance:.2f}$\nالمطلوب: {amount:.2f}$", reply_markup=keyboard)
                return
            # إنشاء الكود مسبقاً لكن حفظه معلقاً
            pending_code = hashlib.md5(f"{user_id}{amount}{datetime.now()}".encode()).hexdigest()[:10].upper()
            op_id = db.create_agent_pending_op("code", user_id, amount, code=pending_code)
            if not op_id:
                bot.send_message(chat_id, "حدث خطأ، حاول مجدداً!")
                return
            db.clear_user_state(user_id)
            # إشعار الأدمن
            agents_list = db.get_all_agents()
            ag = next((a for a in agents_list if a['user_id'] == user_id), None)
            ag_name = ag['name'] if ag else str(user_id)
            keyboard_admin = types.InlineKeyboardMarkup()
            keyboard_admin.row(
                types.InlineKeyboardButton("✅ موافقة", callback_data=f"admin_approve_agent_op_{op_id}", style="primary"),
                types.InlineKeyboardButton("❌ رفض مع سبب", callback_data=f"admin_reject_agent_op_reason_{op_id}", style="danger")
            )
            keyboard_admin.row(
                types.InlineKeyboardButton("⛔ رفض فوري", callback_data=f"admin_reject_agent_op_{op_id}", style="danger")
            )
            try:
                bot.send_message(
                    OWNER_ID,
                    f"🔐 *طلب إنشاء كود شحن من وكيل*\n\n"
                    f"الوكيل: {md_escape(ag_name)} (`{user_id}`)\n"
                    f"قيمة الكود: *{amount:.2f}$*\n"
                    f"رصيد الوكيل: {balance:.2f}$\n"
                    f"الكود المقترح: `{pending_code}`",
                    reply_markup=keyboard_admin, parse_mode="Markdown"
                )
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
            bot.send_message(
                chat_id,
                f"⏳ *تم إرسال طلب إنشاء الكود للإدارة*\n\n"
                f"قيمة الكود: {amount:.2f}$\n"
                f"بانتظار موافقة الأدمن — ستصلك رسالة فور الرد.",
                reply_markup=keyboard, parse_mode="Markdown"
            )

        # تحويل مباشر من لوحة الوكيل 
        elif state == "agent_direct_transfer_id":
            if not db.is_agent(user_id): return
            try:
                target_uid = int(message.text.strip())
                target_user = db.get_user(target_uid)
                if not target_user:
                    bot.send_message(chat_id, "المستخدم غير مسجل في البوت!")
                    return
                db.set_user_state(user_id, "agent_direct_transfer_amount", {"target_uid": target_uid})
                uname = f"@{target_user['username']}" if target_user['username'] else target_user['first_name'] or str(target_uid)
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="my_agent_panel", style="danger"))
                bot.send_message(chat_id, f"المستخدم: {uname}\n\nأرسل المبلغ بالدولار:", reply_markup=keyboard)
            except ValueError:
                bot.send_message(chat_id, "أيدي غير صالح!")

        elif state == "agent_direct_transfer_amount":
            if not db.is_agent(user_id): return
            data = user_state.get('data', {}) or {}
            target_uid = data.get('target_uid')
            try:
                amount = float(message.text.strip().replace(',', ''))
                if amount <= 0: raise ValueError
            except ValueError:
                bot.send_message(chat_id, "أدخل مبلغاً صحيحاً.")
                return
            balance = db.get_balance(user_id)
            if balance < amount:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data="my_agent_panel", style="danger"))
                bot.send_message(chat_id, f"رصيدك غير كافٍ!\n\nرصيدك: {balance:.2f}$\nالمطلوب: {amount:.2f}$", reply_markup=keyboard)
                return
            op_id = db.create_agent_pending_op("transfer", user_id, amount, target_uid=target_uid)
            if not op_id:
                bot.send_message(chat_id, "حدث خطأ، حاول مجدداً!")
                return
            target_user = db.get_user(target_uid)
            uname = f"@{target_user['username']}" if target_user and target_user['username'] else str(target_uid)
            agents_list = db.get_all_agents()
            ag = next((a for a in agents_list if a['user_id'] == user_id), None)
            ag_name = ag['name'] if ag else str(user_id)
            keyboard_admin = types.InlineKeyboardMarkup()
            keyboard_admin.row(
                types.InlineKeyboardButton("✅ موافقة", callback_data=f"admin_approve_agent_op_{op_id}", style="primary"),
                types.InlineKeyboardButton("❌ رفض مع سبب", callback_data=f"admin_reject_agent_op_reason_{op_id}", style="danger")
            )
            keyboard_admin.row(
                types.InlineKeyboardButton("⛔ رفض فوري", callback_data=f"admin_reject_agent_op_{op_id}", style="danger")
            )
            try:
                bot.send_message(
                    OWNER_ID,
                    f"💸 *طلب تحويل مباشر من وكيل*\n\n"
                    f"الوكيل: {md_escape(ag_name)} (`{user_id}`)\n"
                    f"المستلم: {md_escape(uname)} (`{target_uid}`)\n"
                    f"المبلغ: *{amount:.2f}$*\n"
                    f"رصيد الوكيل: {balance:.2f}$",
                    reply_markup=keyboard_admin, parse_mode="Markdown"
                )
            except Exception: pass
            db.clear_user_state(user_id)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🤝 لوحة الوكيل", callback_data="my_agent_panel", style="primary"))
            bot.send_message(
                chat_id,
                f"⏳ *تم إرسال طلب التحويل للإدارة*\n\n"
                f"المستلم: {md_escape(uname)}\n"
                f"المبلغ: {amount:.2f}$\n"
                f"بانتظار موافقة الأدمن — ستصلك رسالة فور الرد.",
                reply_markup=keyboard, parse_mode="Markdown"
            )

        elif state.startswith("ai_legal_chat_"):
            # محادثة الذكاء القانوني 
            session_id = int(state.replace("ai_legal_chat_", ""))
            session = db_get_open_legal_session(user_id)
            if not session or session['ticket_id'] != session_id:
                db.clear_user_state(user_id)
                bot.send_message(chat_id, "انتهت جلسة الاستشارة. اضغط القوانين للبدء من جديد.")
                return
            user_text = message.text.strip() if message.text else ""
            if not user_text:
                bot.send_message(chat_id, "أرسل سؤالك نصياً.")
                return
            history = session['ai_history']
            history.append({"role": "user", "content": user_text})
            # مؤشر الانتظار
            wait_msg = bot.send_message(chat_id, "مستشار المزادات يفكر...")
            ai_reply = ask_ai_legal(history)
            if not ai_reply:
                ai_reply = (
                    "عذراً، تعذّر على الذكاء الاصطناعي الرد الآن.\n\n"
                    "يمكنك قراءة القوانين كاملةً من زر القوانين،\n"
                    "أو التواصل مع الإدارة مباشرةً."
                )
            history.append({"role": "assistant", "content": ai_reply})
            # حفظ التاريخ
            cursor_obj = db.conn.cursor()
            cursor_obj.execute(
                "UPDATE support_tickets SET ai_history=? WHERE ticket_id=?",
                (json.dumps(history, ensure_ascii=False), session_id)
            )
            db.conn.commit()
            # حذف مؤشر الانتظار
            try:
                bot.delete_message(chat_id, wait_msg.message_id)
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("📜 عرض القوانين كاملةً", callback_data="rules", style="primary"))
            keyboard.row(types.InlineKeyboardButton("🔹 إنهاء الجلسة", callback_data=f"ai_legal_end_{session_id}", style="danger"))
            bot.send_message(
                chat_id,
                f" *مستشار المزادات:*\n\n{ai_reply}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif state.startswith("ai_support_chat_"):
            ticket_id = int(state.replace("ai_support_chat_", ""))
            ticket = db_get_ticket_by_id(ticket_id)
            if not ticket or ticket['user_id'] != user_id:
                db.clear_user_state(user_id)
                bot.send_message(chat_id, "انتهت جلسة الدعم.")
                return
            user_text = message.text.strip() if message.text else ""
            if not user_text:
                bot.send_message(chat_id, "أرسل رسالة نصية.")
                return
            history = ticket['ai_history']
            history.append({"role": "user", "content": user_text})
            # عدد رسائل المستخدم — لو وصل 4 نقترح الإرسال
            user_msg_count = sum(1 for m in history if m['role'] == 'user')
            # إشعار الانتظار
            wait_msg = bot.send_message(chat_id, "مساعد الدعم يفكر...")
            ai_reply = ask_claude(history, user_id=user_id)
            ai_log_id = get_ai_last_log_id(history)
            if not ai_reply:
                ai_reply = (
                    "شكراً على تواصلك \n\n"
                    "تعذّر الرد الآن، لكن مشكلتك وصلت لي.\n"
                    "اضغط *« إرسال للإدارة»* وستصلهم مباشرة."
                )
            history.append({"role": "assistant", "content": ai_reply})
            db_update_ticket_history(ticket_id, history)
            try:
                bot.delete_message(chat_id, wait_msg.message_id)
            except Exception:
                pass
            keyboard = types.InlineKeyboardMarkup()
            # لو كانت المحادثة طويلة، أظهر زر الإرسال أولاً وبشكل أوضح
            if user_msg_count >= 3:
                keyboard.row(types.InlineKeyboardButton("تم الحل — شكراً!", callback_data=f"ai_support_resolved_{ticket_id}", style="primary"))
                keyboard.row(types.InlineKeyboardButton("🔹 إرسال للإدارة", callback_data=f"ai_support_send_{ticket_id}", style="primary"))
            else:
                keyboard.row(types.InlineKeyboardButton("🔹 إرسال للإدارة", callback_data=f"ai_support_send_{ticket_id}", style="primary"))
            if ai_log_id:
                keyboard.row(
                    types.InlineKeyboardButton("👍 الرد مفيد", callback_data=f"ai_feedback_up_{ai_log_id}", style="primary"),
                    types.InlineKeyboardButton("👎 لم يساعد", callback_data=f"ai_feedback_down_{ai_log_id}", style="danger")
                )
            keyboard.row(types.InlineKeyboardButton("❌ إلغاء", callback_data=f"ai_support_cancel_{ticket_id}", style="danger"))
            bot.send_message(
                chat_id,
                f" *مساعد الدعم:*\n\n{ai_reply}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

        elif state == "support_replying":
            if user_id != OWNER_ID:
                return
            data = user_state.get('data', {}) or {}
            target_uid = data.get('target_uid')
            ticket_id = data.get('ticket_id')
            reply_text = message.text.strip() if message.text else ""
            if not reply_text:
                bot.send_message(chat_id, "الرسالة فارغة!")
                return
            db.clear_user_state(user_id)
            try:
                bot.send_message(
                    target_uid,
                    f" *رد الإدارة على تذكرتك #{ticket_id}:*\n\n{reply_text}",
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup().row(
                        types.InlineKeyboardButton("🔹 فتح تذكرة جديدة", callback_data="ai_support_new", style="primary")
                    )
                )
                keyboard = types.InlineKeyboardMarkup()
                keyboard.row(types.InlineKeyboardButton("🔧 لوحة الإدارة", callback_data="admin_panel", style="primary"))
                bot.send_message(chat_id, f"تم إرسال ردك للمستخدم {target_uid}", reply_markup=keyboard)
            except Exception as e:
                bot.send_message(chat_id, f"فشل الإرسال: {e}")

        else:
            db.clear_user_state(user_id)
            balance = db.get_balance(user_id)
            active_count = len(db.get_active_auctions())
            welcome_text = (
                f"*'''  منصة المزادات الرسمية  '''*\n"
                f"\n\n"
                f"اهلاً بك، *{message.from_user.first_name}*\n\n"
                f"الرصيد:  `{balance:.2f}$`\n"
                f"المزادات النشطة:  `{active_count}`\n\n"
                f"\n"
                f"المنصة الاولى والموثوقة لبيع وشراء\n"
                f"معرفات وقنوات وبوتات وهدايا تيليجرام"
            )
            keyboard = create_main_menu_keyboard(user_id)
            bot.send_message(chat_id, welcome_text, parse_mode="Markdown", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error handling message (state={user_state['state'] if user_state else 'None'}): {e}\n{traceback.format_exc()}")
        bot.send_message(chat_id, "حدث خطأ! حاول مرة أخرى.")
        db.clear_user_state(user_id)

# 
# معالج pre_checkout للنجوم (إلزامي) 
# 
@bot.pre_checkout_query_handler(func=lambda q: True)
def handle_pre_checkout(query):
    try:
        # يجب الرد خلال 10 ثواني وإلا تفشل العملية
        bot.answer_pre_checkout_query(query.id, ok=True)
    except Exception as e:
        logger.error(f"Error answering pre_checkout: {e}")
        bot.answer_pre_checkout_query(query.id, ok=False, error_message="حدث خطأ، حاول مرة أخرى")

# 
# معالج successful_payment للنجوم 
# 
@bot.message_handler(content_types=['successful_payment'])
def handle_successful_payment(message):
    try:
        payment = message.successful_payment
        user_id = message.from_user.id
        chat_id = message.chat.id

        # فقط نعالج مدفوعات النجوم (XTR)
        if payment.currency != "XTR":
            return

        payload = payment.invoice_payload
        charge_id = payment.telegram_payment_charge_id
        stars_amount = payment.total_amount

        # أكمل الدفعة وأضف الرصيد
        success, result = db.complete_stars_payment(payload, charge_id)

        if success:
            credited_user_id, usd_amount = result
            new_balance = db.get_balance(credited_user_id)

            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="back_to_main", style="primary"))

            bot.send_message(
                chat_id,
                f" *تم شحن رصيدك بنجاح!*\n\n"
                f"النجوم المدفوعة: {stars_amount}\n"
                f"الرصيد المضاف: {usd_amount:.2f}$\n"
                f"رصيدك الجديد: {new_balance:.2f}$\n\n"
                f"رقم العملية: `{charge_id}`",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

            # إشعار الأدمن
            user_info = db.get_user(credited_user_id)
            uname = f"@{user_info['username']}" if user_info and user_info['username'] else f"ID {credited_user_id}"
            bot.send_message(
                OWNER_ID,
                f" *شحن ناجح عبر النجوم!*\n\n"
                f"المستخدم: {uname}\n"
                f"النجوم: {stars_amount} \n"
                f"الرصيد المضاف: {usd_amount:.2f}$",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                chat_id,
                f"تم استلام الدفع لكن حدث خطأ في إضافة الرصيد.\n"
                f"رقم العملية: `{charge_id}`\n\n"
                f"تواصل مع الإدارة لحل المشكلة.",
                parse_mode="Markdown"
            )
            bot.send_message(
                OWNER_ID,
                f" *خطأ في إضافة رصيد نجوم!*\n\n"
                f"المستخدم: {user_id}\n"
                f"النجوم: {stars_amount}\n"
                f"الـ payload: `{payload}`\n"
                f"charge_id: `{charge_id}`\n\n"
                f"أضف الرصيد يدوياً!",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error handling successful_payment: {e}")

# 
# نظام نشر وبث المزادات — تصميم بطاقات HTML احترافية 
# 

AUCTION_TYPE_ICONS = {
    "username": "🆔",
    "channel": "📢",
    "group": "👥",
    "bot": "🤖",
    "gift": "🎁",
}

def _auction_type_line(auction_info) -> str:
    t = auction_info.get('auction_type')
    icon = AUCTION_TYPE_ICONS.get(t, "📦")
    label = AUCTION_TYPES.get(t, "")
    return f"{icon} {hb('النوع:')} {html_escape(label)}"

def _auction_target_line(auction_info) -> str:
    if auction_info.get('auction_type') == 'gift':
        label = auction_info.get('title') or 'هدية تيليجرام مميزة'
    else:
        label = auction_info.get('target') or ''
    return f"🎯 {hb('الهدف:')} {html_escape(label)}"

def _platform_line(auction_info) -> str:
    platform = auction_info.get('platform') or ''
    if not platform:
        return ""
    label = "تليجرام" if platform == "telegram" else SOCIAL_PLATFORMS.get(platform, platform)
    return f"🌐 {hb('المنصة:')} {html_escape(label)}"

def _top_bidders_block(auction_id, limit=3) -> str:
    """يبني صندوق اقتباس لأعلى المزايدين مع ميداليات الترتيب"""
    bids = db.get_auction_bids(auction_id)
    if not bids:
        return ""
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, bid in enumerate(bids[:limit]):
        name = f"@{bid['username']}" if bid['username'] else (bid['first_name'] or "مستخدم")
        medal = medals[i] if i < len(medals) else "▪️"
        lines.append(f"{medal} {name} — {fmt_money(bid['amount'])}")
    inner = "\n".join(lines)
    return f"🏆 {hb('أعلى المزايدين')}\n{hquote(inner)}"


def notify_auction_target(auction_info):
    """إشعار القناة/المجموعة المرفوعة مزاداً بأن مزاداً قد بدأ عليها — بطاقة HTML احترافية"""
    auction_type = auction_info.get('auction_type', '')
    target = auction_info.get('target', '')
    if auction_type not in ('channel', 'group'):
        return # فقط للقنوات والمجموعات

    try:
        bot_username = get_bot_info()['username']
        deep_link = f"https://t.me/{bot_username}?start=auction_{auction_info['auction_id']}"
        what = "القناة" if auction_type == "channel" else "المجموعة"
        msg = "\n".join([
            f"📢 {hb('تنبيه مزاد')}",
            DIVIDER,
            f"تم رفع هذه {what} ({html_escape(target)}) للبيع بالمزايدة في بوت المزادات.",
            "",
            f"💰 {hb('السعر الابتدائي:')} {fmt_money(auction_info['starting_price'])}",
            f"⏳ {hb('المدة:')} {html_escape(auction_info['duration_hours'])} ساعة",
            DIVIDER,
            "👇 اضغط للمشاركة في المزايدة",
        ])
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(types.InlineKeyboardButton("🔥 شارك في المزايدة", url=deep_link, style="primary"))
        # استخرج المعرف الحقيقي للقناة
        raw = target.lstrip('@')
        try:
            chat = bot.get_chat(f"@{raw}" if not raw.lstrip('-').isdigit() else int(raw))
            bot.send_message(chat.id, msg, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"Could not notify target {target}: {e}")
    except Exception as e:
        logger.error(f"notify_auction_target error: {e}")


def format_time_remaining(ends_at_dt):
    if not ends_at_dt:
        return "غير محدد"
    diff = ends_at_dt - datetime.now()
    if diff.total_seconds() <= 0:
        return "انتهى"
    h = int(diff.total_seconds() // 3600)
    m = int((diff.total_seconds() % 3600) // 60)
    if h > 0:
        return f"{h}:{m:02d} ساعة"
    return f"{m} دقيقة"


def broadcast_new_auction(auction_info):
    """ينشر بطاقة مزاد جديد بتصميم HTML احترافي في كل قنوات البث"""
    channels = db.get_all_channels()
    if not channels:
        logger.info("لا توجد قنوات مضافة للبث")
        return
    bot_username = get_bot_info()['username']
    deep_link = f"https://t.me/{bot_username}?start=auction_{auction_info['auction_id']}"

    # حساب الوقت المتبقي
    ends_at_dt = db.parse_datetime(auction_info.get('ends_at', '')) if auction_info.get('ends_at') else None
    duration_hours = auction_info.get('duration_hours') or 5
    if not ends_at_dt:
        ends_at_dt = datetime.now() + timedelta(hours=duration_hours)
    created_at_dt = db.parse_datetime(auction_info.get('created_at', '')) if auction_info.get('created_at') else None

    is_urgent = bool(auction_info.get('is_urgent'))
    buy_now_price = auction_info.get('buy_now_price') or 0

    header = ("⚡️🔥 " + hb("مزاد عاجل جديد")) if is_urgent else ("🆕✨ " + hb("مزاد جديد"))

    parts = [
        f"{header}  {hc('#' + str(auction_info['auction_id']))}",
        DIVIDER,
        _auction_type_line(auction_info),
        _auction_target_line(auction_info),
    ]
    platform_line = _platform_line(auction_info)
    if platform_line:
        parts.append(platform_line)
    parts.append(DIVIDER)
    parts.append(f"💰 {hb('السعر الابتدائي:')} {fmt_money(auction_info['starting_price'])}")
    if buy_now_price > 0:
        parts.append(f"🛒 {hb('الشراء الفوري:')} {fmt_money(buy_now_price)}")
    parts.append(auction_time_block(ends_at_dt, duration_hours, created_at_dt))
    parts.append(f"📊 {hb('عدد المزايدات:')} {auction_info.get('bids_count', 0)}")
    if is_urgent:
        parts.append(DIVIDER)
        parts.append("⚡️ " + hb("مزاد عاجل — ينتهي بسرعة، لا تفوّت الفرصة!"))
    parts.append(DIVIDER)
    parts.append("👇 اضغط الزر أدناه للمشاركة في المزايدة الآن")

    message_text = "\n".join(parts)

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("🔥 شارك في المزايدة الآن", url=deep_link, style="primary"))

    def broadcast_thread():
        success_count = 0
        new_auction_sticker = db.get_random_sticker("new_auction")
        for channel in channels:
            channel_id = channel['channel_id']
            try:
                if new_auction_sticker:
                    try:
                        bot.send_sticker(channel_id, new_auction_sticker)
                    except Exception as e:
                        logger.warning(f"تعذر إرسال ملصق المزاد الجديد إلى {channel_id}: {e}")
                sent_msg = bot.send_message(
                    channel_id, message_text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                db.save_broadcast_message(auction_info['auction_id'], channel_id, sent_msg.message_id)
                success_count += 1
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error broadcasting to channel {channel_id}: {e}")
        logger.info(f"تم البث إلى {success_count} من {len(channels)} قنوات")
        # إشعار القناة/المجموعة المرفوعة مزاداً
        notify_auction_target(auction_info)
    thread = threading.Thread(target=broadcast_thread)
    thread.start()

def update_auction_broadcast(auction_id):
    """تحديث رسائل القنوات عند وجود مزايدة جديدة — بطاقة HTML حية تعرض السعر، شريط الوقت، وأعلى المزايدين"""
    broadcast_msgs = db.get_broadcast_messages(auction_id)
    if not broadcast_msgs:
        return
    auction_info = db.get_auction_by_id(auction_id)
    if not auction_info:
        return

    # حساب الوقت المتبقي
    ends_at_dt = db.parse_datetime(auction_info['ends_at'])
    duration_hours = auction_info.get('duration_hours') or 5
    if not ends_at_dt:
        ends_at_dt = datetime.now() + timedelta(hours=duration_hours)
    created_at_dt = db.parse_datetime(auction_info.get('created_at', '')) if auction_info.get('created_at') else None

    bot_username = get_bot_info()['username']
    deep_link = f"https://t.me/{bot_username}?start=auction_{auction_id}"

    top_bidders = _top_bidders_block(auction_id)

    parts = [
        f"🔥 {hb('مزاد نشط')}  {hc('#' + str(auction_id))}",
        DIVIDER,
        _auction_type_line(auction_info),
        _auction_target_line(auction_info),
    ]
    platform_line = _platform_line(auction_info)
    if platform_line:
        parts.append(platform_line)
    parts.append(DIVIDER)
    parts.append(f"💵 {hb('السعر الحالي:')} {fmt_money(auction_info['current_price'])}")
    parts.append(auction_time_block(ends_at_dt, duration_hours, created_at_dt))
    parts.append(f"📊 {hb('عدد المزايدات:')} {auction_info.get('bids_count', 0)}")
    if top_bidders:
        parts.append(DIVIDER)
        parts.append(top_bidders)
    parts.append(DIVIDER)
    parts.append("👇 اضغط للمزايدة الآن وتقدّم على المركز الأول!")

    message_text = "\n".join(parts)

    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("🔥 شارك في المزايدة الآن", url=deep_link, style="primary"))

    def do_update():
        for msg in broadcast_msgs:
            try:
                bot.edit_message_text(
                    message_text, msg['channel_id'], msg['message_id'],
                    parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True
                )
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Error updating broadcast in {msg['channel_id']}: {e}")

    threading.Thread(target=do_update, daemon=True).start()


def finalize_auction_broadcast(auction_id, winner_name=None):
    """تحديث رسائل القنوات عند انتهاء المزاد ببطاقة HTML نهائية، ثم حذفها بعد 5 دقائق"""
    broadcast_msgs = db.get_broadcast_messages(auction_id)
    if not broadcast_msgs:
        return
    auction_info = db.get_auction_by_id(auction_id)
    if not auction_info:
        return

    type_line = _auction_type_line(auction_info)
    target_line = _auction_target_line(auction_info)

    if winner_name:
        message_text = "\n".join([
            f"🏁 {hb('انتهى المزاد')}  {hc('#' + str(auction_id))}",
            DIVIDER,
            type_line,
            target_line,
            DIVIDER,
            f"💰 {hb('سعر البيع النهائي:')} {fmt_money(auction_info['sold_price'])}",
            f"🎉 {hb('الفائز:')} {html_escape(winner_name)}",
            DIVIDER,
            "تهانينا للفائز 🎊 ونلقاكم في مزاد جديد قريباً!",
        ])
    else:
        message_text = "\n".join([
            f"🏁 {hb('انتهى المزاد')}  {hc('#' + str(auction_id))}",
            DIVIDER,
            type_line,
            target_line,
            DIVIDER,
            "😔 انتهى المزاد بدون أي مزايدة",
        ])

    msgs_to_delete = list(broadcast_msgs)

    def do_finalize():
        for msg in msgs_to_delete:
            try:
                bot.edit_message_text(
                    message_text, msg['channel_id'], msg['message_id'],
                    parse_mode="HTML", disable_web_page_preview=True
                )
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Error finalizing broadcast in {msg['channel_id']}: {e}")
        # حذف بعد 5 دقائق
        time.sleep(300)
        for msg in msgs_to_delete:
            try:
                bot.delete_message(msg['channel_id'], msg['message_id'])
            except Exception as e:
                logger.error(f"Error deleting broadcast message: {e}")
        db.delete_broadcast_messages(auction_id)

    threading.Thread(target=do_finalize, daemon=True).start()


def check_ended_auctions():
    notified_30min = set() # تتبع المزادات التي أُرسل لها إشعار 30 دقيقة
    while True:
        try:
            # تنظيف notified_30min دورياً لتجنب تراكم الذاكرة
            if len(notified_30min) > 500:
                notified_30min.clear()

            # نجلب كل المزادات النشطة مباشرة من DB (بدون فلتر الوقت) لضمان معالجة المنتهية
            _cur = db.conn.cursor()
            _cur.execute("SELECT * FROM auctions WHERE status = 'active' ORDER BY ends_at ASC")
            _rows = _cur.fetchall()
            active_auctions = []
            for row in _rows:
                active_auctions.append({
                    'auction_id': row[0], 'user_id': row[1], 'auction_type': row[2],
                    'title': row[3], 'target': row[4], 'description': row[5],
                    'starting_price': row[6] or 0.0, 'current_price': row[7] or 0.0,
                    'current_bidder': row[8], 'status': row[9], 'duration_hours': row[10] or 5,
                    'created_at': row[11], 'ends_at': row[12], 'views': row[13] or 0,
                    'bids_count': row[14] or 0, 'sold_to': row[15], 'sold_at': row[16],
                    'sold_price': row[17] or 0.0, 'platform': row[18] or '', 'commission_paid': bool(row[19])
                })
            for auction in active_auctions:
                ends_at = db.parse_datetime(auction['ends_at'])
                if not ends_at:
                    logger.warning(f"check_ended_auctions: فشل تحليل ends_at للمزاد #{auction['auction_id']}")
                    continue
                time_left = (ends_at - datetime.now()).total_seconds()
                auction_id = auction['auction_id']

                # إشعار قبل الانتهاء بـ 30 دقيقة (بين 29 و31 دقيقة)
                if 1740 < time_left < 1860 and auction_id not in notified_30min:
                    notified_30min.add(auction_id)
                    # إشعار المزايد الحالي
                    if auction['current_bidder']:
                        try:
                            bot.send_message(
                                auction['current_bidder'],
                                "\n".join([
                                    f"⏰ {hb('تنبيه: المزاد ينتهي خلال 30 دقيقة!')}  {hc('#' + str(auction_id))}",
                                    DIVIDER,
                                    f"📦 {hb('المنتج:')} {html_escape(auction['title'])}",
                                    f"🏆 {hb('أنت الرابح حالياً بـ')} {fmt_money(auction['current_price'])}",
                                    DIVIDER,
                                    "🔥 تابع المزاد لضمان فوزك!",
                                ]),
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            logger.error(f"Error sending 30min warning to bidder: {e}")
                    # إشعار مالك المزاد
                    try:
                        bot.send_message(
                            auction['user_id'],
                            "\n".join([
                                f"⏰ {hb('مزادك ينتهي خلال 30 دقيقة!')}  {hc('#' + str(auction_id))}",
                                DIVIDER,
                                f"📦 {hb('المنتج:')} {html_escape(auction['title'])}",
                                f"💰 {hb('السعر الحالي:')} {fmt_money(auction['current_price'])}",
                                f"📊 {hb('عدد المزايدات:')} {auction['bids_count']}",
                            ]),
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Error sending 30min warning to owner: {e}")

                if ends_at <= datetime.now():
                    notified_30min.discard(auction_id)
                    if auction['current_bidder']:
                        complete_auction_sale(auction_id)
                    else:
                        if db.expire_auction(auction_id):
                            refund_starting_price_if_needed(auction)
                            try:
                                bot.send_message(
                                    auction['user_id'],
                                    "\n".join([
                                        f"🏁 {hb('انتهى المزاد!')}  {hc('#' + str(auction_id))}",
                                        DIVIDER,
                                        f"📦 {hb('المنتج:')} {html_escape(auction['title'])}",
                                        f"🎯 {html_escape(auction['target'])}",
                                        DIVIDER,
                                        "😔 لم تتم أي مزايدة على مزادك",
                                        "🔁 يمكنك نشر المزاد مرة أخرى",
                                    ]),
                                    parse_mode="HTML"
                                )
                            except Exception as e:
                                logger.error(f"Error notifying auction owner: {e}")
                            finalize_auction_broadcast(auction_id, winner_name=None)
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error checking ended auctions: {e}")
            time.sleep(300)

def check_subscription_channel_growth():
    while True:
        try:
            channels = db.get_subscription_channels()
            for channel in channels:
                try:
                    current_count = bot.get_chat_member_count(channel['channel_id'])
                    old_count = channel['subscriber_count'] or 0
                    if current_count != old_count:
                        db.update_subscriber_count(channel['channel_id'], current_count)
                        if channel['max_subscribers'] > 0 and current_count >= channel['max_subscribers']:
                            # اشتراك مدفوع انتهى → حذف كامل
                            db.delete_subscription_channel(channel['channel_id'])
                            bot.send_message(OWNER_ID, f"تم حذف قناة الاشتراك المدفوعة تلقائياً!\n\nالقناة: {channel['channel_title']}\n@{channel['channel_username'] if channel['channel_username'] else 'بدون معرف'}\nعدد المشتركين: {current_count}/{channel['max_subscribers']}\n\nانتهت الاشتراكات المدفوعة وتم حذف القناة من الاشتراك الإجباري.")
                        else:
                            bot.send_message(OWNER_ID, f"تحديث عدد المشتركين في قناة {channel['channel_title']}:\n\nالعدد القديم: {old_count}\nالعدد الجديد: {current_count}\nالتغيير: {'+' if current_count > old_count else ''}{current_count - old_count}\n@{channel['channel_username'] if channel['channel_username'] else 'بدون معرف'}")
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"Error checking channel {channel['channel_id']}: {e}")
            time.sleep(6 * 3600)
        except Exception as e:
            logger.error(f"Error checking subscription channel growth: {e}")
            time.sleep(3600)

auction_check_thread = threading.Thread(target=check_ended_auctions, daemon=True)
auction_check_thread.start()

subscription_growth_thread = threading.Thread(target=check_subscription_channel_growth, daemon=True)
subscription_growth_thread.start()

def cleanup_sub_cache():
    """تنظيف كاش التحقق من الاشتراك كل ساعة"""
    import time as _time
    while True:
        _time.sleep(3600)
        try:
            now = _time.time()
            expired = [uid for uid, ts in Database._sub_cache.items() if now - ts > Database._SUB_CACHE_TTL]
            for uid in expired:
                Database._sub_cache.pop(uid, None)
        except Exception:
            pass

cache_cleanup_thread = threading.Thread(target=cleanup_sub_cache, daemon=True)
cache_cleanup_thread.start()


# ================================================================
# تقرير يومي تلقائي للمالك
# ================================================================
def send_daily_report():
    """يرسل تقريراً يومياً للمالك كل صباح الساعة 9"""
    while True:
        try:
            now = datetime.now()
            # حساب الوقت حتى الساعة 9 صباحاً القادمة
            next_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= next_9am:
                next_9am += timedelta(days=1)
            wait_seconds = (next_9am - now).total_seconds()
            time.sleep(wait_seconds)

            # جمع الإحصائيات
            try:
                stats = db.get_stats()
                ext = db.get_extended_stats()
                # طلبات سحب معلقة
                cur_rpt = db.conn.cursor()
                cur_rpt.execute(
                    "SELECT COUNT(*), COALESCE(SUM(ABS(amount)),0) FROM transactions WHERE type='withdraw' AND date(created_at)=date('now','-1 day')"
                )
                wd_row = cur_rpt.fetchone()
                wd_count, wd_total = (wd_row[0] or 0), (wd_row[1] or 0.0)
                # مدفوعات Binance معلقة
                cur_rpt.execute("SELECT COUNT(*) FROM binance_payments WHERE status='pending'")
                pending_binance = cur_rpt.fetchone()[0] or 0
                # مزادات معلقة
                pending_auctions = stats.get('pending_auctions', 0)
                report = (
                    f"📊 *التقرير اليومي — {datetime.now().strftime('%Y-%m-%d')}*\n\n"
                    f"👥 مستخدمون جدد اليوم: *{ext['users_today']}*\n"
                    f"🏷 مزادات اليوم: *{ext['auctions_today']}* | مبيعات: *{ext['sales_today']}*\n"
                    f"💰 إيرادات اليوم: *{ext['revenue_today']:.2f}$*\n"
                    f"📈 إيرادات الأسبوع: *{ext['revenue_week']:.2f}$*\n\n"
                    f"⏳ *يحتاج انتباه:*\n"
                    f"• مزادات معلقة: *{pending_auctions}*\n"
                    f"• مدفوعات Binance معلقة: *{pending_binance}*\n"
                    f"• طلبات سحب أمس: *{wd_count}* ({wd_total:.2f}$)\n\n"
                    f"🏷 نشطة حالياً: *{stats['active_auctions']}* مزاد\n"
                    f"💼 إجمالي الإيرادات: *{stats['total_revenue']:.2f}$*"
                )
                try:
                    bot.send_message(OWNER_ID, report, parse_mode="Markdown")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"send_daily_report stats error: {e}")
        except Exception as e:
            logger.error(f"send_daily_report error: {e}")
            time.sleep(3600)

daily_report_thread = threading.Thread(target=send_daily_report, daemon=True)
daily_report_thread.start()

# ================================================================
# Health Check — فحص صحة البوت كل ساعة
# ================================================================
def health_check_worker():
    """يفحص حالة البوت وقاعدة البيانات كل ساعة ويُنبّه المالك عند وجود مشاكل"""
    time.sleep(300)  # انتظر 5 دقائق بعد الإطلاق
    while True:
        try:
            issues = []
            cur_hc = db.conn.cursor()
            # مزادات active لكن وقتها انتهى منذ أكثر من 30 دقيقة
            cur_hc.execute(
                "SELECT COUNT(*) FROM auctions WHERE status='active' AND ends_at < datetime('now','-30 minutes')"
            )
            stuck = cur_hc.fetchone()[0] or 0
            if stuck > 0:
                issues.append(f"⚠️ {stuck} مزاد انتهى وقته لكنه لا يزال 'active' — تحقق من Thread المزادات.")
            # مدفوعات Binance معلقة أكثر من 6 ساعات
            cur_hc.execute(
                "SELECT COUNT(*) FROM binance_payments WHERE status='pending' AND created_at < datetime('now','-6 hours')"
            )
            old_payments = cur_hc.fetchone()[0] or 0
            if old_payments > 0:
                issues.append(f"💳 {old_payments} دفعة Binance معلقة أكثر من 6 ساعات.")
            if issues:
                try:
                    bot.send_message(
                        OWNER_ID,
                        "🚨 *Health Check — تنبيه*\n\n" + "\n".join(issues),
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"health_check_worker error: {e}")
        time.sleep(3600)  # كل ساعة

health_check_thread = threading.Thread(target=health_check_worker, daemon=True)
health_check_thread.start()

# ================================================================
# Rate Limiting للمزايدات — منع spam
# ================================================================
_bid_rate_limit = {}  # {user_id: [timestamp1, timestamp2, ...]}
_bid_rate_lock = threading.Lock()

def check_bid_rate_limit(user_id: int) -> bool:
    """
    يتحقق من أن المستخدم لم يتجاوز 5 مزايدات في 10 ثواني.
    يعيد True إذا مسموح، False إذا محظور مؤقتاً.
    """
    now = time.time()
    with _bid_rate_lock:
        history = _bid_rate_limit.get(user_id, [])
        # احتفظ بالمزايدات آخر 10 ثواني فقط
        history = [t for t in history if now - t < 10]
        if len(history) >= 5:
            return False
        history.append(now)
        _bid_rate_limit[user_id] = history
    return True

def auto_backup_db():
    """نسخ احتياطي تلقائي لقاعدة البيانات كل 24 ساعة"""
    import shutil
    import glob
    while True:
        time.sleep(24 * 3600)
        try:
            backup_name = os.path.join(os.path.dirname(os.path.abspath(DATABASE_PATH)), f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
            shutil.copy(DATABASE_PATH, backup_name)
            logger.info(f"تم إنشاء نسخة احتياطية: {backup_name}")
            # الإبقاء على آخر 7 نسخ فقط
            backups = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(DATABASE_PATH)), "backup_*.db")))
            for old in backups[:-7]:
                try:
                    os.remove(old)
                    logger.info(f"تم حذف النسخة القديمة: {old}")
                except Exception:
                    pass
            try:
                bot.send_message(OWNER_ID, f" *نسخة احتياطية تلقائية*\n\nتم حفظ: `{backup_name}`\nعدد النسخ المحفوظة: {min(len(backups), 7)}", parse_mode="Markdown")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"خطأ في النسخ الاحتياطي: {e}")

backup_thread = threading.Thread(target=auto_backup_db, daemon=True)
backup_thread.start()

if __name__ == "__main__":
    # التحقق من الإعدادات الأساسية 
    if BOT_TOKEN == "ضع_توكن_البوت_هنا" or not BOT_TOKEN:
        print("خطأ: BOT_TOKEN غير محدد! ضع التوكن في متغير البيئة BOT_TOKEN")
        sys.exit(1)
    if OWNER_ID == 0:
        print("تحذير: OWNER_ID غير محدد! لن تعمل لوحة الإدارة بشكل صحيح.")
        print("أضف OWNER_ID إلى متغيرات البيئة.")
    print("تشغيل البوت...")
    print(f"أيدي المالك: {OWNER_ID}")
    print("البوت يعمل الآن بكامل وظائفه!")
    print("نظام المزادات والمزايدات يعمل بشكل صحيح")
    print("نظام أكواد الشحن جاهز")
    print("نظام قنوات البث والاشتراك يعمل")
    print("نظام الدفع عبر نجوم تيليجرام جاهز")
    print("نظام الكروت والمسابقات جاهز ")
    # استعادة السحوبات المجدولة بعد إعادة التشغيل
    _restore_contest_schedulers()
    # تحميل باكيج الإيموجي البريميوم المتحركة (tgiosicons)
    load_custom_emoji_pack()
    while True:
        try:
            bot.polling(non_stop=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Error running bot: {e}")
            logger.info("إعادة تشغيل البوت خلال 10 ثواني...")
            time.sleep(10)