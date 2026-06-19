"""
DINEaus Chatbot Backend - Fixed Version
Fixes applied:
1. P0: Preorder items fail pe state reset nahi hogi
2. P0: Invalid date/time/guests pe booking restart nahi hogi
3. P1: Natural language booking mein pre-extracted fields use honge
4. P1: Help ke baad booking resume hogi
5. P2: "my order status" bhi track_order intent trigger karega
"""

import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from difflib import get_close_matches
from datetime import datetime, date, timedelta, UTC
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
except Exception:
    pass

try:
    from order_manager import OrderManager
except Exception:
    OrderManager = None

try:
    from chatbot.model_loader import ModelLoader
except Exception:
    ModelLoader = None

try:
    from chatbot.session_manager import get_session, set_session, push_intent, reset_session, clear_temp_order
except Exception:
    get_session = set_session = push_intent = reset_session = clear_temp_order = None

try:
    from chatbot.entity_extractor import extract_order_id, extract_items
    print("entity_extractor loaded")
except Exception:
    print("entity_extractor import warning")
    extract_order_id = extract_items = None

try:
    from groq import Groq
except Exception:
    Groq = None

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

GROQ_API_KEY          = os.getenv("GROQ_API_KEY")
GROQ_MODEL            = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
USE_GROQ              = os.getenv("USE_GROQ", "true").strip().lower() not in {"0", "false", "no", "off"}
GROQ_SYSTEM_PROMPT_PATH = Path(__file__).parent / "data" / "groq_system_prompt.txt"

DB_CONFIG = {
    'user':       os.getenv('DB_USER',  'root'),
    'password':   os.getenv('DB_PASS',  'harshit@123'),
    'host':       os.getenv('DB_HOST',  '127.0.0.1'),
    'database':   os.getenv('DB_NAME',  'college_practice'),
    'port':       int(os.getenv('DB_PORT', '3306')),
    'autocommit': False,
}

app = Flask(__name__)
CORS(app, resources={
    r"/chat":   {"origins": "*"},
    r"/reset":  {"origins": "*"},
    r"/health": {"origins": "*"},
})

if GROQ_API_KEY and Groq is not None and USE_GROQ:
    print(f"GROQ ENABLED\nModel: {GROQ_MODEL}")
else:
    print("GROQ DISABLED")

# ── Constants ──────────────────────────────────────────────────────────────────
WORD_TO_NUMBER = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'a': 1, 'an': 1,
    'ek': 1, 'do': 2, 'teen': 3, 'char': 4, 'paanch': 5,
    'chhe': 6, 'saat': 7, 'aath': 8, 'nau': 9, 'das': 10,
}

_HINDI_MARKERS = {
    'kya','hai','hain','mujhe','chahiye','karo','bhai','kal','aaj','log',
    'kitne','mere','mera','nahi','nhi','kar','krna','krdo','krdiya','batao',
    'wala','wali','smjh','hua','thi','tha','hoga','kab','kaise','kyun',
    'kaun','yahan','wahan','abhi','phir','bolo','dedo','chahte','aana',
    'theek','accha','sahi','bilkul','zaroor','ek','do','teen','char',
    'paanch','log','baje','raat','subah','sham','parso','kitna','kitni',
    'karna','dekho','dikhao','milta','khana','lena','dena','mangwa',
}

BOOKING_EXEMPT_INTENTS = {
    "greeting", "goodbye", "thanks", "help", "account_help",
    "cancel_booking", "booking_interrupt", "navigation_help",
    "site_navigation", "cancel_order", "payment",
}

# ── Language ───────────────────────────────────────────────────────────────────
def detect_language(text: str) -> str:
    words = set(text.lower().split())
    return 'hi' if words & _HINDI_MARKERS else 'en'

def get_lang(session: dict, message: str) -> str:
    if not session.get("lang"):
        session["lang"] = detect_language(message)
    return session["lang"]

# ── Static responses ───────────────────────────────────────────────────────────
RESPONSES = {
    "greeting": {
        "en": "Hi! 👋 I'm DineBot.\n\n💬 Type **'view restaurants'** to start ordering!",
        "hi": "Namaste! 👋 Main DineBot hoon.\n\n💬 **'view restaurants'** type karo aur order shuru karo!",
    },
    "fallback": {
        "en": (
            "🤔 Not sure what you meant.\n\n"
            "Try one of these:\n"
            "🍽️ Order food → **'menu'**\n"
            "🪑 Book a table → **'book a table'**\n"
            "📦 Track order → **'track 123'**\n"
            "🏪 Restaurants → **'view restaurants'**\n"
            "❓ Help → **'help'**"
        ),
        "hi": (
            "🤔 Thoda clear batao.\n\n"
            "Yeh try karo:\n"
            "🍽️ Order → **'menu'**\n"
            "🪑 Table book → **'table book'**\n"
            "📦 Track → **'track 123'**\n"
            "🏪 Restaurants → **'view restaurants'**\n"
            "❓ Help → **'help'**"
        ),
    },
    "thanks": {
        "en": "You're welcome 😊 Need anything else?",
        "hi": "Aapka swagat hai 😊 Aur kuch chahiye?",
    },
    "no_restaurant": {
        "en": "⚠️ Please select a restaurant first.\n\n💬 Type **'view restaurants'**",
        "hi": "⚠️ Pehle restaurant select karo.\n\n💬 **'view restaurants'** type karo",
    },
    "empty_cart": {
        "en": "🛒 Your cart is empty!\n\n💬 Type **'menu'** to see items.",
        "hi": "🛒 Cart khali hai!\n\n💬 **'menu'** type karo.",
    },
    "item_not_found": {
        "en": "🤔 Item not found.\n\n💡 Type **'menu'** to see available items.",
        "hi": "🤔 Item nahi mila.\n\n💡 **'menu'** type karo.",
    },
    "login_required_order": {
        "en": "🔐 Please login to continue.\n\n1) Tap **Login** in the top navbar\n2) Complete login\n3) Come back and try again",
        "hi": "🔐 Continue karne ke liye login karo.\n\n1) Top navbar me **Login** tap karo\n2) Login complete karo\n3) Wapas aake try karo",
    },
    "login_required_booking": {
        "en": "🔐 Please login to continue.\n\n1) Tap **Login** in the top navbar\n2) Complete login\n3) Start booking again",
        "hi": "🔐 Continue karne ke liye login karo.\n\n1) Top navbar me **Login** tap karo\n2) Login complete karo\n3) Booking phir se start karo",
    },
    "login_required_cancel": {
        "en": "🔐 Please login to continue.\n\n1) Tap **Login** in the top navbar\n2) Complete login\n3) Then cancel your order",
        "hi": "🔐 Continue karne ke liye login karo.\n\n1) Top navbar me **Login** tap karo\n2) Login complete karo\n3) Uske baad order cancel karo",
    },
    "switch_warning": {
        "en": "⚠️ You have items in your cart. Switching restaurants will clear your cart.\n\nReply **'yes'** to continue or **'no'** to stay.",
        "hi": "⚠️ Cart mein items hain. Restaurant switch karne par cart clear ho jayega.\n\nContinue ke liye **'yes'** ya **'no'** bolo.",
    },
    "switch_cancelled": {
        "en": "✅ Keeping your current restaurant.\n\nType **'menu'** to continue ordering.",
        "hi": "✅ Current restaurant hi rahega.\n\nAage badhne ke liye **'menu'** type karo.",
    },
    "payment_info": {
        "en": "💳 Payments happen on the website.\n\n1) Open **Cart / Checkout**\n2) Select address\n3) Choose payment (UPI/Card/Pay on Delivery)",
        "hi": "💳 Payment website par hota hai.\n\n1) **Cart / Checkout** open karo\n2) Address select karo\n3) Payment option choose karo",
    },
    "help": {
        "en": (
            "❓ **Help & FAQs**\n\n"
            "🍽️ **Order food:** Home → restaurant → menu → ADD items → cart → checkout\n"
            "🪑 **Book table:** Type **'book a table'** here, or visit restaurant page → **Reserve / Seat / Preorder** button\n"
            "📦 **Track order:** Type **'track 1023'** or go to **Profile → Orders → Track Order**\n"
            "❌ **Cancel order:** Type **'cancel order 1023'** or go to **Profile → Orders → Cancel**\n"
            "🏪 **Restaurants:** Type **'view restaurants'** or browse on Home page\n"
            "🎁 **Offers:** Navbar → **Offers** or Home → Today's Hot Deals\n\n"
            "For complaints: navbar → **Help** (/help) — covers orders, FAQs, partner, safety, legal.\n"
            "Support email: support@dineaus.com"
        ),
        "hi": (
            "❓ **Help & FAQs**\n\n"
            "🍽️ **Order:** Home → restaurant → menu → ADD → cart → checkout\n"
            "🪑 **Table book:** **'book a table'** type karo ya restaurant page → **Reserve / Seat / Preorder** button\n"
            "📦 **Track:** **'track 1023'** type karo ya **Profile → Orders → Track Order**\n"
            "❌ **Cancel:** **'cancel order 1023'** ya **Profile → Orders → Cancel**\n"
            "🏪 **Restaurants:** **'view restaurants'** type karo\n"
            "🎁 **Offers:** Navbar → **Offers** ya Home → Today's Hot Deals\n\n"
            "Complaint ke liye: navbar → **Help** (/help)\n"
            "Support email: support@dineaus.com"
        ),
    },
    "account_help": {
        "en": (
            "🔐 **Account Help**\n\n"
            "• **Login:** Top navbar → **Login** (/login)\n"
            "• **Sign Up:** Top navbar → **SignUp** (/sign)\n"
            "• **Forgot password:** Login page → **Forgot Password** (/forgot)\n"
            "• **Reset:** Check email → open reset link → set new password\n"
            "• **Edit profile:** Top navbar → your name → **Profile** → **Edit Profile** (/profile/edit)\n"
            "• **Update phone/email:** Profile → Edit Profile\n"
            "• **Account issues:** Navbar → **Help** (/help)"
        ),
        "hi": (
            "🔐 **Account Help**\n\n"
            "• **Login:** Top navbar → **Login** (/login)\n"
            "• **Sign Up:** Top navbar → **SignUp** (/sign)\n"
            "• **Forgot password:** Login page → **Forgot Password** (/forgot)\n"
            "• **Reset:** Email link se naya password set karo\n"
            "• **Profile update:** Navbar → naam → **Profile** → **Edit Profile** (/profile/edit)\n"
            "• **Account problem:** Navbar → **Help** (/help)"
        ),
    },
    "booking_interrupt_prompt": {
        "en": (
            "You're currently booking a table.\n\n"
            "Do you want to **continue booking** or **switch to food ordering**?\n"
            "Reply **'continue'** or **'switch'**."
        ),
        "hi": (
            "Aap abhi table booking kar rahe ho.\n\n"
            "Booking continue karni hai ya food ordering pe switch karna hai?\n"
            "**'continue'** ya **'switch'** reply karo."
        ),
    },
}

def get_response(key: str, lang: str) -> str:
    return RESPONSES.get(key, {}).get(lang, RESPONSES.get(key, {}).get('en', ''))

def booking_ask(field: str, lang: str) -> str:
    msgs = {
        "restaurant": {
            "en": "🏪 Which restaurant would you like to book at?\n\nType **'view restaurants'** to see options.",
            "hi": "🏪 Kaunse restaurant mein table book karna hai?\n\n**'view restaurants'** type karo.",
        },
        "booking_type": {
            "en": "🪑 Choose booking type:\n\n1) **Dine-out only**\n2) **Table + pre-order food**\n\nReply **1** or **2**.",
            "hi": "🪑 Booking type choose karo:\n\n1) **Sirf table**\n2) **Table + pre-order food**\n\n**1** ya **2** reply karo.",
        },
        "preorder_items": {
            "en": "🍽️ What would you like to pre-order? Tell me items and quantities.\n\nExample: **'2 pizza and 1 coke'**",
            "hi": "🍽️ Kya pre-order karna hai? Items aur quantity batao.\n\nExample: **'2 pizza aur 1 coke'**",
        },
        "people": {
            "en": "👥 How many people will be joining?\n\nExample: **'4 people'** or just **'4'**",
            "hi": "👥 Kitne logon ke liye table chahiye?\n\nExample: **'4 log'** ya sirf **'4'**",
        },
        "date": {
            "en": "📅 Which date? (**today** or **tomorrow** only)\n\nExample: **'today'** or **'tomorrow'**",
            "hi": "📅 Kaunsi date? (Sirf **aaj** ya **kal**)\n\nExample: **'aaj'** ya **'kal'**",
        },
        "time": {
            "en": "🕒 What time? (11am–3pm or 6pm–10pm)\n\nExample: **'7pm'** or **'19:30'**",
            "hi": "🕒 Kaunsa time? (11am–3pm ya 6pm–10pm)\n\nExample: **'7pm'** ya **'19:30'**",
        },
    }
    return msgs.get(field, {}).get(lang, msgs.get(field, {}).get('en', ''))

# ── Yes / No helpers ───────────────────────────────────────────────────────────
def is_yes(text: str) -> bool:
    return bool(re.search(
        r"\b(yes|y|yeah|yep|ok|okay|sure|confirm|haan|han|ha|bilkul|theek hai|done)\b",
        text, flags=re.I,
    ))

def is_no(text: str) -> bool:
    return bool(re.search(
        r"\b(no|n|nope|nah|stop|nahin|nahi|mat|nai)\b",
        text, flags=re.I,
    ))

