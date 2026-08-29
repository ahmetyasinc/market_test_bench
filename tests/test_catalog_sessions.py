from pathlib import Path

from market_test_bench.catalog import Catalog
from market_test_bench.workspace import Workspace


def test_catalog_tracks_sessions_and_session_files(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    parquet_path = tmp_path / "data" / "normalized" / "BTCUSDT_1d_2024-01.parquet"
    session_path = tmp_path / "sessions" / "session_test"
    session_file_path = session_path / "data" / "BTCUSDT_1d_2024-01.parquet"
    parquet_path.parent.mkdir(parents=True)
    session_file_path.parent.mkdir(parents=True)
    parquet_path.write_bytes(b"fake parquet")
    session_file_path.write_bytes(b"fake parquet")

    normalized_id = catalog.upsert_normalized_file(
        source="binance",
        market="spot",
        data_type="klines",
        symbol="BTCUSDT",
        interval="1d",
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
        interval="1d",
        start_month="2024-01",
        end_month="2024-01",
        target_file_count=100,
        seed=42,
        status="running",
        path=session_path,
    )
    catalog.add_session_file(
        session_id="session_test",
        normalized_file_id=normalized_id,
        session_path=session_file_path,
        sort_order=0,
    )
    catalog.add_session_window(
        session_id="session_test",
        window_id="win_binance_spot_BTCUSDT_1d_202401_abc123",
        normalized_file_id=normalized_id,
        symbol="BTCUSDT",
        interval="1d",
        start_time="2024-01-01T00:00:00",
        end_time="2024-01-31T00:00:00",
        row_count=31,
        sort_order=0,
    )
    catalog.update_session_status(session_id="session_test", status="ready")

    sessions = catalog.list_sessions()
    files = catalog.list_session_files("session_test")
    windows = catalog.list_session_windows("session_test")

    assert sessions[0]["status"] == "ready"
    assert sessions[0]["file_count"] == 1
    assert sessions[0]["window_count"] == 1
    assert files[0]["symbol"] == "BTCUSDT"
    assert files[0]["session_path"] == str(session_file_path)
    assert windows[0]["window_id"] == "win_binance_spot_BTCUSDT_1d_202401_abc123"


def test_delete_session_records_removes_unshared_files(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    session_path = tmp_path / "sessions" / "session_delete"
    session_file_path = session_path / "data" / "klines" / "BTCUSDT_1h_2024-01.parquet"
    session_file_path.parent.mkdir(parents=True)
    session_file_path.write_bytes(b"fake parquet")

    normalized_id = catalog.upsert_normalized_file(
        source="binance",
        market="spot",
        data_type="klines",
        symbol="BTCUSDT",
        interval="1h",
        year_month="2024-01",
        path=session_file_path,
        row_count=31,
        start_time="2024-01-01T00:00:00",
        end_time="2024-01-31T00:00:00",
        file_size_bytes=session_file_path.stat().st_size,
        sha256="abc",
        status="normalized",
    )
    catalog.upsert_classification(
        normalized_file_id=normalized_id,
        labels='["bull"]',
        features_json="{}",
    )
    catalog.create_session(
        session_id="session_delete",
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
        path=session_path,
    )
    catalog.add_session_file(
        session_id="session_delete",
        normalized_file_id=normalized_id,
        session_path=session_file_path,
        sort_order=0,
    )
    catalog.add_session_window(
        session_id="session_delete",
        window_id="win_binance_spot_BTCUSDT_1h_202401_delete",
        normalized_file_id=normalized_id,
        symbol="BTCUSDT",
        interval="1h",
        start_time="2024-01-01T00:00:00",
        end_time="2024-01-31T00:00:00",
        row_count=31,
        sort_order=0,
    )

    deleted = catalog.delete_session_records("session_delete")

    assert deleted is not None
    assert catalog.get_session("session_delete") is None
    assert catalog.list_session_windows("session_delete") == []
    assert catalog.list_normalized_files() == []


def test_delete_session_records_repoints_shared_files(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    catalog = Catalog(workspace)
    first_path = tmp_path / "sessions" / "session_a" / "data" / "klines" / "BTCUSDT_1h_2024-01.parquet"
    second_path = tmp_path / "sessions" / "session_b" / "data" / "klines" / "BTCUSDT_1h_2024-01.parquet"
    first_path.parent.mkdir(parents=True)
    second_path.parent.mkdir(parents=True)
    first_path.write_bytes(b"fake parquet")
    second_path.write_bytes(b"fake parquet")

    normalized_id = catalog.upsert_normalized_file(
        source="binance",
        market="spot",
        data_type="klines",
        symbol="BTCUSDT",
        interval="1h",
        year_month="2024-01",
        path=first_path,
        row_count=31,
        start_time="2024-01-01T00:00:00",
        end_time="2024-01-31T00:00:00",
        file_size_bytes=first_path.stat().st_size,
        sha256="abc",
        status="normalized",
    )
    for session_id, path in (("session_a", first_path.parent.parent.parent), ("session_b", second_path.parent.parent.parent)):
        catalog.create_session(
            session_id=session_id,
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
            path=path,
        )
    catalog.add_session_file(
        session_id="session_a",
        normalized_file_id=normalized_id,
        session_path=first_path,
        sort_order=0,
    )
    catalog.add_session_file(
        session_id="session_b",
        normalized_file_id=normalized_id,
        session_path=second_path,
        sort_order=0,
    )

    catalog.delete_session_records("session_a")
    files = catalog.list_normalized_files()

    assert len(files) == 1
    assert files[0]["path"] == str(second_path)
