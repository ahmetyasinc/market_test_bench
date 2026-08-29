import pytest

from market_test_bench.binance import (
    MissingBinanceDataError,
    filter_top_volume_symbols,
    iter_months,
    monthly_agg_trades_url,
    monthly_kline_url,
    select_candidate_symbol_month_pairs,
    select_symbol_month_pairs,
)


def test_iter_months_is_inclusive() -> None:
    assert iter_months("2024-11", "2025-02") == (
        "2024-11",
        "2024-12",
        "2025-01",
        "2025-02",
    )


def test_requires_at_least_100_monthly_files() -> None:
    with pytest.raises(ValueError, match="at least 100"):
        select_symbol_month_pairs(
            symbols=("BTCUSDT",),
            start_month="2020-01",
            end_month="2026-01",
            pair_count=99,
            seed=42,
        )


def test_symbol_month_pairs_can_span_multiple_symbols() -> None:
    pairs = select_symbol_month_pairs(
        symbols=("BTCUSDT", "ETHUSDT"),
        start_month="2020-01",
        end_month="2026-01",
        pair_count=100,
        seed=42,
    )

    assert len(pairs) == 100
    assert {symbol for symbol, _ in pairs} == {"BTCUSDT", "ETHUSDT"}


def test_candidate_pairs_include_the_full_available_pool() -> None:
    pairs = select_candidate_symbol_month_pairs(
        symbols=("BTCUSDT", "ETHUSDT"),
        start_month="2020-01",
        end_month="2026-01",
        seed=42,
    )

    assert len(pairs) == 146
    assert len(set(pairs)) == 146


def test_top_volume_filter_removes_stable_and_leveraged_pairs() -> None:
    symbols = filter_top_volume_symbols(
        [
            {"symbol": "USD1USDT", "quoteVolume": "999999"},
            {"symbol": "RLUSDUSDT", "quoteVolume": "888888"},
            {"symbol": "ETHUPUSDT", "quoteVolume": "777777"},
            {"symbol": "BTCUSDT", "quoteVolume": "10"},
            {"symbol": "ETHUSDT", "quoteVolume": "9"},
        ],
        limit=2,
    )

    assert symbols == ("BTCUSDT", "ETHUSDT")


def test_monthly_kline_url_uses_expected_binance_path() -> None:
    assert monthly_kline_url(symbol="btcusdt", interval="4h", year_month="2024-01").endswith(
        "/spot/monthly/klines/BTCUSDT/4h/BTCUSDT-4h-2024-01.zip"
    )


def test_monthly_agg_trades_url_uses_expected_binance_path() -> None:
    assert monthly_agg_trades_url(symbol="btcusdt", year_month="2024-01").endswith(
        "/spot/monthly/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2024-01.zip"
    )


def test_missing_data_error_is_a_value_error() -> None:
    assert issubclass(MissingBinanceDataError, ValueError)
