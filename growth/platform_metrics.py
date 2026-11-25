"""Server-side page views and daily browser counts for the development team."""

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import db
from .auth import secret

logger = logging.getLogger(__name__)
COOKIE = "growth_visitor"


def visitor_cookie(value):
    try:
        token, signature = value.split(".")
        expected = hmac.digest(secret, token.encode(), "sha256").hex()
        if len(token) == 32 and hmac.compare_digest(signature, expected):
            return value
    except ValueError:
        pass
    token = secrets.token_hex(16)
    return token + "." + hmac.digest(secret, token.encode(), "sha256").hex()


async def track_visit(req, call_next):
    response = await call_next(req)
    if req.method != "GET" or req.url.path != "/" or response.status_code != 200:
        return response
    agent = req.headers.get("user-agent", "").lower()
    if any(
        word in agent for word in ("bot", "crawler", "spider", "headless", "uptime")
    ):
        return response
    visitor = visitor_cookie(req.cookies.get(COOKIE, ""))
    day = datetime.now(ZoneInfo("Asia/Dushanbe")).date()
    digest = hmac.digest(secret, f"{day}:{visitor}".encode(), "sha256").hex()
    try:
        async with asyncio.timeout(2):
            async with db._pool.acquire() as c:
                await c.execute("select growth.record_site_visit($1,$2)", day, digest)
    except Exception:
        logger.warning("Could not record a site visit")
        return response
    if visitor != req.cookies.get(COOKIE):
        response.set_cookie(
            COOKIE,
            visitor,
            max_age=30 * 86400,
            httponly=True,
            secure=os.getenv("COOKIE_SECURE") == "1",
            samesite="lax",
        )
    return response
