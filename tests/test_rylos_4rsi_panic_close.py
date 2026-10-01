"""Rust output validation for the fork-local rylos 4RSI exit.

The 4RSI exit closes the whole position through Rust's panic-close path while
the side stays in a normal generating mode. Upstream's order-family validation
otherwise rejects a panic close outside panic mode, which would raise
FatalBotException the first time the exit signal fires in production.
"""

import pytest

from passivbot_exceptions import FatalBotException
from live import reconciler

from test_order_churn_gate import (
    SYMBOL,
    _raw_rust_input,
    _raw_rust_order,
    _raw_rust_output_for_long_mode,
)


def _panic_order():
    return _raw_rust_order(
        qty=-1.0,
        order_type="close_panic_long",
        execution_type="limit",
        execution_priority="risk_critical",
        price=99.99,
    )


def _input_with_rylos(enabled: bool, mode: str = "normal"):
    orchestrator_input = _raw_rust_input(long_mode=mode, long_pos_size=1.0)
    for symbol_input in orchestrator_input["symbols"]:
        symbol_input["long"]["bot_params"]["rylos_4rsi_enabled"] = enabled
    return orchestrator_input


@pytest.mark.parametrize("mode", ["normal", "graceful_stop", "tp_only"])
def test_rylos_exit_panic_close_accepted_outside_panic_mode(mode):
    order = _panic_order()
    output = _raw_rust_output_for_long_mode([order], mode)
    if mode == "graceful_stop":
        # A held graceful_stop side generates in normal mode.
        output["diagnostics"]["symbol_states"][0]["long"]["effective_mode"] = "normal"

    assert (
        reconciler.validate_rust_orchestrator_output(
            output,
            {0: SYMBOL},
            _input_with_rylos(True, mode),
        )
        == [order]
    )


def test_panic_close_outside_panic_mode_still_rejected_without_rylos():
    with pytest.raises(FatalBotException, match="order family inconsistent"):
        reconciler.validate_rust_orchestrator_output(
            _raw_rust_output_for_long_mode([_panic_order()], "normal"),
            {0: SYMBOL},
            _input_with_rylos(False),
        )


def test_rylos_does_not_relax_panic_mode_requirements():
    """A rylos side in panic mode must still emit the full-position close."""
    with pytest.raises(FatalBotException, match="missing required full-position panic close"):
        reconciler.validate_rust_orchestrator_output(
            _raw_rust_output_for_long_mode([], "panic"),
            {0: SYMBOL},
            _input_with_rylos(True, "panic"),
        )


def _maker_exit_input(bid, ask):
    orchestrator_input = _raw_rust_input(long_mode="normal", long_pos_size=1.0, bid=bid, ask=ask)
    for symbol_input in orchestrator_input["symbols"]:
        symbol_input["long"]["bot_params"]["rylos_4rsi_enabled"] = True
    return orchestrator_input


@pytest.mark.parametrize(
    "bid, ask, price",
    [
        (99.99, 100.0, 100.0),  # spread di 1 tick: sull'ask
        (99.90, 100.0, 99.99),  # spread largo: un tick sotto l'ask
        (99.99, 100.0, 99.99),  # vecchio prezzo panic (ask - 1 tick) ancora valido
    ],
)
def test_rylos_maker_exit_price_accepted(bid, ask, price):
    order = _raw_rust_order(
        qty=-1.0,
        order_type="close_panic_long",
        execution_type="limit",
        execution_priority="risk_critical",
        price=price,
    )
    assert reconciler.validate_rust_orchestrator_output(
        _raw_rust_output_for_long_mode([order], "normal"),
        {0: SYMBOL},
        _maker_exit_input(bid, ask),
    ) == [order]


def test_rylos_exit_price_above_ask_rejected():
    order = _raw_rust_order(
        qty=-1.0,
        order_type="close_panic_long",
        execution_type="limit",
        execution_priority="risk_critical",
        price=100.01,
    )
    with pytest.raises(FatalBotException, match="panic limit price"):
        reconciler.validate_rust_orchestrator_output(
            _raw_rust_output_for_long_mode([order], "normal"),
            {0: SYMBOL},
            _maker_exit_input(99.99, 100.0),
        )


class _TolBot:
    def live_value(self, key):
        assert key == "order_match_tolerance_pct"
        return 0.005

    exchange = "hyperliquid"


def _order(pb_order_type, price, type_="limit"):
    return {
        "symbol": SYMBOL,
        "side": "sell",
        "position_side": "long",
        "qty": 1.0,
        "price": price,
        "reduce_only": True,
        "type": type_,
        "pb_order_type": pb_order_type,
    }


def test_maker_exit_is_replaced_at_every_new_price():
    old = _order("close_panic_long", 100.00)
    new = _order("close_panic_long", 99.99)
    cancel, create, skipped = reconciler.apply_order_match_tolerance(_TolBot(), [old], [new])
    assert (cancel, create, skipped) == ([old], [new], 0)


def test_other_orders_keep_match_tolerance():
    old = _order("close_grid_long", 100.00)
    new = _order("close_grid_long", 99.99)
    assert reconciler.apply_order_match_tolerance(_TolBot(), [old], [new]) == ([], [], 1)


