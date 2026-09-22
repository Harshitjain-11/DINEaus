import re
from chatbot.llm_handler import VALID_INTENTS, _groq_result_with_timeout

def support_intent_parser(text: str):
    t = text.lower()
    if re.search(r'\b(help|faq|support|complaint|issue|problem)\b', t): return "help"
    return None

def is_unrelated_to_booking(text: str) -> bool:
    t = text.lower()
    if re.search(r'\b(order|cart|checkout|status|track|cancel my order|payment|pay)\b', t): return True
    if re.search(r'\b(menu|what is available|food|dish|biryani|pizza|burger)\b', t): return True
    return False

def detect_multi_intent(message: str, restaurants: list):
    m = message.lower()
    has_order_verb = bool(re.search(r'\b(order|add|get|give|want|chahiye|de do)\b', m))
    has_track_verb = bool(re.search(r'\b(track|status|kahan hai|where is)\b', m))
    if has_order_verb and has_track_verb:
        return "track_order"
    return None

def _looks_like_freeform_text(text: str) -> bool:
    words = text.split()
    return len(words) > 12

def _looks_ambiguous(text: str, session: dict = None) -> bool:
    if not text: return True
    if len(text.split()) <= 2: return False
    score = 0
    if re.search(r'\b(and|also|or|but|then|if)\b', text, re.I): score += 1
    if re.search(r'\b(how|what|where|why|can you|will you)\b', text, re.I): score += 1
    return score >= 2

def simple_intent_parser(text: str, restaurant_names: list = None, word_to_number: dict = None) -> str:
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
    if re.search(r'\b(track|where is|order status|kahan hai|status batao|order kahan|my order status|order ka status|mera order|what is my order)\b', t): return "track_order"
    if re.search(r'\b(quiet|calm|family|romantic|date night|ambience|nice place|good place|seating|crowd|peaceful)\b', t): return "fallback"
    if re.search(r'\b(menu|show menu|items|kya milta|food list|dikhao|kha sakte|khana)\b', t): return "menu"
    if re.search(r'\b(show cart|mera cart|cart dikhao|my cart|view cart|cart mein kya|what is in my cart|cart|basket|bag)\b', t): return "show_cart"
    if re.search(r'\b(change|switch|different|badlo|dusra)\s*(restaurant|place|jagah)?\b', t): return "change_restaurant"
    if re.search(r'\b(make it|change to|ek aur|one more|aur ek|quantity change|badha do|kam karo)\b', t): return "update_quantity"
    if re.search(r'\b(order food|can i order|want to order|i want to order|food order|khana order|hungry|bhook|khaana chahiye)\b', t): return "view_restaurants"
    
    qty_words = '|'.join((word_to_number or {}).keys()) if word_to_number else 'one'
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

def predict_intent(text: str, session: dict = None, ml_model=None, word_to_number: dict = None) -> str:
    cleaned = (text or "").strip()
    regex_intent = simple_intent_parser(cleaned, (session or {}).get("restaurant_names", []), word_to_number=word_to_number)
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

def resolve_intent(
    message: str, 
    session: dict, 
    restaurants: list, 
    ml_model=None, 
    word_to_number=None,
    get_restaurant_menu_func=None, 
    extract_items_func=None
) -> str:
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
        if get_restaurant_menu_func and extract_items_func:
            menu_list, price_map = get_restaurant_menu_func(active_restaurant)
            order_hint = bool(re.search(r"\b(add|order|want|get|give me|i want|i need|chahiye|de do|lena|mangwa)\b", message, flags=re.I))
            qty_hint   = bool(re.search(r"\b(\d+|one|two|three|four|five|ek|do|teen|char|paanch)\b", message, flags=re.I))
            if menu_list and (order_hint or qty_hint) and extract_items_func(message, menu_list, price_map):
                return "order_item"

    return predict_intent(message, session, ml_model=ml_model, word_to_number=word_to_number)
