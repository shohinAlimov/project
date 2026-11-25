"""Run only against a disposable local PostgreSQL server. Each test owns a fresh DB."""

import asyncio
import io
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio
from PIL import Image

import db
import dashboard
from growth import auth, media, telegram

BASE = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pilot(monkeypatch):
    dsn = os.getenv("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("TEST_POSTGRES_URL required")
    monkeypatch.setenv("GROWTH_DEMO", "1")
    monkeypatch.delenv("SUPABASE_STORAGE_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    suffix = uuid4().hex[:12]
    database = f"pilot_{suffix}"
    role = f"web_{suffix}"
    admin = await asyncpg.connect(dsn)
    await admin.execute(f"create database {database}")
    await admin.execute(f"create role {role} nologin")
    c = await asyncpg.connect(dsn, database=database)
    try:
        for path in sorted((BASE / "supabase/migrations").glob("*.sql")):
            await c.execute(path.read_text())
        grants = (
            (BASE / "ops/runtime_grants.sql")
            .read_text()
            .replace(':"runtime_role"', role)
        )
        await c.execute(grants)

        async def setup(conn):
            await conn.execute(f"set role {role}")

        pool = await asyncpg.create_pool(
            dsn, database=database, min_size=1, max_size=8, setup=setup
        )
        monkeypatch.setattr(db, "_pool", pool)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=dashboard.app), base_url="http://test"
        ) as client:
            assert (await client.post("/growth/demo")).is_success
            shop = (
                await client.post(
                    "/growth/onboard",
                    json={
                        "name": "DEMO Rayhon",
                        "language": "ru",
                        "delivery": "Доставка до 18:00",
                    },
                )
            ).json()
            yield client, UUID(shop["id"]), c
        await pool.close()
    finally:
        await c.close()
        await admin.execute(f"drop database {database} with (force)")
        await admin.execute(f"drop role {role}")
        await admin.close()


async def call(client, path, body):
    r = await client.post("/growth/" + path, json=body)
    assert r.is_success, r.text
    return r.json()


def png(color="white"):
    out = io.BytesIO()
    Image.new("RGB", (90, 50), color).save(out, format="PNG")
    return out.getvalue()


async def state(client):
    r = await client.get("/growth/state")
    assert r.is_success, r.text
    return r.json()


async def put_photo(client, kind, data):
    r = await client.post(
        "/growth/receipts/" + kind, files={"file": ("redacted.png", data, "image/png")}
    )
    assert r.is_success, r.text
    return r.json()["id"]


def entry(kind, amount, **extra):
    return dict(
        request_id=str(uuid4()),
        kind=kind,
        amount=amount,
        day="2026-11-24",
        category="DEMO",
        **extra,
    )


async def test_business_handoff_receipts_and_duplicate_confirmations(pilot):
    client, biz, admin = pilot
    product = await call(
        client, "products", {"name": "Медовик", "price": 90000, "availability": "Есть"}
    )
    await call(
        client,
        "faqs",
        {
            "question": "Как забрать заказ?",
            "answer": "После 15:00 у метро.",
            "language": "ru",
        },
    )
    await admin.execute(
        "insert into growth.connections values('test', $1,100,true)", biz
    )
    replies = []
    alerts = []

    async def send(text):
        replies.append(text)

    async def update(mid, msg="", file=None, connection="test", sender=200):
        async def load():
            return file

        async with db._pool.acquire() as c, c.transaction():
            await telegram.handle(
                c,
                connection,
                200,
                mid,
                sender,
                msg,
                load if file else None,
                send,
                outbox=alerts,
            )

    await update(1, "Как забрать заказ?", connection="unknown")
    assert not replies
    await update(1, "Как забрать заказ?")
    assert replies.pop() == "После 15:00 у метро."
    await update(2, "Сколько стоит Медовик?")
    assert replies.pop() == "Медовик — 90 000 UZS"
    assert (
        await client.put(
            "/growth/products/" + product["id"],
            json={"name": "Медовик", "price": 120000},
        )
    ).is_success
    await update(3, "Медовик narxi qancha?")
    assert replies.pop() == "Медовик — 120 000 UZS"
    await update(4, "Хочу индивидуальный дизайн")
    await update(5, "Сколько стоит Медовик?")
    photo = png()
    await update(6, file=photo)
    await update(6, file=photo)
    await update(7, file=photo)
    s = await state(client)
    assert not replies and s["chats"][0]["paused"] and len(s["receipts"]) == 1
    # One alert for the new screenshot only; the resent file and message are not alerted again.
    assert len(alerts) == 1 and alerts[0][0] == 100
    assert "💳" in alerts[0][1] and "Финансы" in alerts[0][1]
    assert s["topics"][0]["count"] == 2
    receipt = s["receipts"][0]
    assert receipt["id"] == await put_photo(client, "income", photo)
    duplicate = io.BytesIO()
    Image.open(io.BytesIO(photo)).save(duplicate, format="PNG", compress_level=0)
    assert duplicate.getvalue() != photo
    assert receipt["id"] == await put_photo(client, "income", duplicate.getvalue())
    assert (await client.get("/growth/files/" + receipt["file_id"])).content == photo
    oid = (
        await call(
            client,
            "orders",
            {"product_id": product["id"], "customer": "200", "total": 120000},
        )
    )["id"]
    assert (await state(client))["receipts"][0]["suggested_order"] == oid
    draft = entry(
        "income",
        40000,
        order_id=oid,
        payment_type="deposit",
        receipt_id=receipt["id"],
        verified=True,
    )
    assert (
        await client.post("/growth/journal", json={**draft, "verified": False})
    ).status_code == 422
    ids = await asyncio.gather(
        *[
            call(client, "journal", {**draft, "request_id": str(uuid4())})
            for _ in range(5)
        ]
    )
    assert len(set(r["id"] for r in ids)) == 1
    s = await state(client)
    assert (
        s["figures"]["outstanding"] == 80000
        and s["figures"]["income"] == 40000
        and len(s["journal"]) == 1
    )
    assert s["journal"][0]["file_id"] == receipt["file_id"]
    assert (
        await client.put("/growth/chats/" + s["chats"][0]["id"], json={"paused": False})
    ).is_success
    await update(8, "Сколько стоит Медовик?")
    assert replies.pop() == "Медовик — 120 000 UZS"
    await update(9, "Беру диалог", sender=100)
    assert (await state(client))["chats"][0]["paused"]


