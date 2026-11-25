"""Personal Telegram screenshots delivered to the authenticated workspace's review queue."""

import hashlib
import io
import os
import secrets

from aiogram import Bot, F, Router
from aiogram.types import Message
from fastapi import APIRouter, HTTPException, Request

import db
from .auth import context, workspace
from . import media

router = Router()
api = APIRouter(prefix="/growth/telegram-uploads")


@api.post("/link")
async def link(req: Request):
    if not os.getenv("BOT_TOKEN"):
        raise HTTPException(503, "Telegram bot is not configured")
    token = secrets.token_urlsafe(24)
    async with workspace(req, ("owner", "finance")) as (c, biz, role, sub):
        try:
            async with Bot(os.environ["BOT_TOKEN"]).context() as bot:
                username = (await bot.get_me(request_timeout=10)).username
        except Exception:
            raise HTTPException(503, "Telegram bot is currently unavailable")
        await c.execute(
            """insert into growth.telegram_upload_links(business_id,subject,token_hash,expires)
            values($1,$2,$3,now()+interval '15 minutes') on conflict(business_id,subject)
            do update set token_hash=excluded.token_hash,expires=excluded.expires""",
            biz,
            sub,
            hashlib.sha256(token.encode()).hexdigest(),
        )
    return {"url": f"https://t.me/{username}?start=upload_{token}"}


@api.get("")
async def status(req: Request):
    async with workspace(req, ("owner", "finance")) as (c, biz, role, sub):
        connected = await c.fetchval(
            "select telegram_id is not null from growth.telegram_upload_links where business_id=$1 and subject=$2",
            biz,
            sub,
        )
        return {"connected": bool(connected)}


@api.delete("/link")
async def unlink(req: Request):
    async with workspace(req, ("owner", "finance")) as (c, biz, role, sub):
        await c.execute(
            "delete from growth.telegram_upload_links where business_id=$1 and subject=$2",
            biz,
            sub,
        )
    return {"ok": True}


@router.message(F.chat.type == "private")
async def incoming(message: Message):
    if message.chat.type != "private" or not message.from_user:
        return
    sender = message.from_user.id
    text = message.text or ""
    if text.startswith("/start upload_"):
        digest = hashlib.sha256(
            text.split("upload_", 1)[1].strip().encode()
        ).hexdigest()
        async with db._pool.acquire() as c, c.transaction():
            await c.execute("select pg_advisory_xact_lock($1)", sender)
            await context(c, "telegram_sender", sender)
            await context(c, "telegram_claim", digest)
            row = await c.fetchrow(
                "select * from growth.telegram_upload_links where token_hash=$1 and expires>now() for update",
                digest,
            )
            if not row:
                await message.answer(
                    "Ссылка истекла или уже использована. Создайте новую на сайте. / Havola eskirgan. Saytdan yangisini oling."
                )
                return
            await context(c, "subject", row["subject"])
            await context(c, "business", row["business_id"])
            role = await c.fetchval(
                "select role from growth.members where business_id=$1 and subject=$2",
                row["business_id"],
                row["subject"],
            )
            if role not in ("owner", "finance"):
                return
            other = await c.fetchval(
                "select business_id from growth.telegram_upload_links where telegram_id=$1 and (business_id<>$2 or subject<>$3)",
                sender,
                row["business_id"],
                row["subject"],
            )
            if other:
                await message.answer(
                    "Этот Telegram уже привязан к другому магазину. Отключите его на сайте перед новой привязкой."
                )
                return
            await c.execute(
                "update growth.telegram_upload_links set telegram_id=$1,expires=now() where token_hash=$2",
                sender,
                digest,
            )
        await message.answer(
            "Подключено! Пришлите фото или скриншот чека. Для поступления добавьте подпись «доход», иначе будет черновик расхода. Проверьте результат на сайте в «Финансы».\n\nUlandi! Chek rasmini yuboring. Daromad uchun «daromad» deb yozing. Natijani saytdagi «Moliya» bo‘limida tekshiring."
        )
        return
    async with db._pool.acquire() as c, c.transaction():
        await context(c, "telegram_sender", sender)
        row = await c.fetchrow(
            "select * from growth.telegram_upload_links where telegram_id=$1", sender
        )
        if not row:
            await message.answer(
                "Сначала подключите Telegram на сайте в разделе «Финансы». / Avval saytdagi «Moliya» bo‘limida Telegramni ulang."
            )
            return
        await context(c, "business", row["business_id"])
        await context(c, "subject", row["subject"])
        role = await c.fetchval(
            "select role from growth.members where business_id=$1 and subject=$2",
            row["business_id"],
            row["subject"],
        )
        if role not in ("owner", "finance"):
            return
        asset = message.photo[-1] if message.photo else message.document
        if not asset:
            await message.answer(
                "Отправьте изображение JPG, PNG или WebP. / JPG, PNG yoki WebP rasm yuboring."
            )
            return
        if asset.file_size and asset.file_size > media.MAX_BYTES:
            await message.answer(
                "Максимум 8 МиБ на изображение. / Rasm 8 MiB gacha bo‘lsin."
            )
            return
        data = io.BytesIO()
        await message.bot.download(asset, destination=data)
        caption = (message.caption or "").strip().casefold()
        kind = (
            "income"
            if caption.startswith(("доход", "daromad", "income"))
            else "expense"
        )
        try:
            demo = await c.fetchval(
                "select demo from growth.shops where id=$1", row["business_id"]
            )
            await media.receive(c, row["business_id"], data.getvalue(), kind, demo=demo)
        except HTTPException as error:
            if error.status_code in (413, 415):
                await message.answer(
                    "Нужен JPG, PNG или WebP до 8 МиБ. / JPG, PNG yoki WebP, 8 MiB gacha."
                )
                return
            raise
    await message.answer(
        "Сохранено. Откройте сайт → Финансы → Чеки на проверку. Сверьте сумму, дату и тип операции. / Saqlandi. Saytda Moliya → Tekshiriladigan cheklar bo‘limini oching."
    )
