from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass

import polars as pl

DEFAULT_TARGET_LABELS = {
    "bull": 15,
    "bear": 15,
    "sideways": 15,
    "high_volatility": 15,
    "low_volatility": 15,
    "crash": 5,
    "range_bound": 10,
    "breakout": 10,
}

VOLUME_SPIKE_THRESHOLDS = {
    "1m": 300.0,
    "3m": 150.0,
    "5m": 100.0,
    "15m": 60.0,
    "30m": 40.0,
    "1h": 25.0,
    "2h": 18.0,
    "4h": 12.0,
}
ROLLING_BREAK_LOOKBACK = {
    "1m": 1440,
    "3m": 480,
    "5m": 288,
    "15m": 96,
    "30m": 48,
    "1h": 24,
    "2h": 12,
    "4h": 6,
}
BREAKOUT_STRENGTH_THRESHOLDS = {
    "1m": 2.0,
    "3m": 2.5,
    "5m": 3.0,
    "15m": 3.5,
    "30m": 4.0,
    "1h": 5.0,
    "2h": 6.0,
    "4h": 7.0,
}
BREAKDOWN_STRENGTH_THRESHOLDS = {
    "1m": -4.0,
    "3m": -4.8,
    "5m": -4.3,
    "15m": -4.3,
    "30m": -5.0,
    "1h": -5.8,
    "2h": -6.1,
    "4h": -6.7,
}
TRENDING_SMOOTH_THRESHOLDS = {
    "1m": 0.014,
    "3m": 0.024,
    "5m": 0.030,
    "15m": 0.055,
    "30m": 0.080,
    "1h": 0.110,
    "2h": 0.160,
    "4h": 0.240,
}
CHOPPY_FLIP_THRESHOLDS = {
    "1m": 0.54,
    "3m": 0.535,
    "5m": 0.54,
    "15m": 0.545,
    "30m": 0.555,
    "1h": 0.56,
    "2h": 0.575,
    "4h": 0.59,
}


