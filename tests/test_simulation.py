from pathlib import Path

from market_test_bench.catalog import Catalog
from market_test_bench.simulation import (
    SimulationSettings,
    UploadedDecisionFile,
    create_simulation,
)
from market_test_bench.workspace import Workspace


def test_create_simulation_stores_valid_upload(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    _create_ready_session(catalog, tmp_path)

    result = create_simulation(
        workspace=workspace,
        catalog=catalog,
        session_id="session_test",
        name="Smoke run",
        strategy_name="Example strategy",
        strategy_version="v1",
        settings=SimulationSettings(allow_short=False),
        files=[
            UploadedDecisionFile(
                file_name="decisions.csv",
                content=b"timestamp,symbol,target_quantity\n2024-01-01T00:00:00Z,BTCUSDT,0.125\n",
            )
        ],
    )

    simulations = catalog.list_simulations()
    files = catalog.list_simulation_files(result.simulation_id)

    assert result.status == "valid"
    assert result.row_count == 1
    assert simulations[0]["strategy_name"] == "Example strategy"
    assert files[0]["file_name"] == "decisions.csv"
    assert (workspace.simulations_path / result.simulation_id / "simulation.json").exists()


def test_create_simulation_records_validation_errors(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    _create_ready_session(catalog, tmp_path)

    result = create_simulation(
        workspace=workspace,
        catalog=catalog,
        session_id="session_test",
        name="Bad run",
        strategy_name="Example strategy",
        strategy_version=None,
        settings=SimulationSettings(allow_short=False),
        files=[
            UploadedDecisionFile(
                file_name="../bad decisions.txt",
                content=b"timestamp,symbol,target_quantity\n2024-01-01T00:00:00Z,ETHUSDT,-0.5\n",
            )
        ],
    )

    validation = catalog.list_simulation_validation_results(result.simulation_id)
    issue_codes = {item["issue_code"] for item in validation}

    assert result.status == "invalid"
    assert "unknown_symbol" in issue_codes
    assert "short_not_allowed" in issue_codes
    assert catalog.list_simulation_files(result.simulation_id)[0]["file_name"] == "bad_decisions.csv"


def test_create_simulation_accepts_header_only_upload(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    _create_ready_session(catalog, tmp_path)

    result = create_simulation(
        workspace=workspace,
        catalog=catalog,
        session_id="session_test",
        name="No signal run",
        strategy_name="Flat strategy",
        strategy_version=None,
        settings=SimulationSettings(allow_short=False),
        files=[
            UploadedDecisionFile(
                file_name="decisions.csv",
                content=b"window_id,timestamp,symbol,target_quantity\n",
            )
        ],
    )

    files = catalog.list_simulation_files(result.simulation_id)

    assert result.status == "valid"
    assert result.row_count == 0
    assert files[0]["row_count"] == 0


def test_delete_simulation_records_removes_files_and_validation_rows(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    _create_ready_session(catalog, tmp_path)

    result = create_simulation(
        workspace=workspace,
        catalog=catalog,
        session_id="session_test",
        name="Bad run",
        strategy_name="Example strategy",
        strategy_version=None,
        settings=SimulationSettings(allow_short=False),
        files=[
            UploadedDecisionFile(
                file_name="decisions.csv",
                content=b"timestamp,symbol,target_quantity\n2024-01-01T00:00:00Z,ETHUSDT,-0.5\n",
            )
        ],
    )

    deleted = catalog.delete_simulation_records(result.simulation_id)

    assert deleted is not None
    assert catalog.get_simulation(result.simulation_id) is None
    assert catalog.list_simulation_files(result.simulation_id) == []
    assert catalog.list_simulation_validation_results(result.simulation_id) == []


def test_delete_simulation_endpoint_removes_records_and_directory(tmp_path: Path, monkeypatch) -> None:
    from market_test_bench.server import app as app_module

    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    _create_ready_session(catalog, tmp_path)
    result = create_simulation(
        workspace=workspace,
        catalog=catalog,
        session_id="session_test",
        name="Smoke run",
        strategy_name="Example strategy",
        strategy_version=None,
        settings=SimulationSettings(),
        files=[
            UploadedDecisionFile(
                file_name="decisions.csv",
                content=b"timestamp,symbol,target_quantity\n2024-01-01T00:00:00Z,BTCUSDT,0.125\n",
            )
        ],
    )
    simulation_path = workspace.simulations_path / result.simulation_id
    monkeypatch.setattr(app_module, "workspace", workspace)
    monkeypatch.setattr(app_module, "catalog", catalog)

    response = app_module.delete_simulation(result.simulation_id)

    assert response == {"status": "deleted", "simulation_id": result.simulation_id}
    assert catalog.get_simulation(result.simulation_id) is None
    assert not simulation_path.exists()


def _create_ready_session(catalog: Catalog, tmp_path: Path) -> None:
    parquet_path = tmp_path / "sessions" / "session_test" / "data" / "klines" / "BTCUSDT_1h_2024-01.parquet"
    parquet_path.parent.mkdir(parents=True)
    parquet_path.write_bytes(b"fake parquet")
    normalized_id = catalog.upsert_normalized_file(
        source="binance",
        market="spot",
        data_type="klines",
        symbol="BTCUSDT",
        interval="1h",
        year_month="2024-01",
        path=parquet_path,
        row_count=31,
        start_time="2024-01-01T00:00:00",
        end_time="2024-01-31T00:00:00",
        file_size_bytes=parquet_path.stat().st_size,
        sha256="abc",
        status="normalized",
    )
    catalog.create_session(
        session_id="session_test",
        name="test",
        source="binance",
        market="spot",
        data_type="klines",
        interval="1h",
        start_month="2024-01",
        end_month="2024-01",
        target_file_count=100,
        seed=42,
        status="ready",
        path=tmp_path / "sessions" / "session_test",
    )
    catalog.add_session_file(
        session_id="session_test",
        normalized_file_id=normalized_id,
        session_path=parquet_path,
        sort_order=0,
    )
