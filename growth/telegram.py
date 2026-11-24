"""Updates from Telegram Business use their own router and explicit connection allowlist."""

import json
import logging
import os
import re

from aiogram import Router
from aiogram.types import BusinessConnection, Message
from fastapi import HTTPException

import db
from .auth import context
from .media import MAX_BYTES, completion, receive

router = Router()
PATTERNS = {
    "handoff": r"исключени|отсроч|рассроч|в долг|istisno|keyin to.la|жалоб|вернит|возврат|не приш|повреж|испорт|индивидуаль|особый|на заказ|свой дизайн|скидк|shikoyat|qaytar|individual|maxsus|chegirma|custom|complaint",
    "catalog": r"каталог|ассортимент|какие товары|какие торты|mahsulotlar|qanday tortlar|katalog",
    "description": r"состав|описани|tarkib|tavsif",
    "price": r"қанча|нарх|сколько|цен[аыу]|стоимост|стоит|narx|qancha|nech[aip]|price",
    "delivery": r"етказ|достав|самовывоз|yetkaz|olib ket|delivery",
    "payment": r"тўлов|оплат|платить|карт[ау]|to.lov|to.la|payment",
    "variants": r"дизайн|вариант|цвет|dizayn|variant|rang|design",
    "availability": r"борми|мавжуд|наличи|доступ|есть ли|mavjud|bormi|available",
    "lead_time": r"срок|когда готов|muddat|qachon|tayyor",
}


