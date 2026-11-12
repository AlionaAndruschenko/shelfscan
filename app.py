"""ShelfScan — сканер домашньої бібліотеки.

Браузер (камера телефону зчитує штрихкод ISBN)
    -> цей Flask-сервер у Google Cloud Run
        -> Google Books API  (пошук книги за ISBN)
        -> Cloud Firestore   (збереження полиці)

Змінні середовища:
    BOOKS_API_KEY  - ключ Google Books API (необов'язково, але з ним вищі ліміти)
    STORAGE        - "firestore" (за замовчуванням) або "memory" (для локального тесту)
    BOOKS_API_URL  - адреса API (за замовчуванням https://www.googleapis.com/books/v1)
"""
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request

BOOKS_API_URL = os.environ.get("BOOKS_API_URL", "https://www.googleapis.com/books/v1").rstrip("/")
BOOKS_API_KEY = os.environ.get("BOOKS_API_KEY", "").strip()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("shelfscan")


# ---------------------------------------------------------------- ISBN
def normalize_isbn(raw):
    """Повертає ISBN-13 (рядок з 13 цифр) або None, якщо код некоректний."""
    s = re.sub(r"[^0-9Xx]", "", raw or "").upper()
    if len(s) == 10:
        if not re.fullmatch(r"\d{9}[\dX]", s):
            return None
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s))
        if total % 11 != 0:
            return None
        core = "978" + s[:9]
        check = (10 - sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(core)) % 10) % 10
        return core + str(check)
    if len(s) == 13 and s.isdigit() and s[:3] in ("978", "979"):
        total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(s))
        return s if total % 10 == 0 else None
    return None


# ---------------------------------------------------------------- Google Books API
def lookup_book(isbn13):
    """Шукає книгу в Google Books API. Повертає (book | None, час запиту в мс)."""
    params = {"q": "isbn:" + isbn13, "maxResults": 1}
    if BOOKS_API_KEY:
        params["key"] = BOOKS_API_KEY
    t0 = time.time()
    resp = requests.get(BOOKS_API_URL + "/volumes", params=params, timeout=10)
    api_ms = int((time.time() - t0) * 1000)
    resp.raise_for_status()
    data = resp.json()
    log.info("Books API isbn=%s status=%s items=%s %d ms",
             isbn13, resp.status_code, data.get("totalItems", 0), api_ms)
    items = data.get("items") or []
    if not items:
        return None, api_ms
    info = items[0].get("volumeInfo", {})
    images = info.get("imageLinks") or {}
    cover = images.get("thumbnail") or images.get("smallThumbnail") or ""
    cover = cover.replace("http://", "https://").replace("&edge=curl", "")
    year = (info.get("publishedDate") or "")[:4]
    book = {
        "isbn": isbn13,
        "google_id": items[0].get("id", ""),
        "title": info.get("title", "Без назви"),
        "subtitle": info.get("subtitle", ""),
        "authors": info.get("authors") or [],
        "publisher": info.get("publisher", ""),
        "year": int(year) if year.isdigit() else None,
        "pages": info.get("pageCount") or 0,
        "categories": info.get("categories") or [],
        "language": info.get("language", ""),
        "description": (info.get("description") or "")[:800],
        "cover": cover,
        "link": info.get("infoLink") or info.get("canonicalVolumeLink") or "",
        "rating": info.get("averageRating"),
    }
    return book, api_ms


# ---------------------------------------------------------------- сховище полиць
class MemoryStore:
    """Сховище в пам'яті — лише для локального запуску без хмари."""
    name = "memory"

    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def list(self, shelf):
        with self._lock:
            books = list(self._data.get(shelf, {}).values())
        return sorted(books, key=lambda b: b["added_at"], reverse=True)

    def get(self, shelf, isbn):
        with self._lock:
            return self._data.get(shelf, {}).get(isbn)

    def add(self, shelf, book):
        with self._lock:
            self._data.setdefault(shelf, {})[book["isbn"]] = book

    def delete(self, shelf, isbn):
        with self._lock:
            return self._data.get(shelf, {}).pop(isbn, None) is not None


