"""Rule-based parsing of free text. Replace/extend with an AI call later.
Never guesses: if the amount or type is unclear, returns None for it."""
import re
from datetime import date, datetime, timedelta

AMOUNT_RE = re.compile(r"(\d[\d\s.,]*)\s*(млн|миллион\w*|mln|million|тыс\w*|ming|k|к)?(?![\w])", re.I)

INCOME_WORDS = ("получил", "доход", "продал", "продаж", "выручк", "поступлен", "оплатил клиент",
                "daromad", "tushum", "sotdim", "savdo", "oldim", "kirim")
EXPENSE_WORDS = ("потратил", "расход", "купил", "заплатил", "оплатил", "закуп", "аренд",
                 "xarajat", "sarfladim", "sotib oldim", "to‘ladim", "to'ladim", "chiqim", "xarid")

CATEGORIES = {
    "purchases": ("закуп", "товар", "xarid", "tovar", "zakup"),
    "rent": ("аренд", "ijara"),
    "transport": ("такси", "бензин", "транспорт", "benzin", "transport", "taksi"),
    "utilities": ("свет", "газ", "коммунал", "электр", "kommunal", "elektr"),
    "marketing": ("реклам", "reklama", "target"),
    "sales": ("продал", "продаж", "выручк", "sotdim", "savdo"),
}


COUNT_WORDS = ("клиент", "заказ", "покупател", "шт", "mijoz", "buyurtma", "dona", "ta ")


def parse_amount(text: str):
    """Returns the first money-like number; counts (clients, orders) are not money."""
    m = None
    for cand in AMOUNT_RE.finditer(text):
        rest = text[cand.end():cand.end() + 12].lower().strip() + " "
        if not any(rest.startswith(w) for w in COUNT_WORDS):
            m = cand
            break
    if not m:
        return None
    num, unit = m.group(1).strip(), (m.group(2) or "").lower()
    try:
        if unit:
            mult = 1_000_000 if unit.startswith(("млн", "милл", "mln", "mil")) else 1000
            value = float(num.replace(" ", "").replace(",", ".")) * mult
        else:
            value = int(re.sub(r"[\s.,]", "", num))
    except ValueError:
        return None
    value = int(round(value))
    return value if value > 0 else None


def parse_date_strict(text: str):
    text = text.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:  # DD.MM -> current year
        d = datetime.strptime(text, "%d.%m")
        return d.replace(year=date.today().year).date()
    except ValueError:
        return None


def parse(text: str) -> dict:
    low = text.lower()
    kind = None
    inc = any(w in low for w in INCOME_WORDS)
    exp = any(w in low for w in EXPENSE_WORDS)
    if inc and not exp:
        kind = "income"
    elif exp and not inc:
        kind = "expense"

    day = date.today()
    if "вчера" in low or "kecha" in low:
        day -= timedelta(days=1)

    category = None
    for key, words in CATEGORIES.items():
        if any(w in low for w in words):
            category = key
            break
    if kind == "income" and category in ("purchases", "rent", "transport", "utilities", "marketing"):
        category = None
    if kind == "expense" and category == "sales":
        category = None

    return {"type": kind, "amount": parse_amount(text), "date": day, "category": category}
