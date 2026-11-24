"""PostgreSQL storage (asyncpg). Schema: schema.sql"""
import os
from datetime import date, timedelta

import asyncpg

_pool = None


async def init():
    global _pool
    # statement_cache_size=0 keeps it compatible with Supabase poolers
    _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=5,
                                      statement_cache_size=0)


async def close():
    if _pool:
        await _pool.close()


async def get_user(tg_id):
    return await _pool.fetchrow("SELECT * FROM users WHERE telegram_id=$1", tg_id)


async def set_lang(tg_id, lang):
    await _pool.execute(
        "INSERT INTO users(telegram_id, lang) VALUES($1,$2) "
        "ON CONFLICT (telegram_id) DO UPDATE SET lang=EXCLUDED.lang", tg_id, lang)


async def get_lang(tg_id):
    return await _pool.fetchval("SELECT lang FROM users WHERE telegram_id=$1", tg_id) or "ru"


async def get_business(tg_id):
    return await _pool.fetchrow(
        "SELECT b.* FROM businesses b JOIN users u ON u.id=b.owner_id "
        "WHERE u.telegram_id=$1 ORDER BY b.id LIMIT 1", tg_id)


async def create_business(tg_id, name, currency="UZS"):
    await _pool.execute(
        "INSERT INTO businesses(owner_id, name, currency) SELECT id,$2,$3 FROM users WHERE telegram_id=$1",
        tg_id, name, currency)


async def _category_id(conn, business_id, tx_type, value):
    """Find a category by code or name; if the user typed a new one, create it for this business."""
    row = await conn.fetchrow(
        "SELECT id FROM categories WHERE (business_id IS NULL OR business_id=$1) AND type=$2 "
        "AND (code=$3 OR lower(name_ru)=lower($3) OR lower(name_uz)=lower($3)) "
        "ORDER BY business_id NULLS LAST LIMIT 1", business_id, tx_type, value)
    if row:
        return row["id"]
    return await conn.fetchval(
        "INSERT INTO categories(business_id, name_uz, name_ru, type) VALUES($1,$3,$3,$2) RETURNING id",
        business_id, tx_type, value)


async def add_tx(business_id, d):
    """Called ONLY after the user confirmed the draft."""
    async with _pool.acquire() as conn:
        async with conn.transaction():
            cat_id = await _category_id(conn, business_id, d["type"], d["category"])
            await conn.execute(
                "INSERT INTO transactions(business_id,type,amount,occurred_on,category_id,description,source) "
                "VALUES($1,$2,$3,$4,$5,$6,$7)",
                business_id, d["type"], d["amount"], date.fromisoformat(d["date"]),
                cat_id, d["description"], d["source"])


async def find_duplicate(business_id, d):
    return await _pool.fetchrow(
        "SELECT id FROM transactions WHERE business_id=$1 AND type=$2 AND amount=$3 "
        "AND deleted_at IS NULL AND occurred_on BETWEEN $4::date - 1 AND $4::date + 1 LIMIT 1",
        business_id, d["type"], d["amount"], date.fromisoformat(d["date"]))


async def history(business_id, limit=10):
    return await _pool.fetch(
        "SELECT t.id, t.type, t.amount::bigint AS amount, t.occurred_on::text AS date, "
        "COALESCE(c.code, c.name_ru) AS category, t.description "
        "FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
        "WHERE t.business_id=$1 AND t.deleted_at IS NULL "
        "ORDER BY t.occurred_on DESC, t.id DESC LIMIT $2", business_id, limit)


async def summary(business_id, period):
    today = date.today()
    start = {"day": today, "week": today - timedelta(days=6), "month": today.replace(day=1)}[period]
    r = await _pool.fetchrow(
        "SELECT COALESCE(SUM(amount) FILTER (WHERE type='income'),0)::bigint AS income, "
        "COALESCE(SUM(amount) FILTER (WHERE type='expense'),0)::bigint AS expense "
        "FROM transactions WHERE business_id=$1 AND deleted_at IS NULL AND occurred_on BETWEEN $2 AND $3",
        business_id, start, today)
    return r["income"], r["expense"]


# ---------- Dashboard ----------
import hashlib
import secrets


def _h(code):
    return hashlib.sha256(code.encode()).hexdigest()