async def test_web_finance_independent_of_telegram(pilot, monkeypatch):
    client, biz, admin = pilot
    await call(client, "journal", entry("income", 110000))
    await call(client, "journal", entry("expense", 12000))
    photo = png("green")
    rid = await put_photo(client, "expense", photo)
    s = await state(client)
    assert (
        s["connections"] == 0
        and s["receipts"][0]["fields"] == {}
        and s["figures"]["expense"] == 12000
    )
    await call(
        client,
        "journal",
        entry("expense", 15000, receipt_id=rid, verified=True, note="Packaging"),
    )
    payment = await put_photo(client, "income", png("blue"))
    await call(
        client, "journal", entry("income", 30000, receipt_id=payment, verified=True)
    )
    s = await state(client)
    assert (s["figures"]["income"], s["figures"]["expense"]) == (140000, 27000)
    assert not s["receipts"]
    assert (
        await client.post(
            "/growth/receipts/income",
            files={"file": ("invalid.jpg", b"bad", "image/jpeg")},
        )
    ).status_code == 415
    assert (
        await client.post("/growth/invoices", headers={"origin": "https://wrong.test"})
    ).status_code == 403


async def test_quota_failed_generation_billing_expiry(pilot, monkeypatch):
    client, biz, admin = pilot
    pid = (await call(client, "products", {"name": "Medovik", "price": 90000}))["id"]
    real = media.poster

    async def failed(*args):
        raise media.HTTPException(503, "provider unavailable")

    monkeypatch.setattr(media, "poster", failed)
    assert (await client.post("/growth/visuals/" + pid)).status_code == 503
    monkeypatch.setattr(media, "poster", real)
    runs = await asyncio.gather(
        *[client.post("/growth/visuals/" + pid) for _ in range(7)]
    )
    assert sorted(r.status_code for r in runs) == [200] * 5 + [429] * 2
    fid = next(r.json()["file_id"] for r in runs if r.is_success)
    image = Image.open(io.BytesIO((await client.get("/growth/files/" + fid)).content))
    assert image.size == (1024, 1024)
    a = (await call(client, "invoices", {}))["id"]
    first = await call(client, "invoices/" + a + "/simulate", {})
    assert first["plan"] == "Starter" and first["price"] == 48000
    assert (await call(client, "invoices/" + a + "/simulate", {}))["expires"] == first[
        "expires"
    ]
    second = (await call(client, "invoices", {}))["id"]
    await call(client, "invoices/" + second + "/simulate", {})
    assert await admin.fetchval(
        "select paid_until > now()+interval '59 days' from growth.shops where id=$1",
        biz,
    )
    assert (await client.post("/growth/visuals/" + pid)).is_success
    await admin.execute(
        "update growth.shops set paid_until=now()-interval '1 minute' where id=$1", biz
    )
    s = await state(client)
    assert (
        s["billing"]["plan"] == "Free"
        and len(s["visuals"]) == 6
        and s["figures"]["income"] == 0
    )


