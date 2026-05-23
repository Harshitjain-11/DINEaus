#train_model.py
import json
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.preprocessing import LabelEncoder

with open("data/intents.json", "r", encoding="utf-8") as f:
    intents = json.load(f)

texts = []
labels = []

for intent in intents["intents"]:
    tag = intent["tag"]
    for pattern in intent["patterns"]:
        texts.append(pattern)
        labels.append(tag)

vectorizer = TfidfVectorizer()
X = vectorizer.fit_transform(texts)

label_encoder = LabelEncoder()
y = label_encoder.fit_transform(labels)

model = MultinomialNB()
model.fit(X, y)

data_to_save = {
    "model": model,
    "vectorizer": vectorizer,
    "label_encoder": label_encoder
}

with open("data/chatbot_model.pkl", "wb") as f:
    pickle.dump(data_to_save, f)

print("✅ Chatbot model, vectorizer, and label encoder saved successfully in data/chatbot_model.pkl")
