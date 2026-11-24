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