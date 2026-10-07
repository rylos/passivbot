"""Resting entries survive the short trailing-confirmation window after a fill.

Right after a fill the live bot marks the side's trailing inputs unavailable
until the position confirms the fill. Strategies whose entries consume trailing
then emit no entries, and the reconciler used to retire the whole grid one
cancel per cycle and re-post it ~90s later at nearly identical prices. Rust now
flags that exact situation and live keeps the resting entries instead.
"""

import logging
from types import SimpleNamespace

import pytest

from live import reconciler
from passivbot import Passivbot

from test_orchestrator_json_api import (
    adaptive_strategy_params,
    bot_params_pair,
    compute,
    make_input,
    make_symbol,
)

SYMBOL = "HYPE/USDC:USDC"
KEEP = "entry_trailing_pending_with_position"
ENTRY_NEEDS_TRAILING = adaptive_strategy_params(
    entry={"retracement_base_pct": 0.01},
    close={"retracement_base_pct": 0.0},
)


def _long_input(
    *,
    pos_size=1.0,
    strategy=ENTRY_NEEDS_TRAILING,
    trailing_available=False,
    long_mode=None,
    long_bp=None,
    rylos_signal=None,
):
    symbol = make_symbol(
        0,
        bid=100.0,
        ask=100.0,
        long_pos_size=pos_size,
        long_pos_price=100.0 if pos_size else 0.0,
        long_strategy=strategy,
        long_mode=long_mode,
        long_bp=long_bp,
    )
    symbol["long"]["trailing_available"] = trailing_available
    if rylos_signal is not None:
        symbol["long"]["rylos_signal"] = rylos_signal
    inp = make_input(
        balance=1_000.0,
        global_bp=bot_params_pair(long_overrides=long_bp),
        symbols=[symbol],
    )
    inp["global"]["hedge_mode"] = True
    return inp


def _keep_warnings(out):
    return [w[KEEP] for w in out["diagnostics"]["warnings"] if KEEP in w]


def _long_entries(out):
    return [
        o for o in out["orders"]
        if o["pside"] == "long" and o["order_type"].startswith("entry_")
    ]


# ---------------------------------------------------------------- Rust flag


def test_open_position_with_pending_entry_trailing_is_flagged():
    import passivbot_rust as pbr

    inp = _long_input()
    out = compute(pbr, inp)

    assert _long_entries(out) == []
    assert _keep_warnings(out) == [{"symbol_idx": 0, "pside": "long"}]
    assert reconciler.validate_rust_orchestrator_output(
        out, {0: SYMBOL}, inp
    ) == out["orders"]
    assert reconciler.entry_trailing_pending_pairs_from_rust_output(
        out, {0: SYMBOL}
    ) == {(SYMBOL, "long")}


def test_available_trailing_is_not_flagged():
    import passivbot_rust as pbr

    out = compute(pbr, _long_input(trailing_available=True))

    assert not any(
        "strategy_input_unavailable" in w for w in out["diagnostics"]["warnings"]
    )
    assert _keep_warnings(out) == []


def test_flat_side_is_not_flagged():
    """Without a position the 4RSI initial-entry retire must keep working."""
    import passivbot_rust as pbr

    out = compute(pbr, _long_input(pos_size=0.0))

    assert _keep_warnings(out) == []


def test_entries_not_consuming_trailing_are_not_flagged():
    """Only closes miss trailing here: entries are computed, nothing to keep."""
    import passivbot_rust as pbr

    strategy = adaptive_strategy_params(
        entry={"retracement_base_pct": 0.0},
        close={"retracement_base_pct": 0.01},
    )
    out = compute(pbr, _long_input(strategy=strategy))

    assert _keep_warnings(out) == []


def test_forager_missing_input_authority_is_not_flagged():
    import passivbot_rust as pbr

    inp = _long_input()
    inp["symbols"][0]["allow_missing_strategy_inputs"] = True
    out = compute(pbr, inp)

    assert _long_entries(out) == []
    assert _keep_warnings(out) == []


@pytest.mark.parametrize("mode", ["tp_only", "manual", "panic"])
def test_non_entry_modes_are_not_flagged(mode):
    import passivbot_rust as pbr

    out = compute(pbr, _long_input(long_mode=mode))

    assert _keep_warnings(out) == []


