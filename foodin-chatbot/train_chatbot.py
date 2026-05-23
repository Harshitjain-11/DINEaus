#train_chatbot.py
import json
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from sklearn.pipeline import make_pipeline

# Load intents
with open("data/intents.json", "r", encoding="utf-8") as f:
    intents = json.load(f)["intents"]

texts, labels = [], []
for intent in intents:
    for pattern in intent["patterns"]:
        texts.append(pattern.lower())
        labels.append(intent["tag"])

# Encode labels
le = LabelEncoder()
y = le.fit_transform(labels)

# Create pipeline
model = make_pipeline(
    TfidfVectorizer(ngram_range=(1, 2), stop_words="english"),
    LogisticRegression(max_iter=2000)
)

model.fit(texts, y)

# Save everything together
with open("data/chatbot_model.pkl", "wb") as f:
    pickle.dump({
        "model": model,
        "label_encoder": le
    }, f)

print("✅ Improved model trained and saved successfully!")
