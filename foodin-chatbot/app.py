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
    from chatbot.entity_extractor import extract_order_id, extract_items, _NUM_WORDS as WORD_TO_NUMBER
    print("entity_extractor loaded")
except Exception:
    print("entity_extractor import warning")
    extract_order_id = extract_items = None
from chatbot.utils import is_yes, is_no, safe_numeric_user_id
from chatbot.booking_handler import handle_booking

from chatbot.config import (
    DB_CONFIG,
)
from chatbot.llm_handler import VALID_INTENTS, _groq_result_with_timeout
from chatbot.intent_router import resolve_intent

app = Flask(__name__)
CORS(app, resources={
    r"/chat":   {"origins": "*"},
    r"/reset":  {"origins": "*"},
    r"/health": {"origins": "*"},
})


# ── Constants ──────────────────────────────────────────────────────────────────
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

# ══════════════════════════════════════════════════════════════════════════════
# BOOKING STATE MACHINE - FIXED VERSION
# ══════════════════════════════════════════════════════════════════════════════


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
        intent = resolve_intent(
            message=message,
            session=session,
            restaurants=all_rests,
            ml_model=ml_model,
            word_to_number=WORD_TO_NUMBER,
            get_restaurant_menu_func=get_restaurant_menu,
            extract_items_func=extract_items_from_message
        )
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
        reply, extra = handle_booking(
            user_id, message, session, lang, all_rests,
            om=om,
            match_restaurant_func=match_restaurant_in_message,
            get_restaurants_func=_get_restaurants,
            extract_preorder_items_func=extract_preorder_items,
            is_yes_func=is_yes,
            is_no_func=is_no,
            safe_numeric_user_id_func=safe_numeric_user_id
        )
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