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