def test_maker_panic_close_detection():
    from live.order_churn_gate import is_maker_panic_close

    assert is_maker_panic_close(_order("close_panic_long", 100.0))
    assert not is_maker_panic_close(_order("close_panic_long", 100.0, "market"))
    assert not is_maker_panic_close(_order("close_grid_long", 100.0))


@pytest.mark.parametrize(
    "pb_order_type, type_, expected",
    [
        ("close_panic_long", "limit", True),
        ("entry_initial_normal_long", "limit", True),
        ("entry_grid_normal_long", "limit", True),
        ("close_grid_long", "limit", True),
        ("close_panic_long", "market", False),
    ],
)
def test_connectors_send_limit_orders_post_only(pb_order_type, type_, expected):
    from exchanges.bybit import BybitBot
    from exchanges.hyperliquid import HyperliquidBot

    config = {"live": {"time_in_force": "good_till_cancelled"}}
    order = dict(_order(pb_order_type, 100.0, type_), custom_id="x")
    hl = object.__new__(HyperliquidBot)
    hl.config = config
    hl.user_info = {"is_vault": False}
    by = object.__new__(BybitBot)
    by.config = config
    assert (hl._build_order_params(order)["timeInForce"] == "Alo") is expected
    assert (by._build_order_params(order)["timeInForce"] == "postOnly") is expected


def test_hyperliquid_post_only_reject_of_maker_exit_is_not_an_error(monkeypatch):
    import asyncio
    from exchanges.ccxt_bot import CCXTBot
    from exchanges.hyperliquid import HyperliquidBot

    async def reject(self, order):
        raise Exception('hyperliquid {"status":"ok","response":{"type":"order","data":{"statuses":[{"error":"Post only order would have immediately matched, bbo was 99.99@100.0. asset=159"}]}}}')

    monkeypatch.setattr(CCXTBot, "execute_order", reject)
    hl = object.__new__(HyperliquidBot)
    invalidated = []
    hl.market_snapshot_provider = type("P", (), {"invalidate": lambda self, s: invalidated.append(s)})()
    assert asyncio.run(hl.execute_order(_order("close_panic_long", 100.0))) == {}
    assert invalidated == [SYMBOL]
    # anche un ingresso rifiutato post-only si riprova al ciclo dopo
    assert asyncio.run(hl.execute_order(_order("entry_initial_normal_long", 100.0))) == {}

    async def other_error(self, order):
        raise Exception("hyperliquid Insufficient margin to place order")

    monkeypatch.setattr(CCXTBot, "execute_order", other_error)
    with pytest.raises(Exception, match="Insufficient margin"):
        asyncio.run(hl.execute_order(_order("entry_initial_normal_long", 100.0)))


def _live_order(pb_order_type, side, reduce_only, price, symbol=SYMBOL):
    return {
        "symbol": symbol,
        "side": side,
        "position_side": "long",
        "qty": 1.0,
        "price": price,
        "reduce_only": reduce_only,
        "type": "limit",
        "pb_order_type": pb_order_type,
    }


class _HoldBot:
    _config_hedge_mode = False
    hedge_mode = False

    def __init__(self, rylos=True):
        self.rylos = rylos

    def bp(self, pside, key, symbol):
        assert key == "rylos_4rsi_enabled"
        return self.rylos


def test_maker_exit_goes_out_before_entry_cancels():
    from live import executor

    entries = [_live_order("entry_grid_normal_long", "buy", False, 90.0 - i) for i in range(9)]
    other = _live_order("entry_grid_normal_long", "buy", False, 1.0, symbol="ETH/USDC:USDC")
    exit_ = _live_order("close_panic_long", "sell", True, 101.0)
    wave = {"skipped_cancel": 0}
    kept = executor._hold_entry_cancels_behind_maker_exit(
        _HoldBot(), entries + [other], [exit_], wave
    )
    assert kept == [other]  # other scopes untouched
    assert wave["skipped_cancel"] == 9


def test_previous_exit_price_is_still_cancelled_first():
    from live import executor

    old_exit = _live_order("close_panic_long", "sell", True, 100.5)
    entry = _live_order("entry_grid_normal_long", "buy", False, 90.0)
    new_exit = _live_order("close_panic_long", "sell", True, 101.0)
    kept = executor._hold_entry_cancels_behind_maker_exit(
        _HoldBot(), [old_exit, entry], [new_exit], None
    )
    assert kept == [old_exit]


def test_entry_cancels_untouched_without_maker_exit():
    from live import executor

    entries = [_live_order("entry_grid_normal_long", "buy", False, 90.0)]
    market_panic = dict(_live_order("close_panic_long", "sell", True, 101.0), type="market")
    grid = _live_order("entry_grid_normal_long", "buy", False, 89.0)
    for creates in ([], [grid], [market_panic]):
        assert executor._hold_entry_cancels_behind_maker_exit(
            _HoldBot(), entries, creates, None
        ) == entries


