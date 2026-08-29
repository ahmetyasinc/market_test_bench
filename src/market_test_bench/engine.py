from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from market_test_bench.catalog import Catalog
from market_test_bench.simulation import STANDARD_INITIAL_CASH_USDT
from market_test_bench.workspace import Workspace

WINDOW_METRIC_FIELDS = (
    "window_id",
    "symbol",
    "interval",
    "year_month",
    "start_time",
    "end_time",
    "labels",
    "bar_count",
    "decision_count",
    "trade_count",
    "initial_cash",
    "final_equity",
    "pnl",
    "return_pct",
    "max_drawdown_pct",
    "buy_and_hold_return_pct",
    "fee_total",
    "slippage_total",
    "turnover",
    "max_exposure",
    "max_balance_usage_pct",
    "average_balance_usage_pct",
    "ending_quantity",
    "ending_cash",
)
REGIME_SUMMARY_FIELDS = (
    "label",
    "window_count",
    "trade_count",
    "average_return_pct",
    "median_return_pct",
    "best_return_pct",
    "worst_return_pct",
    "winning_window_pct",
    "max_drawdown_pct",
    "fee_total",
    "slippage_total",
    "turnover",
)
TRADE_FIELDS = (
    "window_id",
    "timestamp",
    "decision_timestamp",
    "symbol",
    "side",
    "delta_quantity",
    "target_quantity",
    "price",
    "execution_price",
    "notional",
    "fee",
    "slippage_cost",
    "price_source",
    "source_file",
    "source_row",
)
EQUITY_FIELDS = (
    "window_id",
    "timestamp",
    "symbol",
    "open_time",
    "close",
    "cash",
    "quantity",
    "equity",
    "drawdown_pct",
    "exposure",
    "balance_usage_pct",
)


@dataclass(frozen=True)
class DecisionEvent:
    window_id: str | None
    timestamp_us: int
    symbol: str
    target_quantity: float
    execution_price: float
    source_file: str
    row_number: int


@dataclass(frozen=True)
class FillEvent:
    window_id: str
    timestamp_us: int
    decision_timestamp_us: int
    symbol: str
    target_quantity: float
    execution_price: float
    price_source: str
    source_file: str
    row_number: int


@dataclass(frozen=True)
class EngineResult:
    simulation_id: str
    status: str
    report_path: Path
    total_return_pct: float
    trade_count: int
    window_count: int