# ── Date / Time helpers ────────────────────────────────────────────────────────
def has_date_hint(text: str) -> bool:
    return bool(re.search(
        r"\b(today|tomorrow|tmrw|tmr|tommorow|tomorow|tommorrow|aaj|kal|parso|"
        r"\d{1,2}[/-]\d{1,2}|\d{4}-\d{2}-\d{2}|"
        r"january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b",
        text, flags=re.I,
    ))

def has_time_hint(text: str) -> bool:
    return bool(re.search(
        r"\b(noon|midday|midnight|\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|\d{1,2}(?:am|pm)|\d{1,2}\s*baje)\b",
        text, flags=re.I,
    ))

def parse_time_string(tstr: str):
    if not tstr or not isinstance(tstr, str):
        return None
    s = tstr.lower().strip()
    s = re.sub(r"\bbaje\b", "", s).replace('.', '')
    s = re.sub(r"\s+", " ", s).strip()

    if re.fullmatch(r"\d{1,2}", s):
        hh = int(s)
        if 0 <= hh <= 23:
            return (hh, 0)

    for pattern in [r"\bnoon\b", r"\bmidday\b", r"\bmidnight\b",
                    r"\b\d{1,2}:\d{2}\b", r"\b\d{1,2}\s*(?:am|pm)\b", r"\b\d{1,2}(?:am|pm)\b"]:
        m = re.search(pattern, s, flags=re.I)
        if m:
            token = m.group(0).strip().lower().replace(" ", "")
            if token in {"noon", "midday"}:
                return (12, 0)
            if token == "midnight":
                return (0, 0)
            m2 = re.match(r"^(\d{1,2}):(\d{2})$", token)
            if m2:
                hh, mm = int(m2.group(1)), int(m2.group(2))
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    return (hh, mm)
            m3 = re.match(r"^(\d{1,2})(am|pm)$", token)
            if m3:
                hh, ap = int(m3.group(1)), m3.group(2)
                if hh == 12:
                    hh = 0
                if ap == 'pm':
                    hh += 12
                if 0 <= hh <= 23:
                    return (hh, 0)
    return None

def is_time_allowed_for_date(date_str, time_str: str) -> bool:
    parsed = parse_time_string(time_str)
    if not parsed:
        return False
    hh, _ = parsed
    return (11 <= hh <= 15) or (18 <= hh <= 22)

def is_allowed_booking_time(time_str: str) -> bool:
    return is_time_allowed_for_date(None, time_str)

def is_past_date(date_str: str) -> bool:
    try:
        return date.fromisoformat(date_str) < date.today()
    except Exception:
        return False

def is_allowed_booking_date(date_str: str) -> bool:
    try:
        d = date.fromisoformat(date_str)
    except Exception:
        return False
    if is_past_date(date_str):
        return False
    today    = date.today()
    tomorrow = today + timedelta(days=1)
    return d in (today, tomorrow)

def parse_date_from_text(text: str):
    t = text.lower()
    if re.search(r"\b(today|aaj|todat|todsy|tody|todya|tday)\b", t):
        return date.today().isoformat()
    if re.search(r"\b(tomorrow|tmr|tmrw|kal|tommorow|tomorow|tommorrow)\b", t):
        return (date.today() + timedelta(days=1)).isoformat()
    return None

# ── People count ───────────────────────────────────────────────────────────────
def extract_plain_number_as_people(message: str):
    m = re.match(r'^\s*(\d{1,2})\s*$', message.strip())
    if m:
        val = int(m.group(1))
        if 1 <= val <= 20:
            return val
    for word, val in WORD_TO_NUMBER.items():
        if message.strip().lower() == word and 1 <= val <= 20:
            return val
    return None

