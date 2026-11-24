import os
from fastapi import HTTPException


def price():
    return int(os.getenv("STARTER_PRICE_UZS", "48000"))


async def plan(c, biz):
    r = await c.fetchrow(
        "select paid_until,coalesce(paid_until>now(),false) active,demo from growth.shops where id=$1",
        biz,
    )
    return {
        "plan": "Starter" if r["active"] else "Free",
        "expires": r["paid_until"],
        "price": price(),
        "limit": int(os.getenv("STARTER_VISUAL_LIMIT", "30")) if r["active"] else 5,
        "test": r["demo"],
    }


async def activate(c, biz, invoice, amount, ref, test=False):
    if not ref.strip():
        raise HTTPException(422, "Provider reference required")
    await c.fetchval("select id from growth.shops where id=$1 for update", biz)
    row = await c.fetchrow(
        "select * from growth.invoices where business_id=$1 and id=$2 for update",
        biz,
        invoice,
    )
    if not row or row["amount"] != amount or row["test"] != test:
        raise HTTPException(422, "Invoice mismatch")
    key = ("test:" if test else "merchant:") + ref.strip()
    if row["paid_at"]:
        if row["provider_ref"] == key:
            return await plan(c, biz)
        raise HTTPException(409, "Invoice already settled")
    if await c.fetchval("select 1 from growth.invoices where provider_ref=$1", key):
        raise HTTPException(409, "Transaction already used")
    await c.execute(
        "update growth.invoices set paid_at=now(),provider_ref=$2 where id=$1",
        invoice,
        key,
    )
    await c.execute(
        "update growth.shops set paid_until=greatest(now(),paid_until)+interval '30 days' where id=$1",
        biz,
    )
    return await plan(c, biz)
