"""
RyLoS 4RSI signal indicators (port of RyLoSStrategy.py entry/exit signal).

Computes, on 5m candles aggregated from 1m HLCV data:
- osc_4rsi:  avg(RSI2, RSI7, RSI14) - 50  (Wilder RSI, talib-compatible seed)
- stoch_k:   fast %D of STOCHF(14, 3) = SMA(3) of the raw stochastic
- candle_color: close - open of the 5m candle (open = previous 5m close);
  > 0 green, < 0 red, 0 doji/unknown

Only raw indicator values are produced here; thresholds live in BotParams and
are applied inside the Rust orchestrator, identically for backtest and live.

Alignment (no lookahead): the values of a 5m candle become available at the
1m row on which that candle closes, and are held for the following rows until
the next 5m candle closes. This mirrors freqtrade acting on the closed candle
during the next one. Warmup rows are NaN (Rust treats NaN as "no signal" and
blocks only the initial entry).
"""

import numpy as np

DEFAULT_RYLOS_SIGNAL_CONFIG = {
    "timeframe_minutes": 5,
    "rsi_periods": [2, 7, 14],
    "stoch_period": 14,
    "stoch_smooth": 3,
}

# Minimum number of closed 5m candles for the live signal to be considered
# reliable (Wilder RSI seed convergence), same spirit as freqtrade's
# startup_candle_count = 100.
LIVE_MIN_CANDLES = 100


def _wilder_rsi(close: np.ndarray, period: int) -> np.ndarray:
    """RSI with Wilder smoothing, talib-compatible: seeded with the simple
    average of the first `period` gains/losses, NaN before that."""
    n = len(close)
    out = np.full(n, np.nan)
    if n <= period:
        return out
    delta = np.diff(close)
    gain = np.where(delta > 0.0, delta, 0.0)
    loss = np.where(delta < 0.0, -delta, 0.0)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    inv = 1.0 / period
    keep = 1.0 - inv
    for i in range(period, n):
        if i > period:
            avg_gain = avg_gain * keep + gain[i - 1] * inv
            avg_loss = avg_loss * keep + loss[i - 1] * inv
        if avg_loss > 0.0:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        else:
            out[i] = 100.0 if avg_gain > 0.0 else 50.0
    return out


def _rolling_extreme(values: np.ndarray, period: int, is_max: bool) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) >= period:
        windows = np.lib.stride_tricks.sliding_window_view(values, period)
        out[period - 1 :] = windows.max(axis=1) if is_max else windows.min(axis=1)
    return out


def _sma(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) >= period:
        kernel = np.ones(period) / period
        out[period - 1 :] = np.convolve(values, kernel, mode="valid")
    return out


def _osc_4rsi(close: np.ndarray, rsi_periods) -> np.ndarray:
    rsis = [_wilder_rsi(close, int(p)) for p in rsi_periods]
    return np.mean(rsis, axis=0) - 50.0


def _stoch_k(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int, smooth: int
) -> np.ndarray:
    """SMA(smooth) of the raw stochastic over `period` (= fast %D of STOCHF)."""
    hh = _rolling_extreme(high, period, is_max=True)
    ll = _rolling_extreme(low, period, is_max=False)
    span = hh - ll
    with np.errstate(invalid="ignore", divide="ignore"):
        raw_k = np.where(span > 0.0, (close - ll) / span * 100.0, 50.0)
    raw_k = np.where(np.isnan(span), np.nan, raw_k)
    return _sma(raw_k, smooth)


def _aggregate_5m(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    timestamps_ms: np.ndarray,
    tf_minutes: int,
):
    """
    Aggregate 1m series into tf_minutes candles using wall-clock buckets.

    Returns (candle_high, candle_low, candle_close, candle_color, last_rows)
    where last_rows[j] is the 1m row index at which candle j closes (i.e. the
    row whose bucket differs from the next row's bucket). The trailing
    incomplete bucket is excluded.
    """
    # Row r closes its tf-minute candle iff its (open) minute is the last of
    # the wall-clock bucket. Clock-based, so the freshest closed candle is
    # kept even when the series ends exactly on a bucket boundary. Callers on
    # the live path must exclude the in-progress 1m candle beforehand.
    minute_idx = timestamps_ms // 60_000
    last_rows = np.nonzero(minute_idx % tf_minutes == tf_minutes - 1)[0]
    if len(last_rows) == 0:
        return None
    starts = np.concatenate(([0], last_rows[:-1] + 1))
    c_high = np.maximum.reduceat(highs, starts)
    c_low = np.minimum.reduceat(lows, starts)
    c_close = closes[last_rows]
    # Open = previous 5m close (only HLCV available); first candle unknown.
    c_color = np.empty(len(last_rows))
    c_color[0] = np.nan
    c_color[1:] = c_close[1:] - c_close[:-1]
    return c_high, c_low, c_close, c_color, last_rows


