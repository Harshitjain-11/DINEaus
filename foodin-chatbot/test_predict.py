import sys
import os

# Ensure terminal encoding won't raise on Windows consoles when files print Unicode
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
except Exception:
    pass
from pathlib import Path
from chatbot.model_loader import ModelLoader

def print_top_n(prob_row, loader, n=5):
    """
    Pretty print top-N intents with confidence bars.
    """
    classes = loader.model.classes_
    decoded = loader.decoded_classes()

    paired = list(zip(range(len(prob_row)), prob_row))
    paired.sort(key=lambda x: x[1], reverse=True)

    print("\n🔝 Top predictions:")
    for idx, p in paired[:n]:
        tag = decoded[idx] if idx < len(decoded) else "?"
        bar = "█" * int(p * 20)
        print(f" - {tag:20s}  {p:.4f}  {bar}")

    print()


def run_interactive():
    model_path = Path(__file__).parent / "data" / "chatbot_model.pkl"
    intents_path = Path(__file__).parent / "data" / "intents.json"
    loader = ModelLoader(model_path=model_path, intents_path=intents_path)

    print("\n==============================")
    print("🤖  Chatbot Model Tester")
    print("==============================")
    print("Loaded classes:", loader.decoded_classes())
    print("==============================\n")

    while True:
        text = input("Type something (or press Enter to quit): ").strip()
        if not text:
            break

        probs = loader.predict_proba([text])[0]
        best_pos = probs.argmax()
        conf = float(probs[best_pos])
        best_tag = loader.decode_label(best_pos)

        print("\n======================================")
        print(f"🧠 Predicted intent : {best_tag}")
        print(f"🔢 Confidence       : {conf:.4f}")
        print("--------------------------------------")

        print_top_n(probs, loader, n=5)

        print("📊 Raw model classes:", list(loader.model.classes_))
        print("📝 Decoded classes  :", loader.decoded_classes())
        print("======================================\n")


def run_routing_tests():
    from app import app as flask_app, predict_intent

    predict_cases = [
        ("order food", "view_restaurants"),
        ("can i order", "view_restaurants"),
        ("yes i want to order food", "view_restaurants"),
        ("which restaurant is popular", "recommend_restaurants"),
        ("book a table", "book_table"),
        ("top rated restaurant", "recommend_restaurants"),
        ("show", "view_restaurants"),
    ]

    api_cases = [
        ("order food", "view_restaurants"),
        ("which restaurant is popular", "recommend_restaurants"),
        ("book a table", "book_table"),
        ("top rated restaurant", "recommend_restaurants"),
        ("show", "view_restaurants"),
    ]

    failures = 0
    print("\n=== predict_intent() routing tests ===")
    for text, expected in predict_cases:
        got = predict_intent(text, {"restaurant_names": []})
        ok = got == expected
        status = "OK" if ok else "FAIL"
        print(f"[{status}] '{text}' -> {got} (expected {expected})")
        if not ok:
            failures += 1

    print("\n=== /chat API routing tests ===")
    client = flask_app.test_client()
    for text, expected in api_cases:
        client.post("/reset", json={"user_id": "test-user"})
        resp = client.post(
            "/chat",
            json={"user_id": "test-user", "message": text, "is_logged_in": True},
        )
        data = resp.get_json() or {}
        got = data.get("intent")
        ok = resp.status_code == 200 and got == expected
        status = "OK" if ok else "FAIL"
        print(f"[{status}] '{text}' -> {got} (expected {expected})")
        if not ok:
            failures += 1

    if failures:
        raise SystemExit(1)
    print("\nAll routing tests passed.")


if __name__ == "__main__":
    if "--routing" in sys.argv:
        run_routing_tests()
    else:
        run_interactive()
