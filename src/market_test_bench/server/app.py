from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from market_test_bench.binance import (
    BinanceDataManager,
    DownloadRequest,
    top_symbols_by_quote_volume,
)
from market_test_bench.catalog import Catalog
from market_test_bench.simulation import (
    SimulationSettings,
    UploadedDecisionFile,
    create_simulation,
)
from market_test_bench.workspace import open_workspace

STATIC_DIR = Path(__file__).parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SIMULATION_STANDARD_PATH = PROJECT_ROOT / "docs" / "simulation-standard.md"

workspace = open_workspace()
catalog = Catalog(workspace)
manager = BinanceDataManager(workspace, catalog)
app = FastAPI(title="MarketTestBench", version="0.1.0")
SERVER_INSTANCE_ID = str(uuid4())


class DownloadPayload(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    volume_preset: Literal["top_10", "top_30", "top_100"] | None = None
    interval: str = "1h"
    start_month: str = "2020-01"
    end_month: str = "2026-01"
    month_count: int = Field(default=100, ge=100)
    seed: int = 42
    workers: int = Field(default=4, ge=1, le=16)
    include_agg_trades: bool = False


jobs: dict[str, dict] = {}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "workspace": str(workspace.root),
        "primary_data_format": "parquet",
        "raw_files_policy": "delete_after_normalization",
        "simulation_standard_path": str(SIMULATION_STANDARD_PATH),
        "server_instance_id": SERVER_INSTANCE_ID,
    }


@app.get("/api/datasets")
def datasets() -> dict:
    return {"items": catalog.list_normalized_files()}


@app.get("/api/sessions")
def sessions() -> dict:
    return {"items": [_with_session_runtime_fields(item) for item in catalog.list_sessions()]}


@app.get("/api/sessions/{session_id}/files")
def session_files(session_id: str) -> dict:
    return {"items": catalog.list_session_files(session_id)}


@app.get("/api/sessions/{session_id}/windows")
def session_windows(session_id: str) -> dict:
    return {"items": catalog.list_session_windows(session_id)}


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str) -> dict:
    session = catalog.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    files = catalog.list_session_files(session_id)
    windows = catalog.list_session_windows(session_id)
    return {
        "session": _with_session_runtime_fields(session),
        "files": files,
        "windows": windows,
        "layers": build_session_layers(files),
    }


@app.get("/api/sessions/{session_id}/classification")
def session_classification(session_id: str) -> dict:
    files = catalog.list_session_files(session_id)
    return {"session_id": session_id, "groups": build_classification_groups(files)}


@app.get("/api/simulations")
def simulations() -> dict:
    return {"items": [_with_simulation_runtime_fields(item) for item in catalog.list_simulations()]}


@app.get("/api/simulations/{simulation_id}")
def simulation_detail(simulation_id: str) -> dict:
    simulation = catalog.get_simulation(simulation_id)
    if simulation is None:
        raise HTTPException(status_code=404, detail="Simulation not found.")
    return {
        "simulation": _with_simulation_runtime_fields(simulation),
        "files": catalog.list_simulation_files(simulation_id),
        "validation_results": catalog.list_simulation_validation_results(simulation_id),
    }