def run_simulation_engine(*, workspace: Workspace, catalog: Catalog, simulation_id: str) -> EngineResult:
    simulation = catalog.get_simulation(simulation_id)
    if simulation is None:
        raise ValueError("Simulation not found.")
    if simulation["status"] == "invalid" or int(simulation.get("error_count") or 0) > 0:
        raise ValueError("Only valid simulation uploads can be executed.")

    settings = _load_settings(simulation)
    simulation_path = Path(simulation["path"])
    results_path = simulation_path / "results"
    results_path.mkdir(parents=True, exist_ok=True)

    windows = catalog.list_session_windows(str(simulation["session_id"]))
    if not windows:
        raise ValueError("Selected session does not contain windows.")

    decisions = _read_decisions(catalog.list_simulation_files(simulation_id))
    catalog.update_simulation_status(simulation_id=simulation_id, status="running")
    window_metrics: list[dict] = []
    equity_rows: list[dict] = []
    trade_rows: list[dict] = []

    for window in windows:
        result = _run_window(
            window=window,
            settings=settings,
            decisions=decisions,
        )
        window_metrics.append(result["metrics"])
        equity_rows.extend(result["equity_rows"])
        trade_rows.extend(result["trade_rows"])

    regime_summary = _build_regime_summary(window_metrics)
    summary = _build_summary(window_metrics, trade_rows, settings)
    report = {
        "simulation": {
            "id": simulation_id,
            "name": simulation["name"],
            "strategy_name": simulation["strategy_name"],
            "strategy_version": simulation["strategy_version"],
            "session_id": simulation["session_id"],
            "created_at": simulation["created_at"],
            "completed_at": datetime.now(UTC).isoformat(),
        },
        "settings": settings,
        "summary": summary,
        "regime_summary": regime_summary,
        "window_metrics": window_metrics,
        "artifacts": {
            "report": str(results_path / "report.json"),
            "window_metrics": str(results_path / "window_metrics.csv"),
            "regime_summary": str(results_path / "regime_summary.csv"),
            "trades": str(results_path / "trades.csv"),
            "equity_curve": str(results_path / "equity_curve.csv"),
        },
    }

    _write_csv(results_path / "window_metrics.csv", window_metrics, WINDOW_METRIC_FIELDS)
    _write_csv(results_path / "regime_summary.csv", regime_summary, REGIME_SUMMARY_FIELDS)
    _write_csv(results_path / "trades.csv", trade_rows, TRADE_FIELDS)
    _write_csv(results_path / "equity_curve.csv", equity_rows, EQUITY_FIELDS)
    (results_path / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    catalog.update_simulation_status(simulation_id=simulation_id, status="completed")

    return EngineResult(
        simulation_id=simulation_id,
        status="completed",
        report_path=results_path / "report.json",
        total_return_pct=float(summary["total_return_pct"]),
        trade_count=len(trade_rows),
        window_count=len(window_metrics),
    )


def load_report(*, catalog: Catalog, simulation_id: str) -> dict:
    simulation = catalog.get_simulation(simulation_id)
    if simulation is None:
        raise ValueError("Simulation not found.")
    report_path = Path(simulation["path"]) / "results" / "report.json"
    if not report_path.exists():
        raise ValueError("Report has not been generated yet.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    results_path = report_path.parent
    report["equity_curve"] = _read_grouped_csv_sample(
        results_path / "equity_curve.csv",
        key="window_id",
        max_rows_per_group=240,
    )
    report["trades"] = _read_grouped_csv_sample(
        results_path / "trades.csv",
        key="window_id",
        max_rows_per_group=80,
    )
    report["artifact_row_limits"] = {
        "equity_curve_max_rows_per_window": 240,
        "trades_max_rows_per_window": 80,
    }
    return report


def _run_window(
    *,
    window: dict,
    settings: dict,
    decisions: list[DecisionEvent],
) -> dict:
    window_id = str(window["window_id"])
    symbol = str(window["symbol"])
    market = pl.read_parquet(window["session_path"]).sort("open_time")
    if market.is_empty():
        raise ValueError(f"{window_id} has no market rows.")

    fills = _build_fills(
        window=window,
        decisions=decisions,
    )
    fills_by_close_time: dict[int, list[FillEvent]] = {}
    for fill in fills:
        fills_by_close_time.setdefault(fill.timestamp_us, []).append(fill)

    cash = float(settings["initial_cash"])
    quantity = 0.0
    total_fees = 0.0
    total_slippage = 0.0
    turnover = 0.0
    max_exposure = 0.0
    exposure_values: list[float] = []
    trade_rows: list[dict] = []
    equity_rows: list[dict] = []
    equity_values: list[float] = []

    for row in market.iter_rows(named=True):
        close_time = int(row["close_time"])
        open_time = int(row["open_time"])
        close_price = float(row["close"])
        due_times = [timestamp for timestamp in fills_by_close_time if timestamp <= close_time]
        for timestamp in sorted(due_times):
            for fill in fills_by_close_time.pop(timestamp):
                delta = fill.target_quantity - quantity
                if abs(delta) <= 1e-12:
                    continue
                side = "buy" if delta > 0 else "sell"
                execution_price = fill.execution_price
                notional = abs(delta) * execution_price
                fee = notional * float(settings["fee_bps"]) / 10_000
                slippage_cost = 0.0
                cash -= delta * execution_price
                cash -= fee
                quantity = fill.target_quantity
                total_fees += fee
                total_slippage += slippage_cost
                turnover += notional
                trade_rows.append(
                    {
                        "window_id": window_id,
                        "timestamp": _iso_from_us(fill.timestamp_us),
                        "decision_timestamp": _iso_from_us(fill.decision_timestamp_us),
                        "symbol": symbol,
                        "side": side,
                        "delta_quantity": round(delta, 12),
                        "target_quantity": round(fill.target_quantity, 12),
                        "price": round(fill.execution_price, 12),
                        "execution_price": round(execution_price, 12),
                        "notional": round(notional, 8),
                        "fee": round(fee, 8),
                        "slippage_cost": round(slippage_cost, 8),
                        "price_source": fill.price_source,
                        "source_file": fill.source_file,
                        "source_row": fill.row_number,
                    }
                )
        equity = cash + quantity * close_price
        exposure = abs(quantity * close_price)
        max_exposure = max(max_exposure, exposure)
        exposure_values.append(exposure)
        equity_values.append(equity)
        drawdown_pct = _current_drawdown_pct(equity_values)
        balance_usage_pct = _pct(exposure / float(settings["initial_cash"]))
        equity_rows.append(
            {
                "window_id": window_id,
                "timestamp": _iso_from_us(close_time),
                "symbol": symbol,
                "open_time": _iso_from_us(open_time),
                "close": round(close_price, 12),
                "cash": round(cash, 8),
                "quantity": round(quantity, 12),
                "equity": round(equity, 8),
                "drawdown_pct": round(drawdown_pct, 8),
                "exposure": round(exposure, 8),
                "balance_usage_pct": round(balance_usage_pct, 8),
            }
        )

    final_close = float(market["close"][-1])
    start_close = float(market["close"][0])
    labels = _labels(window)
    metrics = {
        "window_id": window_id,
        "symbol": symbol,
        "interval": window["interval"],
        "year_month": window["year_month"],
        "start_time": window["start_time"],
        "end_time": window["end_time"],
        "labels": "|".join(labels),
        "bar_count": market.height,
        "decision_count": len(_matching_decisions(window, decisions)),
        "trade_count": len(trade_rows),
        "initial_cash": round(float(settings["initial_cash"]), 8),
        "final_equity": round(equity_values[-1], 8),
        "pnl": round(equity_values[-1] - float(settings["initial_cash"]), 8),
        "return_pct": round(_pct(equity_values[-1] / float(settings["initial_cash"]) - 1), 8),
        "max_drawdown_pct": round(_max_drawdown_pct(equity_values), 8),
        "buy_and_hold_return_pct": round(_pct(final_close / start_close - 1), 8),
        "fee_total": round(total_fees, 8),
        "slippage_total": round(total_slippage, 8),
        "turnover": round(turnover, 8),
        "max_exposure": round(max_exposure, 8),
        "max_balance_usage_pct": round(_pct(max_exposure / float(settings["initial_cash"])), 8),
        "average_balance_usage_pct": round(
            _pct(_mean(exposure_values) / float(settings["initial_cash"])),
            8,
        ),
        "ending_quantity": round(quantity, 12),
        "ending_cash": round(cash, 8),
    }
    return {"metrics": metrics, "equity_rows": equity_rows, "trade_rows": trade_rows}


def _build_fills(
    *,
    window: dict,
    decisions: list[DecisionEvent],
) -> list[FillEvent]:
    fills: list[FillEvent] = []
    for decision in _matching_decisions(window, decisions):
        fills.append(
            FillEvent(
                window_id=str(window["window_id"]),
                timestamp_us=decision.timestamp_us,
                decision_timestamp_us=decision.timestamp_us,
                symbol=decision.symbol,
                target_quantity=decision.target_quantity,
                execution_price=decision.execution_price,
                price_source="strategy_csv",
                source_file=decision.source_file,
                row_number=decision.row_number,
            )
        )
    return sorted(fills, key=lambda item: (item.timestamp_us, item.row_number))


def _matching_decisions(window: dict, decisions: list[DecisionEvent]) -> list[DecisionEvent]:
    window_id = str(window["window_id"])
    symbol = str(window["symbol"])
    start_us = _timestamp_to_us(str(window["start_time"]))
    end_us = _timestamp_to_us(str(window["end_time"]))
    return [
        decision
        for decision in decisions
        if decision.symbol == symbol
        and (decision.window_id in {None, "", window_id})
        and start_us <= decision.timestamp_us <= end_us
    ]


def _read_decisions(files: list[dict]) -> list[DecisionEvent]:
    decisions: list[DecisionEvent] = []
    for file in files:
        path = Path(file["path"])
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row_number, row in enumerate(reader, start=2):
                decisions.append(
                    DecisionEvent(
                        window_id=(row.get("window_id") or None),
                        timestamp_us=_timestamp_to_us(str(row["timestamp"])),
                        symbol=_normalize_symbol(str(row["symbol"])),
                        target_quantity=float(row["target_quantity"]),
                        execution_price=float(row["price"]),
                        source_file=str(file["file_name"]),
                        row_number=row_number,
                    )
                )
    return sorted(decisions, key=lambda item: (item.timestamp_us, item.source_file, item.row_number))


def _build_summary(window_metrics: list[dict], trade_rows: list[dict], settings: dict) -> dict:
    initial_cash = float(settings["initial_cash"])
    final_equity = sum(float(row["final_equity"]) for row in window_metrics)
    starting_equity = initial_cash * len(window_metrics)
    returns = [float(row["return_pct"]) for row in window_metrics]
    winning_windows = sum(1 for value in returns if value > 0)
    return {
        "window_count": len(window_metrics),
        "trade_count": len(trade_rows),
        "starting_equity": round(starting_equity, 8),
        "final_equity": round(final_equity, 8),
        "pnl": round(final_equity - starting_equity, 8),
        "total_return_pct": round(_pct(final_equity / starting_equity - 1), 8)
        if starting_equity
        else 0.0,
        "average_window_return_pct": round(_mean(returns), 8),
        "median_window_return_pct": round(_median(returns), 8),
        "best_window_return_pct": round(max(returns, default=0.0), 8),
        "worst_window_return_pct": round(min(returns, default=0.0), 8),
        "winning_window_pct": round(_pct(winning_windows / max(len(window_metrics), 1)), 8),
        "max_window_drawdown_pct": round(min((float(row["max_drawdown_pct"]) for row in window_metrics), default=0.0), 8),
        "fee_total": round(sum(float(row["fee_total"]) for row in window_metrics), 8),
        "slippage_total": round(sum(float(row["slippage_total"]) for row in window_metrics), 8),
        "turnover": round(sum(float(row["turnover"]) for row in window_metrics), 8),
    }


def _build_regime_summary(window_metrics: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in window_metrics:
        labels = str(row["labels"]).split("|") if row["labels"] else ["unlabeled"]
        for label in labels:
            groups.setdefault(label, []).append(row)
    summaries = []
    for label, rows in sorted(groups.items()):
        returns = [float(row["return_pct"]) for row in rows]
        summaries.append(
            {
                "label": label,
                "window_count": len(rows),
                "trade_count": sum(int(row["trade_count"]) for row in rows),
                "average_return_pct": round(_mean(returns), 8),
                "median_return_pct": round(_median(returns), 8),
                "best_return_pct": round(max(returns, default=0.0), 8),
                "worst_return_pct": round(min(returns, default=0.0), 8),
                "winning_window_pct": round(
                    _pct(sum(1 for value in returns if value > 0) / max(len(returns), 1)),
                    8,
                ),
                "max_drawdown_pct": round(min((float(row["max_drawdown_pct"]) for row in rows), default=0.0), 8),
                "fee_total": round(sum(float(row["fee_total"]) for row in rows), 8),
                "slippage_total": round(sum(float(row["slippage_total"]) for row in rows), 8),
                "turnover": round(sum(float(row["turnover"]) for row in rows), 8),
            }
        )
    return summaries


def _load_settings(simulation: dict) -> dict:
    defaults = {
        "initial_cash": STANDARD_INITIAL_CASH_USDT,
        "fee_bps": 10.0,
        "slippage_bps": 0.0,
        "allow_short": False,
        "missing_decision_policy": "hold_last",
        "timestamp_alignment_policy": "exact_or_next_open",
    }
    try:
        loaded = json.loads(simulation["settings_json"])
    except (TypeError, json.JSONDecodeError):
        loaded = {}
    return defaults | loaded


def _write_csv(path: Path, rows: list[dict], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _read_grouped_csv_sample(path: Path, *, key: str, max_rows_per_group: int) -> list[dict]:
    if not path.exists():
        return []
    sampled_rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        current_key: str | None = None
        current_rows: list[dict] = []
        for row in reader:
            row_key = str(row.get(key) or "")
            if current_key is None:
                current_key = row_key
            if row_key != current_key:
                sampled_rows.extend(_downsample_rows(current_rows, max_rows_per_group))
                current_key = row_key
                current_rows = []
            current_rows.append(row)
        if current_rows:
            sampled_rows.extend(_downsample_rows(current_rows, max_rows_per_group))
    return sampled_rows


def _downsample_rows(rows: list[dict], max_rows: int) -> list[dict]:
    if len(rows) <= max_rows:
        return rows
    if max_rows <= 1:
        return [rows[-1]]
    last_index = len(rows) - 1
    selected_indexes = {
        round(index * last_index / (max_rows - 1))
        for index in range(max_rows)
    }
    return [rows[index] for index in sorted(selected_indexes)]


def _labels(window: dict) -> list[str]:
    try:
        labels = json.loads(window.get("labels") or "[]")
    except (TypeError, json.JSONDecodeError):
        labels = []
    return [str(label) for label in labels]


def _max_drawdown_pct(values: list[float]) -> float:
    peak = values[0] if values else 0.0
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, value / peak - 1)
    return _pct(drawdown)


def _current_drawdown_pct(values: list[float]) -> float:
    peak = max(values) if values else 0.0
    if peak <= 0 or not values:
        return 0.0
    return _pct(values[-1] / peak - 1)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _pct(value: float) -> float:
    return value * 100


def _timestamp_to_us(value: str) -> int:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000_000)


def _iso_from_us(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000, tz=UTC).isoformat()


def _normalize_symbol(value: str) -> str:
    return value.upper().replace("-", "").replace("/", "").strip()