@dataclass(frozen=True)
class ClassificationResult:
    labels: tuple[str, ...]
    features: dict[str, float]

    def labels_json(self) -> str:
        return json.dumps(list(self.labels), separators=(",", ":"))

    def features_json(self) -> str:
        return json.dumps(self.features, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class LabelCoverage:
    target_counts: dict[str, int]
    current_counts: dict[str, int]

    @property
    def missing_labels(self) -> set[str]:
        return {
            label
            for label, target_count in self.target_counts.items()
            if self.current_counts.get(label, 0) < target_count
        }

    @property
    def is_satisfied(self) -> bool:
        return not self.missing_labels

    def accepts(self, labels: set[str]) -> bool:
        if self.is_satisfied:
            return True
        return bool(labels & self.missing_labels)


def classify_ohlcv(df: pl.DataFrame) -> ClassificationResult:
    if df.height < 2:
        raise ValueError("At least two bars are required for classification.")

    close = [float(value) for value in df["close"].to_list()]
    high = [float(value) for value in df["high"].to_list()]
    low = [float(value) for value in df["low"].to_list()]
    open_ = [float(value) for value in df["open"].to_list()]
    quote_volume = [float(value) for value in df["quote_volume"].to_list()]
    trade_count = [float(value) for value in df["trade_count"].to_list()]
    interval = str(df["interval"][0]) if "interval" in df.columns else "1h"

    log_returns = [
        math.log(close[index] / close[index - 1])
        for index in range(1, len(close))
        if close[index] > 0 and close[index - 1] > 0
    ]
    return_pct = _pct(close[-1] / close[0] - 1.0)
    realized_vol_pct = _pct(_stddev(log_returns) * math.sqrt(max(len(log_returns), 1)))
    max_drawdown_pct = _max_drawdown_pct(close)
    max_runup_pct = _max_runup_pct(close)
    trend_efficiency = abs(close[-1] - close[0]) / max(sum(_abs_diffs(close)), 1e-12)
    avg_range_pct = _pct(sum((h - l) / c for h, l, c in zip(high, low, close)) / len(close))
    volume_change_pct = _pct((_median(quote_volume[-max(len(quote_volume) // 4, 1) :]) / max(_median(quote_volume[: max(len(quote_volume) // 4, 1)]), 1e-12)) - 1.0)
    volume_spike_ratio = _quantile(quote_volume, 0.99) / max(
        _median([value for value in quote_volume if value > 0]), 1e-12
    )
    direction_flip_rate = _direction_flip_rate(close)
    breakout_close_ratio = close[-1] / max(high[:-1])
    breakdown_close_ratio = close[-1] / min(low[:-1])
    breakout_strength = _max_rolling_breakout_strength(close, high, interval)
    breakdown_strength = _max_rolling_breakdown_strength(close, low, interval)
    wick_body_ratio = _wick_body_ratio(open_, high, low, close)

    features = {
        "return_pct": round(return_pct, 6),
        "realized_volatility_pct": round(realized_vol_pct, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "max_runup_pct": round(max_runup_pct, 6),
        "trend_efficiency": round(trend_efficiency, 6),
        "avg_range_pct": round(avg_range_pct, 6),
        "volume_change_pct": round(volume_change_pct, 6),
        "volume_spike_ratio": round(volume_spike_ratio, 6),
        "avg_quote_volume": round(sum(quote_volume) / len(quote_volume), 6),
        "avg_trade_count": round(sum(trade_count) / len(trade_count), 6),
        "direction_flip_rate": round(direction_flip_rate, 6),
        "breakout_close_ratio": round(breakout_close_ratio, 6),
        "breakdown_close_ratio": round(breakdown_close_ratio, 6),
        "breakout_strength": round(breakout_strength, 6),
        "breakdown_strength": round(breakdown_strength, 6),
        "wick_body_ratio": round(wick_body_ratio, 6),
    }

    labels: set[str] = set()

    if return_pct >= 25:
        labels.add("strong_bull")
    elif return_pct >= 8:
        labels.add("bull")
    elif return_pct <= -25:
        labels.add("strong_bear")
    elif return_pct <= -8:
        labels.add("bear")
    if abs(return_pct) <= 5 and trend_efficiency <= 0.35:
        labels.add("sideways")

    if realized_vol_pct <= 12:
        labels.add("low_volatility")
    elif realized_vol_pct >= 50:
        labels.add("extreme_volatility")
    elif realized_vol_pct >= 32:
        labels.add("high_volatility")
    else:
        labels.add("normal_volatility")

    if max_drawdown_pct <= -30:
        labels.add("crash")
    elif max_drawdown_pct <= -15:
        labels.add("deep_drawdown")
    if max_drawdown_pct <= -12 and max_runup_pct >= 15 and close[-1] > close[0]:
        labels.add("recovery")

    if volume_spike_ratio >= VOLUME_SPIKE_THRESHOLDS.get(interval, 25.0):
        labels.add("volume_spike")
    if volume_change_pct >= 80:
        labels.add("high_volume")
    elif volume_change_pct <= -50:
        labels.add("low_volume")
    else:
        labels.add("normal_volume")

    if breakout_strength >= BREAKOUT_STRENGTH_THRESHOLDS.get(interval, 5.0):
        labels.add("breakout")
    if breakdown_strength <= BREAKDOWN_STRENGTH_THRESHOLDS.get(interval, -5.8):
        labels.add("breakdown")
    if abs(return_pct) <= 6 and max_drawdown_pct > -12 and max_runup_pct < 12:
        labels.add("range_bound")
    if (
        direction_flip_rate >= CHOPPY_FLIP_THRESHOLDS.get(interval, 0.56)
        and trend_efficiency <= TRENDING_SMOOTH_THRESHOLDS.get(interval, 0.11)
    ):
        labels.add("choppy")
    if (
        trend_efficiency >= TRENDING_SMOOTH_THRESHOLDS.get(interval, 0.11)
        and direction_flip_rate <= CHOPPY_FLIP_THRESHOLDS.get(interval, 0.56)
    ):
        labels.add("trending_smooth")
    if wick_body_ratio >= 3:
        labels.add("wicky")

    return ClassificationResult(tuple(sorted(labels)), features)


def compute_coverage(results: list[ClassificationResult], target_counts: dict[str, int]) -> LabelCoverage:
    counts: dict[str, int] = {}
    for result in results:
        for label in result.labels:
            counts[label] = counts.get(label, 0) + 1
    return LabelCoverage(target_counts=target_counts, current_counts=counts)


def _pct(value: float) -> float:
    return value * 100


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _max_drawdown_pct(close: list[float]) -> float:
    peak = close[0]
    drawdown = 0.0
    for value in close:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1.0)
    return _pct(drawdown)


def _max_runup_pct(close: list[float]) -> float:
    trough = close[0]
    runup = 0.0
    for value in close:
        trough = min(trough, value)
        runup = max(runup, value / trough - 1.0)
    return _pct(runup)


def _abs_diffs(values: list[float]) -> list[float]:
    return [abs(values[index] - values[index - 1]) for index in range(1, len(values))]


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = min(max(int((len(sorted_values) - 1) * quantile), 0), len(sorted_values) - 1)
    return sorted_values[index]


def _direction_flip_rate(close: list[float]) -> float:
    directions = []
    for index in range(1, len(close)):
        diff = close[index] - close[index - 1]
        if diff > 0:
            directions.append(1)
        elif diff < 0:
            directions.append(-1)
    if len(directions) < 2:
        return 0.0
    flips = sum(
        1 for index in range(1, len(directions)) if directions[index] != directions[index - 1]
    )
    return flips / (len(directions) - 1)


def _wick_body_ratio(open_: list[float], high: list[float], low: list[float], close: list[float]) -> float:
    bodies = [abs(c - o) for o, c in zip(open_, close)]
    wicks = [(h - l) - body for h, l, body in zip(high, low, bodies)]
    return (sum(wicks) / len(wicks)) / max(sum(bodies) / len(bodies), 1e-12)


def _max_rolling_breakout_strength(close: list[float], high: list[float], interval: str) -> float:
    lookback = ROLLING_BREAK_LOOKBACK.get(interval, 24)
    if len(close) <= lookback:
        return 0.0
    rolling_high_indexes: deque[int] = deque()
    max_strength = 0.0
    for index in range(len(close)):
        if index > 0:
            incoming_index = index - 1
            while rolling_high_indexes and high[rolling_high_indexes[-1]] <= high[incoming_index]:
                rolling_high_indexes.pop()
            rolling_high_indexes.append(incoming_index)
        while rolling_high_indexes and rolling_high_indexes[0] < index - lookback:
            rolling_high_indexes.popleft()
        if index >= lookback and rolling_high_indexes:
            previous_high = high[rolling_high_indexes[0]]
            max_strength = max(max_strength, _pct(close[index] / previous_high - 1.0))
    return max_strength


def _max_rolling_breakdown_strength(close: list[float], low: list[float], interval: str) -> float:
    lookback = ROLLING_BREAK_LOOKBACK.get(interval, 24)
    if len(close) <= lookback:
        return 0.0
    rolling_low_indexes: deque[int] = deque()
    min_strength = 0.0
    for index in range(len(close)):
        if index > 0:
            incoming_index = index - 1
            while rolling_low_indexes and low[rolling_low_indexes[-1]] >= low[incoming_index]:
                rolling_low_indexes.pop()
            rolling_low_indexes.append(incoming_index)
        while rolling_low_indexes and rolling_low_indexes[0] < index - lookback:
            rolling_low_indexes.popleft()
        if index >= lookback and rolling_low_indexes:
            previous_low = low[rolling_low_indexes[0]]
            min_strength = min(min_strength, _pct(close[index] / previous_low - 1.0))
    return min_strength
