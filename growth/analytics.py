"""Workspace activity counts. Stores daily totals without visitor identifiers."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request

from .auth import workspace

router = APIRouter(prefix="/growth/analytics")
logger = logging.getLogger(__name__)


async def record(req, event):
    async with workspace(req) as (c, biz, *_):
        await c.execute(
            """insert into growth.analytics_daily(business_id,event) values($1,$2)
            on conflict(business_id,day,event) do update
            set count=growth.analytics_daily.count+1""",
            biz,
            event,
        )


@router.post("/view")
async def view(req: Request):
    await record(req, "page_view")
    return {"ok": True}


@router.get("")
async def report(req: Request, days: int = Query(default=30, ge=1, le=90)):
    async with workspace(req, ("owner",)) as (c, biz, *_):
        today = datetime.now(ZoneInfo("Asia/Tashkent")).date()
        start = today - timedelta(days=days - 1)
        rows = await c.fetch(
            """select day,event,count from growth.analytics_daily
            where business_id=$1 and day between $2 and $3 order by day,event""",
            biz,
            start,
            today,
        )
        daily = {start + timedelta(days=i): {} for i in range(days)}
        totals = {}
        for row in rows:
            daily[row["day"]][row["event"]] = row["count"]
            totals[row["event"]] = totals.get(row["event"], 0) + row["count"]
        return {
            "days": days,
            "timezone": "Asia/Tashkent",
            "totals": totals,
            "daily": [{"day": day, "events": events} for day, events in daily.items()],
        }


async def track_action(req, call_next):
    response = await call_next(req)
    path = req.url.path
    event = None
    if req.method in ("POST", "PUT") and 200 <= response.status_code < 300:
        if path == "/growth/products" or path.startswith("/growth/products/"):
            event = "product_saved"
        elif path == "/growth/assistant":
            event = "assistant_used"
        elif path == "/growth/orders":
            event = "order_created"
        elif path == "/growth/journal":
            event = "entry_recorded"
        elif path.startswith("/growth/visuals/"):
            event = "visual_created"
    if event:
        try:
            # A telemetry failure must not hide a successfully completed operation.
            import asyncio

            async with asyncio.timeout(2):
                await record(req, event)
        except Exception:
            logger.warning("Could not record workspace event %s", event)
    return response