def test_entry_cancels_untouched_without_rylos():
    from live import executor

    entries = [_live_order("entry_grid_normal_long", "buy", False, 90.0)]
    exit_ = _live_order("close_panic_long", "sell", True, 101.0)
    assert executor._hold_entry_cancels_behind_maker_exit(
        _HoldBot(rylos=False), entries, [exit_], None
    ) == entries


class _AmendBot(_HoldBot):
    _supports_maker_exit_amend = True

    def __init__(self, backoff=None):
        super().__init__()
        self._maker_exit_amend_backoff_until = backoff or {}


def _resting_exit(price, qty=1.0, oid="old-1"):
    return dict(
        _live_order("close_panic_long", "sell", True, price), qty=qty, id=oid, custom_id="cid-old"
    )


def test_maker_exit_reprice_is_paired_as_amend():
    from live import executor

    old = _resting_exit(100.5)
    entry = _live_order("entry_grid_normal_long", "buy", False, 90.0)
    new = _live_order("close_panic_long", "sell", True, 101.0)
    kept = executor._pair_maker_exit_amends(_AmendBot(), [old, entry], [new])
    assert kept == [entry]
    assert new["_amend_from"] == {"id": "old-1", "custom_id": "cid-old", "price": 100.5}


@pytest.mark.parametrize(
    "bot, old",
    [
        (_AmendBot(), _resting_exit(100.5, qty=0.6)),  # partial fill / size change
        (_AmendBot(backoff={SYMBOL: 10**15}), _resting_exit(100.5)),  # after a failed amend
        (_HoldBot(), _resting_exit(100.5)),  # connector without amend
    ],
)
def test_maker_exit_falls_back_to_cancel_create(bot, old):
    from live import executor

    new = _live_order("close_panic_long", "sell", True, 101.0)
    assert executor._pair_maker_exit_amends(bot, [old], [new]) == [old]
    assert "_amend_from" not in new


def _amend_connector(cls, monkeypatch, edit):
    from live import executor

    monkeypatch.setattr(executor, "record_create_connector_admission", lambda bot, order: None)
    bot = object.__new__(cls)
    bot.config = {"live": {"time_in_force": "good_till_cancelled"}}
    bot.user_info = {"is_vault": True, "wallet_address": "0xvault"}
    bot._emit_execution_connector_call_started_event = lambda **kw: None
    bot.cca = type("C", (), {"edit_order": edit})()
    return bot


def _new_exit():
    return dict(
        _live_order("close_panic_long", "sell", True, 101.0),
        custom_id="cid-new",
        _amend_from={"id": "old-1", "custom_id": "cid-old", "price": 100.5},
    )


def test_hyperliquid_amend_is_an_alo_modify(monkeypatch):
    import asyncio
    from exchanges.hyperliquid import HyperliquidBot

    calls = []

    async def edit(self, *args, **kwargs):
        calls.append((args, kwargs))
        return {"id": "new-oid", "info": {"resting": {"oid": 1}}}

    hl = _amend_connector(HyperliquidBot, monkeypatch, edit)
    assert asyncio.run(hl.execute_order(_new_exit()))["id"] == "new-oid"
    (args, kwargs), = calls
    assert args == ("old-1", SYMBOL, "limit", "sell")
    assert kwargs["amount"] == 1.0 and kwargs["price"] == 101.0
    assert kwargs["params"] == {
        "timeInForce": "Alo",
        "reduceOnly": True,
        "clientOrderId": "cid-new",
        "vaultAddress": "0xvault",
    }


def test_bybit_amend_sends_only_the_price_and_keeps_the_client_id(monkeypatch):
    import asyncio
    from exchanges.bybit import BybitBot

    calls = []

    async def edit(self, *args, **kwargs):
        calls.append((args, kwargs))
        return {"id": "old-1", "clientOrderId": "cid-old", "info": {"retCode": 0}}

    by = _amend_connector(BybitBot, monkeypatch, edit)
    order = _new_exit()
    assert asyncio.run(by.execute_order(order))["id"] == "old-1"
    (args, kwargs), = calls
    assert args == ("old-1", SYMBOL, "limit", "sell")
    assert kwargs == {"amount": None, "price": 101.0, "params": {}}
    assert order["custom_id"] == "cid-old"


def test_failed_amend_backs_off_to_cancel_create(monkeypatch):
    import asyncio
    from exchanges.bybit import BybitBot

    async def edit(self, *args, **kwargs):
        raise Exception('bybit {"retCode":110001,"retMsg":"order not exists or too late to replace"}')

    by = _amend_connector(BybitBot, monkeypatch, edit)
    assert asyncio.run(by.execute_order(_new_exit())) == {}
    assert by._maker_exit_amend_backoff_until[SYMBOL] > 0


@pytest.mark.parametrize(
    "rylos, type_, retired",
    [(True, "limit", False), (False, "limit", True), (True, "market", True)],
)
def test_revised_hsl_does_not_retire_the_4rsi_exit(rylos, type_, retired):
    from live import hsl_revised_live

    order = dict(_live_order("close_panic_long", "sell", True, 101.0), type=type_)
    assert hsl_revised_live._rylos_4rsi_exit(_HoldBot(rylos=rylos), order) is (not retired)
