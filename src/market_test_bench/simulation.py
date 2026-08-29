from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from market_test_bench.catalog import Catalog
from market_test_bench.protocol import ValidationIssue, validate_decision_file
from market_test_bench.workspace import Workspace

STANDARD_INITIAL_CASH_USDT = 10_000.0


@dataclass(frozen=True)
class SimulationSettings:
    initial_cash: float = STANDARD_INITIAL_CASH_USDT
    fee_bps: float = 10.0
    slippage_bps: float = 0.0
    allow_short: bool = False
    missing_decision_policy: str = "hold_last"
    timestamp_alignment_policy: str = "exact_or_previous"


@dataclass(frozen=True)
class UploadedDecisionFile:
    file_name: str
    content: bytes


@dataclass(frozen=True)
class SimulationCreateResult:
    simulation_id: str
    path: Path
    status: str
    file_count: int
    row_count: int
    errors: tuple[str, ...]


def create_simulation_id() -> str:
    return f"simulation_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


def create_simulation(
    *,
    workspace: Workspace,
    catalog: Catalog,
    session_id: str,
    name: str,
    strategy_name: str,
    strategy_version: str | None,
    settings: SimulationSettings,
    files: list[UploadedDecisionFile],
) -> SimulationCreateResult:
    session = catalog.get_session(session_id)
    if session is None:
        raise ValueError("Selected session does not exist.")
    if not files:
        raise ValueError("Upload at least one CSV decision file.")

    simulation_id = create_simulation_id()
    simulation_path = workspace.simulations_path / simulation_id
    decisions_path = simulation_path / "decisions"
    results_path = simulation_path / "results"
    decisions_path.mkdir(parents=True, exist_ok=True)
    results_path.mkdir(parents=True, exist_ok=True)

    allowed_symbols = {
        str(row["symbol"])
        for row in catalog.list_session_files(session_id)
        if row.get("data_type") == "klines"
    }
    if not allowed_symbols:
        raise ValueError("Selected session does not contain kline files.")

    all_issues: list[ValidationIssue] = []
    total_rows = 0
    stored_files: list[dict] = []
    used_names: set[str] = set()
    for uploaded_file in files:
        file_name = unique_file_name(uploaded_file.file_name, used_names)
        destination = decisions_path / file_name
        destination.write_bytes(uploaded_file.content)
        result = validate_decision_file(
            destination,
            allowed_symbols=allowed_symbols,
            allow_short=settings.allow_short,
        )
        all_issues.extend(result.issues)
        total_rows += result.row_count
        file_status = "valid" if result.is_valid else "invalid"
        stored_files.append(
            {
                "file_name": file_name,
                "path": str(destination),
                "row_count": result.row_count,
                "status": file_status,
            }
        )

    status = "invalid" if all_issues else "valid"
    settings_json = json.dumps(asdict(settings), sort_keys=True, separators=(",", ":"))
    catalog.create_simulation(
        simulation_id=simulation_id,
        name=name.strip() or simulation_id,
        session_id=session_id,
        strategy_name=strategy_name.strip() or "Unnamed strategy",
        strategy_version=strategy_version.strip() if strategy_version else None,
        status=status,
        path=simulation_path,
        settings_json=settings_json,
    )
    for stored_file in stored_files:
        catalog.add_simulation_file(
            simulation_id=simulation_id,
            file_name=stored_file["file_name"],
            path=Path(stored_file["path"]),
            row_count=int(stored_file["row_count"]),
            status=str(stored_file["status"]),
        )
    for issue in all_issues:
        catalog.add_simulation_validation_result(
            simulation_id=simulation_id,
            file_name=issue.file_name,
            row_number=issue.row_number,
            status="error",
            issue_code=issue.issue_code,
            message=issue.message,
        )

    manifest = {
        "simulation_id": simulation_id,
        "name": name.strip() or simulation_id,
        "session_id": session_id,
        "strategy_name": strategy_name.strip() or "Unnamed strategy",
        "strategy_version": strategy_version.strip() if strategy_version else None,
        "status": status,
        "settings": asdict(settings),
        "files": stored_files,
        "created_at": datetime.now(UTC).isoformat(),
    }
    validation = {
        "is_valid": not all_issues,
        "row_count": total_rows,
        "errors": [issue.message for issue in all_issues],
        "issues": [asdict(issue) for issue in all_issues],
    }
    (simulation_path / "simulation.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    (simulation_path / "validation.json").write_text(
        json.dumps(validation, indent=2),
        encoding="utf-8",
    )

    return SimulationCreateResult(
        simulation_id=simulation_id,
        path=simulation_path,
        status=status,
        file_count=len(stored_files),
        row_count=total_rows,
        errors=tuple(issue.message for issue in all_issues),
    )


def unique_file_name(file_name: str, used_names: set[str]) -> str:
    safe_name = sanitize_file_name(file_name)
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix or ".csv"
    candidate = f"{stem}{suffix}"
    index = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used_names.add(candidate.lower())
    return candidate


def sanitize_file_name(file_name: str) -> str:
    name = Path(file_name).name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    if not name:
        name = "decisions.csv"
    if Path(name).suffix.lower() != ".csv":
        name = f"{Path(name).stem}.csv"
    return name
