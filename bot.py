import asyncio
import logging
import os
from datetime import date

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)
from dotenv import load_dotenv

import db
from text_parser import parse, parse_amount, parse_date_strict
from texts import LANGS, cat_label, t

load_dotenv()
router = Router()
MENU_KEYS = ("menu_income", "menu_expense", "menu_summary", "menu_history", "menu_settings", "menu_dashboard")
MENU = {t(l, k): k for l in LANGS for k in MENU_KEYS}


class S(StatesGroup):
    name = State()
    amount = State()
    edit = State()


# ---------- helpers ----------
def ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=a, callback_data=b) for a, b in row] for row in rows])


def kb_menu(lang):
    b = lambda k: KeyboardButton(text=t(lang, k))
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [b("menu_income"), b("menu_expense")],
        [b("menu_summary"), b("menu_history")],
        [b("menu_settings"), b("menu_dashboard")]])


def money(n):
    return f"{n:,}".replace(",", " ") + " UZS"


def fmt_date(iso):
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def card(lang, d):
    sign = "➕" if d["type"] == "income" else "➖"
    return (f"{t(lang, 'check')}\n\n"
            f"{sign} {t(lang, 'type_' + d['type'])}\n"
            f"{t(lang, 'lbl_amount')}: {money(d['amount'])}\n"
            f"{t(lang, 'lbl_date')}: {fmt_date(d['date'])}\n"
            f"{t(lang, 'lbl_category')}: {cat_label(lang, d['category'])}\n"
            f"{t(lang, 'lbl_desc')}: {d['description']}")


async def show_card(msg: Message, lang, d):
    await msg.answer(card(lang, d), reply_markup=ikb([[
        (t(lang, "btn_confirm"), "ok"), (t(lang, "btn_edit"), "edit"),
        (t(lang, "btn_cancel"), "cancel")]]))


async def advance(msg: Message, state: FSMContext, lang):
    """Ask for what is missing (never guess), otherwise show the review card."""
    d = (await state.get_data())["draft"]
    if not d["amount"]:
        await state.set_state(S.amount)
        await msg.answer(t(lang, "ask_amount"))
        return
    if not d["type"]:
        await state.set_state(None)
        await msg.answer(t(lang, "ask_type"), reply_markup=ikb([[
            (t(lang, "btn_income"), "type:income"), (t(lang, "btn_expense"), "type:expense")]]))
        return
    await state.set_state(None)
    if not d["category"]:
        d["category"] = "other_" + d["type"]
        await state.update_data(draft=d)
    await show_card(msg, lang, d)


def recognize_receipt(photo_bytes):
    """TODO: OCR/AI. Return dict with amount/date/seller, or {} if unclear."""
    return {}


# ---------- onboarding ----------
@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    if await db.get_business(m.from_user.id):
        lang = await db.get_lang(m.from_user.id)
        await m.answer(t(lang, "ready"), reply_markup=kb_menu(lang))
        return
    await m.answer("Tilni tanlang / Выберите язык",
                   reply_markup=ikb([[("O‘zbekcha", "lang:uz"), ("Русский", "lang:ru")]]))


@router.callback_query(F.data.startswith("lang:"))
async def pick_lang(c: CallbackQuery, state: FSMContext):
    lang = c.data.split(":")[1]
    await db.set_lang(c.from_user.id, lang)
    await c.answer()
    if await db.get_business(c.from_user.id):
        await c.message.answer(t(lang, "ready"), reply_markup=kb_menu(lang))
    else:
        await state.set_state(S.name)
        await c.message.answer(t(lang, "ask_name"))


@router.message(S.name, F.text)
async def got_name(m: Message, state: FSMContext):
    lang = await db.get_lang(m.from_user.id)
    await db.create_business(m.from_user.id, m.text.strip()[:100])
    await state.clear()
    await m.answer(t(lang, "ready"), reply_markup=kb_menu(lang))


# ---------- dashboard login code ----------
async def send_dash_code(m: Message, lang):
    if not await db.get_business(m.from_user.id):
        await m.answer(t(lang, "need_start"))
        return
    code = await db.create_link_code(m.from_user.id)
    url = os.getenv("DASHBOARD_URL", "http://localhost:8000")
    await m.answer(t(lang, "dash_code").format(code=code, url=url))