def _rylos_bp(crash_stop_pct=0.05):
    return {
        "rylos_4rsi_enabled": True,
        "rylos_osc_entry_threshold": -14.0,
        "rylos_entry_stoch_threshold": 12.0,
        "rylos_osc_exit_threshold": 20.0,
        "rylos_exit_stoch_threshold": 80.0,
        "rylos_exit_min_gain": 0.005,
        "rylos_crash_stop_pct": crash_stop_pct,
        "rylos_crash_window_minutes": 60.0,
    }


def _signal(drop):
    return {
        "osc_4rsi": 0.0,
        "stoch_k": 50.0,
        "candle_color": 1.0,
        "drop_from_high_1m": drop,
    }


def test_rylos_side_without_crash_pause_is_flagged():
    import passivbot_rust as pbr

    out = compute(pbr, _long_input(long_bp=_rylos_bp(), rylos_signal=_signal(0.01)))

    assert _keep_warnings(out) == [{"symbol_idx": 0, "pside": "long"}]


def test_rylos_crash_pause_is_not_flagged():
    """A crash pause wants no entries: the resting grid must still be retired."""
    import passivbot_rust as pbr

    out = compute(pbr, _long_input(long_bp=_rylos_bp(), rylos_signal=_signal(0.06)))

    assert _long_entries(out) == []
    assert _keep_warnings(out) == []


def test_short_side_is_flagged_symmetrically():
    import passivbot_rust as pbr

    enabled_short = {"n_positions": 1, "total_wallet_exposure_limit": 1.0}
    symbol = make_symbol(
        0,
        bid=100.0,
        ask=100.0,
        short_pos_size=-1.0,
        short_pos_price=100.0,
        short_bp=enabled_short,
        long_strategy=ENTRY_NEEDS_TRAILING,
        short_strategy=ENTRY_NEEDS_TRAILING,
    )
    symbol["short"]["trailing_available"] = False
    inp = make_input(
        balance=1_000.0,
        global_bp=bot_params_pair(short_overrides=enabled_short),
        symbols=[symbol],
    )
    inp["global"]["hedge_mode"] = True
    out = compute(pbr, inp)

    assert _keep_warnings(out) == [{"symbol_idx": 0, "pside": "short"}]


def test_validator_rejects_malformed_keep_warning():
    import passivbot_rust as pbr
    from passivbot_exceptions import FatalBotException

    inp = _long_input()
    out = compute(pbr, inp)
    for warning in out["diagnostics"]["warnings"]:
        if KEEP in warning:
            warning[KEEP]["symbol_idx"] = 7
    with pytest.raises(FatalBotException, match="invalid symbol_idx"):
        reconciler.validate_rust_orchestrator_output(out, {0: SYMBOL}, inp)


# ------------------------------------------------------------- live filter


def _order(pside, reduce_only, price, oid):
    side = ("sell" if pside == "long" else "buy") if reduce_only else (
        "buy" if pside == "long" else "sell"
    )
    return {
        "id": oid,
        "symbol": SYMBOL,
        "side": side,
        "position_side": pside,
        "reduce_only": reduce_only,
        "qty": 1.0,
        "price": price,
    }


def _bot(mode_long="normal", mode_short="normal", kept=None):
    return SimpleNamespace(
        PB_modes={"long": {SYMBOL: mode_long}, "short": {SYMBOL: mode_short}},
        _orchestrator_ema_entry_cancellation_order_keys=set(),
        _orchestrator_kept_entry_psides=kept or {},
    )


def _cancels():
    return [
        _order("long", False, 90.0, "e1"),
        _order("long", False, 89.0, "e2"),
        _order("long", True, 101.0, "c1"),
        _order("short", False, 110.0, "s1"),
    ]


@pytest.mark.parametrize("mode", ["normal", "graceful_stop"])
def test_kept_side_keeps_resting_entries_only(mode):
    bot = _bot(mode_long=mode, kept={SYMBOL: {"long"}})

    to_cancel, to_create = reconciler.apply_mode_filters(bot, SYMBOL, _cancels(), [])

    assert [o["id"] for o in to_cancel] == ["c1", "s1"]
    assert to_create == []