async def test_access_roles_invite_scope_and_revocation(pilot, monkeypatch):
    client, biz, admin = pilot
    other = uuid4()
    await admin.execute(
        "insert into growth.shops(id,name,language) values($1,'Other','uz')", other
    )
    async with db._pool.acquire() as c, c.transaction():
        await auth.context(c, "business", biz)
        assert await c.fetchval("select count(*) from growth.shops") == 1
        assert not await c.fetchval("select id from growth.shops where id=$1", other)
    assert (
        await client.get("/growth/state", headers={"x-business-id": str(other)})
    ).status_code == 404
    invites = []
    for role in ("finance", "marketing"):
        token = (
            await call(
                client, "invites", {"email": role + "@example.test", "role": role}
            )
        )["token"]
        invites.append((role, token))
    for role, token in invites:
        uid = uuid4()

        async def worker(req):
            return uid, role + "@example.test", False

        import growth.api as api

        with monkeypatch.context() as patch:
            patch.setattr(auth, "identity", worker)
            patch.setattr(api, "identity", worker)
            await call(client, "join", {"question": token})
            assert (
                await client.post("/growth/join", json={"question": token})
            ).status_code == 403
            s = await state(client)
            assert ("figures" in s) == (role == "finance")
            assert ("topics" in s) == (role == "marketing")
            assert (await client.post("/growth/invoices")).status_code == 403
            assert (
                await client.post("/growth/journal", json=entry("expense", 2000))
            ).status_code == (200 if role == "finance" else 403)
            await call(client, "notes", {"question": "Shared pilot note"})
        assert (await client.delete("/growth/members/" + str(uid))).is_success
        assert not await admin.fetchval(
            "select 1 from growth.members where subject=$1", uid
        )


async def test_live_paths_with_provider_fixtures(pilot, monkeypatch):
    client, biz, admin = pilot
    await admin.execute("update growth.shops set demo=false where id=$1", biz)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")

    async def fake(path, body):
        assert path == "chat/completions"
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"amount":32000,"day":"2026-11-21","vendor":"DEMO","category":"packaging","reference":null}'
                    }
                }
            ]
        }

    monkeypatch.setattr(media, "openai", fake)
    await put_photo(client, "expense", png("yellow"))
    fields = (await state(client))["receipts"][0]["fields"]
    assert fields == {
        "amount": 32000,
        "day": "2026-11-21",
        "vendor": "DEMO",
        "category": "packaging",
    }
    iid = (await call(client, "invoices", {}))["id"]
    assert (
        await client.post("/growth/invoices/" + iid + "/simulate")
    ).status_code == 403
    from growth import billing

    async with admin.transaction():
        with pytest.raises(media.HTTPException):
            await billing.activate(admin, biz, UUID(iid), 1, "DEMO-ref")
        p = await billing.activate(admin, biz, UUID(iid), 48000, "DEMO-ref")
        assert p["plan"] == "Starter"
    assert (await state(client))["figures"]["income"] == 0


async def test_supabase_auth_storage_contract_and_real_shop_template(
    pilot, monkeypatch
):
    client, biz, admin = pilot
    user = uuid4()
    monkeypatch.setenv("PUBLIC_APP_URL", "https://shop.example.test/")
    monkeypatch.setenv("SUPABASE_URL", "https://dev.example.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "publishable-fixture")
    monkeypatch.setenv("SUPABASE_STORAGE_KEY", "sb_secret_fixture")
    upstream = httpx.AsyncClient
    objects = {}

    def mock_provider(request):
        path = request.url.path
        if path.startswith("/storage/"):
            assert request.headers["apikey"] == "sb_secret_fixture"
            if request.method == "POST":
                objects[path] = request.content
                return httpx.Response(200, json={"Key": path})
            return httpx.Response(200, content=objects[path])
        assert request.headers["apikey"] == "publishable-fixture"
        if path == "/auth/v1/user":
            assert request.headers["authorization"] == "Bearer access-fixture"
            return httpx.Response(
                200, json={"id": str(user), "email": "pilot@example.test"}
            )
        if path in ("/auth/v1/signup", "/auth/v1/resend"):
            assert request.url.params["redirect_to"] == "https://shop.example.test/"
        if path == "/auth/v1/resend":
            import json

            assert json.loads(request.content) == {
                "type": "signup",
                "email": "pilot@example.test",
            }
            return httpx.Response(200, json={})
        if path == "/auth/v1/signup":
            return httpx.Response(200, json={"id": str(user)})
        if path == "/auth/v1/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-fixture",
                    "refresh_token": "refresh-fixture",
                    "expires_in": 3600,
                },
            )
        if path == "/auth/v1/logout":
            return httpx.Response(204)
        raise AssertionError(path)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: upstream(
            transport=httpx.MockTransport(mock_provider), **kwargs
        ),
    )
    credentials = {"email": "pilot@example.test", "password": "fixture-password"}
    assert (await call(client, "auth/signup", credentials))["confirm_email"]
    assert (await call(client, "auth/resend", {"email": credentials["email"]}))[
        "confirm_email"
    ]
    assert (await call(client, "auth/login", credentials))["signed_in"]
    assert "growth_demo" not in client.cookies
    assert not (await client.get("/growth/me")).json()["memberships"]
    real = (await call(client, "onboard", {"name": "QA only", "language": "uz"}))["id"]
    assert real != str(biz)
    assert (await client.post("/growth/refresh")).is_success
    pic = png("beige")
    await put_photo(client, "income", pic)
    r = (await state(client))["receipts"][0]
    assert await admin.fetchval(
        "select bytes is null and object_path is not null from growth.files where id=$1",
        UUID(r["file_id"]),
    )
    assert (await client.get("/growth/files/" + r["file_id"])).content == pic
    pid = (await call(client, "products", {"name": "Tort", "price": 60000}))["id"]
    visual = await call(client, "visuals/" + pid + "?template=true", {})
    assert (await client.get("/growth/files/" + visual["file_id"])).content.startswith(
        b"\x89PNG"
    )
    assert (await client.post("/growth/logout")).is_success
    assert (await client.get("/growth/files/" + r["file_id"])).status_code == 401