async def create_link_code(tg_id):
    """One-time login code for the Dashboard (stored hashed, valid 10 minutes)."""
    code = f"{secrets.randbelow(10**8):08d}"
    await _pool.execute(
        "INSERT INTO link_codes(user_id, code_hash, expires_at) "
        "SELECT id, $2, now() + interval '10 minutes' FROM users WHERE telegram_id=$1", tg_id, _h(code))
    return code


async def use_link_code(code):
    return await _pool.fetchrow(
        "UPDATE link_codes SET used_at=now() WHERE code_hash=$1 AND used_at IS NULL "
        "AND expires_at > now() RETURNING user_id", _h(code))


async def business_of_user(user_id):
    return await _pool.fetchrow(
        "SELECT b.id, b.name, b.currency, u.lang FROM businesses b JOIN users u ON u.id=b.owner_id "
        "WHERE u.id=$1 ORDER BY b.id LIMIT 1", user_id)


async def dash_summary(business_id, start, end):
    base = "FROM transactions WHERE business_id=$1 AND deleted_at IS NULL AND occurred_on BETWEEN $2 AND $3"
    tot = await _pool.fetchrow(
        "SELECT COALESCE(SUM(amount) FILTER (WHERE type='income'),0)::bigint AS received, "
        "COALESCE(SUM(amount) FILTER (WHERE type='expense'),0)::bigint AS spent " + base,
        business_id, start, end)
    days = await _pool.fetch(
        "SELECT occurred_on::text AS d, "
        "COALESCE(SUM(amount) FILTER (WHERE type='income'),0)::bigint AS income, "
        "COALESCE(SUM(amount) FILTER (WHERE type='expense'),0)::bigint AS expense "
        + base + " GROUP BY occurred_on ORDER BY occurred_on", business_id, start, end)
    cats = await _pool.fetch(
        "SELECT COALESCE(c.code, c.name_ru) AS category, SUM(t.amount)::bigint AS total "
        "FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
        "WHERE t.business_id=$1 AND t.deleted_at IS NULL AND t.type='expense' "
        "AND t.occurred_on BETWEEN $2 AND $3 GROUP BY 1 ORDER BY 2 DESC", business_id, start, end)
    return {"received": tot["received"], "spent": tot["spent"], "diff": tot["received"] - tot["spent"],
            "days": [dict(r) for r in days], "categories": [dict(r) for r in cats]}


async def dash_transactions(business_id, start, end, tx_type=None, q=None, limit=500):
    sql = ("SELECT t.id, t.type, t.amount::bigint AS amount, t.occurred_on::text AS date, "
           "COALESCE(c.code, c.name_ru) AS category, t.description, t.is_corrected "
           "FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
           "WHERE t.business_id=$1 AND t.deleted_at IS NULL AND t.occurred_on BETWEEN $2 AND $3")
    args = [business_id, start, end]
    if tx_type in ("income", "expense"):
        args.append(tx_type)
        sql += f" AND t.type=${len(args)}"
    if q:
        args.append(f"%{q}%")
        sql += f" AND (t.description ILIKE ${len(args)} OR t.counterparty ILIKE ${len(args)})"
    args.append(limit)
    sql += f" ORDER BY t.occurred_on DESC, t.id DESC LIMIT ${len(args)}"
    return [dict(r) for r in await _pool.fetch(sql, *args)]


async def dash_update_tx(business_id, tx_id, amount=None, day=None, category=None, description=None):
    async with _pool.acquire() as conn:
        async with conn.transaction():
            tx = await conn.fetchrow(
                "SELECT id, type FROM transactions WHERE id=$1 AND business_id=$2 AND deleted_at IS NULL",
                tx_id, business_id)
            if not tx:
                return False
            cat_id = await _category_id(conn, business_id, tx["type"], category) if category else None
            await conn.execute(
                "UPDATE transactions SET amount=COALESCE($3,amount), occurred_on=COALESCE($4,occurred_on), "
                "category_id=COALESCE($5,category_id), description=COALESCE($6,description) "
                "WHERE id=$1 AND business_id=$2", tx_id, business_id, amount, day, cat_id, description)
    return True


async def dash_delete_tx(business_id, tx_id):
    r = await _pool.execute(
        "UPDATE transactions SET deleted_at=now() WHERE id=$1 AND business_id=$2 AND deleted_at IS NULL",
        tx_id, business_id)
    return r.endswith("1")
