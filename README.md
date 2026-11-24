# Business Assistant — Telegram bot + Web Dashboard

    pip install -r requirements.txt
    cp .env.example .env     # BOT_TOKEN, DATABASE_URL, SESSION_SECRET
    # run schema.sql once in Supabase SQL Editor

    python bot.py            # terminal 1
    python dashboard.py      # terminal 2 -> http://localhost:8000

Login: send /dashboard to the bot (or press the Dashboard button), enter the one-time code on the site.

Files: bot.py, text_parser.py, texts.py, db.py (PostgreSQL), dashboard.py (API), static/index.html (UI), schema.sql.

## Hosting (Render)

One service runs both the site and the bot (`RUN_BOT=1`). See `render.yaml`.
Do not run `python bot.py` locally while the hosted bot is running (Telegram allows one poller).
