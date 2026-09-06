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
    from chatbot.session_manager import get_session, set_session, push_intent, reset_session, clear_temp_order, save_sessions, cleanup_stale_sessions
except Exception:
    get_session = set_session = push_intent = reset_session = clear_temp_order = save_sessions = cleanup_stale_sessions = None

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

from chatbot.config import (
    DB_CONFIG,
    GROQ_API_KEY,
    GROQ_MODEL,
    USE_GROQ,
    GROQ_SYSTEM_PROMPT_PATH,
)

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
    "site_navigation", "cancel_order", "payment", "track_order",
    "remove_item", "show_cart", "about_bot",
}

# ── Language ───────────────────────────────────────────────────────────────────
def detect_language(text: str) -> str:
    words = set(text.lower().split())
    return 'hi' if words & _HINDI_MARKERS else 'en'

def get_lang(session: dict, message: str) -> str:
    # FIX #100/#116 + REG-04: Hybrid detection — only switch if strong signal.
    # Short messages ("7pm", "yes", "ok") keep the previous language.
    words = set(message.lower().split())
    hindi_count = len(words & _HINDI_MARKERS)
    if hindi_count >= 1:
        session["lang"] = "hi"
    elif len(words) >= 4 and hindi_count == 0:
        # Long message with zero Hindi → conclusive English switch
        session["lang"] = "en"
    elif not session.get("lang"):
        session["lang"] = "en"  # default for first message
    # else: keep session["lang"] unchanged for short/ambiguous inputs
    return session["lang"]

# ── Static responses ───────────────────────────────────────────────────────────
from chatbot.response_handler import (
    get_response,
    booking_ask,
    prepare_restaurants_for_json,
    format_restaurant_list,
    format_cart_summary,
    build_fallback_response,
)

# ── Yes / No helpers ───────────────────────────────────────────────────────────
def is_yes(text: str) -> bool:
    # FIX #21/#22/#26/#28: Expand yes detection — handle "absolutely", "of course",
    # "go ahead", stretched "yesss", thumbs up emoji, etc.
    t = text.strip()
    if t in ("👍", "👌", "✅", "💯"): return True
    return bool(re.search(
        r"\b(yes+|y|yeah+|yep|yup|ok|okay|sure|confirm|haan+|han|ha|bilkul|"
        r"theek hai|theek|done|absolutely|of course|go ahead|let'?s do it|"
        r"perfect|definitely|zaroor|pakka|sahi|ji|ji haan|approved|chalo)\b",
        text, flags=re.I,
    ))

