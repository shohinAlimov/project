"""Operator-only provisioning. Use an administrative database URL on a trusted machine."""

import argparse
import asyncio
import os
from uuid import UUID

import asyncpg
from aiogram import Bot
from dotenv import load_dotenv

from . import billing
from .auth import context


async def run(a):
    load_dotenv()
    c = await asyncpg.connect(
        os.environ.get("GROWTH_ADMIN_DATABASE_URL") or os.environ["DATABASE_URL"],
        statement_cache_size=0,
    )
    try:
        async with c.transaction():
            await context(c, "business", a.business)
            if not await c.fetchval(
                "select 1 from growth.shops where id=$1 and not demo", a.business
            ):
                raise ValueError("Choose a real pilot workspace")
            if a.command == "connect":
                async with Bot(os.environ["BOT_TOKEN"]).context() as bot:
                    link = await bot.get_business_connection(a.connection)
                if (
                    not link.is_enabled
                    or link.user.id != a.owner
                    or not link.rights
                    or not link.rights.can_reply
                ):
                    raise ValueError(
                        "Telegram owner, connection status or reply permission does not match"
                    )
                linked = await c.fetchval(
                    """insert into growth.connections(connection,business_id,telegram_owner) values($1,$2,$3)
                    on conflict(connection) do update set enabled=true where growth.connections.business_id=excluded.business_id
                    and growth.connections.telegram_owner=excluded.telegram_owner returning business_id""",
                    a.connection,
                    a.business,
                    a.owner,
                )
                if not linked:
                    raise ValueError("Connection already assigned")
            else:
                await billing.activate(c, a.business, a.invoice, a.amount, a.reference)
        print("Confirmed")
    finally:
        await c.close()


def main():
    p = argparse.ArgumentParser()
    cmds = p.add_subparsers(dest="command", required=True)
    conn = cmds.add_parser("connect")
    conn.add_argument("business", type=UUID)
    conn.add_argument("connection")
    conn.add_argument("owner", type=int)
    inv = cmds.add_parser("activate")
    inv.add_argument("business", type=UUID)
    inv.add_argument("invoice", type=UUID)
    inv.add_argument("amount", type=int)
    inv.add_argument("reference")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
