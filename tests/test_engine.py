from pathlib import Path

import polars as pl

from market_test_bench.catalog import Catalog
from market_test_bench.engine import load_report, run_simulation_engine
from market_test_bench.simulation import SimulationSettings, UploadedDecisionFile, create_simulation
from market_test_bench.workspace import Workspace


def test_engine_executes_strategy_reported_price(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    _create_engine_session(catalog, tmp_path)
    result = create_simulation(
        workspace=workspace,
        catalog=catalog,
        session_id="session_engine",
        name="Engine run",
        strategy_name="Close signal strategy",
        strategy_version=None,
        settings=SimulationSettings(fee_bps=0.0, slippage_bps=0.0, allow_short=False),
        files=[
            UploadedDecisionFile(
                file_name="decisions.csv",
                content=(
                    b"window_id,timestamp,symbol,target_quantity,price\n"
                    b"win_engine,2024-01-01T00:59:59.999999+00:00,BTCUSDT,1.0,115.0\n"
                ),
            )
        ],
    )

    engine_result = run_simulation_engine(
        workspace=workspace,
        catalog=catalog,
        simulation_id=result.simulation_id,
    )
    report = load_report(catalog=catalog, simulation_id=result.simulation_id)

    assert engine_result.status == "completed"
    assert report["summary"]["trade_count"] == 1
    assert report["summary"]["total_return_pct"] == 0.15
    assert report["window_metrics"][0]["final_equity"] == 10015.0
    trade = _read_csv(workspace.simulations_path / result.simulation_id / "results" / "trades.csv")[0]
    assert trade["price"] == "115.0"
    assert trade["execution_price"] == "115.0"
    assert trade["price_source"] == "strategy_csv"
    assert trade["slippage_cost"] == "0.0"


def test_engine_writes_report_artifacts_and_regime_summary(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    _create_engine_session(catalog, tmp_path)
    result = create_simulation(
        workspace=workspace,
        catalog=catalog,
        session_id="session_engine",
        name="Flat run",
        strategy_name="No signal strategy",
        strategy_version=None,
        settings=SimulationSettings(fee_bps=0.0, slippage_bps=0.0, allow_short=False),
        files=[
            UploadedDecisionFile(
                file_name="decisions.csv",
                content=b"window_id,timestamp,symbol,target_quantity,price\n",
            )
        ],
    )

    run_simulation_engine(workspace=workspace, catalog=catalog, simulation_id=result.simulation_id)
    results_path = workspace.simulations_path / result.simulation_id / "results"
    report = load_report(catalog=catalog, simulation_id=result.simulation_id)

    assert (results_path / "report.json").exists()
    assert (results_path / "window_metrics.csv").exists()
    assert (results_path / "regime_summary.csv").exists()
    assert (results_path / "trades.csv").exists()
    assert (results_path / "equity_curve.csv").exists()
    assert report["summary"]["total_return_pct"] == 0.0
    assert report["regime_summary"][0]["label"] == "bull"


def test_delete_report_endpoint_removes_results_and_marks_simulation_valid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from market_test_bench.server import app as app_module

    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    _create_engine_session(catalog, tmp_path)
    result = create_simulation(
        workspace=workspace,
        catalog=catalog,
        session_id="session_engine",
        name="Delete report run",
        strategy_name="No signal strategy",
        strategy_version=None,
        settings=SimulationSettings(fee_bps=0.0, slippage_bps=0.0, allow_short=False),
        files=[
            UploadedDecisionFile(
                file_name="decisions.csv",
                content=b"window_id,timestamp,symbol,target_quantity,price\n",
            )
        ],
    )
    run_simulation_engine(workspace=workspace, catalog=catalog, simulation_id=result.simulation_id)
    monkeypatch.setattr(app_module, "workspace", workspace)
    monkeypatch.setattr(app_module, "catalog", catalog)

    response = app_module.delete_report(result.simulation_id)

    assert response == {"status": "deleted", "simulation_id": result.simulation_id}
    assert not (workspace.simulations_path / result.simulation_id / "results" / "report.json").exists()
    assert catalog.get_simulation(result.simulation_id)["status"] == "valid"


def _create_engine_session(catalog: Catalog, tmp_path: Path) -> None:
    session_path = tmp_path / "sessions" / "session_engine"
    parquet_path = session_path / "data" / "klines" / "BTCUSDT_1h_2024-01.parquet"
    parquet_path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "timestamp": [
                "2024-01-01T00:00:00",
                "2024-01-01T01:00:00",
                "2024-01-01T02:00:00",
            ],
            "symbol": ["BTCUSDT", "BTCUSDT", "BTCUSDT"],
            "source": ["binance", "binance", "binance"],
            "interval": ["1h", "1h", "1h"],
            "open_time": [1_704_067_200_000_000, 1_704_070_800_000_000, 1_704_074_400_000_000],
            "open": [100.0, 110.0, 120.0],
            "high": [112.0, 122.0, 132.0],
            "low": [98.0, 108.0, 118.0],
            "close": [110.0, 120.0, 130.0],
            "volume": [1.0, 1.0, 1.0],
            "close_time": [1_704_070_799_999_999, 1_704_074_399_999_999, 1_704_077_999_999_999],
            "quote_volume": [100.0, 110.0, 120.0],
            "trade_count": [10, 10, 10],
            "taker_buy_base_volume": [0.5, 0.5, 0.5],
            "taker_buy_quote_volume": [50.0, 55.0, 60.0],
            "is_synthetic": [False, False, False],
        }
    ).write_parquet(parquet_path)
    normalized_id = catalog.upsert_normalized_file(
        source="binance",
        market="spot",
        data_type="klines",
        symbol="BTCUSDT",
        interval="1h",
        year_month="2024-01",
        path=parquet_path,
        row_count=3,
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-01-01T02:00:00+00:00",
        file_size_bytes=parquet_path.stat().st_size,
        sha256="abc",
        status="normalized",
    )
    catalog.upsert_classification(
        normalized_file_id=normalized_id,
        labels='["bull"]',
        features_json="{}",
    )
    catalog.create_session(
        session_id="session_engine",
        name="engine",
        source="binance",
        market="spot",
        data_type="klines",
        interval="1h",
        start_month="2024-01",
        end_month="2024-01",
        target_file_count=100,
        seed=42,
        status="ready",
        path=session_path,
    )
    catalog.add_session_file(
        session_id="session_engine",
        normalized_file_id=normalized_id,
        session_path=parquet_path,
        sort_order=0,
    )
    catalog.add_session_window(
        session_id="session_engine",
        window_id="win_engine",
        normalized_file_id=normalized_id,
        symbol="BTCUSDT",
        interval="1h",
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-01-01T02:00:00+00:00",
        row_count=3,
        sort_order=0,
    )


def _read_csv(path: Path) -> list[dict]:
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
