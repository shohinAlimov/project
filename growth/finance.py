from fastapi import HTTPException
from .models import Entry


async def orders(c, biz):
    return await c.fetch(
        """select o.*,p.name product,o.total-coalesce(sum(j.amount),0)::bigint balance
        from growth.orders o join growth.products p on p.id=o.product_id
        left join growth.journal j on j.business_id=o.business_id and j.order_id=o.id
        where o.business_id=$1 group by o.id,p.name order by due nulls last,o.id""",
        biz,
    )


async def record(c, biz, e: Entry):
    # One lock per shop also serializes different receipts claiming the same bank reference.
    await c.fetchval("select id from growth.shops where id=$1 for update", biz)
    prior = await c.fetchval(
        "select id from growth.journal where business_id=$1 and (request_id=$2 or receipt_id=$3)",
        biz,
        e.request_id,
        e.receipt_id,
    )
    if prior:
        return prior
    if e.receipt_id:
        kind = await c.fetchval(
            "select kind from growth.receipts where business_id=$1 and id=$2",
            biz,
            e.receipt_id,
        )
        if kind != e.kind or not e.verified:
            raise HTTPException(422, "Review the receipt before saving")
    ref = e.reference.strip().casefold() or None
    if ref and await c.fetchval(
        "select id from growth.journal where business_id=$1 and kind=$2 and reference=$3",
        biz,
        e.kind,
        ref,
    ):
        raise HTTPException(409, "Reference already recorded")
    if bool(e.order_id) != bool(e.payment_type) or (e.order_id and e.kind != "income"):
        raise HTTPException(422, "Invalid order payment")
    if e.order_id:
        balance = await c.fetchval(
            """select total-(select coalesce(sum(amount),0) from growth.journal j
             where j.business_id=o.business_id and j.order_id=o.id)
             from growth.orders o where business_id=$1 and id=$2""",
            biz,
            e.order_id,
        )
        if balance is None:
            raise HTTPException(404)
        if e.amount > balance or (e.payment_type == "final" and e.amount != balance):
            raise HTTPException(422, "Amount does not match the remaining balance")
    return await c.fetchval(
        """insert into growth.journal(business_id,request_id,kind,amount,day,category,note,reference,order_id,receipt_id,payment_type)
        values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) returning id""",
        biz,
        e.request_id,
        e.kind,
        e.amount,
        e.day,
        e.category,
        e.note,
        ref,
        e.order_id,
        e.receipt_id,
        e.payment_type,
    )


async def figures(c, biz, monthly=False):
    period = (
        " and day between date_trunc('month',now() at time zone 'Asia/Tashkent')::date and (now() at time zone 'Asia/Tashkent')::date"
        if monthly
        else ""
    )
    by = await c.fetch(
        "select kind,category,sum(amount)::bigint total from growth.journal where business_id=$1"
        + period
        + " group by kind,category order by total desc",
        biz,
    )
    due = [dict(o) for o in await orders(c, biz) if o["balance"] > 0]
    return {
        "income": sum(r["total"] for r in by if r["kind"] == "income"),
        "expense": sum(r["total"] for r in by if r["kind"] == "expense"),
        "outstanding": sum(r["balance"] for r in due),
        "due": [
            {"customer": r["customer"], "balance": r["balance"], "due": r["due"]}
            for r in due
        ],
        "expenses": [dict(r) for r in by if r["kind"] == "expense"],
    }