@router.message(Command("dashboard"))
async def dashboard_cmd(m: Message):
    await send_dash_code(m, await db.get_lang(m.from_user.id))


# ---------- main menu ----------
@router.message(F.text.in_(set(MENU)))
async def menu(m: Message, state: FSMContext):
    lang = await db.get_lang(m.from_user.id)
    biz = await db.get_business(m.from_user.id)
    if not biz:
        await m.answer(t(lang, "need_start"))
        return
    action = MENU[m.text]
    await state.clear()
    if action in ("menu_income", "menu_expense"):
        kind = "income" if action == "menu_income" else "expense"
        await state.update_data(preset=kind)
        await m.answer(t(lang, "send_income" if kind == "income" else "send_expense"))
    elif action == "menu_summary":
        await m.answer(t(lang, "pick_period"), reply_markup=ikb([[
            (t(lang, "p_day"), "sum:day"), (t(lang, "p_week"), "sum:week"),
            (t(lang, "p_month"), "sum:month")]]))
    elif action == "menu_history":
        rows = await db.history(biz["id"])
        if not rows:
            await m.answer(t(lang, "empty"))
            return
        lines = [t(lang, "history_title")]
        for r in rows:
            sign = "+" if r["type"] == "income" else "−"
            lines.append(f"{fmt_date(r['date'])}  {sign}{money(r['amount'])}  "
                         f"{cat_label(lang, r['category'])}")
        await m.answer("\n".join(lines))
    elif action == "menu_dashboard":
        await send_dash_code(m, lang)
    elif action == "menu_settings":
        await m.answer(t(lang, "settings"),
                       reply_markup=ikb([[("O‘zbekcha", "lang:uz"), ("Русский", "lang:ru")]]))


@router.callback_query(F.data.startswith("sum:"))
async def show_summary(c: CallbackQuery):
    lang = await db.get_lang(c.from_user.id)
    biz = await db.get_business(c.from_user.id)
    await c.answer()
    if not biz:
        return
    period = c.data.split(":")[1]
    inc, exp = await db.summary(biz["id"], period)
    sign = "+" if inc - exp >= 0 else "−"
    text = (f"{t(lang, 'p_' + period)}\n\n"
            f"{t(lang, 'sum_received')}: {money(inc)}\n"
            f"{t(lang, 'sum_spent')}: {money(exp)}\n"
            f"{t(lang, 'sum_diff')}: {sign}{money(abs(inc - exp))}")
    url = os.getenv("DASHBOARD_URL")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "open_dashboard"), url=url)]]) if url else None
    await c.message.answer(text, reply_markup=kb)


# ---------- receipt photo ----------
@router.message(F.photo)
async def photo(m: Message, state: FSMContext):
    lang = await db.get_lang(m.from_user.id)
    if not await db.get_business(m.from_user.id):
        await m.answer(t(lang, "need_start"))
        return
    found = recognize_receipt(None)  # TODO: download photo, run OCR, store Receipt
    draft = {"type": "expense", "amount": found.get("amount"), "date": date.today().isoformat(),
             "category": None, "description": found.get("seller") or "Receipt", "source": "receipt"}
    await state.update_data(draft=draft)
    if not draft["amount"]:
        await m.answer(t(lang, "receipt_manual"))
        await state.set_state(S.amount)
    else:
        await advance(m, state, lang)


# ---------- state handlers (must come before generic text) ----------
@router.message(S.amount, F.text)
async def got_amount(m: Message, state: FSMContext):
    lang = await db.get_lang(m.from_user.id)
    n = parse_amount(m.text)
    if not n:
        await m.answer(t(lang, "bad_value"))
        return
    d = (await state.get_data())["draft"]
    d["amount"] = n
    await state.update_data(draft=d)
    await advance(m, state, lang)


@router.message(S.edit, F.text)
async def got_edit(m: Message, state: FSMContext):
    lang = await db.get_lang(m.from_user.id)
    data = await state.get_data()
    d, field = data["draft"], data["field"]
    if field == "amount":
        v = parse_amount(m.text)
        if not v:
            await m.answer(t(lang, "bad_value"))
            return
        d["amount"] = v
    elif field == "date":
        v = parse_date_strict(m.text)
        if not v:
            await m.answer(t(lang, "bad_value"))
            return
        d["date"] = v.isoformat()
    else:
        d[field] = m.text.strip()[:200]
    await state.update_data(draft=d)
    await state.set_state(None)
    await show_card(m, lang, d)


