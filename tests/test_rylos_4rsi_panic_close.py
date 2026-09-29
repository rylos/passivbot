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


@pytest.mark.parametrize("pb_order_type, expected", [("close_panic_long", True), ("close_grid_long", False)])
def test_connectors_send_maker_exit_post_only(pb_order_type, expected):
    from exchanges.bybit import BybitBot
    from exchanges.hyperliquid import HyperliquidBot

    config = {"live": {"time_in_force": "good_till_cancelled"}}
    order = dict(_order(pb_order_type, 100.0), custom_id="x")
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
    assert asyncio.run(hl.execute_order(_order("close_panic_long", 100.0))) == {}
    with pytest.raises(Exception, match="Post only"):
        asyncio.run(hl.execute_order(_order("close_grid_long", 100.0)))
