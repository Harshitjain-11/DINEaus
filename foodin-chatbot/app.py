"""
PRODUCTION Flask App - DINEaus Chatbot Backend
All fixes applied (latest version):
- All 8 bugs from chat log fixed
- Booking state properly cleared after success
- Plain number "4" parsed as people count
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

# Avoid UnicodeEncodeError on Windows consoles by forcing UTF-8 with backslashreplace
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
    get_session = None
    set_session = None
    push_intent = None
    reset_session = None
    clear_temp_order = None

try:
    from chatbot.entity_extractor import extract_order_id, extract_items
    print("entity_extractor loaded")
except Exception:
    print("entity_extractor import warning: chatbot.entity_extractor could not be loaded")
    extract_order_id = None
    extract_items = None

try:
    from groq import Groq
except Exception:
    Groq = None

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
USE_GROQ = os.getenv("USE_GROQ", "true").strip().lower() not in {"0", "false", "no", "off"}
GROQ_SYSTEM_PROMPT_PATH = Path(__file__).parent / "data" / "groq_system_prompt.txt"

DB_CONFIG = {
    'user':       os.getenv('DB_USER', 'root'),
    'password':   os.getenv('DB_PASS', 'harshit@123'),
    'host':       os.getenv('DB_HOST', '127.0.0.1'),
    'database':   os.getenv('DB_NAME', 'college_practice'),
    'port':       int(os.getenv('DB_PORT', '3306')),
    'autocommit': False,
}

app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "*"}, r"/reset": {"origins": "*"}, r"/health": {"origins": "*"}})

if GROQ_API_KEY and Groq is not None and USE_GROQ:
    print(f"GROQ ENABLED\nModel: {GROQ_MODEL}\nAPI Key Loaded: True")
else:
    print("GROQ DISABLED")
    print(f"Model: {GROQ_MODEL}\nAPI Key Loaded: {bool(GROQ_API_KEY)}\nUSE_GROQ: {USE_GROQ}")


WORD_TO_NUMBER = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'a': 1, 'an': 1,
    'ek': 1, 'do': 2, 'teen': 3, 'char': 4, 'paanch': 5,
    'chhe': 6, 'saat': 7, 'aath': 8, 'nau': 9, 'das': 10
}

_HINDI_MARKERS = {
    'kya','hai','hain','mujhe','chahiye','karo','bhai','kal','aaj','log',
    'kitne','mere','mera','nahi','nhi','kar','krna','krdo','krdiya','batao',
    'wala','wali','smjh','hua','thi','tha','hoga','kab','kaise','kyun',
    'kaun','yahan','wahan','abhi','phir','bolo','dedo','chahte','aana',
    'theek','accha','sahi','bilkul','zaroor','ek','do','teen','char',
    'paanch','log','baje','raat','subah','sham','parso','kitna','kitni',
    'karna','dekho','dikhao','milta','khana','lena','dena','mangwa'
}

def detect_language(text: str) -> str:
    words = set(text.lower().split())
    return 'hi' if len(words & _HINDI_MARKERS) >= 1 else 'en'

def get_lang(session: dict, message: str) -> str:
    if not session.get("lang"):
        session["lang"] = detect_language(message)
    return session["lang"]


def is_booking_message(text: str) -> bool:
    return bool(re.search(
        r"\b(book|booking|reserve|reservation|table|dine in|dining|seat)\b",
        text,
        flags=re.I,
    ))

RESPONSES = {
    "greeting": {
        "en": "Hi! 👋 I'm DineBot.\n\n💬 Type **'view restaurants'** to start ordering!",
        "hi": "Namaste! 👋 Main DineBot hoon.\n\n💬 **'view restaurants'** type karo aur order shuru karo!"
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
        )
    },
    "thanks": {
        "en": "You're welcome 😊 Need anything else?",
        "hi": "Aapka swagat hai 😊 Aur kuch chahiye?"
    },
    "no_restaurant": {
        "en": "⚠️ Please select a restaurant first.\n\n💬 Type **'view restaurants'**",
        "hi": "⚠️ Pehle restaurant select karo.\n\n💬 **'view restaurants'** type karo"
    },
    "empty_cart": {
        "en": "🛒 Your cart is empty!\n\n💬 Type **'menu'** to see items.",
        "hi": "🛒 Cart khali hai!\n\n💬 **'menu'** type karo."
    },
    "item_not_found": {
        "en": "🤔 Item not found.\n\n💡 Type **'menu'** to see available items.",
        "hi": "🤔 Item nahi mila.\n\n💡 **'menu'** type karo."
    },
    "login_required_order": {
        "en": "🔐 Please login to continue.\n\nSteps:\n1) Tap **Login** or **Sign Up** in the top navbar\n2) Complete login\n3) Come back and try again",
        "hi": "🔐 Continue karne ke liye login karo.\n\nSteps:\n1) Top navbar me **Login** ya **Sign Up** tap karo\n2) Login complete karo\n3) Wapas aake try karo"
    },
    "login_required_booking": {
        "en": "🔐 Please login to continue.\n\nSteps:\n1) Tap **Login** or **Sign Up** in the top navbar\n2) Complete login\n3) Start booking again",
        "hi": "🔐 Continue karne ke liye login karo.\n\nSteps:\n1) Top navbar me **Login** ya **Sign Up** tap karo\n2) Login complete karo\n3) Booking phir se start karo"
    },
    "login_required_cancel": {
        "en": "🔐 Please login to continue.\n\nSteps:\n1) Tap **Login** or **Sign Up** in the top navbar\n2) Complete login\n3) Then cancel your order",
        "hi": "🔐 Continue karne ke liye login karo.\n\nSteps:\n1) Top navbar me **Login** ya **Sign Up** tap karo\n2) Login complete karo\n3) Uske baad order cancel karo"
    },
    "switch_warning": {
        "en": "⚠️ You have items in your cart. Switching restaurants will clear your cart.\n\nReply **'yes'** to continue or **'no'** to stay.",
        "hi": "⚠️ Cart mein items hain. Restaurant switch karne par cart clear ho jayega.\n\nContinue ke liye **'yes'** ya **'no'** bolo."
    },
    "switch_cancelled": {
        "en": "✅ Keeping your current restaurant.\n\nType **'menu'** to continue ordering.",
        "hi": "✅ Current restaurant hi rahega.\n\nAage badhne ke liye **'menu'** type karo."
    },
    "payment_info": {
        "en": "💳 Payments happen on the website.\n\nSteps:\n1) Open **Cart / Checkout**\n2) Select address\n3) Choose a payment option (UPI/Card/Pay on Delivery)",
        "hi": "💳 Payment website par hota hai.\n\nSteps:\n1) **Cart / Checkout** open karo\n2) Address select karo\n3) Payment option choose karo (UPI/Card/Pay on Delivery)"
    },
    "no_order": {
        "en": "No recent order found. 🤷\n\nTry: **'track 123'**",
        "hi": "Koi recent order nahi mila. 🤷\n\nTry: **'track 123'**"
    },
    "help": {
        "en": (
            "❓ **Help & FAQs**\n\n"
            "🍽️ **Order food**\n"
            "  1) Home → choose restaurant\n"
            "  2) Open menu and tap **+**\n"
            "  3) Cart → Checkout\n"
            "🪑 **Book table**\n"
            "  1) Open a restaurant\n"
            "  2) Tap **Reserve / Seat / Preorder**\n"
            "  3) Pick date/slot/guests and book\n"
            "📦 **Track order**\n"
            "  1) Profile icon → Orders\n"
            "  2) Open order or tap Track on success page\n"
            "❌ **Cancel order**\n"
            "  1) Profile icon → Orders\n"
            "  2) Open order → Cancel\n"
            "🏪 **Restaurants**\n"
            "  1) Go Home to browse\n\n"
            "For complaints, open Help/FAQs from the navbar."
        ),
        "hi": (
            "❓ **Help & FAQs**\n\n"
            "🍽️ **Order**\n"
            "  1) Home → restaurant select\n"
            "  2) Menu me **+** tap karo\n"
            "  3) Cart → Checkout\n"
            "🪑 **Table book**\n"
            "  1) Restaurant open karo\n"
            "  2) **Reserve / Seat / Preorder** tap karo\n"
            "  3) Date/slot/guests bhar do\n"
            "📦 **Track**\n"
            "  1) Profile icon → Orders\n"
            "  2) Order open karke track karo\n"
            "❌ **Cancel**\n"
            "  1) Profile icon → Orders\n"
            "  2) Order open karke cancel karo\n"
            "🏪 **Restaurants**\n"
            "  1) Home khol ke browse karo\n\n"
            "Complaint ke liye navbar se Help/FAQs kholo."
        )
    },
    "account_help": {
        "en": (
            "🔐 **Account Help**\n\n"
            "• Login: top navbar → **Login**\n"
            "• Forgot password: Login page → **Forgot Password** (below password field)\n"
            "• Reset: check email → open reset page → set new password\n"
            "• Edit profile: **Profile → Edit Profile** (change email/phone)\n"
            "• Account issues: open **Help/FAQs** from navbar"
        ),
        "hi": (
            "🔐 **Account Help**\n\n"
            "• Login: top navbar → **Login**\n"
            "• Forgot password: Login page → **Forgot Password** (password ke niche)\n"
            "• Reset: email link se naya password set karo\n"
            "• Profile update: **Profile → Edit Profile** (email/phone)\n"
            "• Account problem: navbar se **Help/FAQs** kholo"
        )
    },
    "booking_mode_prompt": {
        "en": (
            "🪑 Choose booking type:\n\n"
            "1) **Dine-out only**\n"
            "2) **Table + pre-order food**\n\n"
            "Reply with **1** or **2**."
        ),
        "hi": (
            "🪑 Booking type choose karo:\n\n"
            "1) **Sirf table (dine-out)**\n"
            "2) **Table + pre-order food**\n\n"
            "**1** ya **2** reply karo."
        )
    },
    "booking_interrupt_prompt": {
        "en": (
            "You're currently booking a table.\n\n"
            "Do you want to continue booking or switch to food ordering?\n"
            "Reply **'continue'** or **'switch'**."
        ),
        "hi": (
            "Aap abhi table booking kar rahe ho.\n\n"
            "Booking continue karni hai ya food ordering pe switch karna hai?\n"
            "**'continue'** ya **'switch'** reply karo."
        )
    }
}

def get_response(key: str, lang: str) -> str:
    return RESPONSES.get(key, {}).get(lang, RESPONSES.get(key, {}).get('en', ''))

def booking_ask(field: str, lang: str) -> str:
    msgs = {
        "people": {
            "en": "👥 How many people will be joining?\n\n📝 Example: **'4 people'** or just **'4'**",
            "hi": "👥 Kitne logon ke liye table chahiye?\n\n📝 Example: **'4 log'** ya sirf **'4'**"
        },
        "date": {
            "en": "📅 Which date?\n\n📝 Example: **'today'** or **'tomorrow'**",
            "hi": "📅 Kaunsi date?\n\n📝 Udaharan: **'aaj'** ya **'kal'**"
        },
        "time": {
            "en": "🕒 Which time?\n\n📝 Example: **7pm** or **19:30**",
            "hi": "🕒 Kaunsa time?\n\n📝 Udaharan: **7pm** ya **19:30**"
        }
    }
    return msgs.get(field, {}).get(lang, msgs.get(field, {}).get('en', ''))

def is_yes(text: str) -> bool:
    return bool(re.search(r"\b(yes|y|yeah|yep|ok|okay|sure|confirm|haan|han|ha)\b", text, flags=re.I))

def is_no(text: str) -> bool:
    return bool(re.search(r"\b(no|n|nope|nah|cancel|stop|nahin|nahi)\b", text, flags=re.I))

def parse_booking_mode(text: str) -> str | None:
    t = text.lower().strip()
    if re.search(r"\b(1|one|dine[-\s]?out|dine in only|only table|just table|sirf table|sirf booking|only booking)\b", t):
        return "dine_out"
    if re.search(r"\b(2|two|pre[-\s]?order|preorder|table\s*\+\s*food|with\s+food|food\s+preorder|khana|khaana|menu)\b", t):
        return "preorder"
    return None

def is_unrelated_to_booking(text: str) -> bool:
    return bool(re.search(
        r"\b(menu|order|cart|checkout|confirm order|track|cancel order|payment|offers|deal|coupon)\b",
        text, flags=re.I
    ))

def detect_booking_interrupt_target(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(track|status)\b", t):
        return "track"
    if re.search(r"\b(cancel order|cancel)\b", t):
        return "cancel"
    if re.search(r"\b(payment|checkout|pay|cart)\b", t):
        return "payment"
    if re.search(r"\b(menu|order|food|items|add)\b", t):
        return "order"
    if re.search(r"\b(help|support|account)\b", t):
        return "help"
    return "order"

def next_booking_prompt(booking_state: dict, lang: str) -> str:
    if not booking_state.get("booking_mode"):
        return get_response("booking_mode_prompt", lang)
    if not booking_state.get("people"):
        return booking_ask("people", lang)
    if not booking_state.get("date"):
        return booking_ask("date", lang)
    if not booking_state.get("time"):
        return booking_ask("time", lang)
    return booking_ask("people", lang)

def has_date_hint(text: str) -> bool:
    return bool(re.search(
        r"\b(today|tomorrow|tmrw|tmr|aaj|kal|yesterday|parso|next week|next month|"
        r"\d{1,2}[/-]\d{1,2}|\d{4}-\d{2}-\d{2}|january|february|march|april|may|"
        r"june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b",
        text, flags=re.I
    ))

def is_allowed_booking_date(date_str: str) -> bool:
    try:
        booking_date = date.fromisoformat(date_str)
    except Exception:
        return False
    if is_past_date(date_str):
        return False
    today = date.today()
    tomorrow = today + timedelta(days=1)
    return booking_date in (today, tomorrow)

def is_past_date(date_str: str) -> bool:
    try:
        booking_date = date.fromisoformat(date_str)
    except Exception:
        return False
    return booking_date < date.today()

def is_allowed_booking_time(time_str: str) -> bool:
    # Deprecated: use is_time_allowed_for_date(date_str, time_str)
    return is_time_allowed_for_date(None, time_str)


def has_time_hint(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(
        r"\b(noon|midday|midnight|\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|\d{1,2}(?:am|pm)|\d{1,2}\s*baje)\b",
        text,
        flags=re.I,
    ))


def parse_time_string(tstr: str):
    """Parse human time strings like '7pm', '7:30 pm', '19:00', '7 baje' -> (hour, minute) in 24h.
    Returns (hour, minute) or None on failure.
    """
    if not tstr or not isinstance(tstr, str):
        return None
    s = tstr.lower().strip()
    s = re.sub(r"\bbaje\b", "", s)
    s = s.replace('.', '')
    s = re.sub(r"\s+", " ", s)

    if re.fullmatch(r"\d{1,2}", s):
        hh = int(s)
        if 0 <= hh <= 23:
            return (hh, 0)

    time_patterns = [
        r"\bnoon\b",
        r"\bmidday\b",
        r"\bmidnight\b",
        r"\b\d{1,2}:\d{2}\b",
        r"\b\d{1,2}\s*(?:am|pm)\b",
        r"\b\d{1,2}(?:am|pm)\b",
    ]

    token = None
    for pattern in time_patterns:
        m = re.search(pattern, s, flags=re.I)
        if m:
            token = m.group(0).strip()
            break

    if not token:
        return None

    lowered = token.lower()
    if lowered in {"noon", "midday"}:
        return (12, 0)
    if lowered == "midnight":
        return (0, 0)

    token = token.replace(" ", "")
    m = re.match(r"^(\d{1,2}):(\d{2})$", token)
    if m:
        hh = int(m.group(1)); mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return (hh, mm)

    m = re.match(r"^(\d{1,2})(am|pm)$", token)
    if m:
        hh = int(m.group(1)); mm = 0; ap = m.group(2)
        if hh == 12:
            hh = 0
        if ap == 'pm':
            hh += 12
        if 0 <= hh <= 23:
            return (hh, mm)
    return None


def is_time_allowed_for_date(date_str: str | None, time_str: str) -> bool:
    """Check allowed windows and ensure 'today' times are in the future when date_str is today.
    Allows 11:00-15:59 and 18:00-22:59.
    If date_str is None, only window checks applied.
    """
    parsed = parse_time_string(time_str)
    if not parsed: return False
    hh, mm = parsed
    # allowed windows
    in_window = (11 <= hh <= 15) or (18 <= hh <= 22)
    if not in_window: return False
    if date_str:
        try:
            bdate = date.fromisoformat(date_str)
        except Exception:
            return False
        if bdate == date.today():
            now = datetime.now()
            if hh < now.hour or (hh == now.hour and mm <= now.minute):
                return False
    return True

def support_intent_parser(text: str) -> str | None:
    t = text.lower().strip()
    if re.search(
        r"\b(reset password|forgot password|change password|password reset|password bhool|password bhul|"
        r"cant login|can't login|login nahi|login problem|login issue|account help|account problem|"
        r"change email|change phone|password yaad nahi|password help)\b",
        t,
    ):
        return "account_help"
    if re.search(r"\b(password|pasword|credentials)\b", t) and re.search(
        r"\b(reset|forgot|forget|change|update|help|kaise|how|bhool|bhul|problem|issue)\b",
        t,
    ):
        return "account_help"
    return None

BOOKING_EXEMPT_INTENTS = {
    "greeting", "goodbye", "thanks", "help", "account_help",
    "cancel_booking", "booking_interrupt", "navigation_help", "site_navigation"
}

def resolve_intent(message: str, session: dict, restaurants: list) -> str:
    booking_state = session.get("booking_state", {})
    if booking_state and booking_state.get("awaiting") != "restaurant":
        if re.search(r"\b(help|faq|support|complaint|issue)\b", message, flags=re.I):
            return "help"
        if re.search(r"\b(navigate|navigation|where is|how to go|link|url|page)\b", message, flags=re.I):
            return "navigation_help"
        support_intent = support_intent_parser(message)
        if support_intent:
            return support_intent
        if is_unrelated_to_booking(message):
            return "booking_interrupt"
        return "book_table"

    temp_items = session.get("temp_order", {}).get("items", [])
    if temp_items and re.search(r"\b(yes|ok|okay|confirm|checkout|place order|order place)\b", message, flags=re.I):
        return "confirm_order"

    support_intent = support_intent_parser(message)
    if support_intent:
        return support_intent

    multi_intent = detect_multi_intent(message, restaurants)
    if multi_intent:
        return multi_intent

    # Fast-path menu item phrases so cart additions do not fall into ML/Groq fallback.
    active_restaurant = session.get("active_restaurant")
    if active_restaurant:
        try:
            menu_list, price_map = get_restaurant_menu(active_restaurant)
        except Exception:
            menu_list, price_map = None, None
        if menu_list and extract_items_from_message(message, menu_list, price_map):
            return "order_item"

    return predict_intent(message, session)

def build_fallback_response(session: dict, lang: str) -> str:
    last_intent = session.get("last_intent")
    stack = session.get("context_stack", []) or []
    if not last_intent and stack:
        last_intent = stack[-1]
    if last_intent is None and stack:
        if "book_table" in stack:
            last_intent = "book_table"
        elif "menu" in stack:
            last_intent = "menu"
        elif "confirm_order" in stack:
            last_intent = "confirm_order"
    if last_intent == "menu":
        return ("Tell me what you want from the menu.\n\nExample: **'2 burgers and a coke'**"
                if lang == "en" else "Menu se kya chahiye?\n\nExample: **'2 burger aur 1 coke'**")
    if last_intent == "book_table":
        return ("If you still want a table, say the missing detail.\n\nExample: **'4 people'** or **'7pm tomorrow'**"
                if lang == "en" else "Agar table book karna hai to detail batao.\n\nExample: **'4 log'** ya **'kal 7 baje'**")
    if last_intent == "confirm_order":
        return ("Type **'confirm order'** to place your order, or add more items."
                if lang == "en" else "Order place karne ke liye **'confirm order'** bolo, ya aur items add karo.")
    return get_response("fallback", lang)

def format_restaurant_list(rows: list, lang: str) -> str:
    if not rows:
        return ("No restaurants available." if lang == "en" else "Koi restaurant available nahi hai.")
    if lang == "en":
        text = "🍽️ **Available Restaurants:**\n\n"
        for rx in rows:
            text += f"{rx['id']}. {rx['name']} ({rx.get('location', '')})\n"
        text += "\n💬 Type the restaurant number to select."
    else:
        text = "🍽️ **Restaurants ki list:**\n\n"
        for rx in rows:
            text += f"{rx['id']}. {rx['name']} ({rx.get('location', '')})\n"
        text += "\n💬 Restaurant ka number type karo select karne ke liye."
    return text

def format_cart_summary(temp_items: list) -> str:
    return "\n".join(
        f"• {i['qty']}x {i['name'].title()} - ₹{i['price'] * i['qty']}"
        for i in temp_items
    )

# ── Order Manager ──────────────────────────────────────────────────────────────
om = None
if OrderManager is not None:
    try:
        om = OrderManager(DB_CONFIG)
        print("OrderManager initialized with MySQL")
    except Exception as e:
        print(f"Warning: Failed to initialize MySQL OrderManager: {e}")

class _InMemoryOrderManager:
    def __init__(self):
        self.orders = {}
        self.reservations = {}
        self.reservation_preorders = []
        self.order_counter = 1000
        self.reservation_counter = 1000
        self.restaurants = [{"id": 1, "name": "Demo Restaurant", "location": "Demo", "image_url": ""}]
        self.menus = {1: [{"item_name": "pizza", "price": 250.0}, {"item_name": "burger", "price": 120.0}]}

    def get_restaurants(self): return self.restaurants
    def get_menu(self, rid): return self.menus.get(rid, [])

    def add_order(self, user_id, restaurant_id, items, total_price, address_id=None):
        oid = self.order_counter; self.order_counter += 1
        self.orders[oid] = {"id": oid, "user_id": user_id, "restaurant_id": restaurant_id,
                            "items": items, "total_price": total_price, "status": "pending",
                            "created_at": datetime.now(UTC).isoformat()}
        return oid

    def add_cart_items(self, user_id, restaurant_id, items): return len(items or [])

    def confirm_order(self, order_id):
        if order_id in self.orders: self.orders[order_id]["status"] = "accepted"; return True
        return False

    def track_order(self, order_id): return self.orders.get(order_id)

    def cancel_order(self, order_id, reason=None):
        if order_id in self.orders: self.orders[order_id]["status"] = "cancelled"; return True
        return False

    def book_table(self, user_id, restaurant_id, customer_name, customer_phone,
                   booking_date, time_slot, guests):
        rid = self.reservation_counter; self.reservation_counter += 1
        self.reservations[rid] = {"id": rid, "restaurant_id": restaurant_id,
                       "customer_name": customer_name, "customer_phone": customer_phone,
                       "date": booking_date, "time_slot": time_slot, "guests": guests,
                       "status": "pending", "created_at": datetime.now(UTC).isoformat()}
        return rid

    def add_reservation_preorders(self, reservation_id, items):
        for item in (items or []):
            self.reservation_preorders.append({
                "reservation_id": reservation_id,
                "item_name": item.get("item_name") or item.get("name"),
                "quantity": item.get("quantity", item.get("qty", 1)),
                "price": item.get("price", 0)
            })
        return len(items or [])

if om is None:
    print("WARNING: Using in-memory OrderManager fallback")
    om = _InMemoryOrderManager()

# ── ML Model ───────────────────────────────────────────────────────────────────
ml_model = None
if ModelLoader is not None:
    try:
        model_path   = Path(os.path.dirname(__file__)) / "data" / "chatbot_model.pkl"
        intents_path = Path(os.path.dirname(__file__)) / "data" / "intents.json"
        ml_model = ModelLoader(model_path=model_path, intents_path=intents_path)
        print("ML Model loaded")
    except Exception as e:
        print(f"WARNING: ML model load failed: {e}")

def load_valid_intents():
    intents = set()
    intents_path = os.path.join(os.path.dirname(__file__), "data", "intents.json")
    try:
        with open(intents_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        for item in payload.get("intents", []):
            tag = str(item.get("tag", "")).strip().lower()
            if tag: intents.add(tag)
    except Exception as e:
        print(f"WARNING: Unable to load intents.json: {e}")
    defaults = {
        "greeting", "about_bot", "view_restaurants", "menu", "order_item",
        "show_cart", "update_quantity", "confirm_order", "track_order",
        "cancel_order", "book_table", "cancel_booking", "restaurant_compare",
        "restaurant_query", "payment", "navigation_help", "restaurant_register",
        "restaurant_login", "delivery_partner", "recommendations", "repeat_order",
        "scheduled_order", "offers_deals", "personal_info", "veg_nonveg",
        "opening_hours", "delivery_area", "current_restaurant", "change_restaurant",
        "help", "fallback", "goodbye", "thanks", "remove_item", "select_restaurant",
        "new_order", "partner", "site_navigation", "compare_restaurants",
        "restaurant_item_query", "account_help", "recommend_restaurants"
    }
    intents.update(defaults)
    return intents

VALID_INTENTS = load_valid_intents()

def load_groq_system_prompt():
    try:
        with open(GROQ_SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"WARNING: Unable to read Groq system prompt: {e}")
        return "Classify the user message into a valid intent. Return only the intent name."

def normalize_intent_name(raw: str) -> str:
    if not raw: return ""
    head    = raw.strip().splitlines()[0].strip()
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "", head)
    return cleaned.lower()

def _looks_like_freeform_text(text: str) -> bool:
    words = re.findall(r"\w+", text.lower())
    if len(words) <= 8:
        return False
    return bool(re.search(r"\b(i|me|my|we|please|can you|could you|yaar|bhai|mujhe|koi|accha|quiet|family|dinner|suggest|recommend)\b", text, flags=re.I))

def _looks_ambiguous(text: str, session: dict = None) -> bool:
    if re.search(r"\b(yaar|bhai|please|maybe|something|somewhere|koi|accha|better|best|quiet|family|date night|hangout)\b", text, flags=re.I):
        return True
    if text.count("?") > 0:
        return True
    if session and session.get("context_stack"):
        stack = session.get("context_stack", [])
        if len(stack) >= 2 and stack[-1] != stack[-2]:
            return True
    return False

def _groq_result_with_timeout(text: str, session: dict, timeout_seconds: float = 2.5):
    if not USE_GROQ or not GROQ_API_KEY or Groq is None:
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

def groq_classify_intent(text: str, session: dict = None):
    if not USE_GROQ or not GROQ_API_KEY or Groq is None:
        return None
    try:
        client        = Groq(api_key=GROQ_API_KEY)
        system_prompt = load_groq_system_prompt()
        intents_list  = ", ".join(sorted(VALID_INTENTS))
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt + "\n\nValid intents: " + intents_list},
                {"role": "user", "content": text}
            ],
            temperature=0, max_tokens=20
        )
        content   = response.choices[0].message.content if response.choices else ""
        candidate = normalize_intent_name(content)
        if candidate in VALID_INTENTS: return candidate
    except Exception as e:
        print(f"Groq intent error: {e}")
    return None

# ── Fallback Session Manager ───────────────────────────────────────────────────
if get_session is None:
    _sessions = {}

    def _default_session():
        return {
            "user_id": None, "is_logged_in": False, "user_name": None,
            "last_intent": None, "temp_order": {"items": []},
            "last_bot_msg": None, "active_restaurant": None,
            "last_order_id": None, "last_booking_id": None,
            "pending_cancel_order_id": None,
            "booking_state": {}, "context_stack": [],
            "lang": None, "pending_switch": None, "pending_booking_switch": None,
            "restaurant_list_shown": False,
            "mentioned_restaurant_id": None, "mentioned_restaurant_name": None,
            "restaurant_names": [],
            "created_at": datetime.now(UTC).isoformat(),
            # Action tracking for duplicate-suppression and pronoun resolution
            "recent_actions": [],  # list of (signature, iso_ts)
            "last_added_item": None,
            "last_action_time": None,
        }

    def get_session(uid):
        if uid not in _sessions:
            _sessions[uid] = _default_session()
        else:
            s = _sessions[uid]
            if not isinstance(s.get("temp_order"), dict): s["temp_order"] = {"items": []}
            if "items" not in s["temp_order"]: s["temp_order"]["items"] = []
            for k, v in _default_session().items():
                if k not in s: s[k] = v
        return _sessions[uid]

    def set_session(uid, data):
        _sessions[uid] = data; return data

    def clear_temp_order(uid):
        s = get_session(uid)
        s["temp_order"] = {"items": []}; s["last_intent"] = None
        return s

    def clear_booking_state(uid):
        s = get_session(uid); s["booking_state"] = {}; return s

    def push_intent(uid, intent):
        s = get_session(uid)
        stack = s.get("context_stack", [])
        stack.append(intent)
        if len(stack) > 3: stack = stack[-3:]
        s["context_stack"] = stack; s["last_intent"] = intent

    def reset_session(uid):
        _sessions[uid] = _default_session(); return _sessions[uid]

# ── Helpers ────────────────────────────────────────────────────────────────────
def is_logged_in_user(user_id, session: dict) -> bool:
    if not isinstance(session, dict):
        return False
    if session.get("is_logged_in") is True:
        return True
    uid = str(user_id or "").lower().strip()
    if not uid or uid in ("anonymous", "guest"):
        return False
    if uid.startswith("guest_"):
        return False
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
    items = []
    message_lower = message.lower()
    qty_words   = '|'.join(WORD_TO_NUMBER.keys())
    qty_pattern = rf'\b(\d+|{qty_words})\s+(?:x\s+)?(\w+(?:\s+\w+){{0,2}})'
    for match in re.finditer(qty_pattern, message_lower):
        matched, confidence = fuzzy_match_item(match.group(2).strip(), menu_list)
        if matched and confidence >= 0.6:
            items.append({"name": matched, "qty": normalize_quantity(match.group(1)),
                          "price": price_map.get(matched, 0)})
    if not items:
        for item_name in menu_list:
            if re.search(r'\b' + re.escape(item_name) + r'\b', message_lower):
                items.append({"name": item_name, "qty": 1, "price": price_map[item_name]})
    if not items:
        for word in message_lower.split():
            if len(word) > 2:
                matched, confidence = fuzzy_match_item(word, menu_list)
                if matched and confidence >= 0.7:
                    items.append({"name": matched, "qty": 1, "price": price_map[matched]}); break
    return items

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
    return [{"item_name": i["name"].title(), "price": i["price"], "quantity": i["qty"]}
            for i in temp_items]

def safe_numeric_user_id(user_id):
    if not user_id or user_id in ("anonymous", ""): return 1
    try: return int(user_id)
    except (ValueError, TypeError): return 1

def prepare_restaurants_for_json(rows):
    return [{"id": r.get("id"), "name": r.get("name", ""),
             "location": r.get("location", ""), "image_url": r.get("image_url") or ""}
            for r in (rows or [])]

# ---------- Duplicate-suppression & recent-action helpers ----------
def _purge_old_actions(session: dict, window_seconds: float = 2.0):
    now = datetime.now(UTC)
    recent = session.get("recent_actions", []) or []
    kept = []
    for sig, t in recent:
        try:
            ts = datetime.fromisoformat(t)
        except Exception:
            continue
        if (now - ts).total_seconds() <= window_seconds:
            kept.append((sig, t))
    session["recent_actions"] = kept

def _is_recent_duplicate(session: dict, signature: str, window_seconds: float = 2.0) -> bool:
    _purge_old_actions(session, window_seconds)
    recent = session.get("recent_actions", []) or []
    for sig, t in recent:
        if sig == signature:
            return True
    return False

def _record_action(session: dict, signature: str):
    now_iso = datetime.now(UTC).isoformat()
    recent = session.get("recent_actions", []) or []
    recent.append((signature, now_iso))
    # keep short history
    session["recent_actions"] = recent[-10:]
    session["last_action_time"] = now_iso

def match_restaurant_in_message(message: str, restaurants: list):
    t = message.lower(); best = None
    for rx in (restaurants or []):
        name = str(rx.get("name", "")).strip()
        if not name: continue
        name_lower = name.lower()
        if name_lower in t:
            if not best or len(name) > len(best.get("name", "")): best = rx
            continue
        tokens = [tok for tok in re.split(r"\W+", name_lower) if tok]
        ignore = {"the", "restaurant", "cafe", "hotel", "dhaba", "bar"}
        tokens = [tok for tok in tokens if tok not in ignore]
        if tokens and all(tok in t for tok in tokens):
            if not best or len(name) > len(best.get("name", "")): best = rx
    return best

def detect_multi_intent(message: str, restaurants: list) -> str:
    t = message.lower()
    has_restaurant = match_restaurant_in_message(message, restaurants) is not None
    has_time       = bool(re.search(r'\b(\d{1,2})(:|\s)?(\d{2})?\s*(am|pm|baje)\b', t))
    has_date       = bool(re.search(r'\b(kal|aaj|tomorrow|today|tonight|parso)\b', t))
    has_food_ctx   = bool(re.search(r'\b(khana|eat|khane|dining|visit|aana|pahunchu|phuchu)\b', t))
    # FIX 4: Explicit booking keyword always wins
    has_booking_kw = bool(re.search(
        r'\b(booking|reserve|book table|table book|reservation|dine in|dining)\b', t))
    if has_booking_kw and (has_restaurant or has_time or has_date): return "book_table"
    if has_restaurant and (has_time or has_date) and has_food_ctx: return "book_table"
    return None

def find_menu_item_in_message(message: str, menu_list: list):
    t = message.lower()
    for item in (menu_list or []):
        if re.search(r'\b' + re.escape(item.lower()) + r'\b', t): return item
    for token in re.split(r"\W+", t):
        matched, conf = fuzzy_match_item(token, menu_list, cutoff=0.7)
        if matched and conf >= 0.7: return matched
    return None

def extract_preorder_items(message: str, restaurant_id: int):
    menu_list, price_map = get_restaurant_menu(restaurant_id)
    if not menu_list: return []
    items = extract_items_from_message(message, menu_list, price_map)
    if not items:
        items = extract_items_from_message(message, menu_list, price_map)
    return items

def extract_booking(message: str):
    text = (message or "").lower().strip()
    result = {"people": None, "date": None, "time": None}

    people = extract_people_count(text)
    if people:
        result["people"] = people

    if re.search(r"\b(today|aaj)\b", text):
        result["date"] = date.today().isoformat()
    elif re.search(r"\b(tomorrow|tmr|tmrw|kal)\b", text):
        result["date"] = (date.today() + timedelta(days=1)).isoformat()

    parsed_time = parse_time_string(text)
    if parsed_time:
        result["time"] = f"{parsed_time[0]:02d}:{parsed_time[1]:02d}"

    return result
# ── FIX 2: Extract plain number as people count ───────────────────────────────
def extract_plain_number_as_people(message: str):
    """If message is just a bare number 1-20, treat as people count."""
    m = re.match(r'^\s*(\d{1,2})\s*$', message.strip())
    if m:
        val = int(m.group(1))
        if 1 <= val <= 20: return val
    for word, val in WORD_TO_NUMBER.items():
        if message.strip().lower() == word and 1 <= val <= 20: return val
    return None


def extract_people_count(message: str):
    text = (message or "").lower().strip()
    bare_number = extract_plain_number_as_people(text)
    if bare_number:
        return bare_number

    m = re.search(r"\b(\d{1,2})\s*(people|person|guests?|log|aadmi|members?)\b", text)
    if m:
        try:
            value = int(m.group(1))
            if 1 <= value <= 20:
                return value
        except Exception:
            pass

    for word, val in WORD_TO_NUMBER.items():
        if re.search(rf"\b{re.escape(word)}\s*(people|person|guests?|log|aadmi|members?)\b", text):
            if 1 <= val <= 20:
                return val
    return None

# ── Intent Detection ───────────────────────────────────────────────────────────
def predict_intent(text: str, session: dict = None) -> str:
    restaurant_names = (session or {}).get("restaurant_names", [])
    cleaned_text = (text or "").strip()

    # Regex first: prevents ML from overriding common user phrases
    regex_intent = simple_intent_parser(cleaned_text, restaurant_names)
    if regex_intent != "fallback":
        print(f"[INTENT] regex -> {regex_intent}")
        return regex_intent

    ml_intent = None
    ml_confidence = 0.0
    if ml_model:
        try:
            results = ml_model.predict([cleaned_text])
            intent, confidence = results[0]
            intent = str(intent).lower().strip()
            ml_confidence = float(confidence or 0.0)
            if confidence > 0.55 and intent in VALID_INTENTS and intent != "fallback":
                print(f"[INTENT] ml -> {intent} ({confidence:.2f})")
                return intent
            if confidence > 0.35 and intent in VALID_INTENTS and intent != "fallback":
                ml_intent = intent
        except Exception as e:
            print(f"ML error: {e}")

    use_groq = False
    if regex_intent == "fallback":
        if ml_intent is None or ml_confidence < 0.35:
            use_groq = True
        if _looks_like_freeform_text(cleaned_text):
            use_groq = True
        if _looks_ambiguous(cleaned_text, session):
            use_groq = True

    if use_groq:
        groq_intent = _groq_result_with_timeout(cleaned_text, session)
        if groq_intent and groq_intent != "fallback":
            print(f"[INTENT] groq -> {groq_intent}")
            return groq_intent

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
    # FIX 3: Expanded thanks including dhanyawad, shukriya
    if re.search(r'\b(thanks|thank you|thx|shukriya|dhanyavaad|dhanyawad|dhanyabad|ty|thankyou|great|awesome|perfect|bahut accha)\b', t):
        return "thanks"
    if re.search(r'\b(help|faq|faqs|support|complaint|query|queries|contact|issue|problem|assist)\b', t):
        return "help"
    if re.search(
        r"\b(reset password|forgot password|change password|password reset|password bhool|password bhul|"
        r"cant login|can't login|login nahi|login problem|login issue|account help|account problem|"
        r"change email|change phone|password yaad nahi|password help)\b",
        t,
    ):
        return "account_help"
    if re.search(r"\b(password|pasword|credentials)\b", t) and re.search(
        r"\b(reset|forgot|forget|change|update|help|kaise|how|bhool|bhul|problem|issue)\b",
        t,
    ):
        return "account_help"
    # FIX 6: Support queries BEFORE food parser
    if re.search(r'\b(partner|add\s+my\s+restaurant|how\s+to\s+add\s+my\s+restaurant|add.{0,10}restaurant|restaurant.{0,10}add|register.{0,10}restaurant|apna restaurant|list restaurant|restaurant join|dineous partner|how to join|join as restaurant|restaurant register|register my restaurant|list my restaurant)\b', t):
        return "partner"
    if re.search(r'\b(who are you|about you|what is dinebot|dinebot|bot info)\b', t): return "about_bot"
    if re.search(r'\b(offer|offers|deal|deals|discount|coupon|promo|promo code)\b', t): return "offers_deals"
    if re.search(r'\b(payment|pay|checkout|online pay|upi|card)\b', t): return "payment"
    if re.search(r'\b(navigate|navigation|where is|how to go|link|url|page)\b', t): return "navigation_help"
    if re.search(r'\b(kaise login|login kaise|signup kaise|profile kahan|order history|kaise use kare|website mein kya|kahan jaaun|how to use|how to login|how to signup|how to register)\b', t):
        return "site_navigation"
    if re.search(r'\b(register restaurant|restaurant registration|list my restaurant|partner signup)\b', t): return "restaurant_register"
    if re.search(r'\b(restaurant login|partner login|owner login)\b', t): return "restaurant_login"
    if re.search(r'\b(delivery partner|delivery signup|rider|courier)\b', t): return "delivery_partner"
    if re.search(
        r"\b(compare|best restaurant|popular restaurant|top restaurant|top rated restaurant|highest rated|"
        r"which restaurant is popular|which restaurant is best|which restaurant is good|konsa accha|"
        r"price kam|cheaper|affordable|better restaurant|which is good|konsa better|rating compare)\b",
        t,
    ):
        return "recommend_restaurants"
    if re.search(r'\b(restaurant info|about restaurant|details of restaurant|rating|reviews)\b', t): return "restaurant_query"
    if re.search(r'\b(recommend|suggest|best|top|popular|bestseller|famous)\b', t):
        if re.search(r'\b(restaurant|restaurants|resto|place|outlet)\b', t):
            return "recommend_restaurants"
        return "recommendations"
    if re.search(r'\b(same as last|same order|wahi order|phir se wahi|repeat order|last order again|dobara same|order again)\b', t): return "repeat_order"
    if re.search(r'\b(schedule|scheduled|later|preorder|pre-order)\b', t): return "scheduled_order"
    if re.search(r'\b(profile|my info|my details|address|phone|email)\b', t): return "personal_info"
    if re.search(r'\b(veg|vegetarian|non-veg|non veg|vegan)\b', t): return "veg_nonveg"
    if re.search(r'\b(opening hours|open time|closing|timings|hours)\b', t): return "opening_hours"
    if re.search(r'\b(delivery area|deliver to|service area|location)\b', t): return "delivery_area"
    if re.search(r'\b(which restaurant|konsa restaurant|current restaurant|selected restaurant|kaunsa select|which one selected|kahan book ki|which restaurant selected|abhi konsa)\b', t): return "current_restaurant"
    if re.search(r'\b(does|kya|milta hai|available hai|hai kya|have|mein milta)\b', t):
        for r in restaurant_names:
            r_lower = r.lower()
            if r_lower in t: return "restaurant_item_query"
            tokens = [tok for tok in re.split(r"\W+", r_lower) if tok and tok != "the"]
            if tokens and all(tok in t for tok in tokens): return "restaurant_item_query"
    if re.search(r'\b(confirm|place order|checkout|finalize|order karo|order kar do|place karo|haan order|yes order|order place)\b', t): return "confirm_order"
    # FIX 4: Cancel booking BEFORE cancel_order and book_table
    if re.search(r'\b(cancl|cancle|cancel|cancelled|cancellation).{0,25}(table|booking|reservation|seat)\b', t): return "cancel_booking"
    if re.search(r'\b(table|booking|reservation|seat).{0,25}(cancl|cancle|cancel|cancelled|cancellation)\b', t): return "cancel_booking"
    if re.search(r'\b(cancel|cancel order|cancel kar|order cancel|order mat|cancel karo)\b', t): return "cancel_order"
    if re.search(r'\b(book|reserve|table|seat|reservation|baithna|dine in|dining)\b', t): return "book_table"
    if re.search(r'\b(remove|delete|hata|nikal|mat chahiye)\b', t): return "remove_item"
    if re.search(r'\b(track|where is|order status|kahan hai|status batao|order kahan)\b', t): return "track_order"
    if re.search(r'\b(quiet|calm|family|romantic|date night|ambience|ambiance|nice place|good place|seating|crowd|crowded|peaceful)\b', t):
        return "fallback"
    if re.search(r'\b(menu|show menu|items|kya milta|food list|dikhao|kha sakte|khana)\b', t): return "menu"
    if re.search(r'\b(show cart|mera cart|cart dikhao|my cart|view cart|cart mein kya|cart dekha|what is in my cart|cart|basket|bag)\b', t): return "show_cart"
    if re.search(r'\b(change|switch|different|badlo|dusra)\s*(restaurant|place|jagah)?\b', t): return "change_restaurant"
    if re.search(r'\b(make it|change to|update|ek aur|one more|aur ek|quantity change|badha do|kam karo)\b', t): return "update_quantity"
    if re.search(r'\b(update|change|set|make)\b.*\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|ek|do|teen|char|paanch)\b', t): return "update_quantity"
    if re.search(r'\b(order food|can i order|want to order|i want to order|food order|khana order|khaana order|hungry|bhook|khaana chahiye)\b', t): return "view_restaurants"
    if re.search(r'^\s*\d+\s*$', t): return "order_item"
    qty_words = '|'.join(WORD_TO_NUMBER.keys())
    food_context = r'\b(food|menu|item|dish|meal|snack|starter|dessert|drink|beverage|pizza|burger|biryani|coke|tea|coffee|juice|fries|sandwich|pasta|rice|noodles|khana|khaana|breakfast|lunch|dinner)\b'
    action_context = r'\b(add|order|want|get me|i want|i need|give me|chahiye|de do|lena|mangwa|dena)\b'
    if re.search(r'^\s*\d+\s+\w+', t) and re.search(food_context, t): return "order_item"
    if re.search(rf'^\s*(?:{qty_words})\s+\w+', t) and re.search(food_context, t): return "order_item"
    if re.search(action_context, t) and re.search(food_context, t): return "order_item"
    if re.search(action_context, t) and re.search(r'\b\d+\b', t): return "order_item"
    if re.search(rf'\b({qty_words})\b', t) and re.search(food_context, t): return "order_item"
    if re.search(r'\b(hungry|bhook|khaana|khana chahiye|order karna)\b', t): return "view_restaurants"
    if re.match(r'^\s*(show|restaurant|restaurants|food|order|new|dikhao)\s*$', t): return "view_restaurants"
    return "fallback"

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return "DineBot backend running ✅"

@app.route("/chat", methods=["POST"])
def chat_handler():
    data    = request.get_json() or {}
    user_id = data.get("user_id", "anonymous")
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"reply": "Please type something! 😊"}), 200

    session = get_session(user_id)
    lang    = get_lang(session, message)
    rows    = []

    session["user_id"] = user_id
    if "is_logged_in" in data: session["is_logged_in"] = bool(data.get("is_logged_in"))
    if data.get("user_name"): session["user_name"] = data.get("user_name")

    # ── PENDING BOOKING INTERRUPT CONFIRMATION ───────────────────────────────
    if session.get("pending_booking_switch"):
        pending_target = session.get("pending_booking_switch")
        if re.search(r"\b(continue|booking|book|resume)\b", message, flags=re.I):
            session["pending_booking_switch"] = None
            bot_response = next_booking_prompt(session.get("booking_state", {}), lang)
            set_session(user_id, session)
            return jsonify({"reply": bot_response, "intent": "book_table",
                            "speak": False, "speech_text": None}), 200

        if re.search(r"\b(switch|change|order|menu|track|cancel|payment)\b", message, flags=re.I) or is_yes(message):
            session["booking_state"] = {}
            session["pending_booking_switch"] = None
            set_session(user_id, session)
            if pending_target == "track":
                return jsonify({
                    "reply": ("Sure. Please share your order ID.\n\nExample: **'track 1023'**"
                              if lang == "en" else "Theek hai. Order ID batao.\n\nExample: **'track 1023'**"),
                    "intent": "track_order", "speak": False, "speech_text": None
                }), 200
            if pending_target == "cancel":
                return jsonify({
                    "reply": ("Okay. Which order should I cancel?\n\nExample: **'cancel 1023'**"
                              if lang == "en" else "Theek hai. Kaunsa order cancel karna hai?\n\nExample: **'cancel 1023'**"),
                    "intent": "cancel_order", "speak": False, "speech_text": None
                }), 200
            if pending_target == "payment":
                return jsonify({
                    "reply": get_response("payment_info", lang),
                    "intent": "payment", "speak": False, "speech_text": None
                }), 200
            if pending_target == "help":
                return jsonify({
                    "reply": get_response("help", lang),
                    "intent": "help", "speak": False, "speech_text": None
                }), 200
            return jsonify({
                "reply": ("Switched to ordering.\n\nType **'view restaurants'** or **'menu'** to start."
                          if lang == "en" else "Ordering mode on.\n\n**'view restaurants'** ya **'menu'** type karo."),
                "intent": "order_item", "speak": False, "speech_text": None
            }), 200

        if is_no(message):
            session["pending_booking_switch"] = None
            bot_response = next_booking_prompt(session.get("booking_state", {}), lang)
            set_session(user_id, session)
            return jsonify({"reply": bot_response, "intent": "book_table",
                            "speak": False, "speech_text": None}), 200

        set_session(user_id, session)
        return jsonify({"reply": get_response("booking_interrupt_prompt", lang), "intent": "book_table",
                        "speak": False, "speech_text": None}), 200

    # ── PENDING RESTAURANT SWITCH CONFIRMATION ─────────────────────────────────
    if session.get("pending_switch"):
        if is_yes(message):
            clear_temp_order(user_id)
            session["active_restaurant"] = None
            session["pending_switch"] = None
            session["restaurant_list_shown"] = True
            try: rows = om.get_restaurants() or []
            except Exception as e: rows = []; print(f"Error: {e}")
            set_session(user_id, session)
            return jsonify({"reply": format_restaurant_list(rows, lang), "intent": "view_restaurants",
                            "restaurants": prepare_restaurants_for_json(rows),
                            "speak": False, "speech_text": None}), 200
        if is_no(message):
            session["pending_switch"] = None
            set_session(user_id, session)
            return jsonify({"reply": get_response("switch_cancelled", lang), "intent": "change_restaurant",
                            "speak": False, "speech_text": None}), 200
        set_session(user_id, session)
        return jsonify({"reply": ("Reply **'yes'** or **'no'**." if lang == "en" else "**'yes'** ya **'no'** bolo."),
                        "intent": "change_restaurant", "speak": False, "speech_text": None}), 200

    # ── FIX 5: PENDING ORDER CANCEL CONFIRMATION ───────────────────────────────
    if session.get("pending_cancel_order_id"):
        pending_cancel_id = session.get("pending_cancel_order_id")
        if is_yes(message):
            try:
                success = om.cancel_order(pending_cancel_id)
                if success:
                    if session.get("last_order_id") == pending_cancel_id: session["last_order_id"] = None
                    bot_response = (f"❌ Order #{pending_cancel_id} cancelled successfully."
                                    if lang == 'en' else f"❌ Order #{pending_cancel_id} cancel ho gaya.")
                else:
                    bot_response = (f"⚠️ Cannot cancel Order #{pending_cancel_id}. May already be delivered."
                                    if lang == 'en' else f"⚠️ Order #{pending_cancel_id} cancel nahi ho sakta.")
            except Exception as e:
                bot_response = f"❌ Error: {str(e)}"
            session["pending_cancel_order_id"] = None
            set_session(user_id, session)
            return jsonify({"reply": bot_response, "intent": "cancel_order",
                            "speak": False, "speech_text": None}), 200
        if is_no(message):
            session["pending_cancel_order_id"] = None
            set_session(user_id, session)
            return jsonify({"reply": ("Okay. Tell me the exact order ID to cancel."
                                      if lang == "en" else "Theek hai. Order ID batao jo cancel karna hai."),
                            "intent": "cancel_order", "speak": False, "speech_text": None}), 200
        set_session(user_id, session)
        return jsonify({"reply": ("Reply **'yes'** or **'no'**." if lang == "en" else "**'yes'** ya **'no'** bolo."),
                        "intent": "cancel_order", "speak": False, "speech_text": None}), 200

    # ── VIEW / CHANGE RESTAURANTS ──────────────────────────────────────────────
    if (re.search(r'\b(change|switch|different|badlo|dusra)\s*(restaurant|place)?\b', message.lower()) or
            re.search(r'\b(view restaurants?|show restaurants?|restaurants dikhao|restaurants batao)\b', message.lower()) or
            "view restaurant" in message.lower()):

        temp_items = session.get("temp_order", {}).get("items", [])
        if session.get("active_restaurant") and temp_items:
            session["pending_switch"] = "view_restaurants"
            set_session(user_id, session)
            return jsonify({"reply": get_response("switch_warning", lang), "intent": "change_restaurant",
                            "speak": False, "speech_text": None}), 200
        try: rows = om.get_restaurants() or []
        except Exception as e: rows = []; print(f"Error: {e}")
        session["active_restaurant"] = None; session["restaurant_list_shown"] = True
        set_session(user_id, session)
        return jsonify({"reply": format_restaurant_list(rows, lang), "intent": "view_restaurants",
                        "restaurants": prepare_restaurants_for_json(rows),
                        "speak": False, "speech_text": None}), 200

    # ── RESTAURANT NAME / NUMBER GUARD ────────────────────────────────────────
    try:
        all_rests        = om.get_restaurants() or []
        rest_names_lower = [rx["name"].lower() for rx in all_rests]
    except:
        rest_names_lower = []; all_rests = []

    session["restaurant_names"] = rest_names_lower
    matched_restaurant = match_restaurant_in_message(message, all_rests)
    if matched_restaurant:
        session["mentioned_restaurant_id"]   = matched_restaurant.get("id")
        session["mentioned_restaurant_name"] = matched_restaurant.get("name")
        if not session.get("active_restaurant") and not is_booking_message(message):
            session["active_restaurant"] = matched_restaurant.get("id")

    if message.lower() in rest_names_lower:
        bot_resp = ("✅ Restaurant already selected! Type **'menu'** to see items."
                    if session.get("active_restaurant") and lang == 'en' else
                    "✅ Restaurant pehle se select hai! **'menu'** type karo."
                    if session.get("active_restaurant") else
                    "Please select by number. Type **'view restaurants'** first."
                    if lang == 'en' else "Number se select karo. **'view restaurants'** type karo.")
        set_session(user_id, session)
        return jsonify({"reply": bot_resp, "intent": "select_restaurant",
                        "speak": False, "speech_text": None}), 200

    if (message.isdigit() and not session.get("active_restaurant")
            and session.get("restaurant_list_shown")
            and session.get("booking_state", {}).get("awaiting") != "restaurant"):
        rid = int(message)
        try:
            restaurants = om.get_restaurants() or []
            rx = next((x for x in restaurants if x['id'] == rid), None)
            if rx:
                session["active_restaurant"] = rx["id"]; session["restaurant_list_shown"] = False
                session["mentioned_restaurant_id"] = rx["id"]
                session["mentioned_restaurant_name"] = rx.get("name")
                set_session(user_id, session)
                return jsonify({
                    "reply": (f"✅ Selected **{rx['name']}**!\n\n💬 Type 'menu' to see items."
                              if lang == 'en' else f"✅ **{rx['name']}** select ho gaya!\n\n💬 'menu' type karo."),
                    "intent": "select_restaurant", "speak": False, "speech_text": None
                }), 200
            else:
                set_session(user_id, session)
                return jsonify({"reply": "❌ Invalid ID. Type 'view restaurants'.",
                                "intent": "select_restaurant", "speak": False, "speech_text": None}), 200
        except Exception as e:
            set_session(user_id, session)
            return jsonify({"reply": f"Error: {str(e)}", "intent": "select_restaurant",
                            "speak": False, "speech_text": None}), 200

    if (message.isdigit() and not session.get("active_restaurant")
            and not session.get("restaurant_list_shown")
            and session.get("booking_state", {}).get("awaiting") != "restaurant"):
        set_session(user_id, session)
        return jsonify({
            "reply": ("Choose a restaurant from the list first.\n\nType **'view restaurants'**."
                      if lang == "en" else "Pehle restaurant list se choose karo.\n\n**'view restaurants'** type karo."),
            "intent": "view_restaurants", "speak": False, "speech_text": None
        }), 200

    # ── INTENT DETECTION ──────────────────────────────────────────────────────
    intent = resolve_intent(message, session, all_rests)
    if intent == "compare_restaurants":
        intent = "recommend_restaurants"

    booking_active      = session.get("booking_state", {})
    booking_interrupted = False

    # Login wall
    requires_login = {"confirm_order", "book_table", "cancel_order", "cancel_booking",
                      "repeat_order", "scheduled_order"}
    if intent in requires_login and not is_logged_in_user(user_id, session):
        key = ("login_required_booking" if intent == "book_table"
               else "login_required_cancel" if intent in {"cancel_order", "cancel_booking"}
               else "login_required_order")
        bot_response = get_response(key, lang) + ("\n\nQuick actions: **Menu** | **Book Table** | **Help**")
        session["last_bot_msg"] = bot_response
        set_session(user_id, session)
        return jsonify({"reply": bot_response, "intent": intent,
                        "speak": False, "speech_text": None}), 200

    # FIX 1+3: Booking state override uses BOOKING_EXEMPT_INTENTS set
    booking_active = session.get("booking_state", {})
    if booking_active:
        missing = (not booking_active.get("booking_mode") or
                   not booking_active.get("people") or
                   not booking_active.get("date") or
                   not booking_active.get("time"))
        if missing and intent not in BOOKING_EXEMPT_INTENTS:
            intent = "book_table"

    push_intent(user_id, intent)
    bot_response      = None
    redirect_url      = None
    booking_completed = False
    order_confirmed   = False
    order_tracked     = False
    order_cancelled   = False
    restaurants_json  = None

    if intent == "view_restaurants":
        try:
            rows = om.get_restaurants() or []
        except Exception as e:
            rows = []
            print(f"Error: {e}")
        session["active_restaurant"] = None
        session["restaurant_list_shown"] = True
        set_session(user_id, session)
        bot_response = format_restaurant_list(rows, lang)
        restaurants_json = prepare_restaurants_for_json(rows)

    elif intent == "greeting":
        if is_logged_in_user(user_id, session) and session.get("user_name"):
            bot_response = (f"Hi {session['user_name']}! 👋\n\n💬 Type **'view restaurants'** to start ordering!"
                            if lang == "en" else
                            f"Namaste {session['user_name']}! 👋\n\n💬 **'view restaurants'** type karo!")
        else:
            bot_response = get_response("greeting", lang)

    elif intent == "goodbye":
        bot_response = get_response("goodbye", lang); clear_temp_order(user_id)

    elif intent == "thanks":
        bot_response = get_response("thanks", lang)

    elif intent == "help":
        bot_response = get_response("help", lang)

    elif intent == "account_help":
        bot_response = get_response("account_help", lang)

    elif intent == "booking_interrupt":
        session["pending_booking_switch"] = detect_booking_interrupt_target(message)
        bot_response = get_response("booking_interrupt_prompt", lang)
        set_session(user_id, session)
        return jsonify({"reply": bot_response, "intent": "book_table",
                        "speak": False, "speech_text": None}), 200

    elif intent == "about_bot":
        bot_response = ("🤖 I'm DineBot, your food ordering and table booking assistant.\n\nStart with **'view restaurants'** or **'menu'**."
                        if lang == "en" else
                        "🤖 Main DineBot hoon, aapka food ordering aur table booking assistant.\n\n**'view restaurants'** ya **'menu'** se shuru karo.")

    elif intent == "offers_deals":
        bot_response = ("🎁 Offers are shown on restaurant menus.\n\n1) Go to Home\n2) Open a restaurant\n3) Check Offers section"
                        if lang == "en" else
                        "🎁 Offers restaurant menus par dikhte hain.\n\n1) Home kholo\n2) Restaurant open karo\n3) Offers section dekho")

    elif intent == "payment":
        bot_response = get_response("payment_info", lang)

    elif intent == "navigation_help":
        bot_response = ("Navigate the site:\n• **Login/Sign Up** → top navbar\n• **Restaurants** → Home list\n• **Search** → Search bar in navbar\n• **Cart/Checkout** → cart icon\n• **Orders** → Profile menu"
                        if lang == "en" else
                        "Site navigate karo:\n• **Login/Sign Up** → top navbar\n• **Restaurants** → Home list\n• **Search** → navbar search\n• **Cart/Checkout** → cart icon\n• **Orders** → Profile menu")

    elif intent == "site_navigation":
        bot_response = {"en": (
            "🗺️ **DINEaus Website Guide**\n\n"
            "👤 **Account:** Top navbar → Login/Sign Up\n"
            "📝 **Profile/Orders:** Profile menu in navbar\n"
            "🍽️ **Order:** Home → Restaurant → Menu → Cart → Checkout\n"
            "🪑 **Table booking:** Restaurant page → **Reserve / Seat / Preorder**\n"
            "🔎 **Search:** Navbar search bar\n"
            "🤝 **Partner:** Home footer → **Partner with us** → **Add Restaurant / Partner** page\n"
            "❓ **Help:** Navbar Help/FAQs"
        ), "hi": (
            "🗺️ **DINEaus Website Guide**\n\n"
            "👤 **Account:** Top navbar → Login/Sign Up\n"
            "📝 **Profile/Orders:** Navbar profile menu\n"
            "🍽️ **Order:** Home → Restaurant → Menu → Cart → Checkout\n"
            "🪑 **Table booking:** Restaurant page → **Reserve / Seat / Preorder**\n"
            "🔎 **Search:** Navbar search bar\n"
            "🤝 **Partner:** Home footer → **Partner with us** → **Add Restaurant / Partner** page\n"
            "❓ **Help:** Navbar Help/FAQs"
        )}.get(lang, "")

    elif intent == "partner":
        bot_response = {"en": (
            "🤝 **Partner with DINEaus (Restaurant Owners)**\n\n"
            "**Open from:** Home footer → **Partner with us** → **Add Restaurant**\n\n"
            "**Step 1:** Open **/dineous-partner**\n"
            "**Step 2:** Go to **Restaurant Information** and fill details\n"
            "**Step 3:** Upload documents on **Documents** page (PAN, GSTIN, FSSAI, bank details)\n"
            "**Step 4:** Open **Menu Setup** → upload menu & cuisines\n\n"
            "**Owner Login:** Use **Restaurant Admin Login** page\n"
            "After login, you can:\n"
            "• **Orders** tab → accept/reject → preparing → ready → completed\n"
            "• **Bookings** tab → accept/reject → arrived → completed\n"
            "• **Menu** → update price, description, images, stock, veg/non-veg"
        ), "hi": (
            "🤝 **DINEaus Restaurant Partner Flow**\n\n"
            "**Open from:** Home footer → **Partner with us** → **Add Restaurant**\n\n"
            "**Step 1:** **/dineous-partner** page kholo\n"
            "**Step 2:** **Restaurant Information** me details bharo\n"
            "**Step 3:** **Documents** page par PAN, GSTIN, FSSAI, bank details upload karo\n"
            "**Step 4:** **Menu Setup** me menu & cuisines add karo\n\n"
            "**Owner Login:** **Restaurant Admin Login** page\n"
            "Login ke baad:\n"
            "• **Orders** tab → accept/reject → preparing → ready → completed\n"
            "• **Bookings** tab → accept/reject → arrived → completed\n"
            "• **Menu** → price/description/image/stock update"
        )}.get(lang, "")

    elif intent == "restaurant_register":
        bot_response = ("Go to Home footer → **Partner with us** → **Add Restaurant**.\n\nThen complete: **Restaurant Information** → **Documents** → **Menu Setup**."
                        if lang == "en" else
                        "Home footer → **Partner with us** → **Add Restaurant** par jao.\n\nPhir: **Restaurant Information** → **Documents** → **Menu Setup** complete karo.")

    elif intent == "restaurant_login":
        bot_response = ("Restaurant owners login from **Restaurant Admin Login** page.\n\nAfter login: Orders tab, Bookings tab, and Menu management are in the dashboard."
                        if lang == "en" else
                        "Restaurant owner login **Restaurant Admin Login** page se hota hai.\n\nLogin ke baad dashboard me Orders, Bookings aur Menu management milta hai.")

    elif intent == "delivery_partner":
        bot_response = ("Join as delivery partner:\n1) Home/footer → **Delivery Partner**\n2) Register\n3) Login after approval"
                        if lang == "en" else "Delivery partner:\n1) Home/footer → **Delivery Partner**\n2) Form bharo\n3) Approval ke baad login karo")

    elif intent in ("restaurant_compare", "restaurant_query"):
        bot_response = ("Restaurant details are on their pages.\n\nType **'view restaurants'** to browse."
                        if lang == "en" else "Restaurant details unke pages par milti hain.")

    elif intent == "recommend_restaurants":
        compare_like = bool(re.search(
            r"\b(compare|best restaurant|popular restaurant|top restaurant|top rated restaurant|highest rated|"
            r"which restaurant is popular|which restaurant is best|which restaurant is good|konsa accha|"
            r"price kam|cheaper|affordable|better restaurant|which is good|konsa better|rating compare)\b",
            message,
            flags=re.I,
        ))
        try: rows = om.get_restaurants() or []
        except: rows = []
        if not rows:
            bot_response = ("No restaurants available right now." if lang == "en" else "Abhi restaurants available nahi hain.")
        elif compare_like:
            comparisons = []
            for rx in rows:
                _, price_map = get_restaurant_menu(rx.get("id"))
                prices = list(price_map.values()) if price_map else []
                if prices:
                    comparisons.append({"name": rx.get("name"), "min": min(prices),
                                        "max": max(prices), "avg": sum(prices)/len(prices)})
            if not comparisons:
                bot_response = ("No menu data for comparison." if lang == "en" else "Comparison ke liye menu data nahi hai.")
            else:
                lines = [f"{i+1}. {r['name']} — Avg ₹{r['avg']:.0f} (₹{r['min']:.0f}–₹{r['max']:.0f})"
                         for i, r in enumerate(comparisons)]
                bot_response = ("📊 **Price Comparison:**\n\n" + "\n".join(lines) + "\n\nType restaurant number to select!"
                                if lang == "en" else
                                "📊 **Price Comparison:**\n\n" + "\n".join(lines) + "\n\nRestaurant number type karo!")
        else:
            bot_response = format_restaurant_list(rows, lang)
            restaurants_json = prepare_restaurants_for_json(rows)

    elif intent == "restaurant_item_query":
        target_id = session.get("mentioned_restaurant_id") or session.get("active_restaurant")
        if not target_id:
            bot_response = ("Which restaurant? Type **'view restaurants'** first." if lang == "en" else "Kaunsa restaurant?")
        else:
            menu_list, price_map = get_restaurant_menu(target_id)
            if not menu_list:
                bot_response = ("No menu found." if lang == "en" else "Menu nahi mila.")
            else:
                matched_item = find_menu_item_in_message(message, menu_list)
                if matched_item:
                    price = price_map.get(matched_item, 0)
                    bot_response = (f"✅ Yes, **{matched_item.title()}** is available — ₹{price}"
                                    if lang == "en" else f"✅ Haan, **{matched_item.title()}** available hai — ₹{price}")
                else:
                    suggestions = suggest_close_items(message, menu_list)
                    if suggestions:
                        sugg = ", ".join(s.title() for s in suggestions)
                        bot_response = (f"Not found. Did you mean: **{sugg}**?" if lang == "en" else f"Nahi mila. Kya yeh chahte the: **{sugg}**?")
                    else:
                        bot_response = ("That item isn't on the menu." if lang == "en" else "Wo item menu mein nahi hai.")

    elif intent == "recommendations":
        if re.search(r"\b(restaurant|restaurants|resto|place|outlet)\b", message, flags=re.I):
            try: rows = om.get_restaurants() or []
            except: rows = []
            if rows:
                bot_response = format_restaurant_list(rows, lang)
                restaurants_json = prepare_restaurants_for_json(rows)
            else:
                bot_response = ("No restaurants available." if lang == "en" else "Koi restaurant available nahi hai.")
        else:
            active = session.get("active_restaurant")
            if not active:
                bot_response = get_response("no_restaurant", lang)
            else:
                menu_list, _ = get_restaurant_menu(active)
                if not menu_list:
                    bot_response = ("No menu available." if lang == "en" else "Menu nahi hai.")
                else:
                    picks = menu_list[:3]
                    bot_response = (f"⭐ Popular picks: **{', '.join(p.title() for p in picks)}**\n\nTell me what to add!"
                                    if lang == "en" else f"⭐ Popular: **{', '.join(p.title() for p in picks)}**\n\nKya add karu?")

    elif intent == "repeat_order":
        if session.get("last_order_id"):
            bot_response = (f"Reorder from #**{session['last_order_id']}** on the website.\n\nGo to **Profile → Orders**."
                            if lang == "en" else f"Last order #**{session['last_order_id']}** se reorder karo.\n\n**Profile → Orders**.")
        else:
            bot_response = ("No previous order found.\n\nGo to **Profile → Orders**." if lang == "en" else "Koi order nahi mila.\n\n**Profile → Orders** dekho.")

    elif intent == "scheduled_order":
        bot_response = ("Schedule delivery at checkout.\n\nGo to **Cart → Checkout**." if lang == "en" else "Schedule delivery checkout par hoti hai.")

    elif intent == "personal_info":
        bot_response = ("Update your profile on the website.\n\nGo to **Profile**." if lang == "en" else "Profile website par update hota hai.")

    elif intent == "veg_nonveg":
        bot_response = ("Both veg & non-veg available!\n\nType **'menu'** after selecting a restaurant."
                        if lang == "en" else "Veg aur Non-veg dono available!\n\nRestaurant select karke **'menu'** type karo.")

    elif intent == "opening_hours":
        bot_response = ("Opening hours are on each restaurant page." if lang == "en" else "Opening hours restaurant page par milte hain.")

    elif intent == "delivery_area":
        bot_response = ("Delivery area depends on your location.\n\nEnter address at checkout." if lang == "en" else "Delivery area location par depend karta hai.")

    elif intent == "current_restaurant":
        active = session.get("active_restaurant")
        if active:
            try:
                rests = om.get_restaurants() or []
                rx    = next((x for x in rests if x['id'] == active), None)
                name  = rx['name'] if rx else f"Restaurant #{active}"
                bot_response = (f"🏪 Currently selected: **{name}**\n\nType 'menu' to see items or 'view restaurants' to change."
                                if lang == 'en' else f"🏪 Abhi **{name}** select hai.\n\n'menu' type karo ya 'view restaurants' se badlo.")
            except: bot_response = f"Restaurant #{active} selected hai."
        else:
            bot_response = ("No restaurant selected.\nType **'view restaurants'**." if lang == 'en' else "Koi restaurant select nahi hai.")

    elif intent == "menu":
        active = session.get("active_restaurant")
        if not active:
            bot_response = get_response("no_restaurant", lang)
        else:
            menu_list, price_map = get_restaurant_menu(active)
            if not menu_list:
                bot_response = ("No menu items found." if lang == 'en' else "Menu abhi available nahi hai.")
            else:
                menu_text = "🍽️ **Menu:**\n\n"
                for idx, item in enumerate(menu_list, 1):
                    menu_text += f"{idx}. {item.title()} - ₹{price_map[item]}\n"
                menu_text += ("\n💬 What would you like?\n💡 Try: **'2 pizzas and a coke'**"
                              if lang == 'en' else "\n💬 Kya loge?\n💡 Try: **'2 pizza aur ek coke'**")
                bot_response = menu_text

    elif intent in ("new_order", "order_item", "fallback"):
        active = session.get("active_restaurant")
        if not active:
            bot_response = (get_response("fallback", lang) if intent == "fallback" else get_response("no_restaurant", lang))
        else:
            menu_list, price_map = get_restaurant_menu(active)
            if not menu_list:
                bot_response = ("No menu available." if lang == 'en' else "Menu nahi hai.")
            else:
                items = extract_items_from_message(message, menu_list, price_map)
                if items:
                    temp_items = session["temp_order"].get("items", [])
                    # Add with duplicate-suppression: skip identical actions within short window
                    for item in items:
                        name = item.get("name")
                        qty = int(item.get("qty", 1) or 1)
                        signature = f"add:{name.lower()}:{qty}"
                        if _is_recent_duplicate(session, signature, window_seconds=2.0):
                            # skip duplicate rapid repeat
                            continue
                        existing = next((i for i in temp_items if i["name"].lower() == name.lower()), None)
                        if existing:
                            existing["qty"] += qty
                        else:
                            temp_items.append({"name": name, "qty": qty, "price": item.get("price", 0)})
                        # record last added item and action
                        session["last_added_item"] = name
                        _record_action(session, signature)
                    session["temp_order"]["items"] = temp_items
                    set_session(user_id, session)
                    total = sum(i['price'] * i['qty'] for i in temp_items)
                    bot_response = (f"✅ Added to cart!\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**\n\n💬 Say **'confirm order'** to place!"
                                    if lang == 'en' else
                                    f"✅ Cart mein add ho gaya!\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**\n\n💬 **'confirm order'** bolo!")
                else:
                    if intent == "fallback":
                        bot_response = build_fallback_response(session, lang)
                    else:
                        suggestions = suggest_close_items(message, menu_list)
                        if suggestions:
                            sugg = ", ".join(s.title() for s in suggestions)
                            bot_response = (f"🤔 Item not found.\n\n💡 Did you mean: **{sugg}**?" if lang == 'en' else f"🤔 Item nahi mila.\n\n💡 Kya yeh chahte the: **{sugg}**?")
                        else:
                            bot_response = get_response("item_not_found", lang)

    elif intent == "show_cart":
        temp_items = session.get("temp_order", {}).get("items", [])
        if not temp_items:
            bot_response = get_response("empty_cart", lang)
        else:
            total = sum(i['price'] * i['qty'] for i in temp_items)
            bot_response = (f"🛒 **Your Cart:**\n\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**\n\n💬 **'confirm order'** to place!"
                            if lang == "en" else
                            f"🛒 **Aapka Cart:**\n\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**\n\n💬 **'confirm order'** bolo!")

    elif intent == "update_quantity":
        temp_items = session.get("temp_order", {}).get("items", [])
        if not temp_items:
            bot_response = get_response("empty_cart", lang)
        else:
            active = session.get("active_restaurant")
            menu_list, price_map = get_restaurant_menu(active) if active else (None, None)
            parsed = extract_items(message, menu_list) if extract_items else []
            if not parsed: parsed = extract_items_from_message(message, menu_list or [], price_map or {})
            updated = []
            for item in parsed:
                name = item.get("name"); qty = int(item.get("qty", 1) or 1)
                if not name: continue
                existing = next((i for i in temp_items if i["name"].lower() == name.lower()), None)
                if existing: existing["qty"] = qty; updated.append(existing["name"].title())
            session["temp_order"]["items"] = temp_items
            if updated:
                total = sum(i['price'] * i['qty'] for i in temp_items)
                bot_response = (f"✅ Updated: {', '.join(updated)}\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**"
                                if lang == "en" else f"✅ Update ho gaya: {', '.join(updated)}\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**")
            else:
                bot_response = ("Tell me which item and new quantity." if lang == "en" else "Kaunsa item aur kitni quantity chahiye?")

    elif intent == "remove_item":
        temp_items = session["temp_order"].get("items", [])
        if not temp_items:
            bot_response = get_response("empty_cart", lang)
        else:
            active = session.get("active_restaurant")
            menu_list, _ = get_restaurant_menu(active) if active else (None, None)
            if not menu_list:
                clear_temp_order(user_id)
                bot_response = ("✅ Cart cleared! 🛒" if lang == 'en' else "✅ Cart saaf ho gaya! 🛒")
            else:
                # Pronoun-resolution: if user said 'remove it/that/this', target last added item
                pronoun_match = re.search(r"\b(it|that|this|them|same|last)\b", message.lower())
                items_to_remove = []
                if pronoun_match:
                    target = session.get("last_added_item")
                    if not target and temp_items:
                        target = temp_items[-1]["name"]
                    if target:
                        items_to_remove = [target]
                if not items_to_remove:
                    items_to_remove = [matched for word in message.lower().split() if len(word) > 2
                                       for matched, conf in [fuzzy_match_item(word, menu_list)] if matched and conf >= 0.6]
                if items_to_remove:
                    removed = []
                    for item_name in items_to_remove:
                        before = len(temp_items)
                        temp_items = [i for i in temp_items if i["name"].lower() != item_name.lower()]
                        if len(temp_items) < before:
                            removed.append(item_name.title())
                    # clear last_added_item if it was removed
                    if session.get("last_added_item") and any(session.get("last_added_item").lower() == r.lower() for r in removed):
                        session["last_added_item"] = None
                    session["temp_order"]["items"] = temp_items
                    set_session(user_id, session)
                    if temp_items:
                        total = sum(i['price'] * i['qty'] for i in temp_items)
                        bot_response = (f"✅ Removed {', '.join(removed)}.\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**"
                                        if lang == 'en' else f"✅ {', '.join(removed)} hata diya.\n\n**Cart:**\n{format_cart_summary(temp_items)}\n\n**Total: ₹{total}**")
                    else:
                        bot_response = ("✅ Cart is now empty! 🛒" if lang == 'en' else "✅ Cart bilkul khali hai! 🛒")
                        clear_temp_order(user_id)
                else:
                    item_names = [i['name'].title() for i in temp_items]
                    bot_response = (f"Which item to remove?\n\nCart: {', '.join(item_names)}" if lang == 'en' else f"Kaun sa item hatana hai?\n\nCart mein: {', '.join(item_names)}")

    elif intent == "confirm_order":
        temp_items = session["temp_order"].get("items", [])
        active     = session.get("active_restaurant")
        if not temp_items: bot_response = get_response("empty_cart", lang)
        elif not active: bot_response = get_response("no_restaurant", lang)
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
                bot_response = (f"🎉 **Order Confirmed!**\n\n📋 Order ID: **{order_id}**\n\n**Items:**\n{items_text}\n\n💰 **Total: ₹{total_price}**\n\n🧾 Your bill is added to the cart.\nOpen Cart → Checkout to pay.\n\n📱 Track: **'track {order_id}'**"
                                if lang == 'en' else
                                f"🎉 **Order Confirm Ho Gaya!**\n\n📋 Order ID: **{order_id}**\n\n**Items:**\n{items_text}\n\n💰 **Total: ₹{total_price}**\n\n🧾 Bill cart me add ho gaya.\nCart → Checkout se payment karo.\n\n📱 Track: **'track {order_id}'**")
                redirect_url = "/cart/checkout"
            except Exception as e:
                import traceback; traceback.print_exc()
                bot_response = f"❌ Error placing order: {str(e)}"

    elif intent == "track_order":
        order_id = None
        if extract_order_id: order_id = extract_order_id(message)
        else:
            m = re.search(r'\b(\d{1,8})\b', message)
            if m:
                try: order_id = int(m.group(1))
                except: pass
        if not order_id and session.get("last_order_id"): order_id = session["last_order_id"]
        if order_id:
            try:
                order = om.track_order(order_id)
                if order:
                    order_tracked = True
                    raw_items  = order.get("items", [])
                    items_text = "\n".join(f"• {i.get('quantity', i.get('qty', 1))}x {i.get('item_name', i.get('name', 'Item')).title()}" for i in raw_items)
                    emoji      = {"pending":"⏳","accepted":"✅","preparing":"👨‍🍳","ready":"🔔","out_for_delivery":"🚗","picked_up":"📦","delivered":"🎉","completed":"✔️","rejected":"❌","cancelled":"❌"}.get(order['status'],"📦")
                    total      = order.get('total_price', order.get('total', 0))
                    bot_response = f"📦 **Order #{order_id}**\n\n{emoji} Status: **{order['status'].upper()}**\n\n**Items:**\n{items_text}\n\n💰 Total: ₹{total}"
                else:
                    bot_response = (f"❌ Order #{order_id} not found." if lang == 'en' else f"❌ Order #{order_id} nahi mila.")
            except Exception as e: bot_response = f"❌ Error: {str(e)}"
        else:
            bot_response = ("📝 Please provide order ID.\n\nExample: **'track 1023'**" if lang == 'en' else "📝 Order ID batao.\n\nExample: **'track 1023'**")

    elif intent == "cancel_order":
        cancel_id = None
        m = re.search(r'\b(\d{1,8})\b', message)
        if m: cancel_id = int(m.group(1))
        elif session.get("last_order_id"): cancel_id = session["last_order_id"]

        if cancel_id:
            latest_order_id = session.get("last_order_id")
            # FIX 5: If user typed wrong ID but we know the latest, suggest it
            if latest_order_id and cancel_id != latest_order_id:
                session["pending_cancel_order_id"] = latest_order_id
                set_session(user_id, session)
                return jsonify({
                    "reply": (f"Your latest order is **#{latest_order_id}**. Cancel that? (yes/no)"
                              if lang == 'en' else f"Aapka latest order **#{latest_order_id}** hai. Kya usi ko cancel karna hai? (yes/no)"),
                    "intent": "cancel_order", "speak": False, "speech_text": None
                }), 200
            try:
                success = om.cancel_order(cancel_id)
                if success:
                    if session.get("last_order_id") == cancel_id: session["last_order_id"] = None
                    order_cancelled = True
                    bot_response = (f"❌ Order #{cancel_id} cancelled successfully." if lang == 'en' else f"❌ Order #{cancel_id} cancel ho gaya.")
                else:
                    bot_response = (f"⚠️ Cannot cancel Order #{cancel_id}. May already be delivered." if lang == 'en' else f"⚠️ Order #{cancel_id} cancel nahi ho sakta.")
            except Exception as e: bot_response = f"❌ Error: {str(e)}"
        else:
            bot_response = ("Which order to cancel?\n\n📝 Try: **'cancel 1023'**" if lang == 'en' else "Kaun sa order cancel karna hai?\n\n📝 Try: **'cancel 1023'**")

    # FIX 4: cancel_booking has proper response with booking ID
    elif intent == "cancel_booking":
        last_booking = session.get("last_booking_id")
        bot_response = (f"To cancel a table booking, go to **Profile → Bookings** on the website.\n\nYour latest Booking ID: **#{last_booking or '?'}**"
                        if lang == 'en' else
                        f"Table booking cancel karne ke liye website pe **Profile → Bookings** mein jao.\n\nLatest Booking ID: **#{last_booking or '?'}**")

    elif intent == "book_table":
        if (not session.get("mentioned_restaurant_id") and not session.get("booking_state", {}).get("restaurant_id")
                and session.get("booking_state", {}).get("awaiting") != "restaurant"):
            try:
                rows = om.get_restaurants() or []
            except Exception as e:
                rows = []
                print(f"Error fetching restaurants: {e}")
            if rows:
                list_text = format_restaurant_list(rows, lang)
                bot_response = ("🏪 **Which restaurant would you like to book a table at?**\n\n"
                                + list_text + "\n\n💬 Reply with the restaurant number."
                                if lang == "en" else
                                "🏪 **Kaunse restaurant mein table book karna hai?**\n\n"
                                + list_text + "\n\n💬 Restaurant ka number reply karo.")
                session["booking_state"] = {"awaiting": "restaurant", "restaurant_id": None, "booking_mode": None, "people": None, "date": None, "time": None, "preorder_items": []}
                session["restaurant_list_shown"] = True
                payload = {"reply": bot_response, "intent": intent,
                           "restaurants": prepare_restaurants_for_json(rows),
                           "speak": False, "speech_text": None}
            else:
                bot_response = ("No restaurants available right now.\n\nType **'view restaurants'**."
                                if lang == "en" else
                                "Abhi koi restaurant available nahi hai.\n\n**'view restaurants'** type karo.")
                payload = {"reply": bot_response, "intent": intent, "speak": False, "speech_text": None}
            set_session(user_id, session)
            return jsonify(payload), 200

        booking_info = extract_booking(message) if extract_booking else {}

        saved = session.get("booking_state", {})
        if not saved.get("restaurant_id") and session.get("mentioned_restaurant_id"):
            saved["restaurant_id"] = session.get("mentioned_restaurant_id")

        if saved.get("awaiting") == "restaurant":
            selected_restaurant = None
            try:
                rows = om.get_restaurants() or []
            except Exception:
                rows = []
            if message.strip().isdigit():
                rid = int(message.strip())
                selected_restaurant = next((x for x in rows if x.get("id") == rid), None)
            if not selected_restaurant:
                lower_message = message.lower().strip()
                selected_restaurant = next((x for x in rows if x.get("name") and x.get("name", "").lower() in lower_message), None)
            if selected_restaurant:
                saved["restaurant_id"] = selected_restaurant.get("id")
                saved["awaiting"] = "booking_type"
                session["booking_state"] = saved
                session["active_restaurant"] = selected_restaurant.get("id")
                session["mentioned_restaurant_id"] = selected_restaurant.get("id")
                session["mentioned_restaurant_name"] = selected_restaurant.get("name")
                session["restaurant_list_shown"] = False
                set_session(user_id, session)
                bot_response = (f"Great — I selected **{selected_restaurant.get('name')}**. How would you like to continue?\n\n1) Dine-out only\n2) Table + pre-order food\n\nReply 1 or 2."
                                if lang == "en" else
                                f"Great — **{selected_restaurant.get('name')}** select ho gaya. Kaise continue karna chahoge?\n\n1) Sirf table\n2) Table + pre-order khana\n\n1 ya 2 bhejo.")
                return jsonify({"reply": bot_response, "intent": intent, "speak": False, "speech_text": None}), 200
            set_session(user_id, session)
            return jsonify({"reply": ("Please reply with the restaurant number from the list above." if lang == "en" else "Upar wali list se restaurant number bhejo."), "intent": intent, "speak": False, "speech_text": None}), 200

        if saved.get("awaiting") == "booking_type":
            lower_message = message.lower().strip()
            if re.search(r"\b(1|dine[-\s]?out|only table|sirf table|table only)\b", lower_message):
                saved["booking_mode"] = "dine_out"
                saved["awaiting"] = "guests"
                session["booking_state"] = saved
                set_session(user_id, session)
                return jsonify({"reply": ("Okay. How many guests?" if lang == "en" else "Theek hai. Kitne guests?"), "intent": intent, "speak": False, "speech_text": None}), 200
            if re.search(r"\b(2|pre[-\s]?order|with food|table\+preorder|preorder food)\b", lower_message):
                saved["booking_mode"] = "preorder"
                saved["awaiting"] = "preorder_items"
                session["booking_state"] = saved
                set_session(user_id, session)
                return jsonify({"reply": ("What would you like to pre-order?" if lang == "en" else "Kya pre-order karna hai?"), "intent": intent, "speak": False, "speech_text": None}), 200
            set_session(user_id, session)
            return jsonify({"reply": ("Reply 1 for dine-out or 2 for pre-order." if lang == "en" else "Dine-out ke liye 1 ya pre-order ke liye 2 bhejo."), "intent": intent, "speak": False, "speech_text": None}), 200

        if saved.get("awaiting") == "preorder_items":
            preorders = extract_preorder_items(message, saved.get("restaurant_id"))
            if not preorders:
                set_session(user_id, session)
                return jsonify({"reply": ("Please tell me the items you want to pre-order." if lang == "en" else "Pre-order ke items batao."), "intent": intent, "speak": False, "speech_text": None}), 200
            saved["preorder_items"] = preorders
            saved["awaiting"] = "guests"
            session["booking_state"] = saved
            set_session(user_id, session)
            return jsonify({"reply": ("How many guests will be coming?" if lang == "en" else "Kitne guests aayenge?"), "intent": intent, "speak": False, "speech_text": None}), 200

        if saved.get("awaiting") == "guests":
            people_count = extract_people_count(message)
            if not people_count:
                m_people = re.search(r"\b(\d{1,2})\b", message)
                if m_people:
                    try:
                        people_count = int(m_people.group(1))
                    except Exception:
                        people_count = None
            if not people_count or people_count < 1 or people_count > 20:
                set_session(user_id, session)
                return jsonify({"reply": ("Please enter a guest count between 1 and 20." if lang == "en" else "Guest count 1 se 20 ke beech do."), "intent": intent, "speak": False, "speech_text": None}), 200
            saved["people"] = people_count
            saved["awaiting"] = "date"
            session["booking_state"] = saved
            set_session(user_id, session)
            return jsonify({"reply": ("Which date? Today or tomorrow?" if lang == "en" else "Kaunsi date? Aaj ya kal?"), "intent": intent, "speak": False, "speech_text": None}), 200

        if saved.get("awaiting") == "date":
            booking_info = extract_booking(message)
            booking_date = booking_info.get("date")
            if not booking_date:
                set_session(user_id, session)
                return jsonify({"reply": ("Please say today or tomorrow." if lang == "en" else "Aaj ya kal bolo."), "intent": intent, "speak": False, "speech_text": None}), 200
            if not is_allowed_booking_date(booking_date):
                set_session(user_id, session)
                return jsonify({"reply": ("Only today or tomorrow are allowed." if lang == "en" else "Sirf aaj ya kal allowed hai."), "intent": intent, "speak": False, "speech_text": None}), 200
            saved["date"] = booking_date
            saved["awaiting"] = "time"
            session["booking_state"] = saved
            set_session(user_id, session)
            return jsonify({"reply": ("What time? For example 7pm." if lang == "en" else "Kitne baje? Jaise 7pm."), "intent": intent, "speak": False, "speech_text": None}), 200

        if saved.get("awaiting") == "time":
            booking_info = extract_booking(message)
            booking_time = booking_info.get("time")
            booking_date = saved.get("date")
            if not booking_time or not is_time_allowed_for_date(booking_date, booking_time):
                set_session(user_id, session)
                return jsonify({"reply": ("Please choose a valid time between 11am-3pm or 6pm-10pm." if lang == "en" else "11am-3pm ya 6pm-10pm ke beech time do."), "intent": intent, "speak": False, "speech_text": None}), 200
            saved["time"] = booking_time
            saved["awaiting"] = "confirmation"
            session["booking_state"] = saved
            set_session(user_id, session)
            try:
                rows = om.get_restaurants() or []
                rx = next((x for x in rows if x.get("id") == saved.get("restaurant_id")), None)
                rname = rx.get("name") if rx else f"Restaurant #{saved.get('restaurant_id')}"
            except Exception:
                rname = f"Restaurant #{saved.get('restaurant_id')}"
            summary = f"Booking: {rname} | {saved.get('people')} guests | {saved.get('date')} at {saved.get('time')}"
            return jsonify({"reply": summary + ("\n\nConfirm booking? (yes/no)" if lang == "en" else "\n\nBooking confirm karein? (yes/no)"), "intent": intent, "speak": False, "speech_text": None}), 200

        if saved.get("awaiting") == "confirmation":
            if is_yes(message):
                try:
                    uid_int = safe_numeric_user_id(user_id)
                    booking_id = om.book_table(uid_int, saved.get("restaurant_id"), f"User{uid_int}", "1234567890", saved.get("date"), saved.get("time"), saved.get("people"))
                    if saved.get("booking_mode") == "preorder" and saved.get("preorder_items") and hasattr(om, "add_reservation_preorders"):
                        om.add_reservation_preorders(booking_id, saved.get("preorder_items"))
                    session["last_booking_id"] = booking_id
                    session["booking_state"] = {}
                    set_session(user_id, session)
                    return jsonify({"reply": (f"✅ Table booked. Booking ID: #{booking_id}" if lang == "en" else f"✅ Table book ho gaya. Booking ID: #{booking_id}"), "intent": "book_table", "speak": True, "speech_text": "Table booked successfully."}), 200
                except Exception as e:
                    set_session(user_id, session)
                    return jsonify({"reply": f"❌ Booking failed: {str(e)}", "intent": intent, "speak": False, "speech_text": None}), 200
            if is_no(message):
                saved["awaiting"] = "restaurant"
                session["booking_state"] = saved
                set_session(user_id, session)
                return jsonify({"reply": ("Okay, choose the restaurant again." if lang == "en" else "Theek hai, restaurant dobara choose karo."), "intent": intent, "speak": False, "speech_text": None}), 200
            set_session(user_id, session)
            return jsonify({"reply": ("Reply yes to confirm or no to change." if lang == "en" else "Confirm ke liye yes ya change ke liye no bolo."), "intent": intent, "speak": False, "speech_text": None}), 200

        saved["people"]        = booking_info.get("people") or saved.get("people")
        saved["time"]          = booking_info.get("time")   or saved.get("time")
        saved["date"]          = booking_info.get("date")   or saved.get("date")
        saved["booking_mode"]  = parse_booking_mode(message) or saved.get("booking_mode")

        invalid_date = False
        if saved.get("date") and not is_allowed_booking_date(saved.get("date")):
            invalid_date = True
            saved["date"] = None

        invalid_time = False
        if saved.get("time") and not is_allowed_booking_time(saved.get("time")):
            invalid_time = True
            saved["time"] = None

        # FIX 2: Plain number = people count
        if not saved.get("people"):
            plain_num = extract_plain_number_as_people(message)
            if plain_num: saved["people"] = plain_num

        if saved.get("restaurant_id") and saved.get("booking_mode") == "preorder":
            if not saved.get("preorder_items"):
                preorders = extract_preorder_items(message, saved.get("restaurant_id"))
                if preorders:
                    saved["preorder_items"] = preorders
        if saved.get("booking_mode") == "dine_out":
            saved["preorder_items"] = []

        session["booking_state"] = saved
        people       = saved.get("people")
        time_slot    = saved.get("time")
        booking_date = saved.get("date")
        active       = saved.get("restaurant_id")

        if not active:
            set_session(user_id, session)
            return jsonify({"reply": ("Please select a restaurant first.\n\nType **'view restaurants'**."
                                      if lang == "en" else "Pehle restaurant select karo.\n\n**'view restaurants'** type karo."),
                            "intent": intent, "speak": False, "speech_text": None}), 200

        if saved.get("booking_mode") == "preorder" and not saved.get("preorder_items"):
            preorders = extract_preorder_items(message, active)
            if preorders:
                saved["preorder_items"] = preorders
                saved["awaiting"] = "guests"
                session["booking_state"] = saved
                set_session(user_id, session)
                return jsonify({"reply": ("How many guests will be coming?" if lang == "en" else "Kitne guests aayenge?"), "intent": intent, "speak": False, "speech_text": None}), 200

        time_hint = bool(re.search(r"\b(\d{1,2}(:\d{2})?\s*(am|pm)|baje)\b", message, flags=re.I))
        people_hint = None
        m_people = re.search(r"\b(\d{1,3})\b", message)
        if m_people:
            try:
                people_hint = int(m_people.group(1))
            except ValueError:
                people_hint = None
        if not saved.get("booking_mode"):
            bot_response = get_response("booking_mode_prompt", lang)
        elif invalid_date and has_date_hint(message):
            bot_response = ("Only **today** or **tomorrow** bookings are allowed."
                            if lang == "en" else "Sirf **aaj** ya **kal** ki booking allowed hai.")
        elif invalid_time:
            bot_response = ("Please choose a time between **11am-3pm** or **6pm-10pm**."
                            if lang == "en" else "**11am-3pm** ya **6pm-10pm** ke beech time choose karo.")
        elif people_hint and people_hint > 20 and not saved.get("people"):
            bot_response = ("Please enter a guest count between **1-20**."
                            if lang == "en" else "Guest count **1-20** ke beech batao.")
        elif time_hint and not time_slot:
            bot_response = ("Please share a valid time like **7pm** or **8:30pm**."
                            if lang == "en" else "Valid time batao jaise **7pm** ya **8:30pm**.")
        elif people and time_slot and booking_date:
            try:
                uid_int    = safe_numeric_user_id(user_id)
                booking_id = om.book_table(uid_int, active, f"User{uid_int}", "1234567890",
                                           booking_date, time_slot, people)
                if saved.get("preorder_items") and hasattr(om, "add_reservation_preorders"):
                    om.add_reservation_preorders(booking_id, saved.get("preorder_items"))

                # FIX 1+7+8: Clear booking state completely, clear context
                session["booking_state"]   = {}
                session["last_booking_id"] = booking_id
                session["last_intent"]     = "booking_completed"
                session["context_stack"]   = []
                session["pending_booking_switch"] = None
                session.pop("mentioned_restaurant_id", None)
                session.pop("mentioned_restaurant_name", None)
                booking_completed = True

                # Get restaurant name
                try:
                    all_r     = om.get_restaurants() or []
                    booked_rx = next((x for x in all_r if x['id'] == active), None)
                    rest_name = booked_rx['name'] if booked_rx else f"Restaurant #{active}"
                except: rest_name = f"Restaurant #{active}"

                bot_response = (f"✅ **Table Booked!**\n\n"
                                f"🆔 Booking ID: {booking_id}\n"
                                f"🏪 Restaurant: {rest_name}\n"
                                f"✅ Reservation mode completed.\n"
                                f"📅 Date: {booking_date}\n"
                                f"🕐 Time: {time_slot}\n"
                                f"👥 Guests: {people}\n\n"
                                f"💳 Pay at restaurant when you arrive.\n"
                                f"Show this Booking ID at reception! 🎉"
                                if lang == 'en' else
                                f"✅ **Table Book Ho Gaya!**\n\n"
                                f"🆔 Booking ID: {booking_id}\n"
                                f"🏪 Restaurant: {rest_name}\n"
                                f"✅ Reservation mode completed.\n"
                                f"📅 Date: {booking_date}\n"
                                f"🕐 Time: {time_slot}\n"
                                f"👥 Guests: {people}\n\n"
                                f"💳 Pahunchne pe restaurant mein payment karna.\n"
                                f"Reception pe yeh Booking ID dikhana! 🎉")
            except Exception as e:
                print(f"Booking error: {e}"); bot_response = f"❌ Error: {str(e)}"
        else:
            if not people:
                bot_response = booking_ask("people", lang)
            elif not booking_date:
                bot_response = booking_ask("date", lang)
            elif not time_slot:
                bot_response = booking_ask("time", lang)

    if not bot_response:
        bot_response = build_fallback_response(session, lang)

    session["last_bot_msg"] = bot_response
    set_session(user_id, session)

    should_speak = False
    if intent == "confirm_order" and order_confirmed:
        should_speak = True
    elif intent == "track_order" and order_tracked:
        should_speak = True
    elif intent == "cancel_order" and order_cancelled:
        should_speak = True
    elif intent == "book_table" and booking_completed:
        should_speak = True

    speech_text = None
    if should_speak:
        speech_text = {"confirm_order": "Order confirmed. Ready in 30 minutes.",
                       "track_order": "Here is your order status.",
                       "book_table": "Table booked successfully.",
                       "cancel_order": "Order cancelled."}.get(intent)

    response_payload = {"reply": bot_response, "intent": intent,
                        "speak": should_speak, "speech_text": speech_text}
    if redirect_url: response_payload["redirect"] = redirect_url
    if restaurants_json: response_payload["restaurants"] = restaurants_json
    return jsonify(response_payload), 200

@app.route("/reset", methods=["POST"])
def reset_chat():
    data = request.get_json() or {}
    reset_session(data.get("user_id", "anonymous"))
    return jsonify({"status": "reset"}), 200

@app.route('/health', methods=['GET'])
def health():
    db_type = ('MySQL' if OrderManager is not None and isinstance(om, OrderManager) else 'In-Memory')
    return jsonify({'status': 'healthy', 'ml_model': ml_model is not None,
                    'order_manager': om is not None, 'database': db_type,
                    'timestamp': datetime.now(UTC).isoformat()}), 200

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '1') == '1'
    port  = int(os.getenv('PORT', 5000))
    print(f"\n🚀 DineBot Server Starting...")
    print(f"📊 ML Model: {'✅' if ml_model else '⚠️ Regex fallback'}")
    print(f"💾 Database: {'✅ MySQL' if (OrderManager is not None and isinstance(om, OrderManager)) else '⚠️ In-Memory'}")
    print(f"🌐 Port: {port}\n")
    app.run(host='0.0.0.0', port=port, debug=debug)