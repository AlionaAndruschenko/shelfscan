"""Перевірка нормалізації ISBN:  python3 -m pytest tests  (або python3 tests/test_isbn.py)."""
import os
import sys

os.environ.setdefault("STORAGE", "memory")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import normalize_isbn  # noqa: E402


def test_isbn13():
    assert normalize_isbn("9780547928227") == "9780547928227"
    assert normalize_isbn("978-0-547-92822-7") == "9780547928227"


def test_isbn10_converted():
    assert normalize_isbn("0-7475-3269-9") == "9780747532699"
    assert normalize_isbn("080442957X") == "9780804429573"


def test_invalid():
    assert normalize_isbn("9780547928228") is None   # неправильна контрольна цифра
    assert normalize_isbn("4820000000000") is None   # штрихкод товару, а не книги
    assert normalize_isbn("123") is None
    assert normalize_isbn("") is None


if __name__ == "__main__":
    test_isbn13(); test_isbn10_converted(); test_invalid()
    print("all ISBN tests passed")
