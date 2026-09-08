# chatbot/booking_handler.py

import re
from datetime import date, timedelta
from chatbot.session_manager import get_session, set_session
from chatbot.response_handler import format_restaurant_list, prepare_restaurants_for_json, booking_ask
from chatbot.entity_extractor import _NUM_WORDS as WORD_TO_NUMBER

# ── Date/Time Parsing & Validation ─────────────────────────────────────────

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
        r"\b(noon|midday|midnight|\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|\d{1,2}(?:am|pm)|\d{1,2}\s*baje"
        r"|morning|evening|lunch|dinner|night|afternoon|subah|sham|shaam|dopahar|raat)\b",
        text, flags=re.I,
    ))

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
            matched = m.group()
            is_pm = "pm" in matched
            is_am = "am" in matched
            if "noon" in matched or "midday" in matched: return (12, 0)
            if "midnight" in matched: return (0, 0)
            nums = re.findall(r"\d+", matched)
            hh = int(nums[0])
            mm = int(nums[1]) if len(nums) > 1 else 0
            if is_pm and hh < 12: hh += 12
            if is_am and hh == 12: hh = 0
            return (hh, mm)
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
    if re.search(r"\b(today|aaj|todat|todsy|tody|todya|tday|2day|tuday)\b", t):
        return date.today().isoformat()
    if re.search(r"\b(tomorrow|tmr|tmrw|tmw|kal|tommorow|tomorow|tommorrow|tomarrow|2morrow|2mrw|tomaro|tomorrw)\b", t):
        return (date.today() + timedelta(days=1)).isoformat()
    return None

# ── People Count Parsing ───────────────────────────────────────────────────

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
    m_for = re.search(r"\bfor\s+(\d{1,2})\b", text)
    if m_for:
        val = int(m_for.group(1))
        if 1 <= val <= 20:
            return val

    for word, val in WORD_TO_NUMBER.items():
        if re.search(rf"\b{re.escape(word)}\s*(people|person|guests?|log|aadmi|members?)\b", text):
            if 1 <= val <= 20:
                return val
        if re.search(rf"\bfor\s+{re.escape(word)}\b", text):
            if 1 <= val <= 20:
                return val
    return None

def extract_booking_fields(message: str) -> dict:
    result = {"people": None, "date": None, "time": None}
    result["people"] = extract_people_count(message)
    result["date"]   = parse_date_from_text(message)
    parsed_time      = parse_time_string(message)
    if parsed_time:
        result["time"] = f"{parsed_time[0]:02d}:{parsed_time[1]:02d}"
    return result

# ── Booking Mode Parsing ───────────────────────────────────────────────────

def parse_booking_mode(text: str):
    t = text.lower().strip()
    if re.search(r"\b(1|one|dine[-\s]?out|only table|just table|sirf table|sirf booking)\b", t):
        return "dine_out"
    if re.search(r"\b(2|two|pre[-\s]?order|preorder|with\s+food|food\s+preorder|khana|khaana|i want|add|order food)\b", t):
        return "preorder"
    return None

# ── State Machine Logic ────────────────────────────────────────────────────

def next_booking_prompt(booking_state: dict, lang: str) -> str:
    awaiting = booking_state.get("awaiting", "restaurant")
    prompt_key = "people" if awaiting == "guests" else awaiting
    return booking_ask(prompt_key, lang)

def _advance_booking_after_mode(user_id: str, session: dict, lang: str):
    saved = session.get("booking_state", {})
    mode  = saved.get("booking_mode")

    if mode == "preorder" and not saved.get("preorder_items"):
        saved["awaiting"] = "preorder_items"
        session["booking_state"] = saved
        set_session(user_id, session)
        return booking_ask("preorder_items", lang), None

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

    return _advance_booking_after_mode(user_id, session, lang)

def _confirm_booking(user_id: str, saved: dict, session: dict, lang: str, om, safe_numeric_user_id_func):
    try:
        uid_int = safe_numeric_user_id_func(user_id)
        if str(user_id).startswith("guest_") or user_id in ("anonymous", ""):
            uid_int = None
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
        if (saved.get("preorder_items") and hasattr(om, "add_reservation_preorders")):
            om.add_reservation_preorders(booking_id, saved.get("preorder_items"))

        session["booking_state"]          = {}
        session["last_booking_id"]        = booking_id
        session["last_intent"]            = "booking_completed"
        session["context_stack"]          = []
        session["pending_booking_switch"] = None
        session.pop("mentioned_restaurant_id",   None)
        session.pop("mentioned_restaurant_name", None)
        set_session(user_id, session)

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