def is_no(text: str) -> bool:
    # FIX #5/#27 + REG-01: Removed cancel/stop/ruko/band karo — those are escape
    # intents, not negation. They must be handled at each call site instead.
    t = text.lower().strip()
    if re.search(r"\bno\s*(problem|worries|doubt|issue|probs)\b", t, flags=re.I):
        return False  # "no problem" is affirmative
    return bool(re.search(
        r"\b(no+|n|nope|nah+|nahin|nahi|mat|nai|nahii+)\b",
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
    # REG-11: Added time aliases to match parse_time_string capabilities
    return bool(re.search(
        r"\b(noon|midday|midnight|\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|\d{1,2}(?:am|pm)|\d{1,2}\s*baje"
        r"|morning|evening|lunch|dinner|night|afternoon|subah|sham|shaam|dopahar|raat)\b",
        text, flags=re.I,
    ))

# FIX #74/#75: Time aliases — "evening", "dinner", "lunch", "morning", "sham", "dopahar"
_TIME_ALIASES = {
    "morning": (10, 0), "subah": (10, 0),
    "lunch": (12, 30), "lunch time": (12, 30), "dopahar": (12, 30),
    "afternoon": (13, 0),
    "evening": (19, 0), "sham": (19, 0), "shaam": (19, 0),
    "dinner": (19, 30), "dinner time": (19, 30), "raat": (20, 0),
    "night": (20, 0),
}

def parse_time_string(tstr: str):
    if not tstr or not isinstance(tstr, str):
        return None
    s = tstr.lower().strip()
    s = re.sub(r"\bbaje\b", "", s).replace('.', '')
    s = re.sub(r"\s+", " ", s).strip()

    # FIX #74/#75: Check time aliases first
    for alias, val in _TIME_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", s):
            return val

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
    # FIX #86: Add more typo variants from speech-to-text
    if re.search(r"\b(today|aaj|todat|todsy|tody|todya|tday|2day|tuday)\b", t):
        return date.today().isoformat()
    if re.search(r"\b(tomorrow|tmr|tmrw|tmw|kal|tommorow|tomorow|tommorrow|tomarrow|2morrow|2mrw|tomaro|tomorrw)\b", t):
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
    # FIX #90: Handle bare "for N" without people keyword
    m_for = re.search(r"\bfor\s+(\d{1,2})\b", text)
    if m_for:
        val = int(m_for.group(1))
        if 1 <= val <= 20:
            return val

    for word, val in WORD_TO_NUMBER.items():
        if re.search(rf"\b{re.escape(word)}\s*(people|person|guests?|log|aadmi|members?)\b", text):
            if 1 <= val <= 20:
                return val
        # FIX #90 for word numbers: "for two"
        if re.search(rf"\bfor\s+{re.escape(word)}\b", text):
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
    # FIX #7/#8/#10/#14-18: Add quit/stop/cancel/nevermind/reset so user can escape booking
    return bool(re.search(
        r"\b(menu|order|cart|checkout|confirm order|track|cancel order|cancel|payment|"
        r"offers|deal|stop|quit|exit|nevermind|never mind|start over|reset|"
        r"i changed my mind|show my bookings|show bookings|my bookings)\b",
        text, flags=re.I,
    ))

def detect_booking_interrupt_target(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(track|status|order status|my order)\b", t): return "track"
    if re.search(r"\b(cancel order|cancel my order)\b", t):       return "cancel"
    if re.search(r"\b(payment|checkout|pay)\b", t):               return "payment"
    if re.search(r"\b(help|support|account)\b", t):               return "help"
    # FIX #7/#8: Bare cancel/stop/quit/nevermind → abandon booking
    if re.search(r"\b(cancel|stop|quit|exit|nevermind|never mind|start over|reset|i changed my mind|band karo|ruko)\b", t):
        return "abandon_booking"
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

    # FIX BUG-13: Missing methods — prevent AttributeError when MySQL is unavailable
    def get_order(self, order_id): return self.orders.get(order_id)
    def get_reservation(self, reservation_id): return self.reservations.get(reservation_id)
    def cancel_reservation(self, reservation_id):
        if reservation_id in self.reservations:
            self.reservations[reservation_id]["status"] = "cancelled"; return True
        return False
    def update_order_status(self, order_id, new_status, update_timestamp=True):
        if order_id in self.orders:
            self.orders[order_id]["status"] = new_status; return True
        return False
    def update_reservation_status(self, reservation_id, new_status):
        if reservation_id in self.reservations:
            self.reservations[reservation_id]["status"] = new_status; return True
        return False

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
            qty = normalize_quantity(match.group(1))
            qty = min(qty, 50)  # FIX #61: Cap quantity at 50 to prevent absurd orders
            items.append({"name": matched, "qty": qty, "price": price_map.get(matched, 0)})
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
    # FIX #81: Fuzzy matching fallback for typos like "piza palace" → "Pizza Palace"
    if not best:
        names = [str(rx.get("name", "")).lower() for rx in (restaurants or []) if rx.get("name")]
        for word in re.split(r"\W+", t):
            if len(word) < 3: continue
            matches = get_close_matches(word, names, n=1, cutoff=0.75)
            if matches:
                best = next((rx for rx in restaurants if rx.get("name", "").lower() == matches[0]), None)
                if best: break
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
        # FIX #2: Allow goodbye to exit booking cleanly
        if re.search(r"\b(bye|goodbye|see you|alvida|chal bye|tata|later)\b", message, flags=re.I): return "goodbye"
        # FIX #50: Allow thanks to pass through during booking
        if re.search(r"\b(thanks|thank you|thanku|shukriya|dhanyavaad)\b", message, flags=re.I) and not re.search(r"\b(book|table|reserve|people|date|time)\b", message, flags=re.I): return "thanks"
        if re.search(r"\b(help|faq|support|complaint)\b", message, flags=re.I): return "help"
        if re.search(r"\b(navigate|navigation|where is|how to go)\b", message, flags=re.I): return "navigation_help"
        s = support_intent_parser(message)
        if s: return s
        # FIX P1: Payment is a stateless interrupt — don't trigger booking_interrupt
        if re.search(r"\b(payment|pay|checkout|upi|card)\b", message, flags=re.I): return "payment"
        # FIX #1: Allow track_order to pass through
        if re.search(r"\b(track|status|where is my order|mera order|order kaha)\b", message, flags=re.I) and re.search(r"\b(order|\d{3,})\b", message, flags=re.I): return "track_order"
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

        # FIX BUG-01: Ensure booking_mode is set in the CURRENT booking_state dict
        # (old code wrote to orphaned `saved` variable that pointed to the empty dict from line 1005)
        if not session["booking_state"].get("booking_mode"):
            session["booking_state"]["booking_mode"] = mode or "dine_out"
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
        # FIX #4: Detect partial field edits BEFORE yes/no check
        # "no, change the time to 8pm" / "change date" / "change people to 6"
        field_edit = re.search(r"\b(change|update|modify|edit|fix|correct)\s+(the\s+)?(time|date|people|guests?|restaurant)", message, flags=re.I)
        if field_edit:
            target_field = field_edit.group(3).lower()
            field_map = {"time": "time", "date": "date", "people": "guests", "guest": "guests", "guests": "guests", "restaurant": "restaurant"}
            awaiting_field = field_map.get(target_field, target_field)
            saved["awaiting"] = awaiting_field
            # Clear the field so it gets re-asked
            if awaiting_field == "time": saved["time"] = None
            elif awaiting_field == "date": saved["date"] = None
            elif awaiting_field == "guests": saved["people"] = None
            elif awaiting_field == "restaurant":
                saved["restaurant_id"] = None; saved["restaurant_name"] = None; saved["awaiting"] = "restaurant"
            session["booking_state"] = saved
            set_session(user_id, session)
            return _continue_booking(user_id, session, lang)

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
        return ("Reply **yes** to confirm, **no** to restart, or **'change time/date/people'** to edit a field."
                if lang == "en" else "Confirm ke liye **yes**, restart ke liye **no**, ya **'change time/date/people'** bolo field edit karne ke liye."), None

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
        uid_int    = safe_numeric_user_id(user_id)  # FIX #111: Use user_id param, not session.get
        # REG-10: Let order_manager's own FK fallback handle guest users.
        # Pass the uid_int as-is — book_table at L353-354 and L374-384
        # already retries with user_id=1 on FK constraint failure.
        # This avoids pre-emptively hijacking real user #1's profile.
        if str(user_id).startswith("guest_") or user_id in ("anonymous", ""):
            uid_int = None  # order_manager treats falsy user_id → 1 at L353
        # FIX #151: Use real user name & phone from session instead of hardcoded values
        customer_name  = session.get("user_name") or f"User{uid_int}"
        customer_phone = session.get("user_phone") or "0000000000"
        booking_id = om.book_table(
            uid_int,
            saved.get("restaurant_id"),
            customer_name,
            customer_phone,
            saved.get("date"),
            saved.get("time"),
            saved.get("people"),
        )
        # FIX BUG-03: Save pre-order items regardless of booking_mode.
        if (saved.get("preorder_items")
                and hasattr(om, "add_reservation_preorders")):
            om.add_reservation_preorders(booking_id, saved.get("preorder_items"))

        session["booking_state"]          = {}
        session["last_booking_id"]        = booking_id
        session["last_intent"]            = "booking_completed"
        session["context_stack"]          = []
        session["pending_booking_switch"] = None
        session.pop("mentioned_restaurant_id",   None)
        session.pop("mentioned_restaurant_name", None)
        set_session(user_id, session)  # FIX #111: Use user_id param, not session.get

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

# FIX #127: Simple in-memory rate limiter
_rate_limit_store = {}  # {user_id: [timestamp, ...]}
_RATE_LIMIT_WINDOW = 10  # seconds
_RATE_LIMIT_MAX    = 20  # max requests per window

def _check_rate_limit(uid: str) -> bool:
    now = datetime.now(UTC).timestamp()
    history = _rate_limit_store.get(uid, [])
    history = [t for t in history if now - t < _RATE_LIMIT_WINDOW]
    if len(history) >= _RATE_LIMIT_MAX:
        _rate_limit_store[uid] = history
        return False  # rate limited
    history.append(now)
    _rate_limit_store[uid] = history
    return True

# REG-08: Prune expired entries from rate limit store to prevent memory leak
_last_rate_cleanup = 0

def _cleanup_rate_limit_store():
    global _last_rate_cleanup
    now = datetime.now(UTC).timestamp()
    if now - _last_rate_cleanup < 60:  # at most every 60 seconds
        return
    _last_rate_cleanup = now
    stale = [uid for uid, hist in _rate_limit_store.items()
             if not hist or (now - max(hist)) > _RATE_LIMIT_WINDOW * 2]
    for uid in stale:
        _rate_limit_store.pop(uid, None)

# FIX #107: Session TTL — purge sessions older than 2 hours
_SESSION_TTL_SECONDS = 7200
_last_session_cleanup = datetime.now(UTC).timestamp()

def _run_periodic_cleanup():
    """REG-02: Delegates to session_manager.cleanup_stale_sessions (has _sessions access)."""
    global _last_session_cleanup
    now = datetime.now(UTC).timestamp()
    if now - _last_session_cleanup < 300:  # at most every 5 minutes
        return
    _last_session_cleanup = now
    try:
        if cleanup_stale_sessions:
            cleanup_stale_sessions(_SESSION_TTL_SECONDS)
    except Exception as e:
        print(f"[SESSION] Cleanup error: {e}")
    _cleanup_rate_limit_store()

@app.route("/chat", methods=["POST"])
def chat_handler():
    data    = request.get_json() or {}
    user_id = data.get("user_id", "anonymous")
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"reply": "Please type something!"}), 200

    # FIX #124: Input length limit — truncate to 500 chars
    if len(message) > 500:
        message = message[:500]

    # FIX #127: Rate limiting
    if not _check_rate_limit(user_id):
        return jsonify({"reply": "⚠️ Too many messages. Please wait a moment.", "intent": "rate_limited"}), 429

    # FIX #107 + REG-02: Periodic session + rate-limiter cleanup
    _run_periodic_cleanup()

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

    # ── CONTEXTUAL INPUT RESOLUTION (NUMERIC AMBIGUITY FIX) ────────────────
    awaiting = session.get("awaiting_input_for")
    if awaiting == "cancel_order_id" and message.isdigit():
        message = f"cancel order {message}"
    elif awaiting == "track_order_id" and message.isdigit():
        message = f"track {message}"
    session["awaiting_input_for"] = None

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
            # FIX #7/#8: abandon_booking = user said cancel/stop/quit during booking
            if pending_target == "abandon_booking":
                return respond("Booking cancelled. 👋\n\nType **'book a table'** to start a new booking or **'view restaurants'** to order food."
                               if lang == "en" else "Booking cancel ho gayi. 👋\n\n**'book a table'** se naya booking karo ya **'view restaurants'** se order karo.", "cancel_booking")
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
        # FIX #39: Allow escape to other intents instead of blocking
        if re.search(r"\b(book|table|track|menu|view restaurants?|help|order|hi|hello)\b", message, flags=re.I):
            session["pending_cancel_order_id"] = None
            set_session(user_id, session)
            # Fall through to normal intent routing below
        else:
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
    # FIX: Run basic intent detection FIRST so we can escape the booking trap
    if (re.search(r"\b(cancel order|cancel my order)\b", message, flags=re.I)
            and not re.search(r"\b(table|booking|reservation)\b", message, flags=re.I)):
        intent = "cancel_order"
    else:
        intent = resolve_intent(message, session, all_rests)
    if intent == "compare_restaurants":
        intent = "recommend_restaurants"

    # Booking state override (THE TRAP FIX)
    booking_active = session.get("booking_state", {})
    if booking_active and booking_active.get("awaiting") not in (None,):
        # We are inside a booking flow.
        # But if the user clearly stated an escape intent, let it pass through.
        if intent in BOOKING_EXEMPT_INTENTS or intent in ("cancel_order", "track_order", "help", "view_restaurants"):
            pass # Allow escape
        else:
            missing = not all([booking_active.get("restaurant_id"), booking_active.get("booking_mode"),
                               booking_active.get("people"), booking_active.get("date"), booking_active.get("time")])
            if missing:
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
        bot_response = ("Of course! 👋 What do you need help with?" if lang == "en" else "Bilkul! 👋 Aapko kis cheez mein help chahiye?")
        extra_payload["action_buttons"] = [
            {"label": "🍽️ Order Food", "action": "send_message", "value": "view restaurants"},
            {"label": "🪑 Book a Table", "action": "send_message", "value": "book a table"},
            {"label": "📦 Track an Order", "action": "send_message", "value": "track order"},
            {"label": "❌ Cancel an Order", "action": "send_message", "value": "cancel order"},
            {"label": "👤 Account & Profile", "action": "send_message", "value": "account help"},
            {"label": "🎁 Offers & Deals", "action": "send_message", "value": "offers"},
            {"label": "🏪 Add Your Restaurant", "action": "send_message", "value": "partner"}
        ]
        # FIX P1: Help ke baad booking state intact rehni chahiye — kuch clear mat karo

    elif intent == "account_help":
        if is_logged_in_user(user_id, session):
            bot_response = ("You're already signed in! You can manage your orders and addresses from your profile." if lang == "en" else "Aap already signed in ho! Aap apna profile se orders aur addresses manage kar sakte ho.")
            extra_payload["action_buttons"] = [{"label": "Open Profile", "action": "navigate", "url": "/profile"}]
        else:
            bot_response = ("You can sign in or create an account using the Login option." if lang == "en" else "Aap login ya naya account bana sakte hain.")
            extra_payload["action_buttons"] = [{"label": "Login", "action": "navigate", "url": "/login"}]

    elif intent == "about_bot":
        bot_response = ("🤖 I'm DineBot — your food ordering and table booking assistant.\n\nStart with **'view restaurants'**."
                        if lang == "en" else "🤖 Main DineBot hoon — food ordering aur table booking assistant.")

    elif intent == "offers_deals":
        bot_response = ("🎁 You can check the latest available deals from the Offers section on the home page." if lang == "en" else "🎁 Aap home page ke Offers section se latest deals check kar sakte hain.")
        extra_payload["action_buttons"] = [{"label": "View Offers", "action": "navigate", "url": "/home"}]

    elif intent == "payment":
        if session.get("temp_order", []):
            bot_response = ("Your cart is ready. You can review it and continue to checkout whenever you're ready." if lang == "en" else "Aapka cart ready hai. Aap review karke checkout kar sakte hain.")
            extra_payload["action_buttons"] = [{"label": "Proceed to Checkout", "action": "navigate", "url": "/cart/checkout"}]
        else:
            bot_response = ("Add items from a restaurant first, and I'll help you continue to payment from there." if lang == "en" else "Pehle items add karein, phir main aapki payment mein madad karunga.")

    elif intent == "navigation_help":
        bot_response = ("I can help you find what you're looking for. Tell me what you need, like 'Where is my profile?' or 'How do I track my order?'" if lang == "en" else "Main aapko sahi page dhoondne mein madad kar sakta hoon. Jaise 'Mera profile kahan hai?'")

    elif intent == "site_navigation":
        bot_response = ("DINEaus makes it easy to order food and book tables. You can use the navigation bar at the top or your Profile to access most features." if lang == "en" else "DINEaus par food order aur table book karna aasan hai. Top navigation ya Profile se features access karein.")


    elif intent in ("partner", "restaurant_register"):
        bot_response = ("🤝 Want to list your restaurant on DINEaus? I can point you to the restaurant onboarding process." if lang == "en" else "🤝 DINEaus par apna restaurant add karna chahte hain? Main aapko onboarding page par le ja sakta hoon.")
        extra_payload["action_buttons"] = [{"label": "Add Your Restaurant", "action": "navigate", "url": "/dineous-partner"}]

    elif intent == "restaurant_login":
        bot_response = ("🏪 If you're already a partner, you can access your dashboard by logging in." if lang == "en" else "🏪 Agar aap already partner hain, toh login karke dashboard access kar sakte hain.")
        extra_payload["action_buttons"] = [{"label": "Restaurant Admin Login", "action": "navigate", "url": "/restaurant-admin/login"}]

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
                    booking_active = session.get("booking_state", {})
                    is_preorder = booking_active and booking_active.get("awaiting") == "preorder_items"
                    
                    if is_preorder:
                        temp_items = booking_active.get("preorder_items", [])
                    else:
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

                    if is_preorder:
                        booking_active["preorder_items"] = temp_items
                        session["booking_state"] = booking_active
                    else:
                        session["temp_order"]["items"] = temp_items
                    set_session(user_id, session)

                    if added_any or temp_items:
                        total = sum(i['price'] * i['qty'] for i in temp_items)
                        if is_preorder:
                            bot_response = (f"✅ Pre-order added!\n\n**Items:**\n{format_cart_summary(temp_items)}\n\n💬 Say **'continue booking'** to finish your booking!"
                                            if lang == "en" else f"✅ Pre-order add ho gaya!\n\n**Items:**\n{format_cart_summary(temp_items)}\n\n💬 **'continue booking'** bolo booking khatam karne ke liye!")
                        else:
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
        # FIX #59: Handle "remove everything" / "remove all" / "clear cart"
        elif re.search(r"\b(everything|all|sab|saara|clear|empty|pura)\b", message, flags=re.I):
            clear_temp_order(user_id)
            bot_response = "✅ Cart cleared! All items removed. 🛒" if lang == "en" else "✅ Cart saaf ho gaya! Sab items hata diye. 🛒"
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
            # FIX #68: Require at least 3 digits to avoid matching quantities like "3 items"
            m = re.search(r'\b(\d{3,8})\b', message)
            if m:
                try: order_id = int(m.group(1))
                except: pass
        if not order_id and re.search(r'\b(it|that|this|last|previous)\b', message, flags=re.I):
            order_id = session.get("last_order_id")
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
            session["awaiting_input_for"] = "track_order_id"
            bot_response = "📝 Please provide order ID.\n\nExample: **'track 1023'**" if lang == "en" else "📝 Order ID batao."

    elif intent == "cancel_order":
        cancel_id = None

        # FIX P0: Extract order ID from message ONLY if explicitly stated (4-8 digit number)
        m = re.search(r'\b(\d{4,8})\b', message)
        if m:
            cancel_id = int(m.group(1))

        # Check for pronouns to auto-resolve to last_order_id
        if not cancel_id and re.search(r'\b(it|that|this|last|previous|latest)\b', message, flags=re.I):
            cancel_id = session.get("last_order_id")

        # FIX P0: If no explicit order ID, ONLY use last_order_id from THIS session
        # NEVER auto-fetch latest DB order — that causes random old-order cancellations
        if not cancel_id:
            session_order_id = session.get("last_order_id")
            if session_order_id:
                cancel_id = session_order_id
            else:
                # No order context at all — ask for ID instead of guessing
                session["awaiting_input_for"] = "cancel_order_id"
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
            session["awaiting_input_for"] = "cancel_order_id"
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