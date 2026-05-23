# chatbot/model_loader.py
import pickle
from pathlib import Path
import json
from typing import Any, Dict, List, Tuple

from sklearn.pipeline import Pipeline
from sklearn.base import BaseEstimator

class ModelLoader:
    """
    Robust loader for chatbot models saved in different formats.

    Supported pickle formats:
    1) {"model": pipeline, "label_encoder": le}
       - 'model' is an sklearn Pipeline that accepts raw text inputs.
    2) {"model": estimator, "vectorizer": vectorizer, "label_encoder": le}
       - legacy format where vectorizer and estimator are saved separately.
       - we will wrap them into a small adapter pipeline so code using .predict_proba works.
    3) Direct pipeline object (Pipeline or similar) - label_encoder must still be provided in a dict or saved separately.
    4) {"pipeline": pipeline, "label_encoder": le} (alternate key)
    """

    def __init__(self,
                 model_path: Path = Path("data/chatbot_model.pkl"),
                 intents_path: Path = Path("data/intents.json")):
        self.model_path = Path(model_path)
        self.intents_path = Path(intents_path)
        self.model = None
        self.label_encoder = None
        self.intents = None

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        # load pickle
        with open(self.model_path, "rb") as f:
            data = pickle.load(f)

        # If data is a plain Pipeline object
        if isinstance(data, Pipeline):
            self.model = data
            # label encoder must be loaded from intents file or not available
            self.label_encoder = None
        elif isinstance(data, dict):
            # common key patterns
            if "model" in data and isinstance(data["model"], (Pipeline, BaseEstimator)):
                # preferred shape: {"model": pipeline, "label_encoder": le}
                self.model = data["model"]
                self.label_encoder = data.get("label_encoder", None)
            elif "pipeline" in data and isinstance(data["pipeline"], (Pipeline, BaseEstimator)):
                self.model = data["pipeline"]
                self.label_encoder = data.get("label_encoder", None)
            elif "model" in data and "vectorizer" in data and "label_encoder" in data:
                # legacy shape: model (estimator), vectorizer, label_encoder
                estimator = data["model"]
                vectorizer = data["vectorizer"]
                le = data["label_encoder"]
                # create a tiny adapter that first vectorizes then calls estimator
                class _VecWrapper(Pipeline):
                    """Simple wrapper pipeline built at runtime from vectorizer + estimator."""
                    def __init__(self, vectorizer, estimator):
                        super().__init__([("vect", vectorizer), ("clf", estimator)])
                self.model = _VecWrapper(vectorizer, estimator)
                self.label_encoder = le
            else:
                # try best-effort: if 'model' is present but label encoder absent, still accept
                if "model" in data:
                    self.model = data["model"]
                    self.label_encoder = data.get("label_encoder", None)
                else:
                    raise ValueError("Unrecognized model file format. Expected keys like 'model'/'pipeline' and optionally 'label_encoder' or legacy 'vectorizer'.")
        else:
            raise ValueError("Unrecognized pickle content for chatbot model.")

        # load intents.json optionally (for response lookups)
        if self.intents_path.exists():
            try:
                with open(self.intents_path, "r", encoding="utf-8") as f:
                    self.intents = json.load(f)
            except Exception:
                self.intents = None

        print("✅ ModelLoader: model loaded.", f"Label encoder: {'present' if self.label_encoder is not None else 'MISSING'}")

    # ---- Low-level passthroughs ----
    def _ensure_model(self):
        if self.model is None:
            raise RuntimeError("Model not loaded correctly.")

    def predict_proba(self, texts) -> Any:
        """
        Return model.predict_proba output.
        Accepts list[str] or array-like of texts.
        """
        self._ensure_model()
        # If model is a pipeline/estimator that expects transformed X, it should handle it.
        return self.model.predict_proba(texts)

    def predict_raw(self, texts) -> Any:
        """
        Return model.predict (raw encoded labels or direct string labels depending on the model).
        """
        self._ensure_model()
        return self.model.predict(texts)

    # ---- Higher-level helpers ----
    def predict(self, texts: List[str]) -> List[Tuple[str, float]]:
        """
        For each input text, return a tuple (decoded_tag, confidence).
        If label_encoder is missing, returns raw predicted value and confidence.
        """
        self._ensure_model()
        # get probabilities and choose best
        probs = self.model.predict_proba(texts)
        results = []
        for prob_row in probs:
            best_idx = int(prob_row.argmax())
            conf = float(prob_row[best_idx])
            # model.classes_ contains encoded class labels (could be ints or strings)
            cls_value = self.model.classes_[best_idx]
            if self.label_encoder is not None:
                try:
                    tag = self.label_encoder.inverse_transform([cls_value])[0]
                except Exception:
                    # if label_encoder expects integer labels but classes_ are strings, try mapping
                    try:
                        tag = self.label_encoder.inverse_transform([int(cls_value)])[0]
                    except Exception:
                        tag = str(cls_value)
            else:
                tag = str(cls_value)
            results.append((tag, conf))
        return results

    def decode_label(self, class_index: int) -> str:
        """
        Given an index into model.classes_ (position), return decoded tag string.
        """
        self._ensure_model()
        if class_index < 0 or class_index >= len(self.model.classes_):
            raise IndexError("class_index out of range for model.classes_")
        encoded_value = self.model.classes_[class_index]
        if self.label_encoder is None:
            return str(encoded_value)
        try:
            return self.label_encoder.inverse_transform([encoded_value])[0]
        except Exception:
            # try fallback if encoded_value is string of an int
            try:
                return self.label_encoder.inverse_transform([int(encoded_value)])[0]
            except Exception:
                return str(encoded_value)

    # convenience: get list of decoded class labels (in the order of model.classes_)
    def decoded_classes(self) -> List[str]:
        self._ensure_model()
        if self.label_encoder is None:
            return [str(c) for c in self.model.classes_]
        decoded = []
        for c in self.model.classes_:
            try:
                decoded.append(self.label_encoder.inverse_transform([c])[0])
            except Exception:
                try:
                    decoded.append(self.label_encoder.inverse_transform([int(c)])[0])
                except Exception:
                    decoded.append(str(c))
        return decoded
