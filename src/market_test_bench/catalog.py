from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from market_test_bench.workspace import Workspace

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS normalized_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    market TEXT NOT NULL,
    data_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    year_month TEXT NOT NULL,
    path TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, market, data_type, symbol, interval, year_month)
);

CREATE TABLE IF NOT EXISTS validation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_file_id INTEGER,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    year_month TEXT NOT NULL,
    status TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(normalized_file_id) REFERENCES normalized_files(id)
);

CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_file_id INTEGER NOT NULL,
    labels TEXT NOT NULL,
    features_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(normalized_file_id) REFERENCES normalized_files(id),
    UNIQUE(normalized_file_id)
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    market TEXT NOT NULL,
    data_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    year_month TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    market TEXT NOT NULL,
    data_type TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_month TEXT NOT NULL,
    end_month TEXT NOT NULL,
    target_file_count INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    status TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS session_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    normalized_file_id INTEGER NOT NULL,
    session_path TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    FOREIGN KEY(normalized_file_id) REFERENCES normalized_files(id),
    UNIQUE(session_id, normalized_file_id)
);

CREATE TABLE IF NOT EXISTS session_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    window_id TEXT NOT NULL,
    normalized_file_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(id),
    FOREIGN KEY(normalized_file_id) REFERENCES normalized_files(id),
    UNIQUE(session_id, window_id),
    UNIQUE(session_id, normalized_file_id)
);

CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    session_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT,
    status TEXT NOT NULL,
    path TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS simulation_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    path TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(simulation_id) REFERENCES simulations(id)
);