def norm(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def language(message, default):
    if re.search(
        r"[ўқғҳ]|қанча|нарх|борми|narx|qancha|bormi|yetkaz|to.lov|qachon|salom|necha",
        message,
        re.I,
    ):
        return "uz"
    return "ru" if re.search(r"[а-яё]", message, re.I) else default


async def answer(c, biz, message, shop):
    lang = language(message, shop["language"])
    products = await c.fetch("select * from growth.products where business_id=$1", biz)
    faqs = await c.fetch(
        "select * from growth.faqs where business_id=$1 and language=$2", biz, lang
    )
    text = norm(message)
    matches = [p for p in products if norm(p["name"]) in text]
    product = matches[0] if len(matches) == 1 else None
    topic = next(
        (key for key, pattern in PATTERNS.items() if re.search(pattern, message, re.I)),
        None,
    )
    faq = next((f for f in faqs if norm(f["question"]) == text), None)
    if topic == "handoff" or len(matches) > 1:
        return "handoff", product, None
    if (
        (
            not topic
            or (
                not product
                and topic in ("price", "availability", "variants", "lead_time")
            )
        )
        and not faq
        and os.getenv("OPENAI_API_KEY")
        and not shop["demo"]
    ):
        try:
            intent = await completion(
                "Classify only. Return JSON with topic (price,delivery,payment,variants,availability,lead_time,faq,handoff), product_id and faq_id from supplied rows or null. Complaints, discounts, custom work, ambiguity and exceptions => handoff. Never write the answer.",
                json.dumps(
                    {
                        "message": message,
                        "products": [[str(p["id"]), p["name"]] for p in products],
                        "faqs": [[str(f["id"]), f["question"]] for f in faqs],
                    },
                    ensure_ascii=False,
                ),
                True,
            )
            topic = intent.get("topic")
            product = next(
                (p for p in products if str(p["id"]) == intent.get("product_id")),
                product,
            )
            if topic == "faq":
                faq = next(
                    (f for f in faqs if str(f["id"]) == intent.get("faq_id")), None
                )
        except (ValueError, KeyError, AttributeError, HTTPException):
            pass
    result = None
    if topic == "handoff":
        return topic, product, None
    if faq and "{price}" in faq["answer"] and product:
        return (
            "faq",
            product,
            faq["answer"].replace("{price}", f"{product['price']:,}".replace(",", " ")),
        )
    if product and topic == "price":
        result = f"{product['name']} — {product['price']:,} UZS".replace(",", " ")
    elif faq:
        result = faq["answer"]
        if "{price}" in result:
            result = (
                result.replace("{price}", str(product["price"])) if product else None
            )
        topic = "faq"
    elif topic == "catalog":
        lines = [
            f"{p['name']} — {p['price']:,} UZS".replace(",", " ") for p in products[:12]
        ]
        result = "\n".join(lines)
    elif product and topic == "description" and lang == shop["language"]:
        result = json.loads(product["details"]).get("description")
    elif topic in ("delivery", "payment"):
        profile = json.loads(shop["profile"])
        result = profile.get(topic if lang == shop["language"] else topic + "_other")
        if topic == "payment":
            links = [
                profile.get(provider)
                for provider in ("payme", "click")
                if profile.get(provider)
            ]
            result = "\n".join(filter(None, [result, *links]))
    elif product and topic in ("variants", "availability", "lead_time"):
        result = json.loads(product["details"]).get(
            topic if lang == shop["language"] else topic + "_other"
        )
    return topic or "handoff", product, result or None


@router.business_connection()
async def connection_changed(event: BusinessConnection):
    # Unknown connections cannot enroll themselves.
    async with db._pool.acquire() as c, c.transaction():
        await context(c, "connection", event.id)
        row = await c.fetchrow(
            "select * from growth.connections where connection=$1", event.id
        )
        if not row and event.is_enabled:
            logging.getLogger("uvicorn.error").info(
                "Pending Business connection %s for Telegram owner %s",
                event.id,
                event.user.id,
            )
        if row and row["telegram_owner"] == event.user.id:
            await context(c, "business", row["business_id"])
            await c.execute(
                "update growth.connections set enabled=$2 where connection=$1",
                event.id,
                event.is_enabled and bool(event.rights and event.rights.can_reply),
            )


async def handle(
    c, connection, chat, message_id, sender, text, load_image, send, from_bot=False
):
    await context(c, "connection", connection)
    mapping = await c.fetchrow(
        "select * from growth.connections where connection=$1 and enabled", connection
    )
    if not mapping or from_bot:
        return
    biz = mapping["business_id"]
    await context(c, "business", biz)
    # Serialize handoffs, receipts and web resume/pause for this chat.
    row = await c.fetchrow(
        """insert into growth.chats(business_id,connection,chat) values($1,$2,$3)
        on conflict(business_id,connection,chat) do update set updated_at=now() returning *""",
        biz,
        connection,
        chat,
    )
    tracked = await c.fetchval(
        """insert into growth.events(business_id,connection,chat,message_id) values($1,$2,$3,$4)
        on conflict do nothing returning message_id""",
        biz,
        connection,
        chat,
        message_id,
    )
    if tracked is None:
        return
    if sender == mapping["telegram_owner"]:
        await c.execute("update growth.chats set paused=true where id=$1", row["id"])
        return
    shop = await c.fetchrow("select * from growth.shops where id=$1", biz)
    if load_image:
        data = await load_image()
        if data:
            await receive(c, biz, data, "income", str(chat), shop["demo"])
        else:
            await c.execute(
                "update growth.chats set paused=true,summary=$2 where id=$1",
                row["id"],
                "📎",
            )
        return
    if not text:
        await c.execute(
            "update growth.chats set paused=true,summary=$2 where id=$1",
            row["id"],
            "📎",
        )
        return
    if row["paused"]:
        reason = row["summary"].partition("\n")[0]
        latest = " ".join(text.split())[:240]
        await c.execute(
            "update growth.chats set summary=$2 where id=$1",
            row["id"],
            "\n".join(filter(None, (reason, latest))),
        )
        return
    topic, product, reply = await answer(c, biz, text[:2000], shop)
    await c.execute(
        """insert into growth.topics(business_id,topic,product) values($1,$2,$3)
        on conflict(business_id,topic,product) do update set count=growth.topics.count+1""",
        biz,
        topic if topic in (*PATTERNS, "faq") else "handoff",
        product["name"] if product else "",
    )
    if reply:
        await send(reply)
    else:
        await c.execute(
            "update growth.chats set paused=true,summary=$2 where id=$1",
            row["id"],
            text[:240],
        )


@router.business_message()
async def business_message(m: Message):
    if not m.business_connection_id or not m.from_user:
        return
    photo = (
        m.photo[-1]
        if m.photo
        else m.document
        if m.document and (m.document.mime_type or "").startswith("image/")
        else None
    )

    async def download():
        if photo.file_size and photo.file_size > MAX_BYTES:
            return None
        stream = await m.bot.download(photo)
        return stream.read(MAX_BYTES + 1) if stream else None

    async def send(text):
        await m.bot.send_message(
            chat_id=m.chat.id,
            business_connection_id=m.business_connection_id,
            text=text,
        )

    async with db._pool.acquire() as c, c.transaction():
        await handle(
            c,
            m.business_connection_id,
            m.chat.id,
            m.message_id,
            m.from_user.id,
            m.text,
            download if photo else None,
            send,
            bool(m.sender_business_bot) or m.from_user.is_bot,
        )


async def pilot_polling():
    """A separate test token can run Business updates without legacy database privileges.
    Advance the offset only after a successful commit. Transient failures are retried.
    """
    import asyncio
    import logging
    from aiogram import Bot
    from aiogram.methods import GetUpdates
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

    async with Bot(os.environ["BOT_TOKEN"]).context() as bot:
        offset = None
        while True:
            updates = await bot(
                GetUpdates(
                    offset=offset,
                    timeout=25,
                    allowed_updates=["business_connection", "business_message"],
                )
            )
            for u in updates:
                delay = 1
                while True:
                    try:
                        if u.business_connection:
                            await connection_changed(u.business_connection)
                        if u.business_message:
                            await business_message(u.business_message.as_(bot))
                        break
                    except (
                        TelegramForbiddenError,
                        TelegramBadRequest,
                        HTTPException,
                    ) as error:
                        m = u.business_message
                        if not m or (
                            isinstance(error, HTTPException)
                            and error.status_code >= 500
                        ):
                            raise
                        # The incoming request still needs an owner when Telegram refuses a reply
                        # or the media was invalid. Persist that handoff before acknowledging.
                        async with db._pool.acquire() as c, c.transaction():
                            await context(c, "connection", m.business_connection_id)
                            biz = await c.fetchval(
                                "select business_id from growth.connections where connection=$1 and enabled",
                                m.business_connection_id,
                            )
                            if biz:
                                await context(c, "business", biz)
                                await c.execute(
                                    """insert into growth.chats(business_id,connection,chat,paused,summary)
                                    values($1,$2,$3,true,$4) on conflict(business_id,connection,chat)
                                    do update set paused=true,summary=excluded.summary,updated_at=now()""",
                                    biz,
                                    m.business_connection_id,
                                    m.chat.id,
                                    (m.text or "📎")[:240],
                                )
                        break
                    except Exception:
                        logging.warning(
                            "Business update %s will be retried", u.update_id
                        )
                        await asyncio.sleep(delay)
                        delay = min(30, delay * 2)
                offset = u.update_id + 1
