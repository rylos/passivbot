"""
Multi-oscillator oversold entry signal computation (RyLoS-style).

Computes RSI, Bollinger Bands %B, Stochastic RSI, and Williams %R on
aggregated candles and produces a boolean signal array compatible with
the Rust backtest engine.
"""

import numpy as np


# ---------------------------------------------------------------------------
# Indicator helpers (numpy-only, no talib dependency)
# ---------------------------------------------------------------------------

def _wilder_ema(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing (equivalent to EMA with alpha = 1/period)."""
    alpha = 1.0 / period
    out = np.empty_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _rsi(close: np.ndarray, period: int = 10) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _wilder_ema(gain, period)
    avg_loss = _wilder_ema(loss, period)
    with np.errstate(invalid="ignore", divide="ignore"):
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100.0)
    return 100.0 - 100.0 / (1.0 + rs)


def _sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average with cumsum trick; first `period-1` values use expanding window."""
    cs = np.cumsum(values)
    out = np.empty_like(values)
    out[:period] = cs[:period] / np.arange(1, period + 1)
    out[period:] = (cs[period:] - cs[:-period]) / period
    return out


def _rolling_std(values: np.ndarray, period: int) -> np.ndarray:
    """Rolling standard deviation (population)."""
    sma = _sma(values, period)
    cs2 = np.cumsum(values ** 2)
    out = np.empty_like(values)
    out[:period] = np.sqrt(
        np.maximum(cs2[:period] / np.arange(1, period + 1) - sma[:period] ** 2, 0.0)
    )
    mean_sq = (cs2[period:] - cs2[:-period]) / period
    out[period:] = np.sqrt(np.maximum(mean_sq - sma[period:] ** 2, 0.0))
    return out


def _bb_percent(close: np.ndarray, period: int = 20, nbdev: float = 2.0) -> np.ndarray:
    """Bollinger Bands %B: (close - lower) / (upper - lower)."""
    mid = _sma(close, period)
    std = _rolling_std(close, period)
    upper = mid + nbdev * std
    lower = mid - nbdev * std
    width = upper - lower
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(width > 0, (close - lower) / width, 0.5)


def _stoch_rsi(close: np.ndarray, rsi_period: int = 10,
               fastk_period: int = 5, fastd_period: int = 3) -> np.ndarray:
    """Stochastic RSI %K (SMA-smoothed)."""
    rsi = _rsi(close, rsi_period)
    n = len(rsi)
    raw_k = np.full(n, 50.0)
    for i in range(fastk_period - 1, n):
        window = rsi[i - fastk_period + 1: i + 1]
        lo, hi = window.min(), window.max()
        raw_k[i] = ((rsi[i] - lo) / (hi - lo) * 100.0) if hi > lo else 50.0
    return _sma(raw_k, fastd_period)


def _williams_r(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                period: int = 10) -> np.ndarray:
    """Williams %R."""
    n = len(close)
    out = np.full(n, -50.0)
    for i in range(period - 1, n):
        hh = high[i - period + 1: i + 1].max()
        ll = low[i - period + 1: i + 1].min()
        out[i] = ((hh - close[i]) / (hh - ll) * -100.0) if hh > ll else -50.0
    return out


# ---------------------------------------------------------------------------
# 1m → Nm aggregation
# ---------------------------------------------------------------------------

def _aggregate_candles(hlcv_1m: np.ndarray, tf_minutes: int) -> dict:
    """
    Aggregate 1m HLCV (shape: T×4, columns: high, low, close, volume)
    into tf_minutes candles. Returns dict with open, high, low, close arrays.
    """
    n = len(hlcv_1m)
    n_candles = n // tf_minutes
    trimmed = n_candles * tf_minutes
    reshaped = hlcv_1m[:trimmed].reshape(n_candles, tf_minutes, 4)
    return {
        "open": reshaped[:, 0, 2],  # close of first 1m bar ≈ open (prev close)
        "high": reshaped[:, :, 0].max(axis=1),
        "low": reshaped[:, :, 1].min(axis=1),
        "close": reshaped[:, :, 2][:, -1],  # last close
    }


# ---------------------------------------------------------------------------
# Default parameters (matching RyLoS optimized values)
# ---------------------------------------------------------------------------

DEFAULT_ENTRY_SIGNAL_CONFIG = {
    "enabled": True,
    "timeframe_minutes": 5,
    "signal_hold_minutes": 10,
    "rsi_period": 10,
    "rsi_oversold": 33.752,
    "bb_period": 20,
    "bb_oversold": 0.116,
    "stochrsi_period": 10,
    "stochrsi_fastk": 5,
    "stochrsi_fastd": 3,
    "stochrsi_oversold": 24.237,
    "williams_period": 10,
    "williams_oversold": -70.16,
    "min_oversold_count": 3,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_entry_signal_for_backtest(
    hlcvs: np.ndarray,
    config: dict | None = None,
) -> np.ndarray:
    """
    Compute multi-oscillator oversold entry signal for all coins.

    Args:
        hlcvs: 3D array (n_timesteps, n_coins, 4) with [high, low, close, volume].
        config: dict with entry_signal parameters (uses defaults if None).

    Returns:
        uint8 array (n_timesteps, n_coins): 1 = entry allowed, 0 = blocked.
    """
    cfg = {**DEFAULT_ENTRY_SIGNAL_CONFIG, **(config or {})}
    if not cfg["enabled"]:
        return np.ones(hlcvs.shape[:2], dtype=np.uint8)

    n_timesteps, n_coins, _ = hlcvs.shape
    tf = int(cfg["timeframe_minutes"])
    signal = np.zeros((n_timesteps, n_coins), dtype=np.uint8)

    for coin_idx in range(n_coins):
        coin_hlcv = hlcvs[:, coin_idx, :]  # (T, 4)
        # Skip coins with no valid data
        if np.all(coin_hlcv[:, 2] == 0):
            continue

        agg = _aggregate_candles(coin_hlcv, tf)
        n_candles = len(agg["close"])

        # Compute indicators on aggregated candles
        rsi = _rsi(agg["close"], int(cfg["rsi_period"]))
        bb = _bb_percent(agg["close"], int(cfg["bb_period"]))
        stochrsi = _stoch_rsi(
            agg["close"],
            int(cfg["stochrsi_period"]),
            int(cfg["stochrsi_fastk"]),
            int(cfg["stochrsi_fastd"]),
        )
        wr = _williams_r(
            agg["high"], agg["low"], agg["close"],
            int(cfg["williams_period"]),
        )

        # Count oversold indicators
        oversold = (
            (rsi < cfg["rsi_oversold"]).astype(np.int8)
            + (bb < cfg["bb_oversold"]).astype(np.int8)
            + (stochrsi < cfg["stochrsi_oversold"]).astype(np.int8)
            + (wr < cfg["williams_oversold"]).astype(np.int8)
        )

        # Signal: enough oversold indicators
        candle_signal = oversold >= int(cfg["min_oversold_count"])

        # Expand aggregated signal back to 1m resolution with hold
        hold_candles = max(1, int(cfg.get("signal_hold_minutes", tf)) // tf)
        trimmed = n_candles * tf
        expanded = np.repeat(candle_signal, tf)
        # Apply hold: once triggered, keep signal=1 for hold_candles consecutive candles
        if hold_candles > 1:
            held = np.zeros(n_candles, dtype=bool)
            countdown = 0
            for i in range(n_candles):
                if candle_signal[i]:
                    countdown = hold_candles
                if countdown > 0:
                    held[i] = True
                    countdown -= 1
            expanded = np.repeat(held, tf)
        signal[:trimmed, coin_idx] = expanded.astype(np.uint8)

    return signal


def compute_entry_signal_live(
    candles_1m: np.ndarray,
    config: dict | None = None,
) -> bool:
    """
    Compute multi-oscillator oversold entry signal for a single coin (live).

    Args:
        candles_1m: 2D array (N, 4) of recent 1m candles [high, low, close, volume].
                    Needs at least timeframe_minutes * max(indicator_periods) bars.
        config: dict with entry_signal parameters.

    Returns:
        True if entry is allowed (oversold condition met), False otherwise.
    """
    cfg = {**DEFAULT_ENTRY_SIGNAL_CONFIG, **(config or {})}
    if not cfg["enabled"]:
        return True

    tf = int(cfg["timeframe_minutes"])
    if len(candles_1m) < tf:
        return False

    agg = _aggregate_candles(candles_1m, tf)
    if len(agg["close"]) < 2:
        return False

    rsi = _rsi(agg["close"], int(cfg["rsi_period"]))
    bb = _bb_percent(agg["close"], int(cfg["bb_period"]))
    stochrsi = _stoch_rsi(
        agg["close"],
        int(cfg["stochrsi_period"]),
        int(cfg["stochrsi_fastk"]),
        int(cfg["stochrsi_fastd"]),
    )
    wr = _williams_r(
        agg["high"], agg["low"], agg["close"],
        int(cfg["williams_period"]),
    )

    # Check last completed candle
    i = -1
    count = (
        int(rsi[i] < cfg["rsi_oversold"])
        + int(bb[i] < cfg["bb_oversold"])
        + int(stochrsi[i] < cfg["stochrsi_oversold"])
        + int(wr[i] < cfg["williams_oversold"])
    )
    return count >= int(cfg["min_oversold_count"])
