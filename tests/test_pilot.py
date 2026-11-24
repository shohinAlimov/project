"""Run only against a disposable local PostgreSQL server. Each test owns a fresh DB."""

import asyncio
import io
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
        await c.execute(
            f"grant usage on schema growth to {role};grant select,insert,update,delete on all tables in schema growth to {role}"
        )

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

    async def send(text):
        replies.append(text)

    async def update(mid, msg="", file=None, connection="test", sender=200):
        async def load():
            return file

        async with db._pool.acquire() as c, c.transaction():
            await telegram.handle(
                c, connection, 200, mid, sender, msg, load if file else None, send
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
    assert s["topics"][0]["count"] == 2
    receipt = s["receipts"][0]
    assert receipt["id"] == await put_photo(client, "income", photo)
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
