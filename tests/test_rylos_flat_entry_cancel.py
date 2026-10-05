"""rylos: dopo una chiusura completa le entrate rimaste si cancellano senza
aspettare una lettura del conto per ogni cancel (prima: una per ciclo)."""
import asyncio
from types import SimpleNamespace

import pytest

from live import hsl_revised_live


def _setup(monkeypatch, size, pb_type="entry_grid_normal_long", reduce_only=False):
    from passivbot import Passivbot
    from live import executor
    from test_hsl_revised_runtime import bot as make_bot, quotes, NOW, SYMBOL
    import utils

    monkeypatch.setattr(utils, "utc_ms", lambda: NOW)
    bot = make_bot("unified")
    bot.get_exchange_time = lambda: NOW
    bot.approved_coins_minus_ignored_coins = {"long": {SYMBOL}, "short": set()}
    bot._live_market_snapshot_max_age_ms = lambda: 10_000
    bot._ensure_freshness_ledger().stamp("open_orders", now_ms=NOW - 200)
    bot._request_authoritative_confirmation = Passivbot._request_authoritative_confirmation.__get__(bot)
    bot.positions = {SYMBOL: {"long": {"size": size, "price": 90.0}, "short": {"size": 0.0, "price": 0.0}}}
    instance = hsl_revised_live.owner(bot)
    wave = instance.capture(quotes())
    orders = [
        dict(id=str(i), symbol=SYMBOL, position_side="long", side="buy", qty=1.0,
             price=80.0 - i, type="limit", pb_order_type=pb_type, reduce_only=reduce_only)
        for i in range(4)
    ]
    instance.bind(wave, orders, ())
    calls, records = [], []

    async def connector(*args, **kwargs):
        calls.append(args)
        await asyncio.sleep(0)
        return {"id": "ack"}

    bot.cca = SimpleNamespace(cancel_order=connector)
    bot._emit_execution_connector_call_started_event = lambda **kwargs: None
    monkeypatch.setattr(executor, "record_cancel_connector_admission",
                        lambda bot, order: records.append(order["id"]))
    bot.execute_cancellation = Passivbot.execute_cancellation.__get__(bot)

    async def handle(failures):
        assert not failures

    bot._handle_order_write_failures = handle
    return bot, orders, calls, records


@pytest.mark.asyncio
async def test_flat_entry_cancels_all_go_out_in_one_wave(monkeypatch):
    from exchanges.ccxt_bot import CCXTBot
    from live import executor

    bot, orders, calls, records = _setup(monkeypatch, size=0.0)
    results = await CCXTBot.execute_cancellations(bot, orders)
    assert len(calls) == 4
    assert records == ["0", "1", "2", "3"]
    assert not any(isinstance(r, executor.DeferredOrderCancellation) for r in results)
    # La conferma del conto resta richiesta dopo le scritture.
    assert set(bot._authoritative_pending_confirmations) == {"balance", "positions", "open_orders"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size,pb_type,reduce_only",
    [
        (11.78, "entry_grid_normal_long", False),  # posizione aperta o uscita parziale
        (0.0, "close_panic_long", False),  # non e' un'entrata
        (0.0, "entry_grid_normal_long", True),  # reduce-only
    ],
)
async def test_other_cancels_keep_one_write_per_account_read(monkeypatch, size, pb_type, reduce_only):
    from exchanges.ccxt_bot import CCXTBot
    from live import executor

    bot, orders, calls, records = _setup(monkeypatch, size=size, pb_type=pb_type, reduce_only=reduce_only)
    results = await CCXTBot.execute_cancellations(bot, orders)
    assert len(calls) == 1
    assert records == ["0"]
    assert all(isinstance(r, executor.DeferredOrderCancellation) for r in results[1:])


def test_flat_entry_cancel_needs_known_positions():
    order = dict(symbol="HYPE/USDC:USDC", position_side="long", pb_order_type="entry_grid_normal_long")
    assert not hsl_revised_live._rylos_flat_entry_cancel(SimpleNamespace(positions=None), order)
    assert hsl_revised_live._rylos_flat_entry_cancel(SimpleNamespace(positions={}), order)
