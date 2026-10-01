"""Log of the fork-local 4RSI initial-entry gate (diagnostic only)."""

import logging

from passivbot import Passivbot

SYM = "HYPE/USDT:USDT"
THR = {"rylos_osc_entry_threshold": -14.33, "rylos_entry_stoch_threshold": 12.56}


class _Bot:
    def bp(self, pside, key, symbol):
        return THR[key]


def _sig(osc=-30.0, stoch=8.0, color=-1.0):
    return {"osc_4rsi": osc, "stoch_k": stoch, "candle_color": color}


def _gate_lines(caplog):
    return [r.getMessage() for r in caplog.records if "[rylos] entry gate" in r.getMessage()]


def test_logs_only_on_state_change(caplog):
    bot = _Bot()
    with caplog.at_level(logging.INFO):
        Passivbot._log_rylos_entry_gate(bot, SYM, _sig(), "candles 130 gaps 0 last_lag 0m")
        Passivbot._log_rylos_entry_gate(bot, SYM, _sig(), "candles 130 gaps 0 last_lag 0m")
        Passivbot._log_rylos_entry_gate(bot, SYM, _sig(color=1.0), "candles 130 gaps 0 last_lag 0m")
    lines = _gate_lines(caplog)
    assert len(lines) == 2
    assert f"entry gate {SYM} open" in lines[0]
    assert f"entry gate {SYM} closed" in lines[1] and "color +1" in lines[1]


def test_unavailable_signal_logs_closed_with_candle_info(caplog):
    bot = _Bot()
    with caplog.at_level(logging.INFO):
        Passivbot._log_rylos_entry_gate(bot, SYM, _sig(), "candles 130 gaps 0 last_lag 0m")
        Passivbot._log_rylos_entry_gate(bot, SYM, None, "candles 95 gaps 3 last_lag 2m")
    lines = _gate_lines(caplog)
    assert "closed | signal unavailable | candles 95 gaps 3 last_lag 2m" in lines[-1]


def test_thresholds_match_rust_rule(caplog):
    bot = _Bot()
    with caplog.at_level(logging.INFO):
        Passivbot._log_rylos_entry_gate(bot, SYM, _sig(stoch=12.56), "x")
    assert "closed" in _gate_lines(caplog)[0]  # strict <, like rylos_entry_allowed
