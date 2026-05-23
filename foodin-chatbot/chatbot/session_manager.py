# chatbot/session_manager.py
"""
Fixed session manager — correct defaults, booking state, context stack.
"""
from datetime import datetime, UTC

_sessions = {}

def _default_session() -> dict:
    return {
        "user_id": None,
        "is_logged_in": False,
        "user_name": None,
        "last_intent": None,
        "last_success_action": None,
        "active_restaurant": None,       # int or None
        "temp_order": {"items": []},     # FIX: was {} — app.py needs items key
        "last_order_id": None,           # FIX: was missing — needed for track/cancel
        "last_booking_id": None,
        "pending_cancel_order_id": None,
        "last_bot_msg": None,
        "last_user_message": None,
        "last_user_message_at": None,
        "last_added_item": None,
        "booking_state": {},             # NEW: tracks multi-turn booking fields
        "context_stack": [],             # NEW: last 3 intents for context awareness
        "lang": None,
        "pending_switch": None,
        "pending_booking_switch": None,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "recent_actions": [],
        "last_added_item": None,
        "last_action_time": None,
    }

def get_session(user_id: str) -> dict:
    if user_id not in _sessions:
        _sessions[user_id] = _default_session()
    else:
        # Patch old sessions that are missing keys (hot-reload safety)
        s = _sessions[user_id]
        defaults = _default_session()
        for key, val in defaults.items():
            if key not in s:
                s[key] = val
        # Ensure temp_order always has items list
        if not isinstance(s.get("temp_order"), dict):
            s["temp_order"] = {"items": []}
        if "items" not in s["temp_order"]:
            s["temp_order"]["items"] = []
    return _sessions[user_id]

def set_session(user_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.now(UTC).isoformat()
    _sessions[user_id] = data
    return _sessions[user_id]

def push_intent(user_id: str, intent: str):
    """Keep a rolling window of last 3 intents for context awareness."""
    s = get_session(user_id)
    stack = s.get("context_stack", [])
    stack.append(intent)
    if len(stack) > 3:
        stack = stack[-3:]
    s["context_stack"] = stack
    s["last_intent"] = intent

def clear_temp_order(user_id: str) -> dict:
    s = get_session(user_id)
    s["temp_order"] = {"items": []}  # FIX: was {} 
    s["last_intent"] = None
    return s

def clear_booking_state(user_id: str) -> dict:
    s = get_session(user_id)
    s["booking_state"] = {}
    return s

def reset_session(user_id: str) -> dict:
    """Full reset — called on chat reset button."""
    _sessions[user_id] = _default_session()
    return _sessions[user_id]

def dump_sessions() -> dict:
    """Shallow copy for debugging."""
    return dict(_sessions)