def test_without_flag_the_grid_is_retired_as_before():
    bot = _bot()

    to_cancel, _ = reconciler.apply_mode_filters(bot, SYMBOL, _cancels(), [])

    assert [o["id"] for o in to_cancel] == ["e1", "e2", "c1", "s1"]


def test_flag_on_another_symbol_or_side_changes_nothing():
    bot = _bot(kept={"BTC/USDC:USDC": {"long"}, SYMBOL: {"short"}})

    to_cancel, _ = reconciler.apply_mode_filters(bot, SYMBOL, _cancels(), [])

    assert [o["id"] for o in to_cancel] == ["e1", "e2", "c1"]


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("tp_only", ["c1", "s1"]),
        ("tp_only_with_active_entry_cancellation", ["e1", "e2", "c1", "s1"]),
        ("panic", ["e1", "e2", "c1", "s1"]),
        ("manual", ["s1"]),
    ],
)
def test_other_modes_keep_their_own_rules(mode, expected):
    bot = _bot(mode_long=mode, kept={SYMBOL: {"long"}})

    to_cancel, _ = reconciler.apply_mode_filters(bot, SYMBOL, _cancels(), [])

    assert [o["id"] for o in to_cancel] == expected


def test_keep_is_logged_once_per_change(caplog):
    bot = _bot(kept={SYMBOL: {"long"}})
    with caplog.at_level(logging.INFO):
        reconciler.apply_mode_filters(bot, SYMBOL, _cancels(), [])
        reconciler.apply_mode_filters(bot, SYMBOL, _cancels(), [])
    assert sum("keep 2 resting entries" in r.message for r in caplog.records) == 1


# --------------------------------------------------------------- time bound


def test_keep_is_bounded_in_time(caplog):
    bot = SimpleNamespace()
    pair = {(SYMBOL, "long")}
    cap = Passivbot._ENTRY_TRAILING_PENDING_KEEP_MAX_MS
    keep = Passivbot._entry_trailing_pending_keep.__get__(bot)

    assert keep(pair, now_ms=1_000) == {SYMBOL: {"long"}}
    assert keep(pair, now_ms=1_000 + cap) == {SYMBOL: {"long"}}
    with caplog.at_level(logging.WARNING):
        assert keep(pair, now_ms=1_001 + cap) == {}
        assert keep(pair, now_ms=2_000 + cap) == {}
    assert sum("no longer kept" in r.message for r in caplog.records) == 1


def test_confirmation_resets_the_clock():
    bot = SimpleNamespace()
    pair = {(SYMBOL, "long")}
    cap = Passivbot._ENTRY_TRAILING_PENDING_KEEP_MAX_MS
    keep = Passivbot._entry_trailing_pending_keep.__get__(bot)

    keep(pair, now_ms=0)
    assert keep(set(), now_ms=60_000) == {}
    # A later fill starts a fresh window.
    assert keep(pair, now_ms=cap + 60_000) == {SYMBOL: {"long"}}
    assert keep(pair, now_ms=2 * cap + 60_000) == {SYMBOL: {"long"}}
    assert keep(pair, now_ms=2 * cap + 60_001) == {}


@pytest.mark.asyncio
async def test_each_planning_call_starts_without_kept_entries():
    bot = SimpleNamespace(
        _orchestrator_kept_entry_psides={SYMBOL: {"long"}},
        active_symbols=[],
        _build_live_symbol_universe=lambda: [],
        config={},
    )

    assert await Passivbot.calc_ideal_orders_orchestrator(bot) == {}
    assert bot._orchestrator_kept_entry_psides == {}


def test_twel_gate_blocking_all_entries_wins_over_keep():
    """At or above the TWEL entry cap Rust would emit no entries even with
    trailing available, so the resting grid must not be kept either."""
    import passivbot_rust as pbr

    out = compute(pbr, _long_input(pos_size=20.0))

    assert _long_entries(out) == []
    assert _keep_warnings(out) == []


def test_twel_gate_disabled_does_not_block_keep():
    import passivbot_rust as pbr

    bp = {"risk_twel_entry_gate_enabled": False}
    out = compute(pbr, _long_input(pos_size=20.0, long_bp=bp))

    assert _keep_warnings(out) == [{"symbol_idx": 0, "pside": "long"}]
