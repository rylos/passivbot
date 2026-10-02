"""The live 4RSI signal of a closed 5m candle must not move while the next
candle is in progress (parity with the backtest, which sees whole candles)."""

import numpy as np

from rylos_signal import _aggregate_5m, compute_rylos_signal_live

T0 = 1_790_000_000_000 - (1_790_000_000_000 % 300_000)  # 5m aligned


def _series(n, seed=7):
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.2, n))
    high = close + rng.uniform(0.0, 0.3, n)
    low = close - rng.uniform(0.0, 0.3, n)
    ts = T0 + np.arange(n, dtype=np.int64) * 60_000
    return high, low, close, ts


def test_last_closed_candle_ignores_the_in_progress_bucket():
    high, low, close, ts = _series(23)  # 4 full buckets + 3 rows of the 5th
    low[20:] = 1.0  # a crash inside the in-progress bucket
    high[20:] = 500.0
    c_high, c_low, c_close, _, last_rows = _aggregate_5m(high, low, close, ts, 5)
    assert len(c_close) == 4 and last_rows[-1] == 19
    assert c_low[-1] == low[15:20].min()
    assert c_high[-1] == high[15:20].max()


def test_live_signal_is_stable_inside_the_next_candle():
    high, low, close, ts = _series(700)
    n = 700 - (700 % 5)  # series ends on a closed candle
    base = compute_rylos_signal_live(high[:n], low[:n], close[:n], ts[:n])
    # add 1..4 rows of the next candle with extreme highs/lows: same signal
    ext_high, ext_low = high.copy(), low.copy()
    ext_high[n:] = 1e6
    ext_low[n:] = 1e-6
    for k in range(1, 5):
        sig = compute_rylos_signal_live(
            ext_high[: n + k], ext_low[: n + k], close[: n + k], ts[: n + k]
        )
        assert sig == base
