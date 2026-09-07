# chatbot/llm_handler.py

import re
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

try:
    from groq import Groq
except Exception:
    Groq = None

from chatbot.config import (
    PROJECT_ROOT,
    GROQ_API_KEY,
    GROQ_MODEL,
    USE_GROQ,
    GROQ_SYSTEM_PROMPT_PATH
)

def load_valid_intents():
    intents = set()
    try:
        with open(PROJECT_ROOT / "data" / "intents.json", "r", encoding="utf-8") as f:
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
