from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_ENV_VAR = "MARKET_TEST_BENCH_HOME"
DEFAULT_WORKSPACE_NAME = "MarketTestBenchWorkspace"


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def catalog_path(self) -> Path:
        return self.root / "catalog.sqlite"

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.json"

    @property
    def tmp_path(self) -> Path:
        return self.root / "tmp"

    @property
    def normalized_path(self) -> Path:
        return self.root / "data" / "normalized"

    @property
    def runs_path(self) -> Path:
        return self.root / "runs"

    @property
    def sessions_path(self) -> Path:
        return self.root / "sessions"


def default_workspace_root() -> Path:
    configured = os.environ.get(WORKSPACE_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / DEFAULT_WORKSPACE_NAME


def open_workspace(root: Path | None = None) -> Workspace:
    workspace = Workspace((root or default_workspace_root()).resolve())
    for path in (
        workspace.root,
        workspace.tmp_path,
        workspace.normalized_path,
        workspace.runs_path,
        workspace.sessions_path,
    ):
        path.mkdir(parents=True, exist_ok=True)

    if not workspace.settings_path.exists():
        workspace.settings_path.write_text(
            json.dumps(
                {
                    "workspace_version": 1,
                    "raw_files_policy": "delete_after_normalization",
                    "primary_data_format": "parquet",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    return workspace