async def test_legacy_commands_and_business_dispatch(pilot, monkeypatch):
    import bot
    from aiogram import Bot, Dispatcher
    from aiogram.types import Update

    client, biz, admin = pilot
    await admin.execute("set search_path=growth_legacy,public")
    await admin.execute("insert into users(telegram_id,lang) values(8001,'ru')")
    await admin.execute(
        "insert into businesses(owner_id,name) select id,'DEMO legacy' from users where telegram_id=8001"
    )
    await admin.execute(
        "insert into growth.connections values('qa-wire',$1,8001,true)", biz
    )
    await call(client, "products", {"name": "Медовик", "price": 85000})
    # Legacy schema is accessible only to the original owner-bot service.
    dsn = os.environ["TEST_POSTGRES_URL"]
    pool = await asyncpg.create_pool(
        dsn,
        database=await admin.fetchval("select current_database()"),
        server_settings={"search_path": "growth_legacy,public"},
    )
    monkeypatch.setattr(db, "_pool", pool)
    transport = Bot("100000:TEST_FIXTURE_ONLY")
    sent = []

    async def capture(self, method, request_timeout=None):
        sent.append(method)
        return True

    monkeypatch.setattr(Bot, "__call__", capture)
    dp = Dispatcher()
    dp.include_routers(telegram.router, bot.router)
    try:
        for mid, command in enumerate(("/start", "/dashboard"), 1):
            raw = {
                "message_id": mid,
                "date": 1795500000,
                "chat": {"id": 8001, "type": "private"},
                "from": {"id": 8001, "is_bot": False, "first_name": "Owner"},
                "text": command,
            }
            await dp.feed_update(
                transport,
                Update.model_validate(
                    {"update_id": mid, "message": raw}, context={"bot": transport}
                ),
            )
        assert len(sent) == 2
        assert await admin.fetchval("select count(*) from link_codes") == 1
        raw.update(
            {
                "business_connection_id": "qa-wire",
                "chat": {"id": 9002, "type": "private"},
                "from": {"id": 9002, "is_bot": False, "first_name": "Customer"},
                "text": "Сколько стоит Медовик?",
            }
        )
        await dp.feed_update(
            transport,
            Update.model_validate(
                {"update_id": 3, "business_message": raw}, context={"bot": transport}
            ),
        )
        assert (
            sent[-1].text == "Медовик — 85 000 UZS"
            and sent[-1].business_connection_id == "qa-wire"
        )
    finally:
        await transport.session.close()
        await pool.close()


async def test_text_provider_is_configurable_and_images_stay_on_openai(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '```json\n{"amount": 5}\n```'}}]},
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        media.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "gemini-fixture")
    monkeypatch.setenv("LLM_BASE_URL", "https://gemini.example.test/v1beta/openai/")
    monkeypatch.setenv("LLM_TEXT_MODEL", "gemini-fixture-model")
    assert media.ai_text()
    assert await media.completion("Read it.", "x", True) == {"amount": 5}
    assert seen["url"] == "https://gemini.example.test/v1beta/openai/chat/completions"
    assert seen["auth"] == "Bearer gemini-fixture"
    assert seen["body"]["model"] == "gemini-fixture-model"
    # The text provider's key is never used for image generation.
    seen.clear()
    with pytest.raises(media.HTTPException):
        await media.openai("images/generations", {})
    assert not seen
    # A non-HTTPS provider URL is refused before any request is made.
    monkeypatch.setenv("LLM_BASE_URL", "http://insecure.example.test/")
    with pytest.raises(media.HTTPException):
        await media.completion("Read it.", "x")
    assert not seen