def _candle_indicators(c_high, c_low, c_close, c_color, cfg):
    osc = _osc_4rsi(c_close, cfg["rsi_periods"])
    stoch = _stoch_k(
        c_high, c_low, c_close, int(cfg["stoch_period"]), int(cfg["stoch_smooth"])
    )
    color = np.where(np.isnan(c_color), 0.0, np.sign(c_color))
    return osc, stoch, color


def compute_rylos_indicators_for_backtest(
    hlcvs: np.ndarray,
    timestamps_ms: np.ndarray,
    config: dict | None = None,
) -> np.ndarray:
    """
    Compute the RyLoS 4RSI indicator array for the Rust backtest.

    Args:
        hlcvs: (T, N, 4) float array of 1m candles [high, low, close, volume],
               same column order the backtest receives.
        timestamps_ms: (T,) int64 array of candle timestamps in ms (1m spacing).
        config: optional dict overriding DEFAULT_RYLOS_SIGNAL_CONFIG.

    Returns:
        (T, N, 3) float64 array [osc_4rsi, stoch_k, candle_color], NaN where
        the signal is unavailable (warmup / missing data).
    """
    cfg = {**DEFAULT_RYLOS_SIGNAL_CONFIG, **(config or {})}
    tf = int(cfg["timeframe_minutes"])
    n_timesteps, n_coins = hlcvs.shape[0], hlcvs.shape[1]
    timestamps_ms = np.asarray(timestamps_ms, dtype=np.int64)
    if len(timestamps_ms) != n_timesteps:
        raise ValueError(
            f"timestamps length {len(timestamps_ms)} != hlcvs timesteps {n_timesteps}"
        )
    out = np.full((n_timesteps, n_coins, 3), np.nan)
    for coin in range(n_coins):
        closes = hlcvs[:, coin, 2]
        if not np.any(closes > 0.0):
            continue
        agg = _aggregate_5m(
            hlcvs[:, coin, 0], hlcvs[:, coin, 1], closes, timestamps_ms, tf
        )
        if agg is None:
            continue
        c_high, c_low, c_close, c_color, last_rows = agg
        osc, stoch, color = _candle_indicators(c_high, c_low, c_close, c_color, cfg)
        # Candle j's values hold from its closing row up to (excluding) the
        # closing row of candle j+1; the last candle holds until the end.
        ends = np.concatenate((last_rows[1:], [n_timesteps]))
        for j in range(len(last_rows)):
            if np.isnan(osc[j]) or np.isnan(stoch[j]):
                continue
            out[last_rows[j] : ends[j], coin, 0] = osc[j]
            out[last_rows[j] : ends[j], coin, 1] = stoch[j]
            out[last_rows[j] : ends[j], coin, 2] = color[j]
    return np.ascontiguousarray(out)


def compute_rylos_signal_live(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    timestamps_ms: np.ndarray,
    config: dict | None = None,
) -> dict | None:
    """
    Compute the RyLoS 4RSI signal values of the last *closed* 5m candle from
    recent 1m candles (live path). Stateless: safe across bot restarts.

    Args:
        highs/lows/closes/timestamps_ms: 1m candle series, oldest first; the
            last (possibly incomplete) 5m bucket is ignored.

    Returns:
        {"osc_4rsi": float, "stoch_k": float, "candle_color": float} or None
        when unavailable (insufficient history / warmup).
    """
    cfg = {**DEFAULT_RYLOS_SIGNAL_CONFIG, **(config or {})}
    tf = int(cfg["timeframe_minutes"])
    closes = np.asarray(closes, dtype=np.float64)
    timestamps_ms = np.asarray(timestamps_ms, dtype=np.int64)
    agg = _aggregate_5m(
        np.asarray(highs, dtype=np.float64),
        np.asarray(lows, dtype=np.float64),
        closes,
        timestamps_ms,
        tf,
    )
    if agg is None:
        return None
    c_high, c_low, c_close, c_color, _ = agg
    if len(c_close) < LIVE_MIN_CANDLES:
        return None
    osc, stoch, color = _candle_indicators(c_high, c_low, c_close, c_color, cfg)
    if np.isnan(osc[-1]) or np.isnan(stoch[-1]):
        return None
    return {
        "osc_4rsi": float(osc[-1]),
        "stoch_k": float(stoch[-1]),
        "candle_color": float(color[-1]),
    }
