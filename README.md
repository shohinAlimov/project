# AI Growth Assistant

[Hosted pilot](https://growth-workspace-development.up.railway.app/) · [Статус интеграций, сценарий и подключение первого магазина](PILOT.ru.md)

A mobile owner workspace for online shops and home bakeries in Uzbekistan. FastAPI serves the Uzbek/Russian interface and the original Telegram-code dashboard at `/legacy`. The website and Telegram Business handlers use the same PostgreSQL catalog, receipts, order balances and handoff state.

## Run locally

Use Python 3.12 and PostgreSQL 15+. Create an empty development database first.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set DATABASE_URL to the development database in .env.
set -a
. ./.env
set +a
for file in supabase/migrations/*.sql; do psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f "$file"; done
GROWTH_DEMO=1 RUN_BOT=0 python dashboard.py
```

Open http://localhost:8000 and choose **Demo do‘konni ochish / Открыть демомагазин**. Each demo session starts with its own workspace. Email/password sign-up and login use Supabase Auth. Email confirmation follows the development project's Auth settings. The demo has a separate signed browser session, a template-based poster, a simulated Telegram conversation and test billing. Demo sessions last 24 hours.

For a Supabase project, apply each migration **once**, in filename order, with Supabase migrations or SQL Editor. The first creates the private `growth` schema, its row-level policies and the private `growth-private` bucket. The compatibility migration creates a compatibility schema for new installations of the original bot. Existing installations continue to resolve legacy tables with their existing search path. For a fresh legacy installation, set the legacy DB user's search path to `growth_legacy,public` and grant it access to that schema. The new workspace has its own journal. Importing historical legacy transactions is outside this pilot.

## Deployment

Deploy the `web-mvp` branch as one persistent Railway service. The Dockerfile installs the pinned dependencies, includes a Cyrillic-capable font and starts `python dashboard.py`. Use one replica, health check `/health`, HTTPS and disabled sleeping. Set `COOKIE_SECURE=1`. Keep the existing Render deployment on its current branch and token. The original Render free plan can sleep.

| Variable | Where and how it is used |
| --- | --- |
| DATABASE_URL | Railway variable. PostgreSQL connection URI with TLS for the app's restricted runtime login. Use a Supabase session pooler if the host lacks IPv6. |
| DATABASE_CA_FILE | For the pilot's direct Supabase connection, use `growth/assets/supabase-root-2021.crt`. The server verifies the certificate and hostname using this CA. The certificate comes from [Supabase](https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt). |
| SESSION_SECRET | Railway secret. A long random value shared across restarts. |
| PUBLIC_APP_URL | Public HTTPS origin used by signup and resend. In Supabase Authentication → URL Configuration, set Site URL to this origin and add its exact root URL (with trailing slash) to Redirect URLs. |
| SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY | Development project's API URL and publishable key. Enable Email Auth, configure the public site URL and confirm email delivery in Supabase Auth. |
| SUPABASE_STORAGE_KEY | Optional server-side storage secret for `growth-private`. With it configured, new files go in Supabase Storage. Without it, the same membership-checked file endpoint serves restricted PostgreSQL binary objects. Existing files keep their original backend. |
| OPENAI_API_KEY | Server-side Railway secret for receipt extraction, intent classification, analysis, shared summaries and image generation. A local env file alone cannot power Railway. |
| OPENAI_TEXT_MODEL, OPENAI_IMAGE_MODEL | Defaults `gpt-4o-mini` and `gpt-image-1`. The project needs model access and API billing. |
| BOT_TOKEN, RUN_BOT, BUSINESS_ONLY | Use a separate Business Mode test bot. Set `BUSINESS_ONLY=1` on the pilot service and enable `RUN_BOT=1` only once the token is ready. Keep `RUN_BOT=0` for a web-only pilot. |
| DASHBOARD_URL | Public address for the original bot's dashboard link, e.g. the original host plus `/legacy`. |
| GROWTH_DEMO | Set to `1` to allow isolated demo sessions. Set to `0` to require Supabase Auth. |
| STARTER_PRICE_UZS, STARTER_VISUAL_LIMIT | Defaults 48000 UZS per 30 days and 30 successful posts per calendar month. Free gets five in the Asia/Tashkent calendar month. |
| GROWTH_ADMIN_DATABASE_URL | Operator machine or restricted operator job only. Used to map a verified Telegram account or record a merchant-verified pilot activation. |

After migrations, apply the exact grants with the psql command in `ops/runtime_grants.sql`. Use a non-owner, non-superuser runtime login with `NOBYPASSRLS`. Do not expose the `growth` schema through the public Data API. The authenticated web server selects memberships, enforces roles, and sets the PostgreSQL scope inside each request transaction. The pilot runtime requires schema usage, table reads, inserts into workspace tables, updates to shop/profile/expiry, catalog, FAQ, chat, topic, connection and invoice records, and deletes on invites and members. Keep legacy-schema privileges separate.

## First shop checklist

1. Confirm the owner's language and business type. Sign in, enter the business name and save delivery and payment rules.
2. Add a product with price, design choices, availability and lead time. Save an approved answer in each customer language. A price FAQ can use `{price}` when the customer's question names a product.
3. Add a brand color or select a draft visual direction. Upload a private brand image if available.
4. Create an order and enter the customer's Telegram chat ID as its customer identifier to enable matching. Confirm outstanding balances on the website.
5. In BotFather enable Business Mode for the **test token**. Connect it from the test shop's Telegram Business settings and grant reply rights for test chats. On the pilot service the connection event logs a pending ID and Telegram owner ID. Verify both with the shop owner. Settings shows the workspace ID. Run the operator command below. A received connection event alone never enrolls a shop.
6. Use a second Telegram account to test price, delivery, a custom request, owner takeover, and a redacted payment screenshot. Confirm a receipt only after checking the actual bank account. Stop every local poller and repeat the customer question against the hosted service.
7. For assisted demos, record attendance separately. For a paying pilot, issue a Starter invoice and verify the merchant transfer before activation. Test confirmations and demo traffic are excluded from sales.

```bash
python -m growth.admin connect BUSINESS_UUID CONNECTION_ID OWNER_TELEGRAM_ID
# After matching the invoice, exact UZS amount and unique payment in the merchant account:
python -m growth.admin activate BUSINESS_UUID INVOICE_UUID 48000 VERIFIED_PROVIDER_REFERENCE
```

Settings shows the saved profile, catalog FAQs, connection status and team controls. Invite a finance or marketing worker by email, then share the generated single-use link privately. The worker signs in with that verified address and opens the link. Both roles can see shared notes and a requested AI summary. The owner can revoke access. Team pricing is proposed and Team sales are closed. Subscription invoices, test settlements and merchant references are separate from shop income. Payme hosted checkout is pending merchant onboarding.

## Two-minute demo

| Time | Action and observable result |
| --- | --- |
| 0:00–0:25 | Open the demo shop. Save the profile. In Production add Medovik at 120,000 UZS. In Settings approve a pickup answer. |
| 0:25–0:50 | In Inbox's labeled Telegram simulator ask the exact pickup question, then “Medovik narxi qancha?”. Edit the price and ask again. Ask for a custom design and observe the paused conversation. For the connected pilot, create a signed-in shop named DEMO, then use the customer's real Telegram account. |
| 0:50–1:25 | Create a 140,000 UZS order. Upload a redacted customer screenshot in Finances, or send it in the paused Telegram chat. Open the private image, enter 40,000 UZS and the date, link the order as a deposit, verify funds, and save. The balance becomes 100,000 UZS. Resend the same image and refresh. |
| 1:25–1:45 | Open Marketing to see counted questions. Generate a product post and download its branded PNG. Every shop can choose the branded template. Configured production shops can also select an AI photograph. |
| 1:45–2:00 | Create a Starter test invoice in Billing and simulate payment. Early renewal adds 30 days from expiry. Shop income stays unchanged. |

## Verification

```bash
python -m compileall -q bot.py dashboard.py growth
node --check static/growth/workspace.js
pip install pytest pytest-asyncio
# Disposable local Postgres only. The test login creates/drops temporary databases and roles.
TEST_POSTGRES_URL=postgresql://USER@localhost:5432/postgres python -m pytest -q tests
```

To verify the deployable image, run `docker build -t ai-growth-assistant:pilot .`. A build environment with a private CA can supply its CA bundle as the optional BuildKit secret `build_ca`.

The integration suite uses real PostgreSQL transactions and RLS, isolated demo identities, synthetic receipt images, two simulated Telegram account IDs and test invoices. It exercises fresh catalog prices, approved answers, paused receipts, duplicate confirmations, manual finance, tenant and worker isolation, expiry, concurrent generation limits, private image access and OCR provider fixtures. A real Supabase email exchange, a two-account Telegram session, model inference and a merchant settlement require their respective integrations.

Photo on sign-in: bakery photograph distributed through [Unsplash](https://images.unsplash.com/photo-1509440159596-0249088772ff).

The pilot can also run from an official Python container with an immutable public commit archive. Set the Railway service start command to the command printed by `python ops/railway_release.py COMMIT_SHA`. This deployment route installs dependencies on each restart and requires outbound access to GitHub and PyPI. To roll forward or back, select the corresponding verified commit.
