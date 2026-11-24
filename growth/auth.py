import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

import db
from .models import Credentials

router = APIRouter(prefix="/growth")
secret = (os.getenv("SESSION_SECRET") or secrets.token_hex(32)).encode()


def cookie(response, name, value, age):
    response.set_cookie(
        name,
        value,
        max_age=age,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE") == "1",
        samesite="lax",
        path="/",
    )


def demo_enabled():
    return os.getenv("GROWTH_DEMO") == "1"


def supabase():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_PUBLISHABLE_KEY")
    if not url or not key:
        raise HTTPException(503, "Supabase Auth is not configured")
    return url.rstrip("/"), {"apikey": key}


async def auth_call(method, path, **kwargs):
    url, headers = supabase()
    headers.update(kwargs.pop("headers", {}))
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.request(
                method, url + "/auth/v1/" + path, headers=headers, **kwargs
            )
        except httpx.HTTPError:
            raise HTTPException(503, "Authentication service unavailable")
    if not r.is_success:
        raise HTTPException(
            401 if r.status_code in (400, 401, 403, 422) else 503,
            "Authentication failed",
        )
    return r.json() if r.content else {}


def session(response, data):
    cookie(response, "growth_access", data["access_token"], int(data["expires_in"]))
    cookie(response, "growth_refresh", data["refresh_token"], 30 * 86400)
    response.delete_cookie("growth_demo")


@router.post("/auth/{action}")
async def signin(action: str, body: Credentials, response: Response):
    if action not in ("login", "signup"):
        raise HTTPException(404)
    data = await auth_call(
        "POST",
        "signup" if action == "signup" else "token?grant_type=password",
        json=body.model_dump(),
    )
    if data.get("access_token"):
        session(response, data)
        return {"signed_in": True}
    return {"confirm_email": True}


@router.post("/refresh")
async def refresh(req: Request, response: Response):
    token = req.cookies.get("growth_refresh")
    if not token:
        raise HTTPException(401)
    session(
        response,
        await auth_call(
            "POST", "token?grant_type=refresh_token", json={"refresh_token": token}
        ),
    )
    return {"ok": True}


@router.post("/logout")
async def logout(req: Request, response: Response):
    access = req.cookies.get("growth_access")
    if access:
        try:
            await auth_call(
                "POST", "logout", headers={"Authorization": "Bearer " + access}
            )
        except HTTPException:
            pass
    for name in ("growth_access", "growth_refresh", "growth_demo"):
        response.delete_cookie(name)
    return {"ok": True}


@router.get("/config")
async def config():
    return {"demo": demo_enabled(), "auth": bool(os.getenv("SUPABASE_PUBLISHABLE_KEY"))}


@router.post("/demo")
async def demo(response: Response):
    if not demo_enabled():
        raise HTTPException(404)
    subject = uuid4()
    payload = f"{subject}.{int(time.time()) + 86400}"
    sig = hmac.digest(secret, payload.encode(), "sha256").hex()
    cookie(response, "growth_demo", payload + "." + sig, 86400)
    response.delete_cookie("growth_access")
    response.delete_cookie("growth_refresh")
    return {"ok": True}


async def identity(req):
    demo = req.cookies.get("growth_demo", "")
    if demo_enabled() and demo:
        try:
            sub, end, sig = demo.split(".")
            if int(end) > time.time() and hmac.compare_digest(
                sig, hmac.digest(secret, f"{sub}.{end}".encode(), "sha256").hex()
            ):
                return UUID(sub), "", True
        except ValueError:
            pass
    access = req.cookies.get("growth_access")
    if not access:
        raise HTTPException(401)
    user = await auth_call("GET", "user", headers={"Authorization": "Bearer " + access})
    return UUID(user["id"]), user.get("email", "").lower(), False


async def context(conn, key, value):
    await conn.execute("select set_config($1,$2,true)", "growth." + key, str(value))


@asynccontextmanager
async def workspace(req, roles=("owner", "finance", "marketing")):
    sub, _, _ = await identity(req)
    async with db._pool.acquire() as conn, conn.transaction():
        await context(conn, "subject", sub)
        rows = await conn.fetch(
            "select * from growth.members where subject=$1 order by role='owner' desc,business_id",
            sub,
        )
        wanted = req.headers.get("x-business-id") or req.query_params.get("workspace")
        member = next(
            (r for r in rows if not wanted or str(r["business_id"]) == wanted), None
        )
        if not member:
            raise HTTPException(404, "Workspace not found")
        biz = member["business_id"]
        await context(conn, "business", biz)
        if member["role"] not in roles:
            raise HTTPException(403)
        yield conn, biz, member["role"], sub