def handle_booking(
    user_id: str,
    message: str,
    session: dict,
    lang: str,
    all_rests: list,
    om,
    match_restaurant_func,
    get_restaurants_func,
    extract_preorder_items_func,
    is_yes_func,
    is_no_func,
    safe_numeric_user_id_func
):
    saved = session.get("booking_state", {})

    if not saved:
        matched = match_restaurant_func(message, all_rests)
        if matched:
            restaurant_id   = matched.get("id")
            restaurant_name = matched.get("name")
        elif session.get("mentioned_restaurant_id"):
            restaurant_id   = session["mentioned_restaurant_id"]
            restaurant_name = session.get("mentioned_restaurant_name", f"Restaurant #{restaurant_id}")
        else:
            rows = get_restaurants_func()
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

        fields = extract_booking_fields(message)
        mode   = parse_booking_mode(message)

        extracted_date = fields.get("date")
        if extracted_date and not is_allowed_booking_date(extracted_date):
            extracted_date = None

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
        session["mentioned_restaurant_id"]  = restaurant_id
        session["mentioned_restaurant_name"]= restaurant_name
        session["restaurant_list_shown"]    = False
        set_session(user_id, session)

        if not session["booking_state"].get("booking_mode"):
            session["booking_state"]["booking_mode"] = mode or "dine_out"
        set_session(user_id, session)
        return _advance_booking_after_mode(user_id, session, lang)

    awaiting = saved.get("awaiting", "restaurant")

    if awaiting == "restaurant":
        selected = None
        rows = get_restaurants_func()
        if message.strip().isdigit():
            rid = int(message.strip())
            selected = next((x for x in rows if x.get("id") == rid), None)
        if not selected:
            lm = message.lower().strip()
            selected = next((x for x in rows if x.get("name", "").lower() in lm), None)
        if not selected:
            selected = match_restaurant_func(message, rows)
        if not selected:
            session["booking_state"] = saved
            set_session(user_id, session)
            return ("Please reply with the restaurant number from the list above."
                    if lang == "en" else "Upar wali list se restaurant number bhejo."), None

        saved["restaurant_id"]   = selected.get("id")
        saved["restaurant_name"] = selected.get("name")
        saved["booking_mode"]    = "dine_out"
        saved["awaiting"]        = "guests"
        session["booking_state"] = saved
        session["mentioned_restaurant_id"]   = selected.get("id")
        session["mentioned_restaurant_name"] = selected.get("name")
        session["restaurant_list_shown"]     = False
        set_session(user_id, session)
        return _advance_booking_after_mode(user_id, session, lang)

    if awaiting == "booking_type":
        mode = parse_booking_mode(message)
        saved["booking_mode"] = mode or "dine_out"
        saved["awaiting"]     = "guests"
        session["booking_state"] = saved
        set_session(user_id, session)
        return _advance_booking_after_mode(user_id, session, lang)

    if awaiting == "preorder_items":
        if re.search(r'\b(skip|no|nahi|mat|baad mein|later|without|sirf table|only table|no food)\b', message, flags=re.I):
            saved["preorder_items"] = []
            saved["awaiting"]       = "guests"
            session["booking_state"] = saved
            set_session(user_id, session)
            return _continue_booking(user_id, session, lang)

        preorders = extract_preorder_items_func(message, saved.get("restaurant_id"))
        if not preorders:
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

    if awaiting == "guests":
        people_count = extract_people_count(message)
        if not people_count or not (1 <= people_count <= 20):
            session["booking_state"] = saved
            set_session(user_id, session)
            return ("Please enter a guest count between **1 and 20**.\n\nExample: **'4 people'** or just **'4'**"
                    if lang == "en" else "Guest count **1 se 20** ke beech do.\n\nExample: **'4 log'** ya sirf **'4'**"), None
        saved["people"]   = people_count
        saved["awaiting"] = "date"
        session["booking_state"] = saved
        set_session(user_id, session)
        return _continue_booking(user_id, session, lang)

    if awaiting == "date":
        booking_date = parse_date_from_text(message)
        if not booking_date:
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

    if awaiting == "time":
        parsed = parse_time_string(message)
        if not parsed:
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
            session["booking_state"] = saved
            set_session(user_id, session)
            return (
                "❌ Please choose a time between **11am-3pm** or **6pm-10pm**.\n\nExample: **'7pm'** or **'1pm'**"
                if lang == "en" else
                "❌ **11am-3pm** ya **6pm-10pm** ke beech time do.\n\nExample: **'7pm'** ya **'1pm'**"
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

    if awaiting == "confirmation":
        field_edit = re.search(r"\b(change|update|modify|edit|fix|correct)\s+(the\s+)?(time|date|people|guests?|restaurant)", message, flags=re.I)
        if field_edit:
            target_field = field_edit.group(3).lower()
            field_map = {"time": "time", "date": "date", "people": "guests", "guest": "guests", "guests": "guests", "restaurant": "restaurant"}
            awaiting_field = field_map.get(target_field, target_field)
            saved["awaiting"] = awaiting_field
            if awaiting_field == "time": saved["time"] = None
            elif awaiting_field == "date": saved["date"] = None
            elif awaiting_field == "guests": saved["people"] = None
            elif awaiting_field == "restaurant":
                saved["restaurant_id"] = None; saved["restaurant_name"] = None; saved["awaiting"] = "restaurant"
            session["booking_state"] = saved
            set_session(user_id, session)
            return _continue_booking(user_id, session, lang)

        if is_yes_func(message):
            return _confirm_booking(user_id, saved, session, lang, om, safe_numeric_user_id_func)
        if is_no_func(message):
            session["booking_state"] = {
                "awaiting": "restaurant",
                "restaurant_id": None, "restaurant_name": None,
                "booking_mode": None, "people": None,
                "date": None, "time": None, "preorder_items": [],
            }
            session["restaurant_list_shown"] = True
            rows = get_restaurants_func()
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

        session["booking_state"] = saved
        set_session(user_id, session)
        return ("Reply **yes** to confirm, **no** to restart, or **'change time/date/people'** to edit a field."
                if lang == "en" else "Confirm ke liye **yes**, restart ke liye **no**, ya **'change time/date/people'** bolo field edit karne ke liye."), None

    session["booking_state"] = saved
    set_session(user_id, session)
    return next_booking_prompt(saved, lang), None
