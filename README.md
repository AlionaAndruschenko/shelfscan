# ShelfScan — сканер домашньої бібліотеки

PoC для курсу «Хмарні обчислення» (завдання 2). Автор: Андрущенко Альона, ТТП-42, ФКНК КНУ.

Наводиш камеру телефону на штрихкод книжки — і вона з обкладинкою, автором, описом і кількістю сторінок
з'являється на твоїй віртуальній полиці. Полиця зберігається в хмарі й однакова на всіх пристроях.

## Хмарні сервіси та API

| Сервіс | Навіщо |
|---|---|
| **Google Books API** | пошук книги за ISBN: назва, автори, рік, сторінки, опис, обкладинка |
| **Cloud Firestore** | NoSQL-база, де зберігаються полиці (`shelves/{shelf}/books/{isbn}`) |
| **Cloud Run** | запуск Flask-сервера в контейнері, автоматичний HTTPS (потрібен для камери) |
| Cloud Build + Artifact Registry | збирання контейнера з коду під час `gcloud run deploy --source` |

## Як працює

```
Телефон / браузер ──(HTTPS)──> Cloud Run: Flask (app.py)
   │ камера зчитує EAN-13           ├──> Google Books API  GET /books/v1/volumes?q=isbn:...
   │ (html5-qrcode, без ШІ)         └──> Cloud Firestore   shelves/{shelf}/books/{isbn}
   └── кожні 4 с оновлює полицю (синхронізація між пристроями)
```

1. Браузер зчитує штрихкод (EAN-13, ISBN починається з 978/979) бібліотекою html5-qrcode.
2. `POST /api/shelf` → сервер перевіряє контрольну цифру ISBN і звертається до Google Books API.
3. Дані книги зберігаються в Firestore; у відповіді є час запиту до Books API і до Firestore.
4. Інші пристрої, відкриті на тій самій полиці, бачать нову книжку протягом 4 секунд.

## REST API застосунку

| Метод | Шлях | Опис |
|---|---|---|
| GET | `/api/lookup?isbn=` | знайти книгу в Google Books (без збереження) |
| GET | `/api/shelf?shelf=` | список книжок на полиці |
| POST | `/api/shelf` `{"isbn","shelf"}` | додати книжку |
| DELETE | `/api/shelf/<isbn>?shelf=` | прибрати книжку |
| GET | `/healthz` | перевірка стану |

## Розгортання (Google Cloud Shell)

```bash
git clone https://github.com/AlionaAndruschenko/shelfscan && cd shelfscan
PROJECT_ID=<твій-project-id> bash deploy/deploy_gcp.sh     # 5-7 хв, наприкінці друкує адресу
bash deploy/teardown_gcp.sh                                  # видалити після здачі
```

## Локальний запуск

```bash
pip install -r requirements.txt
STORAGE=memory python3 app.py        # без Firestore, дані в пам'яті
# відкрити http://localhost:8080 (камера працює на localhost без HTTPS)
python3 tests/test_isbn.py           # тести перевірки ISBN
```

Бібліотека сканування: [html5-qrcode](https://github.com/mebjas/html5-qrcode) 2.3.8 (Apache-2.0), лежить у `static/`.