class FirestoreStore:
    """Cloud Firestore: колекція shelves/{shelf}/books/{isbn}."""
    name = "firestore"

    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client()

    def _col(self, shelf):
        return self.db.collection("shelves").document(shelf).collection("books")

    def list(self, shelf):
        docs = self._col(shelf).order_by("added_at", direction="DESCENDING").stream()
        return [d.to_dict() for d in docs]

    def get(self, shelf, isbn):
        doc = self._col(shelf).document(isbn).get()
        return doc.to_dict() if doc.exists else None

    def add(self, shelf, book):
        self._col(shelf).document(book["isbn"]).set(book)

    def delete(self, shelf, isbn):
        ref = self._col(shelf).document(isbn)
        if not ref.get().exists:
            return False
        ref.delete()
        return True


def make_store():
    if os.environ.get("STORAGE", "firestore").lower() == "memory":
        return MemoryStore()
    try:
        return FirestoreStore()
    except Exception as e:  # немає облікових даних -> локальний режим
        log.warning("Firestore недоступний (%s), використовую пам'ять", e)
        return MemoryStore()


store = make_store()
log.info("Storage: %s", store.name)


def shelf_name():
    raw = (request.args.get("shelf") or (request.get_json(silent=True) or {}).get("shelf") or "main")
    s = re.sub(r"[^a-z0-9-]", "", raw.lower())[:40]
    return s or "main"


# ---------------------------------------------------------------- маршрути
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "storage": store.name}


@app.get("/api/lookup")
def api_lookup():
    isbn = normalize_isbn(request.args.get("isbn"))
    if not isbn:
        return jsonify(error="bad_isbn", message="Це не схоже на ISBN книжки"), 400
    try:
        book, api_ms = lookup_book(isbn)
    except requests.RequestException as e:
        log.error("Books API error: %s", e)
        return jsonify(error="api_error", message="Google Books API не відповідає"), 502
    if not book:
        return jsonify(error="not_found", message="Книгу з таким ISBN не знайдено", isbn=isbn, api_ms=api_ms), 404
    return jsonify(book=book, api_ms=api_ms)


@app.get("/api/shelf")
def api_shelf():
    shelf = shelf_name()
    t0 = time.time()
    books = store.list(shelf)
    return jsonify(shelf=shelf, books=books, storage=store.name, db_ms=int((time.time() - t0) * 1000))


@app.post("/api/shelf")
def api_add():
    shelf = shelf_name()
    payload = request.get_json(silent=True) or {}
    isbn = normalize_isbn(payload.get("isbn"))
    if not isbn:
        return jsonify(error="bad_isbn", message="Це не схоже на ISBN книжки"), 400
    existing = store.get(shelf, isbn)
    if existing:
        return jsonify(book=existing, duplicate=True)
    try:
        book, api_ms = lookup_book(isbn)
    except requests.RequestException as e:
        log.error("Books API error: %s", e)
        return jsonify(error="api_error", message="Google Books API не відповідає"), 502
    if not book:
        return jsonify(error="not_found", message="Книгу з таким ISBN не знайдено в Google Books", isbn=isbn, api_ms=api_ms), 404
    book["added_at"] = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    store.add(shelf, book)
    db_ms = int((time.time() - t0) * 1000)
    log.info("Added isbn=%s to shelf=%s (api %d ms, db %d ms)", isbn, shelf, api_ms, db_ms)
    return jsonify(book=book, api_ms=api_ms, db_ms=db_ms), 201


@app.delete("/api/shelf/<isbn>")
def api_delete(isbn):
    shelf = shelf_name()
    isbn13 = normalize_isbn(isbn)
    if not isbn13 or not store.delete(shelf, isbn13):
        return jsonify(error="not_found"), 404
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