# ---------- free text -> draft ----------
@router.message(F.text & ~F.text.startswith("/"))
async def free_text(m: Message, state: FSMContext):
    lang = await db.get_lang(m.from_user.id)
    if not await db.get_business(m.from_user.id):
        await m.answer(t(lang, "need_start"))
        return
    data = await state.get_data()
    p = parse(m.text)  # TODO: swap for AI parsing; keep "no guessing" rule
    draft = {"type": p["type"] or data.get("preset"), "amount": p["amount"],
             "date": p["date"].isoformat(), "category": p["category"],
             "description": m.text.strip()[:200], "source": "text"}
    await state.update_data(draft=draft, preset=None)
    await advance(m, state, lang)


# ---------- card actions ----------
@router.callback_query(F.data.startswith("type:"))
async def set_type(c: CallbackQuery, state: FSMContext):
    await c.answer()
    d = (await state.get_data()).get("draft")
    if not d:
        return
    d["type"] = c.data.split(":")[1]
    await state.update_data(draft=d)
    await advance(c.message, state, await db.get_lang(c.from_user.id))


@router.callback_query(F.data.in_({"ok", "ok!"}))
async def confirm(c: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(c.from_user.id)
    biz = await db.get_business(c.from_user.id)
    d = (await state.get_data()).get("draft")
    await c.answer()
    if not d or not biz:
        return
    if c.data == "ok" and await db.find_duplicate(biz["id"], d):
        await c.message.answer(t(lang, "dup_warn"), reply_markup=ikb([[
            (t(lang, "btn_save_anyway"), "ok!"), (t(lang, "btn_cancel"), "cancel")]]))
        return
    await db.add_tx(biz["id"], d)
    await state.update_data(draft=None)
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(t(lang, "saved"))


@router.callback_query(F.data == "cancel")
async def cancel(c: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(c.from_user.id)
    await c.answer()
    await state.update_data(draft=None)
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(t(lang, "cancelled"))


@router.callback_query(F.data == "edit")
async def edit(c: CallbackQuery):
    lang = await db.get_lang(c.from_user.id)
    await c.answer()
    await c.message.answer(t(lang, "edit_what"), reply_markup=ikb([
        [(t(lang, "f_amount"), "edit:amount"), (t(lang, "f_date"), "edit:date")],
        [(t(lang, "f_category"), "edit:category"), (t(lang, "f_desc"), "edit:description")],
        [(t(lang, "f_type"), "edit:type")]]))


@router.callback_query(F.data.startswith("edit:"))
async def edit_field(c: CallbackQuery, state: FSMContext):
    lang = await db.get_lang(c.from_user.id)
    field = c.data.split(":")[1]
    d = (await state.get_data()).get("draft")
    await c.answer()
    if not d:
        return
    if field == "type":
        d["type"] = "expense" if d["type"] == "income" else "income"
        d["category"] = "other_" + d["type"]
        await state.update_data(draft=d)
        await show_card(c.message, lang, d)
        return
    await state.update_data(field=field)
    await state.set_state(S.edit)
    await c.message.answer(t(lang, "ask_value"))


async def run_polling():
    from growth.telegram import pilot_polling, router as business_router
    if os.getenv("BUSINESS_ONLY")=="1":
        return await pilot_polling()
    bot = Bot(os.environ["BOT_TOKEN"])
    dp = Dispatcher(storage=MemoryStorage())
    from growth.uploads import router as upload_router
    dp.include_routers(upload_router, business_router, router)
    try:
        await dp.start_polling(bot, handle_as_tasks=False, handle_signals=False)
    finally:
        # A supervisor can reattach both routers after a transient startup failure.
        for child in (upload_router, business_router, router):
            dp.sub_routers.remove(child)
            child._parent_router = None


async def main():
    logging.basicConfig(level=logging.INFO)
    await db.init()
    try:
        await run_polling()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
