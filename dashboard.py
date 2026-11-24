"""Web Dashboard backend (FastAPI). Run: python dashboard.py  ->  http://localhost:8000"""
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import db

load_dotenv()
BASE = Path(__file__).parent
SECRET = (os.getenv("SESSION_SECRET") or secrets.token_hex(32)).encode()
COOKIE, TTL = "ba_session", 30 * 24 * 3600
attempts: dict = {}


def sign(user_id: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"u": user_id, "e": int(time.time()) + TTL}).encode()).decode()
    return payload + "." + hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()


def unsign(token: str):
    try:
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data["u"] if data["e"] > time.time() else None
    except Exception:
        return None


@asynccontextmanager
async def lifespan(app):
    await db.init()
    yield
    await db.close()


app = FastAPI(lifespan=lifespan)


async def current(request: Request):
    uid = unsign(request.cookies.get(COOKIE, ""))
    biz = await db.business_of_user(uid) if uid else None
    if not biz:
        raise HTTPException(401)
    return biz


def period(start: Optional[str], end: Optional[str]):
    today = date.today()
    try:
        s = date.fromisoformat(start) if start else today.replace(day=1)
        e = date.fromisoformat(end) if end else today
    except ValueError:
        raise HTTPException(400, "bad date")
    return s, e


class Login(BaseModel):
    code: str


class TxPatch(BaseModel):
    amount: Optional[int] = None
    date: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None


@app.get("/")
async def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/api/login")
async def login(body: Login, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in attempts.get(ip, []) if now - t < 60]
    if len(recent) >= 5:
        raise HTTPException(429, "too many attempts")
    attempts[ip] = recent + [now]
    row = await db.use_link_code(body.code.strip())
    if not row:
        raise HTTPException(401, "bad code")
    response.set_cookie(COOKIE, sign(row["user_id"]), max_age=TTL, httponly=True, samesite="lax",
                        secure=os.getenv("COOKIE_SECURE") == "1")
    return {"ok": True}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
async def me(biz=Depends(current)):
    return {"business": biz["name"], "lang": biz["lang"], "currency": biz["currency"]}


@app.get("/api/summary")
async def summary(start: str = None, end: str = None, biz=Depends(current)):
    s, e = period(start, end)
    return await db.dash_summary(biz["id"], s, e)


@app.get("/api/transactions")
async def transactions(start: str = None, end: str = None, type: str = None, q: str = None,
                       biz=Depends(current)):
    s, e = period(start, end)
    return await db.dash_transactions(biz["id"], s, e, type, q)


@app.patch("/api/transactions/{tx_id}")
async def patch_tx(tx_id: int, body: TxPatch, biz=Depends(current)):
    if body.amount is not None and body.amount <= 0:
        raise HTTPException(400, "amount must be > 0")
    day = None
    if body.date:
        try:
            day = date.fromisoformat(body.date)
        except ValueError:
            raise HTTPException(400, "bad date")
    desc = body.description.strip()[:200] if body.description is not None else None
    cat = body.category.strip()[:80] if body.category else None
    if not await db.dash_update_tx(biz["id"], tx_id, body.amount, day, cat, desc):
        raise HTTPException(404)
    return {"ok": True}


@app.delete("/api/transactions/{tx_id}")
async def delete_tx(tx_id: int, biz=Depends(current)):
    if not await db.dash_delete_tx(biz["id"], tx_id):
        raise HTTPException(404)
    return {"ok": True}


@app.get("/api/export.csv")
async def export(start: str = None, end: str = None, type: str = None, q: str = None, biz=Depends(current)):
    s, e = period(start, end)
    rows = await db.dash_transactions(biz["id"], s, e, type, q, limit=100000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "type", "amount", "category", "description"])
    for r in rows:
        w.writerow([r["date"], r["type"], r["amount"], r["category"], r["description"]])
    data = "\ufeff" + buf.getvalue()  # BOM so Excel reads UTF-8
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=transactions.csv"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
