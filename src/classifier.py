"""Part 3: classification of requests with an LLM (Google Gemini).

SDK: google-genai (https://ai.google.dev/gemini-api/docs/quickstart?lang=python)

    client = genai.Client(api_key=...)
    response = client.models.generate_content(model=..., contents=..., config=...)

The answer is forced into JSON with a fixed list of categories
(structured output: response_mime_type + response_json_schema), so the
model cannot invent a category or reply with free text.

Results are cached in cache/classifications.json, keyed by request id and
a hash of the text. Re-running the program does not call the API again
(the free tier has a small requests-per-minute limit), and the program
also works without an API key if the cache is present.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path

from google import genai
from google.genai import errors, types

log = logging.getLogger(__name__)

CATEGORIES = ["ზარალი", "საჩივარი", "ინფორმაციის მოთხოვნა", "სხვა"]
# gemini-2.5-flash returns 404 for new API keys ("no longer available to new
# users"); gemini-3.x flash models returned 503 (high demand) during testing.
# flash-lite answered reliably and is enough for a 4-class task.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
REQUEST_TIMEOUT_MS = 60_000

SYSTEM_PROMPT = """\
შენ ხარ სადაზღვევო კომპანიის მომხმარებელთა მიმართვების კლასიფიკატორი.
თითოეულ მიმართვას მიანიჭე ზუსტად ერთი კატეგორია:

- ზარალი: მომხმარებელი აცხადებს სადაზღვევო შემთხვევას (ავარია, დაზიანება,
  ქურდობა, მკურნალობა, ბარგის დაკარგვა და ა.შ.) ან ითხოვს მის ანაზღაურებას.
- საჩივარი: მომხმარებელი უკმაყოფილოა კომპანიის მომსახურებით
  (დაგვიანება, არასწორი თანხა, თანამშრომლის ქცევა, ტექნიკური ხარვეზი და ა.შ.).
- ინფორმაციის მოთხოვნა: მომხმარებელი სვამს კითხვას პროდუქტზე, დაფარვაზე,
  ფასზე ან პროცედურაზე და შემთხვევას არ აცხადებს.
- სხვა: ყველაფერი, რაც ზემოთ ჩამოთვლილს არ ეკუთვნის.

თუ მიმართვა რამდენიმე კატეგორიას შეესაბამება, აირჩიე მთავარი მიზანი.
reason ველში ერთი მოკლე წინადადებით ახსენი არჩევანი ქართულად.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "reason": {"type": "string"},
    },
    "required": ["category", "reason"],
}

RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class GeminiClassifier:
    def __init__(self, api_key, model=None, retries=5, base_delay=5.0):
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        )
        self.model = model or DEFAULT_MODEL
        self.retries = retries
        self.base_delay = base_delay
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,  # same input -> same answer as far as possible
            response_mime_type="application/json",
            response_json_schema=RESPONSE_SCHEMA,
        )

    def classify(self, text):
        """Return {"category", "reason"}. Raise on unrecoverable error."""
        for attempt in range(1, self.retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=text, config=self.config)
                return self._parse(response.text)
            except errors.APIError as e:
                if e.code not in RETRYABLE_CODES or attempt == self.retries:
                    raise
                # 429 = free-tier rate limit; wait and try again.
                delay = self.base_delay * 2 ** (attempt - 1)
                log.warning("Gemini %s (attempt %d/%d), retry in %.0fs",
                            e.code, attempt, self.retries, delay)
                time.sleep(delay)
            except ValueError as e:
                # Invalid JSON or unknown category: ask once more.
                if attempt == self.retries:
                    raise
                log.warning("Invalid model answer (attempt %d): %s", attempt, e)

    @staticmethod
    def _parse(raw):
        if not raw:
            raise ValueError("empty response")
        data = json.loads(raw)
        if data.get("category") not in CATEGORIES:
            raise ValueError(f"unknown category: {data.get('category')!r}")
        return {"category": data["category"], "reason": str(data.get("reason", "")).strip()}


def _load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("Cache %s is unreadable, ignoring it: %s", path, e)
        return {}


def _save_cache(cache, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def classify_records(records, cache_path, api_key=None, model=None):
    """Add `category` (and `category_reason`) to every record (in place).

    If a record cannot be classified, category is None and the program
    continues.
    """
    cache_path = Path(cache_path)
    cache = _load_cache(cache_path)
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    classifier = GeminiClassifier(api_key, model) if api_key else None
    if classifier is None:
        log.warning("GEMINI_API_KEY is not set: only cached classifications are used")

    for r in records:
        key = f"{r['id']}:{_text_hash(r['text'])}"
        result = cache.get(key)

        if result is None and classifier is not None:
            try:
                result = classifier.classify(r["text"])
                result["model"] = model
                cache[key] = result
                _save_cache(cache, cache_path)  # keep progress if a later call fails
            except Exception as e:  # network error, API error, bad answer...
                log.warning("Could not classify %s: %s", r["id"], e)

        r["category"] = result["category"] if result else None
        r["category_reason"] = result["reason"] if result else None

    return records
