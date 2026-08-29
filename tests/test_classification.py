import polars as pl

from market_test_bench.classification import classify_ohlcv, compute_coverage


def test_classifies_bull_breakout_window() -> None:
    df = pl.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0, 140.0],
            "high": [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 112.0, 145.0],
            "low": [99.0, 100.0, 101.0, 102.0, 103.0, 104.0, 109.0, 139.0],
            "close": [101.0, 102.0, 103.0, 104.0, 105.0, 110.0, 140.0, 144.0],
            "quote_volume": [1000.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1700.0, 1800.0],
            "trade_count": [100, 110, 120, 130, 140, 150, 160, 170],
            "interval": ["4h"] * 8,
        }
    )

    result = classify_ohlcv(df)

    assert "strong_bull" in result.labels
    assert "breakout" in result.labels


def test_volume_spike_threshold_is_interval_aware() -> None:
    df = pl.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [101.0] * 20,
            "low": [99.0] * 20,
            "close": [100.0] * 20,
            "quote_volume": [1000.0] * 19 + [20_000.0],
            "trade_count": [100] * 20,
            "interval": ["1m"] * 20,
        }
    )

    result = classify_ohlcv(df)

    assert "volume_spike" not in result.labels


def test_coverage_accepts_only_missing_labels() -> None:
    bull = classify_ohlcv(
        pl.DataFrame(
            {
                "open": [100.0, 110.0, 120.0],
                "high": [111.0, 121.0, 133.0],
                "low": [99.0, 109.0, 119.0],
                "close": [110.0, 120.0, 132.0],
                "quote_volume": [1000.0, 1100.0, 1200.0],
                "trade_count": [100, 110, 120],
            }
        )
    )
    coverage = compute_coverage([bull], {"bull": 1, "crash": 1})

    assert not coverage.is_satisfied
    assert coverage.accepts({"crash"})
    assert not coverage.accepts({"sideways"})