CREATE TABLE IF NOT EXISTS simulation_validation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL,
    file_name TEXT,
    row_number INTEGER,
    status TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(simulation_id) REFERENCES simulations(id)
);
"""


class Catalog:
    def __init__(self, workspace: Workspace):
        self.path = workspace.catalog_path
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(SCHEMA)

    def list_normalized_files(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT nf.*, c.labels, c.features_json
                FROM normalized_files nf
                LEFT JOIN classifications c ON c.normalized_file_id = nf.id
                ORDER BY nf.symbol, nf.interval, nf.year_month
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_all_data_records(self) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM simulation_validation_results")
            connection.execute("DELETE FROM simulation_files")
            connection.execute("DELETE FROM simulations")
            connection.execute("DELETE FROM session_windows")
            connection.execute("DELETE FROM session_files")
            connection.execute("DELETE FROM sessions")
            connection.execute("DELETE FROM classifications")
            connection.execute("DELETE FROM validation_results")
            connection.execute("DELETE FROM download_jobs")
            connection.execute("DELETE FROM normalized_files")

    def list_sessions(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.*,
                    COUNT(DISTINCT CASE WHEN nf.data_type = 'klines' THEN sf.id END) AS file_count,
                    COUNT(DISTINCT CASE WHEN nf.data_type = 'aggTrades' THEN sf.id END) AS agg_trades_file_count,
                    COUNT(DISTINCT sf.id) AS total_file_count,
                    COUNT(DISTINCT sw.id) AS window_count,
                    COUNT(DISTINCT CASE WHEN nf.data_type = 'klines' THEN nf.symbol END) AS symbol_count
                FROM sessions s
                LEFT JOIN session_files sf ON sf.session_id = s.id
                LEFT JOIN normalized_files nf ON nf.id = sf.normalized_file_id
                LEFT JOIN session_windows sw ON sw.session_id = s.id
                GROUP BY s.id
                ORDER BY s.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    s.*,
                    COUNT(DISTINCT CASE WHEN nf.data_type = 'klines' THEN sf.id END) AS file_count,
                    COUNT(DISTINCT CASE WHEN nf.data_type = 'aggTrades' THEN sf.id END) AS agg_trades_file_count,
                    COUNT(DISTINCT sf.id) AS total_file_count,
                    COUNT(DISTINCT sw.id) AS window_count,
                    COUNT(DISTINCT CASE WHEN nf.data_type = 'klines' THEN nf.symbol END) AS symbol_count
                FROM sessions s
                LEFT JOIN session_files sf ON sf.session_id = s.id
                LEFT JOIN normalized_files nf ON nf.id = sf.normalized_file_id
                LEFT JOIN session_windows sw ON sw.session_id = s.id
                WHERE s.id = ?
                GROUP BY s.id
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_session_files(self, session_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT nf.*, c.labels, c.features_json, sf.session_path, sf.sort_order
                FROM session_files sf
                JOIN normalized_files nf ON nf.id = sf.normalized_file_id
                LEFT JOIN classifications c ON c.normalized_file_id = nf.id
                WHERE sf.session_id = ?
                ORDER BY sf.sort_order
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_session_windows(self, session_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    sw.*,
                    nf.source,
                    nf.market,
                    nf.data_type,
                    nf.year_month,
                    nf.path,
                    nf.sha256,
                    sf.session_path,
                    c.labels,
                    c.features_json
                FROM session_windows sw
                JOIN normalized_files nf ON nf.id = sw.normalized_file_id
                JOIN session_files sf
                    ON sf.session_id = sw.session_id
                    AND sf.normalized_file_id = sw.normalized_file_id
                LEFT JOIN classifications c ON c.normalized_file_id = nf.id
                WHERE sw.session_id = ?
                ORDER BY sw.sort_order
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_simulations(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    sim.*,
                    s.interval,
                    s.start_month,
                    s.end_month,
                    COUNT(sf.id) AS file_count,
                    COUNT(CASE WHEN svr.status = 'error' THEN 1 END) AS error_count
                FROM simulations sim
                LEFT JOIN sessions s ON s.id = sim.session_id
                LEFT JOIN simulation_files sf ON sf.simulation_id = sim.id
                LEFT JOIN simulation_validation_results svr ON svr.simulation_id = sim.id
                GROUP BY sim.id
                ORDER BY sim.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_simulation(self, simulation_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    sim.*,
                    s.interval,
                    s.start_month,
                    s.end_month,
                    COUNT(sf.id) AS file_count,
                    COUNT(CASE WHEN svr.status = 'error' THEN 1 END) AS error_count
                FROM simulations sim
                LEFT JOIN sessions s ON s.id = sim.session_id
                LEFT JOIN simulation_files sf ON sf.simulation_id = sim.id
                LEFT JOIN simulation_validation_results svr ON svr.simulation_id = sim.id
                WHERE sim.id = ?
                GROUP BY sim.id
                """,
                (simulation_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_simulation_files(self, simulation_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM simulation_files
                WHERE simulation_id = ?
                ORDER BY file_name
                """,
                (simulation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_simulation_validation_results(self, simulation_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM simulation_validation_results
                WHERE simulation_id = ?
                ORDER BY file_name, row_number, id
                """,
                (simulation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_simulation_records(self, simulation_id: str) -> dict | None:
        with self.connect() as connection:
            simulation = connection.execute(
                "SELECT * FROM simulations WHERE id = ?",
                (simulation_id,),
            ).fetchone()
            if simulation is None:
                return None

            connection.execute(
                "DELETE FROM simulation_validation_results WHERE simulation_id = ?",
                (simulation_id,),
            )
            connection.execute("DELETE FROM simulation_files WHERE simulation_id = ?", (simulation_id,))
            connection.execute("DELETE FROM simulations WHERE id = ?", (simulation_id,))
        return dict(simulation)

    def create_simulation(
        self,
        *,
        simulation_id: str,
        name: str,
        session_id: str,
        strategy_name: str,
        strategy_version: str | None,
        status: str,
        path: Path,
        settings_json: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO simulations (
                    id, name, session_id, strategy_name, strategy_version, status, path, settings_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    simulation_id,
                    name,
                    session_id,
                    strategy_name,
                    strategy_version,
                    status,
                    str(path),
                    settings_json,
                ),
            )

    def update_simulation_status(self, *, simulation_id: str, status: str) -> None:
        completed_sql = ", completed_at = CURRENT_TIMESTAMP" if status in {"completed", "failed"} else ""
        with self.connect() as connection:
            connection.execute(
                f"UPDATE simulations SET status = ?{completed_sql} WHERE id = ?",
                (status, simulation_id),
            )

    def add_simulation_file(
        self,
        *,
        simulation_id: str,
        file_name: str,
        path: Path,
        row_count: int,
        status: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO simulation_files (simulation_id, file_name, path, row_count, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (simulation_id, file_name, str(path), row_count, status),
            )

    def add_simulation_validation_result(
        self,
        *,
        simulation_id: str,
        file_name: str | None,
        row_number: int | None,
        status: str,
        issue_code: str,
        message: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO simulation_validation_results (
                    simulation_id, file_name, row_number, status, issue_code, message
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (simulation_id, file_name, row_number, status, issue_code, message),
            )

    def delete_session_records(self, session_id: str) -> dict | None:
        with self.connect() as connection:
            session = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                return None

            normalized_ids = [
                int(row["normalized_file_id"])
                for row in connection.execute(
                    "SELECT normalized_file_id FROM session_files WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
            ]

            connection.execute("DELETE FROM session_windows WHERE session_id = ?", (session_id,))
            for normalized_id in normalized_ids:
                replacement = connection.execute(
                    """
                    SELECT session_path
                    FROM session_files
                    WHERE normalized_file_id = ? AND session_id != ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (normalized_id, session_id),
                ).fetchone()
                if replacement:
                    connection.execute(
                        "UPDATE normalized_files SET path = ? WHERE id = ?",
                        (replacement["session_path"], normalized_id),
                    )
                    continue

                connection.execute(
                    "DELETE FROM validation_results WHERE normalized_file_id = ?",
                    (normalized_id,),
                )
                connection.execute(
                    "DELETE FROM classifications WHERE normalized_file_id = ?",
                    (normalized_id,),
                )
                connection.execute(
                    "DELETE FROM normalized_files WHERE id = ?",
                    (normalized_id,),
                )

            connection.execute("DELETE FROM session_files WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return dict(session)

    def get_normalized_file(
        self, *, source: str, market: str, data_type: str, symbol: str, interval: str, year_month: str
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM normalized_files
                WHERE source = ? AND market = ? AND data_type = ?
                  AND symbol = ? AND interval = ? AND year_month = ?
                """,
                (source, market, data_type, symbol, interval, year_month),
            ).fetchone()
        return dict(row) if row else None

    def normalized_file_exists(
        self, *, source: str, market: str, data_type: str, symbol: str, interval: str, year_month: str
    ) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM normalized_files
                WHERE source = ? AND market = ? AND data_type = ?
                  AND symbol = ? AND interval = ? AND year_month = ?
                """,
                (source, market, data_type, symbol, interval, year_month),
            ).fetchone()
        return row is not None

    def create_session(
        self,
        *,
        session_id: str,
        name: str,
        source: str,
        market: str,
        data_type: str,
        interval: str,
        start_month: str,
        end_month: str,
        target_file_count: int,
        seed: int,
        status: str,
        path: Path,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    id, name, source, market, data_type, interval, start_month, end_month,
                    target_file_count, seed, status, path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    name,
                    source,
                    market,
                    data_type,
                    interval,
                    start_month,
                    end_month,
                    target_file_count,
                    seed,
                    status,
                    str(path),
                ),
            )

    def update_session_status(self, *, session_id: str, status: str) -> None:
        completed_sql = ", completed_at = CURRENT_TIMESTAMP" if status in {"ready", "failed"} else ""
        with self.connect() as connection:
            connection.execute(
                f"UPDATE sessions SET status = ?{completed_sql} WHERE id = ?",
                (status, session_id),
            )

    def add_session_file(
        self,
        *,
        session_id: str,
        normalized_file_id: int,
        session_path: Path,
        sort_order: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO session_files (
                    session_id, normalized_file_id, session_path, sort_order
                )
                VALUES (?, ?, ?, ?)
                """,
                (session_id, normalized_file_id, str(session_path), sort_order),
            )

    def add_session_window(
        self,
        *,
        session_id: str,
        window_id: str,
        normalized_file_id: int,
        symbol: str,
        interval: str,
        start_time: str,
        end_time: str,
        row_count: int,
        sort_order: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO session_windows (
                    session_id, window_id, normalized_file_id, symbol, interval,
                    start_time, end_time, row_count, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    window_id,
                    normalized_file_id,
                    symbol,
                    interval,
                    start_time,
                    end_time,
                    row_count,
                    sort_order,
                ),
            )

    def upsert_normalized_file(
        self,
        *,
        source: str,
        market: str,
        data_type: str,
        symbol: str,
        interval: str,
        year_month: str,
        path: Path,
        row_count: int,
        start_time: str,
        end_time: str,
        file_size_bytes: int,
        sha256: str,
        status: str,
    ) -> int:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO normalized_files (
                    source, market, data_type, symbol, interval, year_month, path, row_count,
                    start_time, end_time, file_size_bytes, sha256, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, market, data_type, symbol, interval, year_month) DO UPDATE SET
                    path = excluded.path,
                    row_count = excluded.row_count,
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    file_size_bytes = excluded.file_size_bytes,
                    sha256 = excluded.sha256,
                    status = excluded.status
                """,
                (
                    source,
                    market,
                    data_type,
                    symbol,
                    interval,
                    year_month,
                    str(path),
                    row_count,
                    start_time,
                    end_time,
                    file_size_bytes,
                    sha256,
                    status,
                ),
            )
            row = connection.execute(
                """
                SELECT id FROM normalized_files
                WHERE source = ? AND market = ? AND data_type = ?
                  AND symbol = ? AND interval = ? AND year_month = ?
                """,
                (source, market, data_type, symbol, interval, year_month),
            ).fetchone()
        return int(row["id"])

    def add_validation_issue(
        self,
        *,
        normalized_file_id: int | None,
        symbol: str,
        interval: str,
        year_month: str,
        status: str,
        issue_code: str,
        message: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO validation_results (
                    normalized_file_id, symbol, interval, year_month, status, issue_code, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (normalized_file_id, symbol, interval, year_month, status, issue_code, message),
            )

    def upsert_classification(
        self, *, normalized_file_id: int, labels: str, features_json: str
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO classifications (normalized_file_id, labels, features_json)
                VALUES (?, ?, ?)
                ON CONFLICT(normalized_file_id) DO UPDATE SET
                    labels = excluded.labels,
                    features_json = excluded.features_json,
                    created_at = CURRENT_TIMESTAMP
                """,
                (normalized_file_id, labels, features_json),
            )

    def record_job(
        self,
        *,
        source: str,
        market: str,
        data_type: str,
        symbol: str,
        interval: str,
        year_month: str,
        status: str,
        message: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO download_jobs (
                    source, market, data_type, symbol, interval, year_month, status, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source, market, data_type, symbol, interval, year_month, status, message),
            )