@app.delete("/api/simulations/{simulation_id}")
def delete_simulation(simulation_id: str) -> dict:
    simulation = catalog.get_simulation(simulation_id)
    if simulation is None:
        raise HTTPException(status_code=404, detail="Simulation not found.")

    simulation_path = Path(simulation["path"]).resolve()
    simulations_root = workspace.simulations_path.resolve()
    if not simulation_path.is_relative_to(simulations_root):
        raise HTTPException(status_code=400, detail="Simulation path is outside the workspace simulations directory.")

    deleted = catalog.delete_simulation_records(simulation_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Simulation not found.")
    if simulation_path.exists():
        shutil.rmtree(simulation_path)
    return {"status": "deleted", "simulation_id": simulation_id}


@app.post("/api/simulations")
async def upload_simulation(
    session_id: Annotated[str, Form()],
    name: Annotated[str, Form()],
    strategy_name: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    strategy_version: Annotated[str, Form()] = "",
    fee_bps: Annotated[float, Form()] = 10.0,
    slippage_bps: Annotated[float, Form()] = 5.0,
    allow_short: Annotated[bool, Form()] = False,
) -> dict:
    uploaded_files: list[UploadedDecisionFile] = []
    for file in files:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"{file.filename} is empty.")
        uploaded_files.append(
            UploadedDecisionFile(
                file_name=file.filename or "decisions.csv",
                content=content,
            )
        )
    try:
        result = create_simulation(
            workspace=workspace,
            catalog=catalog,
            session_id=session_id,
            name=name,
            strategy_name=strategy_name,
            strategy_version=strategy_version or None,
            settings=SimulationSettings(
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                allow_short=allow_short,
            ),
            files=uploaded_files,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "simulation_id": result.simulation_id,
        "status": result.status,
        "path": str(result.path),
        "file_count": result.file_count,
        "row_count": result.row_count,
        "errors": result.errors,
    }


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    session = catalog.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    session_path = Path(session["path"]).resolve()
    sessions_root = workspace.sessions_path.resolve()
    if not session_path.is_relative_to(sessions_root):
        raise HTTPException(status_code=400, detail="Session path is outside the workspace sessions directory.")

    deleted = catalog.delete_session_records(session_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session_path.exists():
        shutil.rmtree(session_path)
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/symbols/top-volume/{preset}")
def top_volume_symbols(preset: Literal["top_10", "top_30", "top_100"]) -> dict:
    return {"symbols": list(top_symbols_by_quote_volume(preset))}


@app.post("/api/downloads")
def start_download(payload: DownloadPayload, background_tasks: BackgroundTasks) -> dict:
    if not payload.symbols and not payload.volume_preset:
        raise HTTPException(status_code=400, detail="Select symbols or a volume preset.")
    job_id = f"job_{len(jobs) + 1:04d}"
    jobs[job_id] = {
        "status": "queued",
        "events": [],
        "messages": [],
        "attempted_files": 0,
        "valid_files": 0,
        "target_valid_files": payload.month_count,
        "candidate_files": 0,
    }
    background_tasks.add_task(_run_download_job, job_id, payload)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/downloads/{job_id}")
def download_status(job_id: str) -> dict:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Download job not found.")
    return jobs[job_id]


def _run_download_job(job_id: str, payload: DownloadPayload) -> None:
    jobs[job_id].update({"status": "running"})
    try:
        _record_job_event(
            job_id,
            {
                "type": "resolving_symbols",
                "target_valid_files": payload.month_count,
                "message": "Resolving selected symbols.",
            },
        )
        summary = manager.download_dataset(
            DownloadRequest(
                symbols=tuple(symbol.upper() for symbol in payload.symbols),
                volume_preset=payload.volume_preset,
                interval=payload.interval,
                start_month=payload.start_month,
                end_month=payload.end_month,
                month_count=payload.month_count,
                seed=payload.seed,
                workers=payload.workers,
                include_agg_trades=payload.include_agg_trades,
            ),
            progress_callback=lambda event: _record_job_event(job_id, event),
        )
    except Exception as exc:  # noqa: BLE001 - user-facing job state must survive failures.
        jobs[job_id].update({"status": "failed", "messages": [str(exc)]})
        return
    jobs[job_id].update({
        "status": "completed",
        "session_id": summary.session_id,
        "session_path": str(summary.session_path),
        "requested_months": summary.requested_months,
        "candidate_months": summary.candidate_months,
        "attempted_files": summary.attempted_files,
        "valid_files": summary.normalized_files + summary.skipped_existing,
        "normalized_files": summary.normalized_files,
        "skipped_existing": summary.skipped_existing,
        "agg_trades_files": summary.agg_trades_normalized + summary.agg_trades_skipped_existing,
        "agg_trades_normalized": summary.agg_trades_normalized,
        "agg_trades_skipped_existing": summary.agg_trades_skipped_existing,
        "failed_files": summary.failed_files,
        "messages": summary.messages,
    })


def _record_job_event(job_id: str, event: dict) -> None:
    job = jobs[job_id]
    job["events"].append(event)
    if len(job["events"]) > 300:
        job["events"] = job["events"][-300:]
    for key in ("attempted_files", "valid_files", "target_valid_files", "candidate_files"):
        if key in event:
            job[key] = event[key]


def build_classification_groups(files: list[dict]) -> dict:
    groups = {
        "total": {},
        "trend": {},
        "volatility": {},
        "drawdown": {},
        "volume": {},
        "structure": {},
    }
    label_groups = {
        "trend": {"strong_bull", "bull", "sideways", "bear", "strong_bear"},
        "volatility": {
            "low_volatility",
            "normal_volatility",
            "high_volatility",
            "extreme_volatility",
        },
        "drawdown": {"deep_drawdown", "crash", "recovery"},
        "volume": {"low_volume", "normal_volume", "high_volume", "volume_spike"},
        "structure": {
            "breakout",
            "breakdown",
            "range_bound",
            "choppy",
            "trending_smooth",
            "wicky",
        },
    }
    for file in files:
        if file["data_type"] != "klines":
            continue
        labels = json.loads(file["labels"] or "[]")
        for label in labels:
            groups["total"][label] = groups["total"].get(label, 0) + 1
            for group_name, group_labels in label_groups.items():
                if label in group_labels:
                    groups[group_name][label] = groups[group_name].get(label, 0) + 1
    return groups


def build_session_layers(files: list[dict]) -> dict:
    layers: dict[str, dict] = {}
    for file in files:
        data_type = file["data_type"]
        layer = layers.setdefault(
            data_type,
            {
                "files": 0,
                "symbols": set(),
                "rows": 0,
                "bytes": 0,
                "path": str(Path(file["session_path"]).parent),
            },
        )
        layer["files"] += 1
        layer["symbols"].add(file["symbol"])
        layer["rows"] += file["row_count"] or 0
        layer["bytes"] += file["file_size_bytes"] or 0
    for layer in layers.values():
        layer["symbols"] = len(layer["symbols"])
    return layers


def _with_session_runtime_fields(session: dict) -> dict:
    session = dict(session)
    session_path = Path(session["path"])
    data_path = session_path / "data"
    session["disk_size_bytes"] = directory_size(session_path)
    session["strategy_data_path"] = str(data_path)
    session["kline_data_path"] = str(data_path / "klines")
    session["agg_trades_data_path"] = str(data_path / "aggTrades")
    session["simulation_standard_path"] = str(SIMULATION_STANDARD_PATH)
    return session


def _with_simulation_runtime_fields(simulation: dict) -> dict:
    simulation = dict(simulation)
    simulation_path = Path(simulation["path"])
    simulation["disk_size_bytes"] = directory_size(simulation_path)
    simulation["decisions_path"] = str(simulation_path / "decisions")
    simulation["results_path"] = str(simulation_path / "results")
    try:
        simulation["settings"] = json.loads(simulation["settings_json"])
    except (TypeError, json.JSONDecodeError):
        simulation["settings"] = {}
    return simulation


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
