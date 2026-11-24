# Business Assistant — Telegram bot skeleton

    pip install -r requirements.txt
    cp .env.example .env      # put BOT_TOKEN
    python bot.py

Files: `bot.py` (handlers), `text_parser.py` (text parsing), `db.py` (SQLite), `texts.py` (UZ/RU).
Nothing is saved without the user pressing "Confirm".
TODO: OCR in `recognize_receipt`, AI parsing in `text_parser.parse`, edit/delete history, reminders.
