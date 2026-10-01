"""rylos: 4RSI thresholds can differ per coin through coin_overrides."""

from copy import deepcopy

import pytest

from config.load import prepare_config
from config.overrides import parse_overrides
from config.schema import get_template_config
from config.shared_bot import get_grouped_bot_value

RYLOS_OVERRIDE = {
    "osc_entry_threshold": -20.5,
    "entry_stoch_threshold": 9.5,
    "osc_exit_threshold": 30.25,
    "exit_stoch_threshold": 80.5,
    "exit_min_gain": 0.0061,
    "crash_stop_pct": 0.12,
    "crash_window_minutes": 45.0,
}


def _parse(overrides):
    source = get_template_config()
    source["live"]["user"] = "tester"
    source["coin_overrides"] = deepcopy(overrides)
    prepared = prepare_config(source, verbose=False, log_config_transforms=False)
    return parse_overrides(
        prepared,
        verbose=False,
        override_loader=lambda config, coin: {},
        symbol_normalizer=lambda coin: coin,
    )


@pytest.mark.parametrize("key,value", sorted(RYLOS_OVERRIDE.items()))
def test_rylos_4rsi_thresholds_are_overridable_per_coin(key, value):
    parsed = _parse({"NEAR": {"bot": {"long": {"rylos_4rsi": {key: value}}}}})
    side = parsed["coin_overrides"]["NEAR"]["bot"]["long"]
    assert side["rylos_4rsi"][key] == value
    assert get_grouped_bot_value(side, f"rylos_{key}") == value


def test_rylos_4rsi_enabled_stays_global():
    with pytest.raises(ValueError, match="rylos_4rsi.enabled is not overridable"):
        _parse({"NEAR": {"bot": {"long": {"rylos_4rsi": {"enabled": False}}}}})
