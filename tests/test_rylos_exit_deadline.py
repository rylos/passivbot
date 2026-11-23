"""4RSI exit deadline (Marco, 21/11).

Once the 4RSI exit starts, a long still open after 60 s is closed in full at
market whatever the signal and the price. On 20/11 06:53 the ry-hl maker exit
never filled, was withdrawn when the bid fell back under the exit floor, and
the position stayed open down to the HSL.
"""

from types import SimpleNamespace

import pytest

from live import executor
from passivbot import Passivbot

from test_orchestrator_json_api import compute
from test_rylos_keep_entries_trailing_pending import _long_input, _rylos_bp

SYMBOL = "HYPE/USDC:USDC"


def _signal(force):
    sig = {
        "osc_4rsi": 0.0,
        "stoch_k": 50.0,
        "candle_color": -1.0,
        "drop_from_high_1m": 0.0,
    }
    if force is not None:
        sig["exit_force_market"] = force
    return sig


def _panic_closes(out):
    return [o for o in out["orders"] if o["order_type"] == "close_panic_long"]


# ---------------------------------------------------------------- Rust


@pytest.mark.parametrize("force", [None, False])
def test_no_flag_no_forced_close(force):
    import passivbot_rust as pbr

    out = compute(pbr, _long_input(long_bp=_rylos_bp(crash_stop_pct=0.0), rylos_signal=_signal(force)))

    assert _panic_closes(out) == []


def test_flag_closes_whole_position_at_market_below_entry():
    """Bid at the position price: no exit signal, no gain, still a full market close."""
    import passivbot_rust as pbr

    out = compute(pbr, _long_input(long_bp=_rylos_bp(crash_stop_pct=0.0), rylos_signal=_signal(True)))

    closes = _panic_closes(out)
    assert len(closes) == 1
    assert closes[0]["qty"] == pytest.approx(-1.0)
    assert closes[0]["execution_type"] == "market"
    assert [o for o in out["orders"] if o["order_type"].startswith("entry_")] == []


def test_flag_without_position_does_nothing():
    import passivbot_rust as pbr

    out = compute(
        pbr,
        _long_input(pos_size=0.0, long_bp=_rylos_bp(crash_stop_pct=0.0), rylos_signal=_signal(True)),
    )

    assert _panic_closes(out) == []


# ---------------------------------------------------------------- executor


def _exit_order(**extra):
    return {
        "symbol": SYMBOL,
        "side": "sell",
        "position_side": "long",
        "qty": -1.0,
        "price": 100.0,
        "reduce_only": True,
        "type": "limit",
        "custom_id": "0x0a1b" + "c" * 28,
        "pb_order_type": "close_panic_long",
        **extra,
    }


def _exec_bot():
    return SimpleNamespace(
        bp=lambda pside, key, symbol=None: True,
        open_orders={},
        _maker_exit_taker_fee_gap=0.0,
    )


def test_executor_records_exit_start_once(monkeypatch):
    bot = _exec_bot()
    monkeypatch.setattr(executor, "_is_rylos_maker_exit", lambda b, o: o.get("pb_order_type") == "close_panic_long")
    monkeypatch.setattr(executor, "_utc_ms", lambda: 1_000)
    executor._apply_maker_exit_taker_cap(bot, [], [_exit_order()])
    monkeypatch.setattr(executor, "_utc_ms", lambda: 5_000)
    executor._apply_maker_exit_taker_cap(bot, [], [_exit_order()])

    assert bot._rylos_exit_started == {SYMBOL: 1_000}


def test_executor_ignores_buys_and_other_orders(monkeypatch):
    bot = _exec_bot()
    monkeypatch.setattr(executor, "_is_rylos_maker_exit", lambda b, o: o.get("pb_order_type") == "close_panic_long")
    monkeypatch.setattr(executor, "_utc_ms", lambda: 1_000)
    executor._apply_maker_exit_taker_cap(
        bot,
        [],
        [_exit_order(side="buy"), _exit_order(pb_order_type="entry_grid_normal_long")],
    )

    assert getattr(bot, "_rylos_exit_started", {}) == {}


# ---------------------------------------------------------------- deadline


def _deadline_bot(size, started_at):
    bot = SimpleNamespace(positions={SYMBOL: {"long": {"size": size, "price": 100.0}}})
    if started_at is not None:
        bot._rylos_exit_started = {SYMBOL: started_at}
    return bot


def _apply(bot, signals, now, monkeypatch):
    import passivbot as pb_mod

    monkeypatch.setattr(pb_mod, "utc_ms", lambda: now)
    Passivbot._apply_rylos_exit_deadline(bot, signals)
    return signals


def test_deadline_not_reached_keeps_signal(monkeypatch):
    bot = _deadline_bot(1.0, 0)
    sig = _signal(None)
    out = _apply(bot, {SYMBOL: sig}, executor.RYLOS_EXIT_FORCE_MARKET_MS - 1, monkeypatch)

    assert "exit_force_market" not in out[SYMBOL]
    assert bot._rylos_exit_started == {SYMBOL: 0}