def extract_people_count(message: str):
    text = (message or "").lower().strip()
    bare = extract_plain_number_as_people(text)
    if bare:
        return bare
    m = re.search(r"\b(\d{1,2})\s*(people|person|guests?|log|aadmi|members?)\b", text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 20:
            return val
    for word, val in WORD_TO_NUMBER.items():
        if re.search(rf"\b{re.escape(word)}\s*(people|person|guests?|log|aadmi|members?)\b", text):
            if 1 <= val <= 20:
                return val
    return None

# ── Extract booking fields from a message ──────────────────────────────────────
def extract_booking_fields(message: str) -> dict:
    result = {"people": None, "date": None, "time": None}
    result["people"] = extract_people_count(message)
    result["date"]   = parse_date_from_text(message)
    parsed_time      = parse_time_string(message)
    if parsed_time:
        result["time"] = f"{parsed_time[0]:02d}:{parsed_time[1]:02d}"
    return result

# ── Booking mode ───────────────────────────────────────────────────────────────
def parse_booking_mode(text: str):
    t = text.lower().strip()
    if re.search(r"\b(1|one|dine[-\s]?out|only table|just table|sirf table|sirf booking)\b", t):
        return "dine_out"
    if re.search(r"\b(2|two|pre[-\s]?order|preorder|with\s+food|food\s+preorder|khana|khaana|i want|add|order food)\b", t):
        return "preorder"
    return None

# ── Support intent ─────────────────────────────────────────────────────────────
def support_intent_parser(text: str):
    t = text.lower().strip()
    if re.search(
        r"\b(reset password|forgot password|change password|password reset|password bhool|"
        r"cant login|can't login|login nahi|login problem|account help|account problem|"
        r"change email|change phone|password yaad nahi|password help)\b", t,
    ):
        return "account_help"
    if re.search(r"\b(password|credentials)\b", t) and re.search(
        r"\b(reset|forgot|forget|change|update|help|bhool|problem|issue)\b", t,
    ):
        return "account_help"
    return None

def is_booking_message(text: str) -> bool:
    return bool(re.search(
        r"\b(book|booking|reserve|reservation|table|dine in|dining|seat)\b",
        text, flags=re.I,
    ))

def is_unrelated_to_booking(text: str) -> bool:
    return bool(re.search(
        r"\b(menu|order|cart|checkout|confirm order|track|cancel order|payment|offers|deal)\b",
        text, flags=re.I,
    ))

def detect_booking_interrupt_target(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(track|status)\b", t):       return "track"
    if re.search(r"\b(cancel order)\b", t):        return "cancel"
    if re.search(r"\b(payment|checkout|pay)\b", t): return "payment"
    if re.search(r"\b(help|support|account)\b", t): return "help"
    return "order"

# ── Next booking prompt ────────────────────────────────────────────────────────
def next_booking_prompt(booking_state: dict, lang: str) -> str:
    awaiting = booking_state.get("awaiting", "restaurant")
    prompt_key = "people" if awaiting == "guests" else awaiting
    return booking_ask(prompt_key, lang)

# ── Session Manager fallback ───────────────────────────────────────────────────
if get_session is None:
    _sessions: dict = {}

    def _default_session() -> dict:
        return {
            "user_id": None, "is_logged_in": False, "user_name": None,
            "lang": None,
            "active_restaurant": None,
            "restaurant_list_shown": False,
            "restaurant_names": [],
            "mentioned_restaurant_id": None,
            "mentioned_restaurant_name": None,
            "temp_order": {"items": []},
            "last_order_id": None,
            "last_booking_id": None,
            "booking_state": {},
            "pending_cancel_order_id": None,
            "pending_switch": None,
            "pending_booking_switch": None,
            "last_intent": None,
            "last_bot_msg": None,
            "context_stack": [],
            "recent_actions": [],
            "last_added_item": None,
            "last_action_time": None,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def get_session(uid):
        if uid not in _sessions:
            _sessions[uid] = _default_session()
        else:
            s = _sessions[uid]
            defaults = _default_session()
            for k, v in defaults.items():
                if k not in s:
                    s[k] = v
            if not isinstance(s.get("temp_order"), dict):
                s["temp_order"] = {"items": []}
            if "items" not in s["temp_order"]:
                s["temp_order"]["items"] = []
        return _sessions[uid]

    def set_session(uid, data):
        _sessions[uid] = data
        return data

    def clear_temp_order(uid):
        s = get_session(uid)
        s["temp_order"] = {"items": []}
        s["last_intent"] = None
        return s

    def push_intent(uid, intent):
        s = get_session(uid)
        stack = s.get("context_stack", [])
        stack.append(intent)
        s["context_stack"] = stack[-5:]
        s["last_intent"] = intent

    def reset_session(uid):
        _sessions[uid] = _default_session()
        return _sessions[uid]

# ── Order Manager ──────────────────────────────────────────────────────────────
om = None
if OrderManager is not None:
    try:
        om = OrderManager(DB_CONFIG)
        print("OrderManager initialized with MySQL")
    except Exception as e:
        print(f"Warning: MySQL OrderManager failed: {e}")

class _InMemoryOrderManager:
    def __init__(self):
        self.orders = {}
        self.reservations = {}
        self.order_counter = 1000
        self.reservation_counter = 1000
        self.restaurants = [{"id": 1, "name": "Demo Restaurant", "location": "Demo", "image_url": ""}]
        self.menus = {1: [{"item_name": "pizza", "price": 250.0}, {"item_name": "burger", "price": 120.0}]}

    def get_restaurants(self): return self.restaurants
    def get_menu(self, rid): return self.menus.get(rid, [])

    def add_order(self, user_id, restaurant_id, items, total_price, address_id=None):
        oid = self.order_counter; self.order_counter += 1
        self.orders[oid] = {
            "id": oid, "user_id": user_id, "restaurant_id": restaurant_id,
            "items": items, "total_price": total_price, "status": "pending",
        }
        return oid

    def add_cart_items(self, user_id, restaurant_id, items): return len(items or [])

    def confirm_order(self, order_id):
        if order_id in self.orders:
            self.orders[order_id]["status"] = "accepted"; return True
        return False

    def track_order(self, order_id): return self.orders.get(order_id)

    def cancel_order(self, order_id, reason=None):
        if order_id in self.orders:
            self.orders[order_id]["status"] = "cancelled"; return True
        return False

    def get_latest_active_order_for_user(self, user_id):
        for o in reversed(list(self.orders.values())):
            if o.get("user_id") == user_id and o.get("status") not in ("delivered","completed","cancelled"):
                return {**o, "order_id": o["id"]}
        return None

    def get_latest_order_for_user(self, user_id):
        for o in reversed(list(self.orders.values())):
            if o.get("user_id") == user_id:
                return {**o, "order_id": o["id"]}
        return None

    def book_table(self, user_id, restaurant_id, customer_name, customer_phone,
                   booking_date, time_slot, guests):
        rid = self.reservation_counter; self.reservation_counter += 1
        self.reservations[rid] = {
            "id": rid, "restaurant_id": restaurant_id,
            "date": booking_date, "time_slot": time_slot, "guests": guests, "status": "pending",
        }
        return rid

    def add_reservation_preorders(self, reservation_id, items): return len(items or [])

if om is None:
    print("WARNING: Using in-memory OrderManager")
    om = _InMemoryOrderManager()

# ── ML Model ───────────────────────────────────────────────────────────────────
ml_model = None
if ModelLoader is not None:
    try:
        ml_model = ModelLoader(
            model_path=Path(__file__).parent / "data" / "chatbot_model.pkl",
            intents_path=Path(__file__).parent / "data" / "intents.json",
        )
        print("ML Model loaded")
    except Exception as e:
        print(f"WARNING: ML model load failed: {e}")

def load_valid_intents():
    intents = set()
    try:
        with open(Path(__file__).parent / "data" / "intents.json", "r", encoding="utf-8") as f:
            for item in json.load(f).get("intents", []):
                tag = str(item.get("tag", "")).strip().lower()
                if tag: intents.add(tag)
    except Exception:
        pass
    intents.update({
        "greeting","about_bot","view_restaurants","menu","order_item","show_cart",
        "update_quantity","confirm_order","track_order","cancel_order","book_table",
        "cancel_booking","restaurant_compare","restaurant_query","payment",
        "navigation_help","restaurant_register","restaurant_login","delivery_partner",
        "recommendations","repeat_order","scheduled_order","offers_deals","personal_info",
        "veg_nonveg","opening_hours","delivery_area","current_restaurant","change_restaurant",
        "help","fallback","goodbye","thanks","remove_item","select_restaurant","new_order",
        "partner","site_navigation","compare_restaurants","restaurant_item_query",
        "account_help","recommend_restaurants",
    })
    return intents

VALID_INTENTS = load_valid_intents()

# ── Groq ───────────────────────────────────────────────────────────────────────
def load_groq_system_prompt():
    try:
        with open(GROQ_SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "Classify the user message into a valid intent. Return only the intent name."

def normalize_intent_name(raw: str) -> str:
    if not raw: return ""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "", raw.strip().splitlines()[0].strip())
    return cleaned.lower()

def groq_classify_intent(text: str, session: dict = None):
    if not (USE_GROQ and GROQ_API_KEY and Groq):
        return None
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": load_groq_system_prompt() + "\n\nValid intents: " + ", ".join(sorted(VALID_INTENTS))},
                {"role": "user",   "content": text},
            ],
            temperature=0, max_tokens=20,
        )
        content   = response.choices[0].message.content if response.choices else ""
        candidate = normalize_intent_name(content)
        return candidate if candidate in VALID_INTENTS else None
    except Exception as e:
        print(f"Groq error: {e}")
        return None

def _groq_result_with_timeout(text: str, session: dict, timeout_seconds: float = 2.5):
    if not (USE_GROQ and GROQ_API_KEY and Groq):
        return None
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(groq_classify_intent, text, session)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            print("[INTENT] groq -> timeout")
            return None
        except Exception as exc:
            print(f"[INTENT] groq -> error: {exc}")
            return None

# ── Helpers ────────────────────────────────────────────────────────────────────
def is_logged_in_user(user_id, session: dict) -> bool:
    if not isinstance(session, dict): return False
    if session.get("is_logged_in") is True: return True
    uid = str(user_id or "").lower().strip()
    if not uid or uid in ("anonymous", "guest"): return False
    if uid.startswith("guest_"): return False
    return True

def normalize_quantity(qty_str):
    qty_str = qty_str.lower().strip()
    if qty_str in WORD_TO_NUMBER: return WORD_TO_NUMBER[qty_str]
    try: return int(qty_str)
    except: return 1

def fuzzy_match_item(user_input, menu_list, cutoff=0.6):
    if not menu_list: return None, 0
    user_input = user_input.lower().strip()
    if user_input in menu_list: return user_input, 1.0
    matches = get_close_matches(user_input, menu_list, n=1, cutoff=cutoff)
    return (matches[0], 0.8) if matches else (None, 0)

def extract_items_from_message(message, menu_list, price_map):
    message = re.sub(r'([a-zA-Z])and\b', r'\1 and', message)
    message = re.sub(r'\band([a-zA-Z])', r'and \1', message)
    items = []
    message_lower = message.lower()
    qty_words = '|'.join(WORD_TO_NUMBER.keys())
    qty_pattern = rf'\b(\d+|{qty_words})\s+(?:x\s+)?(\w+(?:\s+\w+){{0,2}})'
    for match in re.finditer(qty_pattern, message_lower):
        matched, confidence = fuzzy_match_item(match.group(2).strip(), menu_list)
        if matched and confidence >= 0.6:
            items.append({"name": matched, "qty": normalize_quantity(match.group(1)), "price": price_map.get(matched, 0)})
    if not items:
        for item_name in menu_list:
            if re.search(r'\b' + re.escape(item_name) + r'\b', message_lower):
                items.append({"name": item_name, "qty": 1, "price": price_map[item_name]})
    if not items:
        for word in message_lower.split():
            if len(word) > 2:
                matched, confidence = fuzzy_match_item(word, menu_list, cutoff=0.7)
                if matched and confidence >= 0.7:
                    items.append({"name": matched, "qty": 1, "price": price_map[matched]}); break
    merged = {}
    for item in items:
        name = item.get("name")
        if not name: continue
        key = name.lower()
        qty = int(item.get("qty", 1) or 1)
        if key not in merged:
            merged[key] = {"name": name, "qty": qty, "price": item.get("price", 0)}
        else:
            merged[key]["qty"] += qty
    return list(merged.values())

def suggest_close_items(user_input, menu_list, n=3):
    suggestions = set()
    for word in user_input.lower().split():
        if len(word) > 2:
            suggestions.update(get_close_matches(word, menu_list, n=n, cutoff=0.5))
    return list(suggestions)[:n]

def get_restaurant_menu(restaurant_id):
    try:
        rows = om.get_menu(restaurant_id)
        if not rows: return None, None
        menu_list = [row["item_name"].lower() for row in rows]
        price_map = {row["item_name"].lower(): float(row["price"]) for row in rows}
        return menu_list, price_map
    except Exception as e:
        print(f"Error fetching menu: {e}"); return None, None

def format_items_for_db(temp_items):
    return [{"item_name": i["name"].title(), "price": i["price"], "quantity": i["qty"]} for i in temp_items]

def safe_numeric_user_id(user_id):
    if not user_id or user_id in ("anonymous", ""): return 1
    try: return int(user_id)
    except: return 1

def prepare_restaurants_for_json(rows):
    return [{"id": r.get("id"), "name": r.get("name", ""), "location": r.get("location", ""), "image_url": r.get("image_url") or ""} for r in (rows or [])]

def format_restaurant_list(rows: list, lang: str) -> str:
    if not rows:
        return "No restaurants available." if lang == "en" else "Koi restaurant available nahi hai."
    text = "🍽️ **Available Restaurants:**\n\n" if lang == "en" else "🍽️ **Restaurants ki list:**\n\n"
    for rx in rows:
        text += f"{rx['id']}. {rx['name']} ({rx.get('location', '')})\n"
    text += "\n💬 Type the restaurant number to select." if lang == "en" else "\n💬 Restaurant ka number type karo."
    return text

def format_cart_summary(temp_items: list) -> str:
    return "\n".join(f"• {i['qty']}x {i['name'].title()} - ₹{i['price'] * i['qty']}" for i in temp_items)

def match_restaurant_in_message(message: str, restaurants: list):
    t = message.lower(); best = None
    for rx in (restaurants or []):
        name = str(rx.get("name", "")).strip()
        if not name: continue
        name_lower = name.lower()
        if name_lower in t:
            if not best or len(name) > len(best.get("name", "")): best = rx; continue
        tokens = [tok for tok in re.split(r"\W+", name_lower) if tok]
        ignore = {"the", "restaurant", "cafe", "hotel", "dhaba", "bar"}
        tokens = [tok for tok in tokens if tok not in ignore]
        if tokens and all(tok in t for tok in tokens):
            if not best or len(name) > len(best.get("name", "")): best = rx
    return best

def extract_preorder_items(message: str, restaurant_id: int):
    menu_list, price_map = get_restaurant_menu(restaurant_id)
    if not menu_list: return []
    return extract_items_from_message(message, menu_list, price_map)

# ── Duplicate suppression ──────────────────────────────────────────────────────
def _purge_old_actions(session: dict, window_seconds: float = 2.0):
    now    = datetime.now(UTC)
    recent = session.get("recent_actions", []) or []
    session["recent_actions"] = [
        (sig, t) for sig, t in recent
        if (now - datetime.fromisoformat(t)).total_seconds() <= window_seconds
    ]

def _is_recent_duplicate(session: dict, signature: str, window_seconds: float = 2.0) -> bool:
    _purge_old_actions(session, window_seconds)
    return any(sig == signature for sig, _ in session.get("recent_actions", []))

def _record_action(session: dict, signature: str):
    now_iso = datetime.now(UTC).isoformat()
    recent  = session.get("recent_actions", [])
    recent.append((signature, now_iso))
    session["recent_actions"] = recent[-10:]
    session["last_action_time"] = now_iso

# ── Intent detection ───────────────────────────────────────────────────────────
def _looks_like_freeform_text(text: str) -> bool:
    words = re.findall(r"\w+", text.lower())
    if len(words) <= 8: return False
    return bool(re.search(r"\b(i|me|my|we|please|can you|could you|yaar|bhai|mujhe|suggest|recommend)\b", text, flags=re.I))

def _looks_ambiguous(text: str, session: dict = None) -> bool:
    if re.search(r"\b(yaar|bhai|please|maybe|something|somewhere|koi|accha|better|best|quiet|family)\b", text, flags=re.I): return True
    if "?" in text: return True
    return False

def detect_multi_intent(message: str, restaurants: list):
    t = message.lower()
    has_booking_kw  = bool(re.search(r'\b(booking|reserve|book table|table book|reservation|dine in|dining)\b', t))
    has_restaurant  = match_restaurant_in_message(message, restaurants) is not None
    has_time        = bool(re.search(r'\b(\d{1,2})(:|\s)?(\d{2})?\s*(am|pm|baje)\b', t))
    has_date        = bool(re.search(r'\b(kal|aaj|tomorrow|today|tonight|parso)\b', t))
    has_food_ctx    = bool(re.search(r'\b(khana|eat|dining|visit|aana)\b', t))
    if has_booking_kw and (has_restaurant or has_time or has_date): return "book_table"
    if has_restaurant and (has_time or has_date) and has_food_ctx:  return "book_table"
    return None

def find_menu_item_in_message(message: str, menu_list: list):
    t = message.lower()
    for item in (menu_list or []):
        if re.search(r'\b' + re.escape(item.lower()) + r'\b', t): return item
    for token in re.split(r"\W+", t):
        matched, conf = fuzzy_match_item(token, menu_list, cutoff=0.7)
        if matched and conf >= 0.7: return matched
    return None

def resolve_intent(message: str, session: dict, restaurants: list) -> str:
    booking_state = session.get("booking_state", {})

    if booking_state and booking_state.get("awaiting") not in (None, "restaurant"):
        if re.search(r"\b(help|faq|support|complaint)\b", message, flags=re.I): return "help"
        if re.search(r"\b(navigate|navigation|where is|how to go)\b", message, flags=re.I): return "navigation_help"
        s = support_intent_parser(message)
        if s: return s
        # FIX P1: Payment is a stateless interrupt — don't trigger booking_interrupt
        if re.search(r"\b(payment|pay|checkout|upi|card)\b", message, flags=re.I): return "payment"
        if is_unrelated_to_booking(message): return "booking_interrupt"
        return "book_table"

    temp_items = session.get("temp_order", {}).get("items", [])
    if temp_items and re.search(r"\b(yes|ok|okay|confirm|checkout|place order)\b", message, flags=re.I):
        return "confirm_order"

    s = support_intent_parser(message)
    if s: return s

    multi = detect_multi_intent(message, restaurants)
    if multi: return multi

    active_restaurant = session.get("active_restaurant")
    if active_restaurant and not re.search(
        r"\b(cancel|track|status|confirm order|checkout|payment|help|book|booking|table|people|guests?|person)\b",
        message, flags=re.I,
    ):
        menu_list, price_map = get_restaurant_menu(active_restaurant)
        order_hint = bool(re.search(r"\b(add|order|want|get|give me|i want|i need|chahiye|de do|lena|mangwa)\b", message, flags=re.I))
        qty_hint   = bool(re.search(r"\b(\d+|one|two|three|four|five|ek|do|teen|char|paanch)\b", message, flags=re.I))
        if menu_list and (order_hint or qty_hint) and extract_items_from_message(message, menu_list, price_map):
            return "order_item"

    return predict_intent(message, session)

def predict_intent(text: str, session: dict = None) -> str:
    cleaned = (text or "").strip()
    regex_intent = simple_intent_parser(cleaned, (session or {}).get("restaurant_names", []))
    if regex_intent != "fallback":
        print(f"[INTENT] regex -> {regex_intent}")
        return regex_intent

    ml_intent = None; ml_confidence = 0.0
    if ml_model:
        try:
            intent, confidence = ml_model.predict([cleaned])[0]
            intent = str(intent).lower().strip()
            ml_confidence = float(confidence or 0.0)
            if confidence > 0.55 and intent in VALID_INTENTS and intent != "fallback":
                print(f"[INTENT] ml -> {intent} ({confidence:.2f})")
                return intent
            if confidence > 0.35 and intent in VALID_INTENTS and intent != "fallback":
                ml_intent = intent
        except Exception as e:
            print(f"ML error: {e}")

    use_groq = ml_intent is None or ml_confidence < 0.35 or _looks_like_freeform_text(cleaned) or _looks_ambiguous(cleaned, session)
    if use_groq:
        g = _groq_result_with_timeout(cleaned, session)
        if g and g != "fallback":
            print(f"[INTENT] groq -> {g}")
            return g

    if ml_intent:
        print(f"[INTENT] ml -> {ml_intent} ({ml_confidence:.2f})")
        return ml_intent

    print("[INTENT] fallback")
    return "fallback"

def simple_intent_parser(text: str, restaurant_names: list = None) -> str:
    t = text.lower().strip()
    restaurant_names = restaurant_names or []

    if re.search(r'\b(hi|hello|hey|namaste|hlo|hii|sup|howdy|yo|hiya)\b', t): return "greeting"
    if re.search(r'\b(bye|goodbye|see you|alvida|chal bye|tata|later)\b', t): return "goodbye"
    if re.search(r'\b(thanks|thank you|thx|thankyu|thanku|shukriya|dhanyavaad|dhanyawad|ty|thankyou|great|awesome|perfect|bahut accha)\b', t): return "thanks"
    if re.search(r'\b(help|faq|faqs|support|complaint|query|contact|issue|problem|assist)\b', t): return "help"
    if re.search(r"\b(reset password|forgot password|change password|cant login|can't login|login nahi|account help|change email|change phone|password yaad nahi)\b", t): return "account_help"
    if re.search(r"\b(password|credentials)\b", t) and re.search(r"\b(reset|forgot|forget|change|update|help|bhool|problem|issue)\b", t): return "account_help"
    if re.search(r'\b(partner|add\s+my\s+restaurant|how\s+to\s+add\s+my\s+restaurant|apna restaurant|list restaurant|restaurant join|dineous partner|restaurant register)\b', t): return "partner"
    if re.search(r'\b(who are you|about you|what is dinebot|dinebot|bot info)\b', t): return "about_bot"
    if re.search(r'\b(offer|offers|deal|deals|discount|coupon|promo)\b', t): return "offers_deals"
    if re.search(r'\b(payment|pay|checkout|online pay|upi|card)\b', t): return "payment"
    if re.search(r'\b(navigate|navigation|where is|how to go|link|url|page)\b', t): return "navigation_help"
    if re.search(r'\b(kaise login|login kaise|how to use|how to login|how to signup|how to register|profile kahan|order history)\b', t): return "site_navigation"
    if re.search(r'\b(register restaurant|restaurant registration|list my restaurant|partner signup)\b', t): return "restaurant_register"
    if re.search(r'\b(restaurant login|partner login|owner login)\b', t): return "restaurant_login"
    if re.search(r'\b(delivery partner|delivery signup|rider|courier)\b', t): return "delivery_partner"
    if re.search(r"\b(compare|best restaurant|popular restaurant|top restaurant|highest rated|which restaurant is popular|which restaurant is best|konsa accha|cheaper|affordable|better restaurant|rating compare)\b", t): return "recommend_restaurants"
    if re.search(r'\b(restaurant info|about restaurant|rating|reviews)\b', t): return "restaurant_query"
    if re.search(r'\b(recommend|suggest|best|top|popular|bestseller|famous)\b', t):
        if re.search(r'\b(restaurant|restaurants|resto|place|outlet)\b', t): return "recommend_restaurants"
        return "recommendations"
    if re.search(r'\b(same as last|repeat order|last order again|dobara same|order again)\b', t): return "repeat_order"
    if re.search(r'\b(schedule|scheduled|later)\b', t): return "scheduled_order"
    if re.search(r'\b(profile|my info|my details|address|phone|email)\b', t): return "personal_info"
    if re.search(r'\b(veg|vegetarian|non-veg|non veg|vegan)\b', t): return "veg_nonveg"
    if re.search(r'\b(opening hours|open time|closing|timings|hours)\b', t): return "opening_hours"
    if re.search(r'\b(delivery area|deliver to|service area)\b', t): return "delivery_area"
    # FIX P1: "konsa restaurant accha hai" / "which restaurant is best" → recommend, not current_restaurant
    if re.search(r'\b(which restaurant|konsa restaurant|abhi konsa|current restaurant|selected restaurant)\b', t):
        if re.search(r'\b(accha|best|popular|better|suggest|recommend|good|top|famous|rated|try)\b', t):
            return "recommend_restaurants"
        return "current_restaurant"
    if re.search(r'\b(does|kya|milta hai|available hai|hai kya|have|mein milta)\b', t):
        for r in restaurant_names:
            r_lower = r.lower()
            if r_lower in t: return "restaurant_item_query"
            tokens = [tok for tok in re.split(r"\W+", r_lower) if tok and tok not in {"the"}]
            if tokens and all(tok in t for tok in tokens): return "restaurant_item_query"
    if re.search(r'\b(confirm|place order|finalize|order karo|order kar do|place karo|haan order|yes order|order place)\b', t): return "confirm_order"
    if re.search(r'\b(cancl|cancle|cancel|cancelled).{0,25}(table|booking|reservation|seat)\b', t): return "cancel_booking"
    if re.search(r'\b(table|booking|reservation|seat).{0,25}(cancel|cancelled)\b', t): return "cancel_booking"
    if re.search(r'\b(cancel order|cancel my order|cancel this order|cancel it|cancel last order|cancel previous order|cancel the order|order cancel|order mat|cancel karo)\b', t): return "cancel_order"
    if re.search(r'\b(book|reserve|table|seat|reservation|baithna|dine in|dining)\b', t): return "book_table"
    if re.search(r'\b(remove|delete|hata|nikal|mat chahiye)\b', t): return "remove_item"
    # FIX P2: "my order status" aur "mera order" bhi track karega
    if re.search(r'\b(track|where is|order status|kahan hai|status batao|order kahan|my order status|order ka status|mera order|what is my order)\b', t): return "track_order"
    if re.search(r'\b(quiet|calm|family|romantic|date night|ambience|nice place|good place|seating|crowd|peaceful)\b', t): return "fallback"
    if re.search(r'\b(menu|show menu|items|kya milta|food list|dikhao|kha sakte|khana)\b', t): return "menu"
    if re.search(r'\b(show cart|mera cart|cart dikhao|my cart|view cart|cart mein kya|what is in my cart|cart|basket|bag)\b', t): return "show_cart"
    if re.search(r'\b(change|switch|different|badlo|dusra)\s*(restaurant|place|jagah)?\b', t): return "change_restaurant"
    if re.search(r'\b(make it|change to|ek aur|one more|aur ek|quantity change|badha do|kam karo)\b', t): return "update_quantity"
    if re.search(r'\b(order food|can i order|want to order|i want to order|food order|khana order|hungry|bhook|khaana chahiye)\b', t): return "view_restaurants"
    qty_words    = '|'.join(WORD_TO_NUMBER.keys())
    food_context = r'\b(food|menu|item|dish|meal|pizza|burger|biryani|coke|tea|coffee|juice|fries|noodles|khana)\b'
    action_ctx   = r'\b(add|order|want|get me|i want|i need|give me|chahiye|de do|lena|mangwa)\b'
    if re.search(r'^\s*\d+\s*$', t): return "order_item"
    if re.search(r'^\s*\d+\s+\w+', t) and re.search(food_context, t): return "order_item"
    if re.search(rf'^\s*(?:{qty_words})\s+\w+', t) and re.search(food_context, t): return "order_item"
    if re.search(action_ctx, t) and re.search(food_context, t): return "order_item"
    if re.search(action_ctx, t) and re.search(r'\b\d+\b', t): return "order_item"
    if re.search(rf'\b({qty_words})\b', t) and re.search(food_context, t): return "order_item"
    if re.match(r'^\s*(show|restaurant|restaurants|food|order|new|dikhao)\s*$', t): return "view_restaurants"
    return "fallback"

def build_fallback_response(session: dict, lang: str) -> str:
    last = session.get("last_intent") or (session.get("context_stack") or [None])[-1]
    if last == "menu":
        return "Tell me what you want.\n\nExample: **'2 burgers and a coke'**" if lang == "en" else "Menu se kya chahiye?"
    if last == "book_table":
        return "Still want a table? Tell me the missing detail." if lang == "en" else "Table book karna hai? Missing detail batao."
    if last == "confirm_order":
        return "Type **'confirm order'** to place your order." if lang == "en" else "**'confirm order'** bolo."
    return get_response("fallback", lang)

# ══════════════════════════════════════════════════════════════════════════════
# BOOKING STATE MACHINE - FIXED VERSION
# ══════════════════════════════════════════════════════════════════════════════

def _handle_booking(user_id: str, message: str, session: dict, lang: str, all_rests: list):
    saved = session.get("booking_state", {})

    # ── No booking state — start fresh ────────────────────────────────────────
    if not saved:
        matched = match_restaurant_in_message(message, all_rests)
        if matched:
            restaurant_id   = matched.get("id")
            restaurant_name = matched.get("name")
        elif session.get("mentioned_restaurant_id"):
            restaurant_id   = session["mentioned_restaurant_id"]
            restaurant_name = session.get("mentioned_restaurant_name", f"Restaurant #{restaurant_id}")
        else:
            rows = _get_restaurants()
            list_text = format_restaurant_list(rows, lang)
            session["booking_state"] = {
                "awaiting": "restaurant",
                "restaurant_id": None, "restaurant_name": None,
                "booking_mode": None, "people": None,
                "date": None, "time": None, "preorder_items": [],
            }
            session["restaurant_list_shown"] = True
            set_session(user_id, session)
            reply = (
                "🏪 **Which restaurant would you like to book a table at?**\n\n"
                + list_text + "\n\n💬 Reply with the restaurant number."
                if lang == "en" else
                "🏪 **Kaunse restaurant mein table book karna hai?**\n\n"
                + list_text + "\n\n💬 Restaurant ka number reply karo."
            )
            return reply, {"restaurants": prepare_restaurants_for_json(rows)}

        # Restaurant found — extract all fields from first message
        fields = extract_booking_fields(message)
        mode   = parse_booking_mode(message)

        # Validate date if extracted
        extracted_date = fields.get("date")
        if extracted_date and not is_allowed_booking_date(extracted_date):
            extracted_date = None

        # Validate time if extracted
        extracted_time = fields.get("time")
        if extracted_time and not is_allowed_booking_time(extracted_time):
            extracted_time = None

        session["booking_state"] = {
            "awaiting": "booking_type",
            "restaurant_id":   restaurant_id,
            "restaurant_name": restaurant_name,
            "booking_mode": mode,
            "people": fields.get("people"),
            "date":   extracted_date,
            "time":   extracted_time,
            "preorder_items": [],
        }
        # NOTE: active_restaurant sirf delivery ke liye — booking_state mein alag track hoga
        session["mentioned_restaurant_id"]  = restaurant_id
        session["mentioned_restaurant_name"]= restaurant_name
        session["restaurant_list_shown"]    = False
        set_session(user_id, session)

        # UX FIX: Default to dine-out. Skip booking type 1/2 prompt entirely.
        # Pre-order will be offered optionally at the end before confirmation.
        if not saved.get("booking_mode"):
            saved["booking_mode"] = mode or "dine_out"
            session["booking_state"] = saved
        set_session(user_id, session)
        return _advance_booking_after_mode(user_id, session, lang)

    awaiting = saved.get("awaiting", "restaurant")

    # ── Restaurant selection ───────────────────────────────────────────────────
    if awaiting == "restaurant":
        selected = None
        rows = _get_restaurants()
        if message.strip().isdigit():
            rid = int(message.strip())
            selected = next((x for x in rows if x.get("id") == rid), None)
        if not selected:
            lm = message.lower().strip()
            selected = next((x for x in rows if x.get("name", "").lower() in lm), None)
        if not selected:
            selected = match_restaurant_in_message(message, rows)
        if not selected:
            # FIX P0: State preserve karo, restart mat karo
            session["booking_state"] = saved
            set_session(user_id, session)
            return ("Please reply with the restaurant number from the list above."
                    if lang == "en" else "Upar wali list se restaurant number bhejo."), None

        saved["restaurant_id"]   = selected.get("id")
        saved["restaurant_name"] = selected.get("name")
        # UX FIX: Skip booking type prompt — go directly to guests
        saved["booking_mode"]    = "dine_out"
        saved["awaiting"]        = "guests"
        session["booking_state"] = saved
        session["mentioned_restaurant_id"]   = selected.get("id")
        session["mentioned_restaurant_name"] = selected.get("name")
        session["restaurant_list_shown"]     = False
        set_session(user_id, session)
        return _advance_booking_after_mode(user_id, session, lang)

    # ── Booking type (legacy state — migrate to guests directly) ─────────────
    if awaiting == "booking_type":
        # UX FIX: booking_type step no longer shown. If session has old state, move forward.
        mode = parse_booking_mode(message)
        saved["booking_mode"] = mode or "dine_out"
        saved["awaiting"]     = "guests"
        session["booking_state"] = saved
        set_session(user_id, session)
        return _advance_booking_after_mode(user_id, session, lang)

    # ── Pre-order items ────────────────────────────────────────────────────────
    if awaiting == "preorder_items":
        # UX FIX: Allow 'skip' to bypass pre-order
        if re.search(r'\b(skip|no|nahi|mat|baad mein|later|without|sirf table|only table|no food)\b', message, flags=re.I):
            saved["preorder_items"] = []
            saved["awaiting"]       = "guests"
            session["booking_state"] = saved
            set_session(user_id, session)
            return _continue_booking(user_id, session, lang)

        preorders = extract_preorder_items(message, saved.get("restaurant_id"))
        if not preorders:
            # Try generic entity extractor as fallback
            try:
                from chatbot.entity_extractor import extract_items as ee
                if ee:
                    raw = ee(message)
                    if raw:
                        preorders = [{"name": i.get("name",""), "qty": i.get("qty",1), "price": 0} for i in raw if i.get("name")]
            except Exception:
                pass

        if not preorders:
            session["booking_state"] = saved
            set_session(user_id, session)
            return (
                "🤔 I couldn't find those items on the menu.\n\n"
                "💡 Type **'menu'** to see available items, or say **'skip'** to skip pre-order.\n\n"
                "Example: **'2 pizza and 1 coke'**"
                if lang == "en" else
                "🤔 Ye items menu mein nahi mile.\n\n"
                "💡 **'menu'** type karo items dekhne ke liye, ya **'skip'** bolo pre-order skip karne ke liye.\n\n"
                "Example: **'2 pizza aur 1 coke'**"
            ), None

        saved["preorder_items"] = preorders
        saved["awaiting"]       = "guests"
        session["booking_state"] = saved
        set_session(user_id, session)
        return _continue_booking(user_id, session, lang)

    # ── Guests ────────────────────────────────────────────────────────────────
    if awaiting == "guests":
        people_count = extract_people_count(message)
        if not people_count or not (1 <= people_count <= 20):
            # FIX P0: State preserve karo
            session["booking_state"] = saved
            set_session(user_id, session)
            return ("Please enter a guest count between **1 and 20**.\n\nExample: **'4 people'** or just **'4'**"
                    if lang == "en" else "Guest count **1 se 20** ke beech do.\n\nExample: **'4 log'** ya sirf **'4'**"), None
        saved["people"]   = people_count
        saved["awaiting"] = "date"
        session["booking_state"] = saved
        set_session(user_id, session)
        return _continue_booking(user_id, session, lang)

    # ── Date ──────────────────────────────────────────────────────────────────
    if awaiting == "date":
        booking_date = parse_date_from_text(message)
        if not booking_date:
            # FIX P0: State preserve karo — restart mat karo
            session["booking_state"] = saved
            set_session(user_id, session)
            return (
                "❌ Couldn't understand the date.\n\n"
                "Please say **today** or **tomorrow** only.\n\nExample: **'today'** or **'tomorrow'**"
                if lang == "en" else
                "❌ Date samajh nahi aaya.\n\n"
                "Sirf **aaj** ya **kal** bolo.\n\nExample: **'aaj'** ya **'kal'**"
            ), None
        if not is_allowed_booking_date(booking_date):
            # FIX P0: State preserve karo
            session["booking_state"] = saved
            set_session(user_id, session)
            return (
                "❌ Only **today** or **tomorrow** bookings are allowed.\n\nPlease say **today** or **tomorrow**."
                if lang == "en" else
                "❌ Sirf **aaj** ya **kal** ki booking allowed hai.\n\n**Aaj** ya **kal** bolo."
            ), None
        saved["date"]    = booking_date
        saved["awaiting"] = "time"
        session["booking_state"] = saved
        set_session(user_id, session)
        return _continue_booking(user_id, session, lang)

    # ── Time ──────────────────────────────────────────────────────────────────
    if awaiting == "time":
        parsed = parse_time_string(message)
        if not parsed:
            # FIX P0: State preserve karo
            session["booking_state"] = saved
            set_session(user_id, session)
            return (
                "❌ Couldn't understand the time.\n\n"
                "Please give a valid time.\n\nExample: **'7pm'** or **'19:30'**"
                if lang == "en" else
                "❌ Time samajh nahi aaya.\n\nValid time batao.\n\nExample: **'7pm'** ya **'19:30'**"
            ), None
        hh, mm = parsed
        booking_time = f"{hh:02d}:{mm:02d}"
        if not is_time_allowed_for_date(saved.get("date"), booking_time):
            # FIX P0: State preserve karo
            session["booking_state"] = saved
            set_session(user_id, session)
            return (
                "❌ Please choose a time between **11am–3pm** or **6pm–10pm**.\n\nExample: **'7pm'** or **'1pm'**"
                if lang == "en" else
                "❌ **11am–3pm** ya **6pm–10pm** ke beech time do.\n\nExample: **'7pm'** ya **'1pm'**"
            ), None
        saved["time"]    = booking_time
        saved["awaiting"] = "confirmation"
        session["booking_state"] = saved

        rname = saved.get("restaurant_name") or f"Restaurant #{saved.get('restaurant_id')}"
        preorder_text = ""
        if saved.get("preorder_items"):
            preorder_text = "\n🍽️ Pre-order: " + ", ".join(
                f"{i.get('qty',1)}x {i.get('name','Item').title()}" for i in saved["preorder_items"]
            )
        summary = (
            f"📋 **Booking Summary:**\n\n"
            f"🏪 Restaurant: {rname}\n"
            f"👥 Guests: {saved.get('people')}\n"
            f"📅 Date: {saved.get('date')}\n"
            f"🕐 Time: {saved.get('time')}"
            f"{preorder_text}\n\n"
            f"Confirm booking? Reply **yes** or **no**."
            if lang == "en" else
            f"📋 **Booking Summary:**\n\n"
            f"🏪 Restaurant: {rname}\n"
            f"👥 Guests: {saved.get('people')}\n"
            f"📅 Date: {saved.get('date')}\n"
            f"🕐 Time: {saved.get('time')}"
            f"{preorder_text}\n\n"
            f"Booking confirm karein? **yes** ya **no** bolo."
        )
        set_session(user_id, session)
        return summary, None

    # ── Confirmation ───────────────────────────────────────────────────────────
    if awaiting == "confirmation":
        if is_yes(message):
            return _confirm_booking(user_id, saved, session, lang)
        if is_no(message):
            session["booking_state"] = {
                "awaiting": "restaurant",
                "restaurant_id": None, "restaurant_name": None,
                "booking_mode": None, "people": None,
                "date": None, "time": None, "preorder_items": [],
            }
            session["restaurant_list_shown"] = True
            rows = _get_restaurants()
            set_session(user_id, session)
            reply = (
                "Okay, let's start over.\n\n"
                "🏪 **Which restaurant?**\n\n"
                + format_restaurant_list(rows, lang)
                if lang == "en" else
                "Theek hai, phir se shuru karte hain.\n\n"
                "🏪 **Kaunsa restaurant?**\n\n"
                + format_restaurant_list(rows, lang)
            )
            return reply, {"restaurants": prepare_restaurants_for_json(rows)}
        # FIX P0: Unknown input pe state preserve karo
        session["booking_state"] = saved
        set_session(user_id, session)
        return ("Reply **yes** to confirm or **no** to restart."
                if lang == "en" else "Confirm ke liye **yes** ya restart ke liye **no** bolo."), None

    session["booking_state"] = saved
    set_session(user_id, session)
    return next_booking_prompt(saved, lang), None


def _advance_booking_after_mode(user_id: str, session: dict, lang: str):
    """
    FIX P1: Mode set hone ke baad skip already-filled fields.
    Agar date/time/people pehle se hai toh directly summary dikhao.
    """
    saved = session.get("booking_state", {})
    mode  = saved.get("booking_mode")

    # Preorder mode — pehle items maango
    if mode == "preorder" and not saved.get("preorder_items"):
        saved["awaiting"] = "preorder_items"
        session["booking_state"] = saved
        set_session(user_id, session)
        return booking_ask("preorder_items", lang), None

    # Ab guests/date/time check karo
    if not saved.get("people"):
        saved["awaiting"] = "guests"
        session["booking_state"] = saved
        set_session(user_id, session)
        return booking_ask("people", lang), None

    if not saved.get("date"):
        saved["awaiting"] = "date"
        session["booking_state"] = saved
        set_session(user_id, session)
        return booking_ask("date", lang), None

    if not saved.get("time"):
        saved["awaiting"] = "time"
        session["booking_state"] = saved
        set_session(user_id, session)
        return booking_ask("time", lang), None

    # UX FIX: All required fields filled — offer optional pre-order before summary
    # Only ask once: if mode is dine_out AND preorder_items is not yet set AND we haven't asked
    if (saved.get("booking_mode") == "dine_out"
            and "preorder_items_asked" not in saved
            and not saved.get("preorder_items")):
        saved["preorder_items_asked"] = True
        saved["awaiting"] = "preorder_items"
        session["booking_state"] = saved
        set_session(user_id, session)
        return (
            "🍽️ **Would you like to pre-order food?**\n\n"
            "Tell me items & quantities — e.g. **'2 pizza and 1 coke'**\n\n"
            "Or say **'skip'** to just book the table."
            if lang == "en" else
            "🍽️ **Khana pre-order karna chahoge?**\n\n"
            "Items aur quantity batao — e.g. **'2 pizza aur 1 coke'**\n\n"
            "Ya **'skip'** bolo sirf table book karne ke liye."
        ), None

    # Sab fields hain — summary dikhao
    saved["awaiting"] = "confirmation"
    session["booking_state"] = saved
    rname = saved.get("restaurant_name") or f"Restaurant #{saved.get('restaurant_id')}"
    preorder_text = ""
    if saved.get("preorder_items"):
        preorder_text = "\n🍽️ Pre-order: " + ", ".join(
            f"{i.get('qty',1)}x {i.get('name','Item').title()}" for i in saved["preorder_items"]
        )
    summary = (
        f"📋 **Booking Summary:**\n\n"
        f"🏪 Restaurant: {rname}\n"
        f"👥 Guests: {saved.get('people')}\n"
        f"📅 Date: {saved.get('date')}\n"
        f"🕐 Time: {saved.get('time')}"
        f"{preorder_text}\n\n"
        f"Confirm booking? Reply **yes** or **no**."
        if lang == "en" else
        f"📋 **Booking Summary:**\n\n"
        f"🏪 Restaurant: {rname}\n"
        f"👥 Guests: {saved.get('people')}\n"
        f"📅 Date: {saved.get('date')}\n"
        f"🕐 Time: {saved.get('time')}"
        f"{preorder_text}\n\n"
        f"Booking confirm karein? **yes** ya **no** bolo."
    )
    set_session(user_id, session)
    return summary, None


def _continue_booking(user_id: str, session: dict, lang: str):
    """Ask for next unfilled booking field."""
    saved = session.get("booking_state", {})

    if not saved.get("people"):
        saved["awaiting"] = "guests"
        session["booking_state"] = saved
        set_session(user_id, session)
        return booking_ask("people", lang), None

    if not saved.get("date"):
        saved["awaiting"] = "date"
        session["booking_state"] = saved
        set_session(user_id, session)
        return booking_ask("date", lang), None

    if not saved.get("time"):
        saved["awaiting"] = "time"
        session["booking_state"] = saved
        set_session(user_id, session)
        return booking_ask("time", lang), None

    # All fields filled — show confirmation summary
    return _advance_booking_after_mode(user_id, session, lang)


def _confirm_booking(user_id: str, saved: dict, session: dict, lang: str):
    try:
        uid_int    = safe_numeric_user_id(session.get("user_id", "1"))
        booking_id = om.book_table(
            uid_int,
            saved.get("restaurant_id"),
            f"User{uid_int}",
            "1234567890",
            saved.get("date"),
            saved.get("time"),
            saved.get("people"),
        )
        if (saved.get("booking_mode") == "preorder"
                and saved.get("preorder_items")
                and hasattr(om, "add_reservation_preorders")):
            om.add_reservation_preorders(booking_id, saved.get("preorder_items"))

        session["booking_state"]          = {}
        session["last_booking_id"]        = booking_id
        session["last_intent"]            = "booking_completed"
        session["context_stack"]          = []
        session["pending_booking_switch"] = None
        session.pop("mentioned_restaurant_id",   None)
        session.pop("mentioned_restaurant_name", None)
        set_session(session.get("user_id", "1"), session)

        rname = saved.get("restaurant_name") or f"Restaurant #{saved.get('restaurant_id')}"
        reply = (
            f"✅ **Table Booked!**\n\n"
            f"🆔 Booking ID: **{booking_id}**\n"
            f"🏪 Restaurant: {rname}\n"
            f"📅 Date: {saved.get('date')}\n"
            f"🕐 Time: {saved.get('time')}\n"
            f"👥 Guests: {saved.get('people')}\n\n"
            f"💳 Pay at restaurant when you arrive.\n"
            f"Show Booking ID **{booking_id}** at reception! 🎉"
            if lang == "en" else
            f"✅ **Table Book Ho Gaya!**\n\n"
            f"🆔 Booking ID: **{booking_id}**\n"
            f"🏪 Restaurant: {rname}\n"
            f"📅 Date: {saved.get('date')}\n"
            f"🕐 Time: {saved.get('time')}\n"
            f"👥 Guests: {saved.get('people')}\n\n"
            f"💳 Pahunchne pe restaurant mein payment karna.\n"
            f"Reception pe Booking ID **{booking_id}** dikhana! 🎉"
        )
        return reply, {"booking_completed": True}
    except Exception as e:
        print(f"Booking error: {e}")
        return f"❌ Booking failed: {str(e)}", None


def _get_restaurants():
    try:
        return om.get_restaurants() or []
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CHAT HANDLER
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def home():
    return "DineBot backend running ✅"

@app.route("/chat", methods=["POST"])
def chat_handler():
    data    = request.get_json() or {}
    user_id = data.get("user_id", "anonymous")
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"reply": "Please type something!"}), 200

    session = get_session(user_id)
    lang    = get_lang(session, message)

    session["user_id"] = user_id
    if "is_logged_in" in data: session["is_logged_in"] = bool(data.get("is_logged_in"))
    if data.get("user_name"):  session["user_name"]    = data.get("user_name")

    def respond(reply, intent, **extra):
        session["last_bot_msg"] = reply
        set_session(user_id, session)
        payload = {"reply": reply, "intent": intent, "speak": extra.pop("speak", False), "speech_text": extra.pop("speech_text", None)}
        payload.update(extra)
        return jsonify(payload), 200

    # ── PENDING BOOKING INTERRUPT ──────────────────────────────────────────────
    if session.get("pending_booking_switch"):
        pending_target = session.get("pending_booking_switch")

        if re.search(r"\b(continue|booking|book|resume)\b", message, flags=re.I):
            session["pending_booking_switch"] = None
            bot_response = next_booking_prompt(session.get("booking_state", {}), lang)
            set_session(user_id, session)
            return respond(bot_response, "book_table")

        if re.search(r"\b(switch|change|order|menu|track|payment)\b", message, flags=re.I) or is_yes(message):
            session["booking_state"] = {}
            session["pending_booking_switch"] = None
            # FIX P1: mentioned_restaurant clear karo
            session["mentioned_restaurant_id"]   = None
            session["mentioned_restaurant_name"] = None
            set_session(user_id, session)
            if pending_target == "track":
                return respond("Sure. Share your order ID.\n\nExample: **'track 1023'**", "track_order")
            if pending_target == "cancel":
                return respond("Okay. Which order to cancel?\n\nExample: **'cancel 1023'**", "cancel_order")
            if pending_target == "payment":
                return respond(get_response("payment_info", lang), "payment")
            if pending_target == "help":
                return respond(get_response("help", lang), "help")
            return respond("Switched to ordering.\n\nType **'view restaurants'** to start.", "order_item")

        if is_no(message):
            session["pending_booking_switch"] = None
            bot_response = next_booking_prompt(session.get("booking_state", {}), lang)
            set_session(user_id, session)
            return respond(bot_response, "book_table")

        return respond(get_response("booking_interrupt_prompt", lang), "book_table")

    # ── PENDING RESTAURANT SWITCH ──────────────────────────────────────────────
    if session.get("pending_switch"):
        if re.search(r"\b(cancel order|track|help|menu|confirm order)\b", message, flags=re.I):
            session["pending_switch"] = None
        elif is_yes(message):
            clear_temp_order(user_id)
            session["active_restaurant"]    = None
            session["pending_switch"]       = None
            session["restaurant_list_shown"]= True
            rows = _get_restaurants()
            set_session(user_id, session)
            return respond(format_restaurant_list(rows, lang), "view_restaurants",
                           restaurants=prepare_restaurants_for_json(rows))
        elif is_no(message):
            session["pending_switch"] = None
            set_session(user_id, session)
            return respond(get_response("switch_cancelled", lang), "change_restaurant")
        else:
            set_session(user_id, session)
            return respond("Reply **'yes'** or **'no'**." if lang == "en" else "**'yes'** ya **'no'** bolo.", "change_restaurant")

    # ── PENDING CANCEL CONFIRMATION ────────────────────────────────────────────
    if session.get("pending_cancel_order_id"):
        pending_cancel_id = session["pending_cancel_order_id"]
        if is_yes(message) or re.search(r"\b(cancel order|cancel)\b", message, flags=re.I):
            try:
                success = om.cancel_order(pending_cancel_id)
                if success:
                    if session.get("last_order_id") == pending_cancel_id:
                        session["last_order_id"] = None
                    reply = (f"❌ Order #{pending_cancel_id} cancelled successfully."
                             if lang == "en" else f"❌ Order #{pending_cancel_id} cancel ho gaya.")
                else:
                    reply = (f"⚠️ Cannot cancel Order #{pending_cancel_id}. It may be delivered already."
                             if lang == "en" else f"⚠️ Order #{pending_cancel_id} cancel nahi ho sakta.")
            except Exception as e:
                reply = f"❌ Error: {str(e)}"
            session["pending_cancel_order_id"] = None
            set_session(user_id, session)
            return respond(reply, "cancel_order", speak=True, speech_text="Order cancelled.")
        if is_no(message):
            session["pending_cancel_order_id"] = None
            set_session(user_id, session)
            return respond("Okay, order not cancelled. Tell me the exact order ID if you want to cancel a specific one.",
                           "cancel_order")
        return respond("Reply **yes** to confirm cancel or **no** to keep the order."
                       if lang == "en" else "Cancel ke liye **yes** ya rakhne ke liye **no** bolo.", "cancel_order")

    # ── VIEW / CHANGE RESTAURANTS ──────────────────────────────────────────────
    wants_change = bool(re.search(r'\b(change|switch|different|badlo|dusra)\s*(restaurant|place)?\b', message.lower()))
    wants_view   = bool(re.search(r'\b(view restaurants?|show restaurants?|restaurants dikhao)\b', message.lower())
                        or "view restaurant" in message.lower())

    if wants_change or wants_view:
        temp_items = session.get("temp_order", {}).get("items", [])
        if temp_items and session.get("active_restaurant"):
            session["pending_switch"] = "view_restaurants"
            set_session(user_id, session)
            return respond(get_response("switch_warning", lang), "change_restaurant")
        if temp_items:
            clear_temp_order(user_id)
        rows = _get_restaurants()
        session["active_restaurant"]    = None
        session["restaurant_list_shown"]= True
        set_session(user_id, session)
        return respond(format_restaurant_list(rows, lang), "view_restaurants",
                       restaurants=prepare_restaurants_for_json(rows))

    # ── RESTAURANT LIST ────────────────────────────────────────────────────────
    try:
        all_rests        = om.get_restaurants() or []
        rest_names_lower = [rx["name"].lower() for rx in all_rests]
    except Exception:
        all_rests = []; rest_names_lower = []

    session["restaurant_names"] = rest_names_lower
    matched_rest = match_restaurant_in_message(message, all_rests)
    if matched_rest:
        session["mentioned_restaurant_id"]   = matched_rest.get("id")
        session["mentioned_restaurant_name"] = matched_rest.get("name")
        if not session.get("active_restaurant") and not is_booking_message(message):
            session["active_restaurant"] = matched_rest.get("id")

    if message.lower() in rest_names_lower:
        if session.get("active_restaurant"):
            set_session(user_id, session)
            return respond("✅ Restaurant already selected! Type **'menu'** to see items."
                           if lang == "en" else "✅ Restaurant pehle se select hai! **'menu'** type karo.",
                           "select_restaurant")
        set_session(user_id, session)
        return respond("Please select by number. Type **'view restaurants'** first."
                       if lang == "en" else "Number se select karo. **'view restaurants'** type karo.",
                       "select_restaurant")

    if (message.isdigit()
            and not session.get("active_restaurant")
            and session.get("restaurant_list_shown")
            and session.get("booking_state", {}).get("awaiting") != "restaurant"):
        rid = int(message)
        rx  = next((x for x in all_rests if x['id'] == rid), None)
        if rx:
            session["active_restaurant"]         = rx["id"]
            session["restaurant_list_shown"]     = False
            session["mentioned_restaurant_id"]   = rx["id"]
            session["mentioned_restaurant_name"] = rx.get("name")
            set_session(user_id, session)
            return respond(
                f"✅ Selected **{rx['name']}**!\n\n💬 Type 'menu' to see items."
                if lang == "en" else f"✅ **{rx['name']}** select ho gaya!\n\n💬 'menu' type karo.",
                "select_restaurant",
            )
        set_session(user_id, session)
        return respond("❌ Invalid restaurant number. Type **'view restaurants'**.", "select_restaurant")

    if (message.isdigit()
            and not session.get("active_restaurant")
            and not session.get("restaurant_list_shown")
            and session.get("booking_state", {}).get("awaiting") != "restaurant"):
        set_session(user_id, session)
        return respond("Choose a restaurant from the list first.\n\nType **'view restaurants'**."
                       if lang == "en" else "Pehle restaurant list se choose karo.", "view_restaurants")

    # ── INTENT DETECTION ───────────────────────────────────────────────────────
    if (re.search(r"\b(cancel order|cancel my order)\b", message, flags=re.I)
            and not re.search(r"\b(table|booking|reservation)\b", message, flags=re.I)):
        intent = "cancel_order"
    else:
        intent = resolve_intent(message, session, all_rests)
    if intent == "compare_restaurants":
        intent = "recommend_restaurants"

    # Booking state override
    booking_active = session.get("booking_state", {})
    if booking_active and booking_active.get("awaiting") not in (None,):
        missing = not all([booking_active.get("restaurant_id"), booking_active.get("booking_mode"),
                           booking_active.get("people"), booking_active.get("date"), booking_active.get("time")])
        if missing and intent not in BOOKING_EXEMPT_INTENTS:
            intent = "book_table"

    # FIX P0: Only restart booking if user EXPLICITLY says "book a table" AND
    # no booking data has been collected yet. Never destroy an in-progress booking.
    if intent == "book_table" and booking_active and booking_active.get("awaiting"):
        has_any_data = any([
            booking_active.get("restaurant_id"),
            booking_active.get("people"),
            booking_active.get("date"),
            booking_active.get("time"),
            booking_active.get("preorder_items"),
        ])
        if has_any_data:
            pass  # Booking in progress with data — let _handle_booking process it
        elif is_booking_message(message) and not match_restaurant_in_message(message, all_rests):
            # Truly bare "book a table" with zero data collected — restart is safe
            session["booking_state"]             = {}
            session["mentioned_restaurant_id"]   = None
            session["mentioned_restaurant_name"] = None
            set_session(user_id, session)


    # Login wall
    requires_login = {"confirm_order", "book_table", "cancel_order", "cancel_booking", "repeat_order"}
    if intent in requires_login and not is_logged_in_user(user_id, session):
        key = ("login_required_booking" if intent == "book_table"
               else "login_required_cancel" if intent in {"cancel_order", "cancel_booking"}
               else "login_required_order")
        set_session(user_id, session)
        return respond(get_response(key, lang), intent)

    push_intent(user_id, intent)
    bot_response     = None
    extra_payload    = {}
    order_confirmed  = False
    order_tracked    = False
    order_cancelled  = False
    booking_completed = False

    # ── INTENT HANDLERS ────────────────────────────────────────────────────────

    if intent == "view_restaurants":
        rows = _get_restaurants()
        session["active_restaurant"]    = None
        session["restaurant_list_shown"]= True
        set_session(user_id, session)
        bot_response = format_restaurant_list(rows, lang)
        extra_payload["restaurants"] = prepare_restaurants_for_json(rows)

    elif intent == "greeting":
        if is_logged_in_user(user_id, session) and session.get("user_name"):
            bot_response = (f"Hi {session['user_name']}! 👋\n\n💬 Type **'view restaurants'** to start!"
                            if lang == "en" else f"Namaste {session['user_name']}! 👋\n\n💬 **'view restaurants'** type karo!")
        else:
            bot_response = get_response("greeting", lang)

    elif intent == "goodbye":
        bot_response = ("Goodbye! 👋 Have a great day!" if lang == "en" else "Alvida! 👋 Accha din ho!")
        clear_temp_order(user_id)
        session["booking_state"]          = {}
        session["pending_booking_switch"] = None
        session["pending_switch"]         = None
        set_session(user_id, session)

    elif intent == "thanks":
        bot_response = get_response("thanks", lang)

    elif intent == "help":
        bot_response = get_response("help", lang)
        # FIX P1: Help ke baad booking state intact rehni chahiye — kuch clear mat karo

    elif intent == "account_help":
        bot_response = get_response("account_help", lang)

    elif intent == "about_bot":
        bot_response = ("🤖 I'm DineBot — your food ordering and table booking assistant.\n\nStart with **'view restaurants'**."
                        if lang == "en" else "🤖 Main DineBot hoon — food ordering aur table booking assistant.")

    elif intent == "offers_deals":
        bot_response = (
            "🎁 **Offers & Deals on DINEaus**\n\n"
            "1. **Navbar** → click **Offers NEW** in the top navigation\n"
            "2. **Home page** → scroll to **Today's Hot Deals** section:\n"
            "   • FREEDEL — Free Delivery (Save ₹299)\n"
            "   • SWEET2X — Buy 1 Get 1 Free (Desserts)\n"
            "   • UPISAVE — 20% Cashback (UPI)\n"
            "   • FIRST50 — 50% OFF (First Order)\n\n"
            "3. **Restaurant page** → **Deals for you** section (TRYNEW, FLATDEAL)\n"
            "4. **Home filter bar** → click **Offers** chip to filter restaurants with offers"
            if lang == "en" else
            "🎁 **DINEaus par Offers**\n\n"
            "1. **Navbar** → **Offers NEW** click karo\n"
            "2. **Home page** → **Today's Hot Deals** section mein:\n"
            "   • FREEDEL, SWEET2X, UPISAVE, FIRST50\n\n"
            "3. **Restaurant page** → **Deals for you** section\n"
            "4. **Home filter** → **Offers** chip click karo"
        )

    elif intent == "payment":
        bot_response = get_response("payment_info", lang)

    elif intent == "navigation_help":
        bot_response = (
            "🗺️ **DINEaus Navigation Guide**\n\n"
            "👤 **Login/Sign Up** → Top navbar (right side) → /login or /sign\n"
            "🏠 **Home** → Click **DINEaus** logo or **Home** link → /home\n"
            "🔎 **Search** → Navbar search bar → /search\n"
            "🛒 **Cart** → Cart icon (🛒) in navbar → /cart/checkout\n"
            "👤 **Profile** → Click your name → Profile dropdown → /profile\n"
            "📦 **Orders** → Profile → Orders tab\n"
            "🪑 **Bookings** → Profile → Bookings tab\n"
            "📍 **Addresses** → Profile → Address tab\n"
            "🤝 **Partner** → Home footer → Partner with us → /dineous-partner\n"
            "❓ **Help** → Navbar → Help → /help\n"
            "🎁 **Offers** → Navbar → Offers NEW"
            if lang == "en" else
            "🗺️ **DINEaus Navigation**\n\n"
            "👤 **Login/Sign Up** → Top navbar → /login ya /sign\n"
            "🏠 **Home** → Logo ya Home link → /home\n"
            "🔎 **Search** → Navbar search bar\n"
            "🛒 **Cart** → Cart icon navbar mein\n"
            "👤 **Profile** → Naam click → Profile\n"
            "📦 **Orders** → Profile → Orders tab\n"
            "🤝 **Partner** → Footer → Partner with us\n"
            "❓ **Help** → Navbar → Help"
        )

    elif intent == "site_navigation":
        bot_response = (
            "🗺️ **DINEaus Website Guide**\n\n"
            "👤 **Account:** Top navbar → **Login** (/login) or **SignUp** (/sign)\n"
            "🍽️ **Order Food:** Home → click restaurant → view menu → **ADD** items → **Cart** (🛒) → Checkout → Pay\n"
            "🪑 **Book Table:** Restaurant page → **Reserve / Seat / Preorder** button → fill details → **Book Now**\n"
            "   Or type **'book a table'** here in chat!\n"
            "🔎 **Search:** Navbar search bar — search restaurants or dishes (/search)\n"
            "📦 **Track Order:** **Profile → Orders → Track Order** (/track-order/:id)\n"
            "🤝 **Partner:** Home footer → **Partner with us** (/dineous-partner)\n"
            "🚗 **Delivery Partner:** /delivery/register\n"
            "❓ **Help:** Navbar → **Help** (/help)\n"
            "🎁 **Offers:** Navbar → **Offers NEW** or Home → Today's Hot Deals"
            if lang == "en" else
            "🗺️ **DINEaus Website Guide**\n\n"
            "👤 **Account:** Navbar → **Login** (/login) ya **SignUp** (/sign)\n"
            "🍽️ **Order:** Home → restaurant click → menu → **ADD** → **Cart** → Checkout\n"
            "🪑 **Table:** Restaurant page → **Reserve / Seat / Preorder** button\n"
            "   Ya chat mein **'book a table'** type karo!\n"
            "🔎 **Search:** Navbar search bar (/search)\n"
            "📦 **Track:** **Profile → Orders → Track Order**\n"
            "🤝 **Partner:** Footer → **Partner with us** (/dineous-partner)\n"
            "❓ **Help:** Navbar → **Help** (/help)\n"
            "🎁 **Offers:** Navbar → **Offers NEW**"
        )

    elif intent == "partner":
        bot_response = (
            "🤝 **Add Your Restaurant to DINEaus**\n\n"
            "**How to start:**\n"
            "1. Go to Home page footer → under 'Contact us' → click **Partner with us**\n"
            "   Or visit directly: /dineous-partner\n\n"
            "**4-Step Onboarding:**\n"
            "📋 Step 1: **Restaurant Information** — name, address, owner contact, working hours\n"
            "📄 Step 2: **Documents** — PAN card, GSTIN, FSSAI license, bank details\n"
            "🍽️ Step 3: **Menu Setup** — cuisine type, upload menu (max 25MB), set prices\n"
            "📝 Step 4: **Partner Contract**\n\n"
            "**Required documents:** FSSAI License, PAN Card, GSTIN, Bank Account, Menu\n\n"
            "After approval, login at **/restaurant-admin/login** to manage orders & bookings."
            if lang == "en" else
            "🤝 **Apna Restaurant DINEaus par Add Karo**\n\n"
            "**Kaise shuru kare:**\n"
            "1. Home footer → 'Contact us' → **Partner with us** click karo\n"
            "   Ya directly jao: /dineous-partner\n\n"
            "**4-Step Process:**\n"
            "📋 Step 1: **Restaurant Information** — naam, address, contact, hours\n"
            "📄 Step 2: **Documents** — PAN, GSTIN, FSSAI, bank details\n"
            "🍽️ Step 3: **Menu Setup** — cuisine, menu upload, prices\n"
            "📝 Step 4: **Partner Contract**\n\n"
            "Approval ke baad **/restaurant-admin/login** se login karo."
        )

    elif intent == "restaurant_register":
        bot_response = (
            "Go to Home footer → **Partner with us** (/dineous-partner) → click **Continue**.\n\n"
            "Complete: Restaurant Information → Documents (PAN, GSTIN, FSSAI, bank) → Menu Setup → Partner Contract.\n\n"
            "After approval, login at **/restaurant-admin/login**."
            if lang == "en" else
            "Home footer → **Partner with us** (/dineous-partner) → **Continue** click karo.\n\n"
            "Restaurant Info → Documents → Menu Setup complete karo.\n\n"
            "Approval ke baad **/restaurant-admin/login** se login karo."
        )

    elif intent == "restaurant_login":
        bot_response = (
            "🏪 Restaurant owners login at: **/restaurant-admin/login**\n\n"
            "Enter your restaurant credentials to access the dashboard where you can:\n"
            "• Accept/Reject orders\n"
            "• Manage table bookings\n"
            "• View order history"
            if lang == "en" else
            "🏪 Restaurant owner login: **/restaurant-admin/login**\n\n"
            "Dashboard par orders aur bookings manage karo."
        )

    elif intent == "delivery_partner":
        bot_response = (
            "🚗 **Become a Delivery Partner**\n\n"
            "1. Go to **/delivery/register** to sign up\n"
            "2. Fill in your details and register\n"
            "3. Login at **/delivery/login**\n"
            "4. Access your dashboard to accept & deliver orders!\n\n"
            "📍 Access via Home footer → 'Ride with us'"
            if lang == "en" else
            "🚗 **Delivery Partner Bano**\n\n"
            "1. **/delivery/register** par jao\n"
            "2. Details bharo aur register karo\n"
            "3. **/delivery/login** se login karo\n"
            "4. Dashboard se orders accept karo!"
        )

    elif intent in ("restaurant_compare", "restaurant_query"):
        bot_response = ("Restaurant details are on their pages.\n\nType **'view restaurants'** to browse."
                        if lang == "en" else "Restaurant details unke pages par milti hain.")

    elif intent == "recommend_restaurants":
        rows = _get_restaurants()
        compare_like = bool(re.search(
            r"\b(compare|best restaurant|popular|top restaurant|highest rated|cheapest|cheaper|affordable|which is good)\b",
            message, flags=re.I,
        ))
        if not rows:
            bot_response = "No restaurants available right now." if lang == "en" else "Abhi koi restaurant available nahi hai."
        elif compare_like:
            comparisons = []
            for rx in rows:
                _, pm = get_restaurant_menu(rx.get("id"))
                prices = list(pm.values()) if pm else []
                if prices:
                    comparisons.append({"name": rx.get("name"), "min": min(prices), "max": max(prices), "avg": sum(prices)/len(prices)})
            if not comparisons:
                bot_response = "No menu data for comparison." if lang == "en" else "Comparison ke liye menu data nahi hai."
            else:
                lines = [f"{i+1}. {r['name']} — Avg ₹{r['avg']:.0f} (₹{r['min']:.0f}–₹{r['max']:.0f})" for i, r in enumerate(comparisons)]
                bot_response = ("📊 **Price Comparison:**\n\n" + "\n".join(lines) + "\n\nType restaurant number to select!"
                                if lang == "en" else "📊 **Price Comparison:**\n\n" + "\n".join(lines) + "\n\nRestaurant number type karo!")
        else:
            bot_response = format_restaurant_list(rows, lang)
            extra_payload["restaurants"] = prepare_restaurants_for_json(rows)

    elif intent == "restaurant_item_query":
        target_id = session.get("mentioned_restaurant_id") or session.get("active_restaurant")
        if not target_id:
            bot_response = "Which restaurant? Type **'view restaurants'** first." if lang == "en" else "Kaunsa restaurant?"
        else:
            menu_list, price_map = get_restaurant_menu(target_id)
            if not menu_list:
                bot_response = "No menu found." if lang == "en" else "Menu nahi mila."
            else:
                matched_item = find_menu_item_in_message(message, menu_list)
                if matched_item:
                    price = price_map.get(matched_item, 0)
                    bot_response = (f"✅ Yes, **{matched_item.title()}** is available — ₹{price}"
                                    if lang == "en" else f"✅ Haan, **{matched_item.title()}** available hai — ₹{price}")
                else:
                    sugg = suggest_close_items(message, menu_list)
                    if sugg:
                        bot_response = f"Not found. Did you mean: **{', '.join(s.title() for s in sugg)}**?"
                    else:
                        bot_response = "That item isn't on the menu." if lang == "en" else "Wo item menu mein nahi hai."

    elif intent == "recommendations":
        active = session.get("active_restaurant")
        if re.search(r"\b(restaurant|restaurants|place|outlet)\b", message, flags=re.I):
            rows = _get_restaurants()
            if rows:
                bot_response = format_restaurant_list(rows, lang)
                extra_payload["restaurants"] = prepare_restaurants_for_json(rows)
            else:
                bot_response = "No restaurants available." if lang == "en" else "Koi restaurant available nahi hai."
        elif not active:
            bot_response = get_response("no_restaurant", lang)
        else:
            menu_list, _ = get_restaurant_menu(active)
            if not menu_list:
                bot_response = "No menu available." if lang == "en" else "Menu nahi hai."
            else:
                picks = menu_list[:3]
                bot_response = (f"⭐ Popular picks: **{', '.join(p.title() for p in picks)}**\n\nTell me what to add!"
                                if lang == "en" else f"⭐ Popular: **{', '.join(p.title() for p in picks)}**\n\nKya add karu?")

    elif intent == "repeat_order":
        if session.get("last_order_id"):
            bot_response = (f"Reorder from #**{session['last_order_id']}**.\n\nGo to **Profile → Orders**."
                            if lang == "en" else f"Last order #**{session['last_order_id']}** se reorder karo.")
        else:
            bot_response = "No previous order found.\n\nGo to **Profile → Orders**." if lang == "en" else "Koi order nahi mila."

    elif intent == "scheduled_order":
        bot_response = (
            "⏰ **Schedule an Order**\n\n"
            "1. Add items to your **Cart** (🛒 icon in navbar)\n"
            "2. Go to **Checkout** (/cart/checkout)\n"
            "3. Look for the **Schedule** option\n"
            "4. Set your preferred delivery date and time\n"
            "5. Complete payment — order delivers at scheduled time!\n\n"
            "Cancel scheduled orders: **Profile → Orders → Cancel Order**"
            if lang == "en" else
            "⏰ **Order Schedule Karo**\n\n"
            "1. **Cart** mein items add karo\n"
            "2. **Checkout** (/cart/checkout) jao\n"
            "3. **Schedule** option set karo\n"
            "4. Payment complete karo — scheduled time par deliver hoga!"
        )

    elif intent == "personal_info":
        bot_response = (
            "👤 **Your Profile**\n\n"
            "Go to: top navbar → click your **name** → **Profile** (/profile)\n\n"
            "**Profile tabs:**\n"
            "📦 Orders — View, track, reorder\n"
            "🪑 Bookings — View, cancel table bookings\n"
            "❤️ Favourites — Saved restaurants\n"
            "💳 Payments — Saved payment methods\n"
            "📍 Address — Add/manage delivery addresses\n"
            "⚙️ Settings — Preferences\n\n"
            "**Edit profile:** Profile → **Edit Profile** (/profile/edit) to update phone or email"
            if lang == "en" else
            "👤 **Aapka Profile**\n\n"
            "Navbar → apna **naam** click karo → **Profile** (/profile)\n\n"
            "📦 Orders · 🪑 Bookings · ❤️ Favourites · 💳 Payments · 📍 Address · ⚙️ Settings\n\n"
            "Phone/email update: Profile → **Edit Profile** (/profile/edit)"
        )

    elif intent == "veg_nonveg":
        bot_response = (
            "🥬 **Veg & Non-Veg Options**\n\n"
            "Both available! On any restaurant page:\n"
            "• Click the **Veg** toggle to show only vegetarian items\n"
            "• Click the **Non-Veg** toggle for non-veg items\n\n"
            "On Home page: use the **Pure Veg** filter chip to see veg-only restaurants.\n\n"
            "Select a restaurant and type **'menu'** to see items!"
            if lang == "en" else
            "🥬 Veg aur Non-veg dono available!\n\n"
            "Restaurant page par **Veg/Non-Veg** toggle use karo.\n"
            "Home page par **Pure Veg** filter chip click karo."
        )

    elif intent == "opening_hours":
        bot_response = (
            "🕒 **Restaurant Hours**\n\n"
            "Opening/closing times are shown on each restaurant's page.\n\n"
            "For **table bookings**, available slots are:\n"
            "🍽️ Lunch: 11:00 AM – 3:00 PM\n"
            "🌙 Dinner: 6:00 PM – 10:00 PM\n\n"
            "Browse restaurants: type **'view restaurants'** or go to Home (/home)"
            if lang == "en" else
            "🕒 **Restaurant Hours**\n\n"
            "Timings restaurant page par dikhte hain.\n\n"
            "Table booking slots:\n"
            "🍽️ Lunch: 11 AM – 3 PM\n"
            "🌙 Dinner: 6 PM – 10 PM"
        )

    elif intent == "delivery_area":
        bot_response = (
            "📍 **Delivery Area**\n\n"
            "DINEaus delivers in **679+ cities** across India!\n\n"
            "To check if we deliver to your area:\n"
            "1. Add items to cart\n"
            "2. Go to **Checkout** (/cart/checkout)\n"
            "3. Enter your delivery address\n"
            "4. Available restaurants will be shown for your location\n\n"
            "You can also set your address in **Profile → Address** tab."
            if lang == "en" else
            "📍 DINEaus **679+ cities** mein deliver karta hai!\n\n"
            "Checkout par address enter karo — delivery check ho jayega."
        )

    elif intent == "current_restaurant":
        active = session.get("active_restaurant")
        if active:
            rx = next((x for x in all_rests if x['id'] == active), None)
            name = rx['name'] if rx else f"Restaurant #{active}"
            bot_response = (f"🏪 Currently selected: **{name}**\n\nType **'menu'** to see items or **'view restaurants'** to change."
                            if lang == "en" else f"🏪 Abhi **{name}** select hai.\n\n**'menu'** type karo ya **'view restaurants'** se badlo.")
        else:
            bot_response = "No restaurant selected.\n\nType **'view restaurants'**." if lang == "en" else "Koi restaurant select nahi hai."

    elif intent == "menu":
        active = session.get("active_restaurant")
        if not active:
            bot_response = get_response("no_restaurant", lang)
        else:
            menu_list, price_map = get_restaurant_menu(active)
            if not menu_list:
                bot_response = "No menu items found." if lang == "en" else "Menu abhi available nahi hai."
            else:
                menu_text = "🍽️ **Menu:**\n\n"
                for idx, item in enumerate(menu_list, 1):
                    menu_text += f"{idx}. {item.title()} - ₹{price_map[item]}\n"
                menu_text += "\n💬 What would you like?\n💡 Try: **'2 pizzas and a coke'**" if lang == "en" else "\n💬 Kya loge?\n💡 Try: **'2 pizza aur ek coke'**"
                bot_response = menu_text

    elif intent in ("new_order", "order_item", "fallback"):
        active = session.get("active_restaurant")
        if not active:
            bot_response = get_response("fallback", lang) if intent == "fallback" else get_response("no_restaurant", lang)
        else:
            menu_list, price_map = get_restaurant_menu(active)
            if not menu_list:
                bot_response = "No menu available." if lang == "en" else "Menu nahi hai."
            else:
                items = extract_items_from_message(message, menu_list, price_map)
                if items:
                    temp_items = session["temp_order"].get("items", [])
                    added_any  = False
                    for item in items:
                        name      = item.get("name")
                        qty       = int(item.get("qty", 1) or 1)
                        signature = f"add:{name.lower()}:{qty}"
                        if _is_recent_duplicate(session, signature, window_seconds=2.0):
                            continue
                        existing = next((i for i in temp_items if i["name"].lower() == name.lower()), None)
                        if existing:
                            existing["qty"] += qty
                        else:
                            temp_items.append({"name": name, "qty": qty, "price": item.get("price", 0)})
                        session["last_added_item"] = name
                        _record_action(session, signature)
                        added_any = True
                    session["temp_order"]["items"] = temp_items
                    set_session(user_id, session)
                    if added_any or temp_items:
                        total = sum(i['price'] * i['qty'] for i in temp_items)
                        bot_response = (f"✅ Added to cart!\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**\n\n💬 Say **'confirm order'** to place!"
                                        if lang == "en" else f"✅ Cart mein add ho gaya!\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**\n\n💬 **'confirm order'** bolo!")
                    else:
                        bot_response = get_response("item_not_found", lang)
                else:
                    if intent == "fallback":
                        bot_response = build_fallback_response(session, lang)
                    else:
                        sugg = suggest_close_items(message, menu_list)
                        if sugg:
                            bot_response = (f"🤔 Item not found.\n\n💡 Did you mean: **{', '.join(s.title() for s in sugg)}**?"
                                            if lang == "en" else f"🤔 Item nahi mila.\n\n💡 Kya yeh chahte the: **{', '.join(s.title() for s in sugg)}**?")
                        else:
                            bot_response = get_response("item_not_found", lang)

    elif intent == "show_cart":
        temp_items = session.get("temp_order", {}).get("items", [])
        if not temp_items:
            bot_response = get_response("empty_cart", lang)
        else:
            total = sum(i['price'] * i['qty'] for i in temp_items)
            bot_response = (f"🛒 **Your Cart:**\n\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**\n\n💬 **'confirm order'** to place!"
                            if lang == "en" else f"🛒 **Aapka Cart:**\n\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**\n\n💬 **'confirm order'** bolo!")

    elif intent == "update_quantity":
        temp_items = session.get("temp_order", {}).get("items", [])
        if not temp_items:
            bot_response = get_response("empty_cart", lang)
        else:
            active = session.get("active_restaurant")
            menu_list, price_map = get_restaurant_menu(active) if active else (None, None)
            parsed = []
            if extract_items: parsed = extract_items(message, menu_list)
            if not parsed:    parsed = extract_items_from_message(message, menu_list or [], price_map or {})
            updated = []
            for item in parsed:
                name = item.get("name"); qty = int(item.get("qty", 1) or 1)
                if not name: continue
                existing = next((i for i in temp_items if i["name"].lower() == name.lower()), None)
                if existing:
                    existing["qty"] = qty; updated.append(existing["name"].title())
            session["temp_order"]["items"] = temp_items
            if updated:
                total = sum(i['price'] * i['qty'] for i in temp_items)
                bot_response = (f"✅ Updated: {', '.join(updated)}\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**"
                                if lang == "en" else f"✅ Update ho gaya: {', '.join(updated)}")
            else:
                bot_response = "Tell me which item and new quantity." if lang == "en" else "Kaunsa item aur kitni quantity chahiye?"

    elif intent == "remove_item":
        temp_items = session["temp_order"].get("items", [])
        if not temp_items:
            bot_response = get_response("empty_cart", lang)
        else:
            active = session.get("active_restaurant")
            menu_list, _ = get_restaurant_menu(active) if active else (None, None)
            if not menu_list:
                clear_temp_order(user_id)
                bot_response = "✅ Cart cleared! 🛒" if lang == "en" else "✅ Cart saaf ho gaya! 🛒"
            else:
                pronoun_match = re.search(r"\b(it|that|this|them|same|last)\b", message.lower())
                items_to_remove = []
                if pronoun_match:
                    target = session.get("last_added_item") or (temp_items[-1]["name"] if temp_items else None)
                    if target: items_to_remove = [target]
                if not items_to_remove:
                    items_to_remove = [
                        matched for word in message.lower().split() if len(word) > 2
                        for matched, conf in [fuzzy_match_item(word, menu_list)] if matched and conf >= 0.6
                    ]
                if items_to_remove:
                    removed = []
                    for item_name in items_to_remove:
                        before     = len(temp_items)
                        temp_items = [i for i in temp_items if i["name"].lower() != item_name.lower()]
                        if len(temp_items) < before: removed.append(item_name.title())
                    if session.get("last_added_item") and any(session["last_added_item"].lower() == r.lower() for r in removed):
                        session["last_added_item"] = None
                    session["temp_order"]["items"] = temp_items
                    set_session(user_id, session)
                    if temp_items:
                        total = sum(i['price'] * i['qty'] for i in temp_items)
                        bot_response = (f"✅ Removed {', '.join(removed)}.\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**"
                                        if lang == "en" else f"✅ {', '.join(removed)} hata diya.")
                    else:
                        bot_response = "✅ Cart is now empty! 🛒" if lang == "en" else "✅ Cart bilkul khali hai! 🛒"
                        clear_temp_order(user_id)
                else:
                    item_names = [i['name'].title() for i in temp_items]
                    bot_response = (f"Which item to remove?\n\nCart: {', '.join(item_names)}"
                                    if lang == "en" else f"Kaun sa item hatana hai?\n\nCart: {', '.join(item_names)}")

    elif intent == "confirm_order":
        temp_items = session["temp_order"].get("items", [])
        active     = session.get("active_restaurant")
        if not temp_items:
            bot_response = get_response("empty_cart", lang)
        elif not active:
            bot_response = get_response("no_restaurant", lang)
        else:
            try:
                total_price = sum(i["qty"] * i["price"] for i in temp_items)
                db_items    = format_items_for_db(temp_items)
                uid_int     = safe_numeric_user_id(user_id)
                order_id    = om.add_order(uid_int, active, db_items, total_price)
                if hasattr(om, "add_cart_items"): om.add_cart_items(uid_int, active, db_items)
                om.confirm_order(order_id)
                items_text = "\n".join(f"• {i['qty']}x {i['name'].title()}" for i in temp_items)
                clear_temp_order(user_id)
                session["last_order_id"] = order_id
                set_session(user_id, session)
                order_confirmed = True
                bot_response = (f"🎉 **Order Confirmed!**\n\n📋 Order ID: **{order_id}**\n\n**Items:**\n{items_text}\n\n💰 **Total: ₹{total_price}**\n\n🧾 Open Cart → Checkout to pay.\n\n📱 Track: **'track {order_id}'**"
                                if lang == "en" else f"🎉 **Order Confirm Ho Gaya!**\n\n📋 Order ID: **{order_id}**\n\n**Items:**\n{items_text}\n\n💰 **Total: ₹{total_price}**\n\n📱 Track: **'track {order_id}'**")
                extra_payload["redirect"] = "/cart/checkout"
            except Exception as e:
                import traceback; traceback.print_exc()
                bot_response = f"❌ Error placing order: {str(e)}"

    elif intent == "track_order":
        order_id = None
        if extract_order_id: order_id = extract_order_id(message)
        if not order_id:
            m = re.search(r'\b(\d{1,8})\b', message)
            if m:
                try: order_id = int(m.group(1))
                except: pass
        if not order_id and session.get("last_order_id"): order_id = session["last_order_id"]
        if order_id:
            try:
                order = om.track_order(order_id)
                if order:
                    session["last_order_id"] = order_id  # FIX P0: Remember tracked order for "my order status"
                    order_tracked = True
                    raw_items  = order.get("items", [])
                    items_text = "\n".join(f"• {i.get('quantity', i.get('qty', 1))}x {i.get('item_name', i.get('name', 'Item')).title()}" for i in raw_items)
                    emoji      = {"pending":"⏳","accepted":"✅","preparing":"👨‍🍳","ready":"🔔","out_for_delivery":"🚗","picked_up":"📦","delivered":"🎉","completed":"✔️","rejected":"❌","cancelled":"❌"}.get(order['status'], "📦")
                    total      = order.get('total_price', order.get('total', 0))
                    bot_response = f"📦 **Order #{order_id}**\n\n{emoji} Status: **{order['status'].upper()}**\n\n**Items:**\n{items_text}\n\n💰 Total: ₹{total}"
                else:
                    bot_response = f"❌ Order #{order_id} not found." if lang == "en" else f"❌ Order #{order_id} nahi mila."
            except Exception as e:
                bot_response = f"❌ Error: {str(e)}"
        else:
            bot_response = "📝 Please provide order ID.\n\nExample: **'track 1023'**" if lang == "en" else "📝 Order ID batao."

    elif intent == "cancel_order":
        cancel_id = None

        # FIX P0: Extract order ID from message ONLY if explicitly stated (4-8 digit number)
        m = re.search(r'\b(\d{4,8})\b', message)
        if m:
            cancel_id = int(m.group(1))

        # FIX P0: If no explicit order ID, ONLY use last_order_id from THIS session
        # NEVER auto-fetch latest DB order — that causes random old-order cancellations
        if not cancel_id:
            session_order_id = session.get("last_order_id")
            if session_order_id:
                cancel_id = session_order_id
            else:
                # No order context at all — ask for ID instead of guessing
                set_session(user_id, session)
                bot_response = (
                    "Which order would you like to cancel?\n\n"
                    "📝 Type: **'cancel order 1023'** with your order number.\n\n"
                    "Find your order ID in **Profile → Orders** or on your order confirmation."
                    if lang == "en" else
                    "Kaun sa order cancel karna hai?\n\n"
                    "📝 Type karo: **'cancel order 1023'** apna order number ke saath.\n\n"
                    "Order ID **Profile → Orders** mein ya order confirmation mein milega."
                )
                return respond(bot_response, "cancel_order")

        if cancel_id:
            items_text = ""
            try:
                order = om.track_order(cancel_id)
                if order:
                    raw = order.get("items", [])
                    items_text = ", ".join(
                        f"{i.get('quantity', i.get('qty',1))}x {i.get('item_name', i.get('name','Item')).title()}"
                        for i in raw
                    ) if raw else ""
            except Exception:
                pass
            session["pending_cancel_order_id"] = cancel_id
            set_session(user_id, session)
            item_line = f"\n📦 Items: {items_text}" if items_text else ""
            return respond(
                f"⚠️ **Cancel Order #{cancel_id}?**{item_line}\n\nReply **'yes'** to cancel or **'no'** to keep."
                if lang == "en" else
                f"⚠️ **Order #{cancel_id} cancel karna hai?**{item_line}\n\n**'yes'** bolo cancel ke liye ya **'no'** rakhne ke liye.",
                "cancel_order",
            )
        else:
            bot_response = "Which order to cancel?\n\n📝 Try: **'cancel order 1023'**" if lang == "en" else "Kaun sa order cancel karna hai?\n\n📝 Try: **'cancel order 1023'**"

    elif intent == "cancel_booking":
        last_booking = session.get("last_booking_id")
        bot_response = (
            f"❌ **Cancel a Table Booking**\n\n"
            f"1. Go to **Profile** (click your name in navbar)\n"
            f"2. Click the **Bookings** tab\n"
            f"3. Find your booking → click **Cancel Booking**\n\n"
            f"⚠️ You can cancel while status is **Pending** or **Accepted**.\n"
            f"Once the restaurant marks you as **Arrived**, cancellation is closed.\n\n"
            f"Your latest Booking ID: **#{last_booking or '?'}**\n\n"
            f"📍 Direct link: /profile (then click Bookings tab)"
            if lang == "en" else
            f"❌ **Table Booking Cancel Karo**\n\n"
            f"1. **Profile** jao (navbar mein naam click karo)\n"
            f"2. **Bookings** tab click karo\n"
            f"3. Booking dhundho → **Cancel Booking** click karo\n\n"
            f"⚠️ Cancel tab **Pending** ya **Accepted** status tak kar sakte ho.\n\n"
            f"Latest Booking ID: **#{last_booking or '?'}**"
        )

    elif intent == "booking_interrupt":
        session["pending_booking_switch"] = detect_booking_interrupt_target(message)
        bot_response = get_response("booking_interrupt_prompt", lang)
        set_session(user_id, session)
        return respond(bot_response, "book_table")

    elif intent == "book_table":
        reply, extra = _handle_booking(user_id, message, session, lang, all_rests)
        session = get_session(user_id)
        bot_response = reply
        if extra:
            extra_payload.update(extra)
            if extra.get("booking_completed"):
                booking_completed = True

    if not bot_response:
        bot_response = build_fallback_response(session, lang)

    session["last_bot_msg"] = bot_response
    set_session(user_id, session)

    should_speak = (
        (intent == "confirm_order" and order_confirmed)
        or (intent == "track_order" and order_tracked)
        or (intent == "cancel_order" and order_cancelled)
        or (intent == "book_table"   and booking_completed)
    )
    speech_text = {
        "confirm_order": "Order confirmed. Ready in 30 minutes.",
        "track_order":   "Here is your order status.",
        "book_table":    "Table booked successfully.",
        "cancel_order":  "Order cancelled.",
    }.get(intent) if should_speak else None

    payload = {"reply": bot_response, "intent": intent, "speak": should_speak, "speech_text": speech_text}
    payload.update(extra_payload)
    return jsonify(payload), 200


@app.route("/reset", methods=["POST"])
def reset_chat():
    data = request.get_json() or {}
    reset_session(data.get("user_id", "anonymous"))
    return jsonify({"status": "reset"}), 200


@app.route('/health', methods=['GET'])
def health():
    db_type = 'MySQL' if (OrderManager is not None and isinstance(om, OrderManager)) else 'In-Memory'
    return jsonify({
        'status':        'healthy',
        'ml_model':      ml_model is not None,
        'order_manager': om is not None,
        'database':      db_type,
        'timestamp':     datetime.now(UTC).isoformat(),
    }), 200


if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '1') == '1'
    port  = int(os.getenv('PORT', 5000))
    print(f"\n🚀 DineBot Server Starting...")
    print(f"📊 ML Model: {'✅' if ml_model else '⚠️ Regex fallback'}")
    print(f"💾 Database: {'✅ MySQL' if (OrderManager is not None and isinstance(om, OrderManager)) else '⚠️ In-Memory'}")
    print(f"🌐 Port: {port}\n")
    app.run(host='0.0.0.0', port=port, debug=debug)