def test_deadline_reached_forces_market(monkeypatch):
    bot = _deadline_bot(1.0, 0)
    out = _apply(bot, {SYMBOL: _signal(None)}, executor.RYLOS_EXIT_FORCE_MARKET_MS, monkeypatch)

    assert out[SYMBOL]["exit_force_market"] is True


def test_deadline_without_fresh_signal_still_forces(monkeypatch):
    bot = _deadline_bot(1.0, 0)
    out = _apply(bot, {SYMBOL: None}, executor.RYLOS_EXIT_FORCE_MARKET_MS, monkeypatch)

    assert out[SYMBOL]["exit_force_market"] is True
    # neutral values: no new entry can open
    assert out[SYMBOL]["stoch_k"] == 100.0


def test_flat_position_forgets_start(monkeypatch):
    bot = _deadline_bot(0.0, 0)
    out = _apply(bot, {SYMBOL: _signal(None)}, executor.RYLOS_EXIT_FORCE_MARKET_MS * 5, monkeypatch)

    assert "exit_force_market" not in out[SYMBOL]
    assert bot._rylos_exit_started == {}


def test_no_start_no_change(monkeypatch):
    bot = _deadline_bot(1.0, None)
    sig = _signal(None)
    out = _apply(bot, {SYMBOL: sig}, 10**12, monkeypatch)

    assert out[SYMBOL] is sig


# ---------------------------------------------------------------- no overlap

from test_order_churn_cancel_first import _PlanBot, _order, execution_shell  # noqa: E402,F401


@pytest.mark.asyncio
async def test_forced_market_waits_until_resting_limit_exit_is_cancelled(execution_shell):
    """The resting limit exit and the forced market close never coexist: the
    cancel-first barrier sends the cancel, holds the market create, and only
    the next plan (limit gone) sends it."""
    bot = _PlanBot()
    resting_limit = _order("resting_limit_exit", panic=True)
    forced_market = _order("forced_market", panic=True, execution_type="market")

    await executor.execute_order_plan(bot, [resting_limit], [forced_market])
    assert bot.cancelled == [resting_limit]
    assert bot.created == []

    bot.cancelled = []
    await executor.execute_order_plan(bot, [], [forced_market])
    assert bot.cancelled == []
    assert bot.created == [forced_market]


# ---------------------------------------------------------------- Bybit resting exit (23/11)


def _venue_cid(pb_type: str) -> str:
    import passivbot_rust as pbr

    return "0x%04x" % int(pbr.order_type_snake_to_id(pb_type)) + "a" * 26


def _bybit_raw_open_order(price: float) -> dict:
    """Shape of a Bybit open order as ccxt returns it: no custom_id, no
    pb_order_type, the client id only as clientOrderId / info.orderLinkId."""
    cid = _venue_cid("close_panic_long")
    return {
        "id": "bybit-1",
        "symbol": SYMBOL,
        "side": "sell",
        "position_side": "long",
        "qty": 1.0,
        "price": price,
        "reduceOnly": True,
        "type": "limit",
        "clientOrderId": cid,
        "info": {"orderLinkId": cid},
    }


@pytest.mark.parametrize("where", ["top", "info"])
def test_pb_type_read_from_bybit_client_id(where):
    order = _bybit_raw_open_order(100.0)
    if where == "info":
        del order["clientOrderId"]
    assert executor._order_pb_type(order) == "close_panic_long"


def test_bybit_taker_cap_survives_a_cycle_without_new_exit(monkeypatch):
    """23/11 04:25 ry-bybit: cycles that only cancel entries alternated with
    exit amends; the resting exit was not recognised, the episode restarted
    from the current price each time and the cap never fired."""
    bot = SimpleNamespace(
        bp=lambda pside, key, symbol=None: True,
        open_orders={},
        _maker_exit_taker_fee_gap=0.00035,
    )
    monkeypatch.setattr(executor, "_is_rylos_maker_exit", lambda b, o: o.get("pb_order_type") == "close_panic_long")
    monkeypatch.setattr(executor, "_utc_ms", lambda: 1_000)
    executor._apply_maker_exit_taker_cap(bot, [], [_exit_order(price=100.0)])
    # entry-cancel-only cycle: only the resting (raw Bybit) exit is visible
    bot.open_orders = {SYMBOL: [_bybit_raw_open_order(100.0)]}
    monkeypatch.setattr(executor, "_utc_ms", lambda: 5_000)
    executor._apply_maker_exit_taker_cap(bot, [], [])
    assert bot._maker_exit_episodes[SYMBOL]["first"] == 100.0
    # next exit 0.11% lower: the cap fires
    new = _exit_order(price=99.89)
    monkeypatch.setattr(executor, "_utc_ms", lambda: 13_000)
    executor._apply_maker_exit_taker_cap(bot, [], [new])
    assert new.get("_rylos_taker") is True
