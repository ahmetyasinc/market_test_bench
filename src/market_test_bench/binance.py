from __future__ import annotations

import hashlib
import io
import json
import os
import random
import shutil
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import polars as pl

from market_test_bench.catalog import Catalog
from market_test_bench.classification import ClassificationResult, classify_ohlcv
from market_test_bench.workspace import Workspace

BINANCE_DATA_BASE_URL = "https://data.binance.vision/data"
BINANCE_24HR_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
STABLE_BASE_ASSETS = {
    "BUSD",
    "DAI",
    "FDUSD",
    "PAX",
    "PAXG",
    "PYUSD",
    "RLUSD",
    "TUSD",
    "USD1",
    "USDC",
    "USDD",
    "USDP",
    "UST",
    "USTC",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
)
AGG_TRADE_COLUMNS = (
    "aggregate_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
    "is_best_match",
)
AGG_TRADES_INTERVAL = "tick"
INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}


@dataclass(frozen=True)
class DownloadRequest:
    symbols: tuple[str, ...] = ()
    volume_preset: str | None = None
    interval: str = "1h"
    start_month: str = "2020-01"
    end_month: str = "2026-01"
    month_count: int = 100
    seed: int = 42
    min_valid_months: int = 100
    workers: int = 4
    include_agg_trades: bool = False


@dataclass
class DownloadSummary:
    session_id: str
    session_path: Path
    requested_months: int
    candidate_months: int
    attempted_files: int = 0
    normalized_files: int = 0
    skipped_existing: int = 0
    agg_trades_normalized: int = 0
    agg_trades_skipped_existing: int = 0
    failed_files: int = 0
    windows: list[dict] = field(default_factory=list)
    classifications: list[ClassificationResult] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DownloadedFile:
    status: str
    normalized_file_id: int | None
    path: Path
    source: str
    market: str
    data_type: str
    symbol: str
    interval: str
    year_month: str
    row_count: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    file_size_bytes: int | None = None
    sha256: str | None = None
    labels_json: str | None = None
    features_json: str | None = None
    validation_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DownloadedCandidate:
    kline: DownloadedFile
    agg_trades: DownloadedFile | None = None


ProgressCallback = Callable[[dict], None]


class MissingBinanceDataError(ValueError):
    """Raised when Binance does not publish the requested symbol/month file."""


class BinanceDataManager:
    def __init__(self, workspace: Workspace, catalog: Catalog):
        self.workspace = workspace
        self.catalog = catalog

    def download_dataset(
        self, request: DownloadRequest, progress_callback: ProgressCallback | None = None
    ) -> DownloadSummary:
        _emit(
            progress_callback,
            {
                "type": "resolving_symbols",
                "target_valid_files": max(request.month_count, request.min_valid_months),
                "message": "Resolving selected symbols.",
            },
        )
        symbols = self.resolve_symbols(request)
        session_id = create_session_id()
        session_path = self.workspace.sessions_path / session_id
        session_data_path = session_path / "data"
        session_data_path.mkdir(parents=True, exist_ok=True)
        target_valid_files = max(request.month_count, request.min_valid_months)
        self.catalog.create_session(
            session_id=session_id,
            name=f"{request.interval} {request.start_month} to {request.end_month}",
            source="binance",
            market="spot",
            data_type="klines+aggTrades" if request.include_agg_trades else "klines",
            interval=request.interval,
            start_month=request.start_month,
            end_month=request.end_month,
            target_file_count=target_valid_files,
            seed=request.seed,
            status="running",
            path=session_path,
        )
        _emit(
            progress_callback,
            {
                "type": "symbols_resolved",
                "session_id": session_id,
                "session_path": str(session_path),
                "symbols": list(symbols),
                "target_valid_files": target_valid_files,
                "message": f"Resolved {len(symbols)} symbols.",
                "include_agg_trades": request.include_agg_trades,
            },
        )
        pairs = select_candidate_symbol_month_pairs(
            symbols=symbols,
            start_month=request.start_month,
            end_month=request.end_month,
            seed=request.seed,
        )
        if len(pairs) < target_valid_files:
            self.catalog.update_session_status(session_id=session_id, status="failed")
            raise ValueError(
                "The selected symbols and months cannot produce the required 100 valid monthly files."
            )

        summary = DownloadSummary(
            session_id=session_id,
            session_path=session_path,
            requested_months=target_valid_files,
            candidate_months=len(pairs),
        )
        _emit(
            progress_callback,
            {
                "type": "planned",
                "symbols": list(symbols),
                "target_valid_files": target_valid_files,
                "candidate_files": len(pairs),
            },
        )
        workers = max(1, min(request.workers, 16))
        summary = self._download_pairs_with_workers(
            pairs=pairs,
            request=request,
            summary=summary,
            session_id=session_id,
            session_path=session_path,
            session_data_path=session_data_path,
            target_valid_files=target_valid_files,
            workers=workers,
            progress_callback=progress_callback,
        )

        valid_files = summary.normalized_files + summary.skipped_existing
        if valid_files < target_valid_files:
            self.catalog.update_session_status(session_id=session_id, status="failed")
            raise ValueError(
                f"Only {valid_files} valid monthly files were produced after trying "
                f"{summary.attempted_files} candidates. Add more symbols or widen the date range."
            )

        write_session_manifest(
            session_path=session_path,
            summary=summary,
            request=request,
            symbols=symbols,
        )
        self.catalog.update_session_status(session_id=session_id, status="ready")
        return summary

    def _download_pairs_with_workers(
        self,
        *,
        pairs: tuple[tuple[str, str], ...],
        request: DownloadRequest,
        summary: DownloadSummary,
        session_id: str,
        session_path: Path,
        session_data_path: Path,
        target_valid_files: int,
        workers: int,
        progress_callback: ProgressCallback | None,
    ) -> DownloadSummary:
        next_pair_index = 0
        active: dict[Future[DownloadedCandidate], tuple[str, str]] = {}

        with ThreadPoolExecutor(max_workers=workers) as executor:
            while (
                next_pair_index < len(pairs)
                and len(active) < workers
                and summary.normalized_files + summary.skipped_existing < target_valid_files
            ):
                next_pair_index = self._submit_next_download(
                    executor=executor,
                    pairs=pairs,
                    next_pair_index=next_pair_index,
                    request=request,
                    summary=summary,
                    session_data_path=session_data_path,
                    active=active,
                    target_valid_files=target_valid_files,
                    progress_callback=progress_callback,
                )

            while active and summary.normalized_files + summary.skipped_existing < target_valid_files:
                completed, _ = wait(active.keys(), return_when=FIRST_COMPLETED)
                for future in completed:
                    symbol, year_month = active.pop(future)
                    self._handle_download_result(
                        future=future,
                        symbol=symbol,
                        year_month=year_month,
                        request=request,
                        summary=summary,
                        session_id=session_id,
                        session_path=session_path,
                        session_data_path=session_data_path,
                        target_valid_files=target_valid_files,
                        candidate_files=len(pairs),
                        progress_callback=progress_callback,
                    )
                    while (
                        next_pair_index < len(pairs)
                        and len(active) < workers
                        and summary.normalized_files + summary.skipped_existing < target_valid_files
                    ):
                        next_pair_index = self._submit_next_download(
                            executor=executor,
                            pairs=pairs,
                            next_pair_index=next_pair_index,
                            request=request,
                            summary=summary,
                            session_data_path=session_data_path,
                            active=active,
                            target_valid_files=target_valid_files,
                            progress_callback=progress_callback,
                        )
            for future in active:
                future.cancel()

        return summary

    def _submit_next_download(
        self,
        *,
        executor: ThreadPoolExecutor,
        pairs: tuple[tuple[str, str], ...],
        next_pair_index: int,
        request: DownloadRequest,
        summary: DownloadSummary,
        session_data_path: Path,
        active: dict[Future[DownloadedCandidate], tuple[str, str]],
        target_valid_files: int,
        progress_callback: ProgressCallback | None,
    ) -> int:
        symbol, year_month = pairs[next_pair_index]
        summary.attempted_files += 1
        _emit(
            progress_callback,
            {
                "type": "file_started",
                "symbol": symbol,
                "interval": request.interval,
                "year_month": year_month,
                "attempted_files": summary.attempted_files,
                "valid_files": summary.normalized_files + summary.skipped_existing,
                "target_valid_files": target_valid_files,
                "candidate_files": len(pairs),
            },
        )
        future = executor.submit(
            self.download_candidate,
            symbol=symbol,
            interval=request.interval,
            year_month=year_month,
            include_agg_trades=request.include_agg_trades,
            session_data_path=session_data_path,
        )
        active[future] = (symbol, year_month)
        return next_pair_index + 1

    def _handle_download_result(
        self,
        *,
        future: Future[DownloadedCandidate],
        symbol: str,
        year_month: str,
        request: DownloadRequest,
        summary: DownloadSummary,
        session_id: str,
        session_path: Path,
        session_data_path: Path,
        target_valid_files: int,
        candidate_files: int,
        progress_callback: ProgressCallback | None,
    ) -> None:
        try:
            result = future.result()
        except MissingBinanceDataError as exc:
            message = f"{symbol} {request.interval} {year_month}: {exc}"
            summary.messages.append(message)
            _emit(
                progress_callback,
                {
                    "type": "file_missing",
                    "symbol": symbol,
                    "interval": request.interval,
                    "year_month": year_month,
                    "message": str(exc),
                    "attempted_files": summary.attempted_files,
                    "valid_files": summary.normalized_files + summary.skipped_existing,
                    "target_valid_files": target_valid_files,
                    "candidate_files": candidate_files,
                },
            )
            self.catalog.record_job(
                source="binance",
                market="spot",
                data_type="klines",
                symbol=symbol,
                interval=request.interval,
                year_month=year_month,
                status="missing",
                message=message,
            )
            return
        except Exception as exc:  # noqa: BLE001 - failures are stored per file for the dashboard.
            summary.failed_files += 1
            message = f"{symbol} {request.interval} {year_month}: {exc}"
            summary.messages.append(message)
            _emit(
                progress_callback,
                {
                    "type": "file_failed",
                    "symbol": symbol,
                    "interval": request.interval,
                    "year_month": year_month,
                    "message": str(exc),
                    "attempted_files": summary.attempted_files,
                    "valid_files": summary.normalized_files + summary.skipped_existing,
                    "target_valid_files": target_valid_files,
                    "candidate_files": candidate_files,
                },
            )
            self.catalog.record_job(
                source="binance",
                market="spot",
                data_type="klines",
                symbol=symbol,
                interval=request.interval,
                year_month=year_month,
                status="failed",
                message=message,
            )
            return

        if summary.normalized_files + summary.skipped_existing >= target_valid_files:
            result.kline.path.unlink(missing_ok=True)
            if result.agg_trades is not None:
                result.agg_trades.path.unlink(missing_ok=True)
            return

        kline_session_path = session_data_path / "klines" / f"{symbol}_{request.interval}_{year_month}.parquet"
        kline_normalized_id = self._commit_prepared_file(result.kline, kline_session_path)
        sort_order = summary.normalized_files + summary.skipped_existing
        self.catalog.add_session_file(
            session_id=session_id,
            normalized_file_id=kline_normalized_id,
            session_path=kline_session_path,
            sort_order=sort_order,
        )
        window_id = data_window_id(result.kline)
        self.catalog.add_session_window(
            session_id=session_id,
            window_id=window_id,
            normalized_file_id=kline_normalized_id,
            symbol=result.kline.symbol,
            interval=result.kline.interval,
            start_time=result.kline.start_time or "",
            end_time=result.kline.end_time or "",
            row_count=result.kline.row_count or 0,
            sort_order=sort_order,
        )
        summary.windows.append(
            {
                "window_id": window_id,
                "normalized_file_id": kline_normalized_id,
                "symbol": result.kline.symbol,
                "interval": result.kline.interval,
                "year_month": result.kline.year_month,
                "start_time": result.kline.start_time,
                "end_time": result.kline.end_time,
                "row_count": result.kline.row_count,
                "session_path": str(kline_session_path),
            }
        )
        if result.kline.status == "skipped":
            summary.skipped_existing += 1
        else:
            summary.normalized_files += 1
        if result.agg_trades is not None:
            agg_session_path = session_data_path / "aggTrades" / f"{symbol}_aggTrades_{year_month}.parquet"
            agg_trades_normalized_id = self._commit_prepared_file(result.agg_trades, agg_session_path)
            self.catalog.add_session_file(
                session_id=session_id,
                normalized_file_id=agg_trades_normalized_id,
                session_path=agg_session_path,
                sort_order=summary.normalized_files + summary.skipped_existing,
            )
            if result.agg_trades.status == "skipped":
                summary.agg_trades_skipped_existing += 1
            else:
                summary.agg_trades_normalized += 1
        _emit(
            progress_callback,
            {
                "type": "file_completed",
                "result": result.kline.status,
                "agg_trades": result.agg_trades.status if result.agg_trades is not None else None,
                "session_id": session_id,
                "session_path": str(session_path),
                "session_file_path": str(kline_session_path),
                "symbol": symbol,
                "interval": request.interval,
                "year_month": year_month,
                "attempted_files": summary.attempted_files,
                "valid_files": summary.normalized_files + summary.skipped_existing,
                "target_valid_files": target_valid_files,
                "candidate_files": candidate_files,
            },
        )

    def download_candidate(
        self,
        *,
        symbol: str,
        interval: str,
        year_month: str,
        include_agg_trades: bool,
        session_data_path: Path,
    ) -> DownloadedCandidate:
        kline = self.download_month(
            symbol=symbol,
            interval=interval,
            year_month=year_month,
            output_path=session_data_path / "klines" / f"{symbol}_{interval}_{year_month}.parquet",
        )
        agg_trades = None
        if include_agg_trades:
            agg_trades = self.download_agg_trades_month(
                symbol=symbol,
                year_month=year_month,
                output_path=session_data_path / "aggTrades" / f"{symbol}_aggTrades_{year_month}.parquet",
            )
        return DownloadedCandidate(kline=kline, agg_trades=agg_trades)

    def _commit_prepared_file(self, file: DownloadedFile, destination: Path) -> int:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if file.status == "skipped":
            if file.normalized_file_id is None:
                raise ValueError("Existing normalized file is missing its catalog id.")
            if file.path != destination:
                link_or_copy_file(file.path, destination)
            if file.row_count is None or file.start_time is None or file.end_time is None:
                return file.normalized_file_id
            return self.catalog.upsert_normalized_file(
                source=file.source,
                market=file.market,
                data_type=file.data_type,
                symbol=file.symbol,
                interval=file.interval,
                year_month=file.year_month,
                path=destination,
                row_count=file.row_count,
                start_time=file.start_time,
                end_time=file.end_time,
                file_size_bytes=destination.stat().st_size,
                sha256=_sha256(destination),
                status="normalized",
            )

        if file.row_count is None or file.start_time is None or file.end_time is None or file.sha256 is None:
            raise ValueError("Prepared file is missing required metadata.")
        if file.path != destination:
            destination.unlink(missing_ok=True)
            shutil.move(str(file.path), destination)

        normalized_id = self.catalog.upsert_normalized_file(
            source=file.source,
            market=file.market,
            data_type=file.data_type,
            symbol=file.symbol,
            interval=file.interval,
            year_month=file.year_month,
            path=destination,
            row_count=file.row_count,
            start_time=file.start_time,
            end_time=file.end_time,
            file_size_bytes=destination.stat().st_size,
            sha256=_sha256(destination),
            status="normalized",
        )
        if file.labels_json is not None and file.features_json is not None:
            self.catalog.upsert_classification(
                normalized_file_id=normalized_id,
                labels=file.labels_json,
                features_json=file.features_json,
            )
        self.catalog.record_job(
            source=file.source,
            market=file.market,
            data_type=file.data_type,
            symbol=file.symbol,
            interval=file.interval,
            year_month=file.year_month,
            status="normalized",
        )
        for issue in file.validation_warnings:
            self.catalog.add_validation_issue(
                normalized_file_id=normalized_id,
                symbol=file.symbol,
                interval=file.interval,
                year_month=file.year_month,
                status="warning",
                issue_code="timestamp_gap_repaired",
                message=issue,
            )
        return normalized_id

    def download_month(
        self, *, symbol: str, interval: str, year_month: str, output_path: Path
    ) -> DownloadedFile:
        symbol = symbol.upper()
        existing_file = self.catalog.get_normalized_file(
            source="binance",
            market="spot",
            data_type="klines",
            symbol=symbol,
            interval=interval,
            year_month=year_month,
        )
        if existing_file and Path(existing_file["path"]).exists():
            return DownloadedFile(
                status="skipped",
                normalized_file_id=int(existing_file["id"]),
                path=Path(existing_file["path"]),
                source="binance",
                market="spot",
                data_type="klines",
                symbol=symbol,
                interval=interval,
                year_month=year_month,
                row_count=int(existing_file["row_count"]),
                start_time=str(existing_file["start_time"]),
                end_time=str(existing_file["end_time"]),
                file_size_bytes=int(existing_file["file_size_bytes"]),
                sha256=str(existing_file["sha256"]),
            )

        zip_name = f"{symbol}-{interval}-{year_month}.zip"
        raw_path = self.workspace.tmp_path / zip_name
        checksum_path = self.workspace.tmp_path / f"{zip_name}.CHECKSUM"
        url = monthly_kline_url(symbol=symbol, interval=interval, year_month=year_month)

        try:
            checksum_downloaded = _try_download_file(f"{url}.CHECKSUM", checksum_path)
            _download_file(url, raw_path)
            if checksum_downloaded:
                expected_hash = _parse_checksum(checksum_path)
                actual_hash = _sha256(raw_path)
                if expected_hash and expected_hash != actual_hash:
                    raise ValueError("checksum mismatch")

            dataframe = _read_kline_zip(raw_path, symbol=symbol, interval=interval)
            issues = validate_klines(dataframe, interval=interval)
            gap_issues = [issue for issue in issues if issue.startswith("timestamp gaps")]
            critical_issues = [issue for issue in issues if issue not in gap_issues]
            if critical_issues:
                raise ValueError("; ".join(critical_issues))
            if gap_issues:
                dataframe = repair_kline_gaps(dataframe, interval=interval)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            dataframe.write_parquet(output_path)
            classification = classify_ohlcv(dataframe)
            prepared_file = DownloadedFile(
                status="normalized",
                normalized_file_id=None,
                path=output_path,
                source="binance",
                market="spot",
                data_type="klines",
                symbol=symbol,
                interval=interval,
                year_month=year_month,
                row_count=dataframe.height,
                start_time=dataframe["timestamp"][0].isoformat(),
                end_time=dataframe["timestamp"][-1].isoformat(),
                file_size_bytes=output_path.stat().st_size,
                sha256=_sha256(output_path),
                labels_json=classification.labels_json(),
                features_json=classification.features_json(),
                validation_warnings=tuple(gap_issues),
            )
        finally:
            raw_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)

        return prepared_file

    def download_agg_trades_month(
        self, *, symbol: str, year_month: str, output_path: Path
    ) -> DownloadedFile:
        symbol = symbol.upper()
        existing_file = self.catalog.get_normalized_file(
            source="binance",
            market="spot",
            data_type="aggTrades",
            symbol=symbol,
            interval=AGG_TRADES_INTERVAL,
            year_month=year_month,
        )
        if existing_file and Path(existing_file["path"]).exists():
            return DownloadedFile(
                status="skipped",
                normalized_file_id=int(existing_file["id"]),
                path=Path(existing_file["path"]),
                source="binance",
                market="spot",
                data_type="aggTrades",
                symbol=symbol,
                interval=AGG_TRADES_INTERVAL,
                year_month=year_month,
                row_count=int(existing_file["row_count"]),
                start_time=str(existing_file["start_time"]),
                end_time=str(existing_file["end_time"]),
                file_size_bytes=int(existing_file["file_size_bytes"]),
                sha256=str(existing_file["sha256"]),
            )

        zip_name = f"{symbol}-aggTrades-{year_month}.zip"
        raw_path = self.workspace.tmp_path / zip_name
        checksum_path = self.workspace.tmp_path / f"{zip_name}.CHECKSUM"
        url = monthly_agg_trades_url(symbol=symbol, year_month=year_month)

        try:
            checksum_downloaded = _try_download_file(f"{url}.CHECKSUM", checksum_path)
            _download_file(url, raw_path)
            if checksum_downloaded:
                expected_hash = _parse_checksum(checksum_path)
                actual_hash = _sha256(raw_path)
                if expected_hash and expected_hash != actual_hash:
                    raise ValueError("checksum mismatch")

            dataframe = _read_agg_trades_zip(raw_path, symbol=symbol)
            issues = validate_agg_trades(dataframe)
            if issues:
                raise ValueError("; ".join(issues))

            output_path.parent.mkdir(parents=True, exist_ok=True)
            dataframe.write_parquet(output_path)
            prepared_file = DownloadedFile(
                status="normalized",
                normalized_file_id=None,
                path=output_path,
                source="binance",
                market="spot",
                data_type="aggTrades",
                symbol=symbol,
                interval=AGG_TRADES_INTERVAL,
                year_month=year_month,
                row_count=dataframe.height,
                start_time=dataframe["timestamp"][0].isoformat(),
                end_time=dataframe["timestamp"][-1].isoformat(),
                file_size_bytes=output_path.stat().st_size,
                sha256=_sha256(output_path),
            )
        finally:
            raw_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)

        return prepared_file

    def resolve_symbols(self, request: DownloadRequest) -> tuple[str, ...]:
        if request.symbols:
            return tuple(symbol.upper() for symbol in request.symbols)
        if request.volume_preset:
            return top_symbols_by_quote_volume(request.volume_preset)
        raise ValueError("At least one symbol or volume preset is required.")


def monthly_kline_url(*, symbol: str, interval: str, year_month: str) -> str:
    return (
        f"{BINANCE_DATA_BASE_URL}/spot/monthly/klines/"
        f"{symbol.upper()}/{interval}/{symbol.upper()}-{interval}-{year_month}.zip"
    )


def monthly_agg_trades_url(*, symbol: str, year_month: str) -> str:
    return (
        f"{BINANCE_DATA_BASE_URL}/spot/monthly/aggTrades/"
        f"{symbol.upper()}/{symbol.upper()}-aggTrades-{year_month}.zip"
    )


def select_months(*, start_month: str, end_month: str, month_count: int, seed: int) -> tuple[str, ...]:
    months = list(iter_months(start_month, end_month))
    if month_count < 100:
        raise ValueError("Every dataset must request at least 100 monthly files.")
    if len(months) < month_count:
        raise ValueError("The selected date range contains fewer months than requested.")
    rng = random.Random(seed)
    return tuple(sorted(rng.sample(months, month_count)))


def select_candidate_symbol_month_pairs(
    *,
    symbols: tuple[str, ...],
    start_month: str,
    end_month: str,
    seed: int,
) -> tuple[tuple[str, str], ...]:
    pairs = [(symbol, month) for symbol in symbols for month in iter_months(start_month, end_month)]
    rng = random.Random(seed)
    rng.shuffle(pairs)
    return tuple(pairs)


def select_symbol_month_pairs(
    *,
    symbols: tuple[str, ...],
    start_month: str,
    end_month: str,
    pair_count: int,
    seed: int,
) -> tuple[tuple[str, str], ...]:
    if pair_count < 100:
        raise ValueError("Every dataset must request at least 100 monthly files.")
    pairs = select_candidate_symbol_month_pairs(
        symbols=symbols,
        start_month=start_month,
        end_month=end_month,
        seed=seed,
    )
    if len(pairs) < pair_count:
        raise ValueError(
            "The selected symbols and date range cannot produce enough monthly files. "
            "Add symbols or widen the date range."
        )
    return tuple(sorted(pairs[:pair_count]))


def iter_months(start_month: str, end_month: str) -> tuple[str, ...]:
    start_year, start_month_number = _parse_year_month(start_month)
    end_year, end_month_number = _parse_year_month(end_month)
    months: list[str] = []
    year = start_year
    month = start_month_number
    while (year, month) <= (end_year, end_month_number):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return tuple(months)


def top_symbols_by_quote_volume(preset: str) -> tuple[str, ...]:
    preset_counts = {"top_10": 10, "top_30": 30, "top_100": 100}
    if preset not in preset_counts:
        raise ValueError(f"Unsupported volume preset: {preset}")
    with urllib.request.urlopen(BINANCE_24HR_TICKER_URL, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return filter_top_volume_symbols(payload, limit=preset_counts[preset])


def filter_top_volume_symbols(rows: list[dict], *, limit: int) -> tuple[str, ...]:
    usdt_pairs = [row for row in rows if is_supported_volume_symbol(row["symbol"])]
    ranked = sorted(usdt_pairs, key=lambda row: float(row.get("quoteVolume", 0.0)), reverse=True)
    return tuple(row["symbol"] for row in ranked[:limit])


def is_supported_volume_symbol(symbol: str) -> bool:
    if not symbol.endswith("USDT"):
        return False
    base_asset = symbol.removesuffix("USDT")
    if base_asset in STABLE_BASE_ASSETS:
        return False
    return not base_asset.endswith(LEVERAGED_SUFFIXES)


def validate_klines(df: pl.DataFrame, *, interval: str) -> list[str]:
    issues: list[str] = []
    if df.height == 0:
        return ["empty kline file"]
    if interval not in INTERVAL_SECONDS:
        issues.append(f"unsupported interval for continuity check: {interval}")
        return issues
    if df["open_time"].n_unique() != df.height:
        issues.append("duplicate open_time values")
    if not df["open_time"].is_sorted():
        issues.append("open_time values are not sorted")

    expected_step_us = INTERVAL_SECONDS[interval] * 1_000_000
    diffs = df["open_time"].diff().drop_nulls()
    irregular_diffs = diffs.filter(diffs != expected_step_us)
    if irregular_diffs.len() > 0:
        missing_bars = sum(max(int(diff // expected_step_us) - 1, 0) for diff in irregular_diffs)
        missing_ratio = missing_bars / max(df.height + missing_bars, 1)
        if missing_ratio > 0.05:
            issues.append(
                f"timestamp gaps exceed repair threshold: {missing_bars} missing bars "
                f"({missing_ratio:.2%})"
            )
        else:
            issues.append(f"timestamp gaps repaired: {missing_bars} missing bars")
    return issues


def validate_agg_trades(df: pl.DataFrame) -> list[str]:
    issues: list[str] = []
    if df.height == 0:
        return ["empty aggTrades file"]
    if df["aggregate_trade_id"].n_unique() != df.height:
        issues.append("duplicate aggregate_trade_id values")
    if not df["aggregate_trade_id"].is_sorted():
        issues.append("aggregate_trade_id values are not sorted")
    if not df["transact_time"].is_sorted():
        issues.append("transact_time values are not sorted")
    return issues


def repair_kline_gaps(df: pl.DataFrame, *, interval: str) -> pl.DataFrame:
    expected_step_us = INTERVAL_SECONDS[interval] * 1_000_000
    start = int(df["open_time"][0])
    end = int(df["open_time"][-1])
    full_times = pl.DataFrame({"open_time": list(range(start, end + expected_step_us, expected_step_us))})
    repaired = full_times.join(df, on="open_time", how="left").with_columns(
        pl.col("symbol").is_null().alias("is_synthetic"),
        pl.col("symbol").fill_null(strategy="forward").fill_null(strategy="backward"),
        pl.col("source").fill_null(strategy="forward").fill_null(strategy="backward"),
        pl.col("interval").fill_null(strategy="forward").fill_null(strategy="backward"),
        pl.col("close").fill_null(strategy="forward"),
        pl.col("volume").fill_null(0.0),
        pl.col("quote_volume").fill_null(0.0),
        pl.col("trade_count").fill_null(0),
        pl.col("taker_buy_base_volume").fill_null(0.0),
        pl.col("taker_buy_quote_volume").fill_null(0.0),
    )
    repaired = repaired.with_columns(
        pl.col("open").fill_null(pl.col("close")),
        pl.col("high").fill_null(pl.col("close")),
        pl.col("low").fill_null(pl.col("close")),
        pl.col("close_time").fill_null(pl.col("open_time") + expected_step_us - 1),
        pl.col("timestamp").fill_null(pl.from_epoch("open_time", time_unit="us")),
    )
    return repaired.select(df.columns)


def _read_kline_zip(path: Path, *, symbol: str, interval: str) -> pl.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("zip must contain exactly one csv file")
        with archive.open(names[0]) as csv_file:
            raw = csv_file.read()

    first_line = raw.splitlines()[0].decode("utf-8", errors="ignore")
    has_header = first_line.lower().startswith("open_time")
    dataframe = pl.read_csv(
        io.BytesIO(raw),
        has_header=has_header,
        separator=",",
        new_columns=list(KLINE_COLUMNS) if not has_header else None,
    )
    if dataframe.width != len(KLINE_COLUMNS):
        raise ValueError(f"expected {len(KLINE_COLUMNS)} columns, got {dataframe.width}")
    if has_header:
        dataframe = dataframe.rename(dict(zip(dataframe.columns, KLINE_COLUMNS, strict=True)))

    dataframe = dataframe.with_columns(
        pl.col("open_time").cast(pl.Int64).map_elements(_timestamp_to_microseconds, return_dtype=pl.Int64),
        pl.col("close_time").cast(pl.Int64).map_elements(_timestamp_to_microseconds, return_dtype=pl.Int64),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64),
        pl.col("quote_volume").cast(pl.Float64),
        pl.col("trade_count").cast(pl.Int64),
        pl.col("taker_buy_base_volume").cast(pl.Float64),
        pl.col("taker_buy_quote_volume").cast(pl.Float64),
    ).with_columns(
        pl.from_epoch("open_time", time_unit="us").alias("timestamp"),
        pl.lit(symbol.upper()).alias("symbol"),
        pl.lit(interval).alias("interval"),
        pl.lit("binance").alias("source"),
        pl.lit(False).alias("is_synthetic"),
    )

    return dataframe.select(
        [
            "timestamp",
            "symbol",
            "source",
            "interval",
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trade_count",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
            "is_synthetic",
        ]
    )


def _read_agg_trades_zip(path: Path, *, symbol: str) -> pl.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("zip must contain exactly one csv file")
        with archive.open(names[0]) as csv_file:
            raw = csv_file.read()

    first_line = raw.splitlines()[0].decode("utf-8", errors="ignore")
    has_header = first_line.lower().startswith("agg_trade_id") or first_line.lower().startswith(
        "aggregate_trade_id"
    )
    dataframe = pl.read_csv(
        io.BytesIO(raw),
        has_header=has_header,
        separator=",",
        new_columns=list(AGG_TRADE_COLUMNS) if not has_header else None,
    )
    if dataframe.width != len(AGG_TRADE_COLUMNS):
        raise ValueError(f"expected {len(AGG_TRADE_COLUMNS)} columns, got {dataframe.width}")
    if has_header:
        dataframe = dataframe.rename(dict(zip(dataframe.columns, AGG_TRADE_COLUMNS, strict=True)))

    dataframe = dataframe.with_columns(
        pl.col("aggregate_trade_id").cast(pl.Int64),
        pl.col("price").cast(pl.Float64),
        pl.col("quantity").cast(pl.Float64),
        pl.col("first_trade_id").cast(pl.Int64),
        pl.col("last_trade_id").cast(pl.Int64),
        pl.col("transact_time").cast(pl.Int64).map_elements(
            _timestamp_to_microseconds, return_dtype=pl.Int64
        ),
        pl.col("is_buyer_maker").cast(pl.Boolean),
        pl.col("is_best_match").cast(pl.Boolean),
    ).with_columns(
        pl.from_epoch("transact_time", time_unit="us").alias("timestamp"),
        pl.lit(symbol.upper()).alias("symbol"),
        pl.lit("binance").alias("source"),
    )

    return dataframe.select(
        [
            "timestamp",
            "symbol",
            "source",
            "aggregate_trade_id",
            "price",
            "quantity",
            "first_trade_id",
            "last_trade_id",
            "transact_time",
            "is_buyer_maker",
            "is_best_match",
        ]
    )


def _timestamp_to_microseconds(value: int) -> int:
    if value < 10_000_000_000_000:
        return value * 1_000
    return value


def _download_file(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as response, path.open("wb") as output:
            shutil.copyfileobj(response, output)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MissingBinanceDataError(
                "Binance has no monthly data file for this symbol, interval, and month."
            ) from exc
        raise ValueError(f"download failed: {url} returned HTTP {exc.code}") from exc


def _try_download_file(url: str, path: Path) -> bool:
    try:
        _download_file(url, path)
    except (MissingBinanceDataError, ValueError):
        path.unlink(missing_ok=True)
        return False
    return True


def _parse_checksum(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return text.split()[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_year_month(value: str) -> tuple[int, int]:
    parsed = datetime.strptime(value, "%Y-%m").replace(tzinfo=UTC)
    return parsed.year, parsed.month


def _emit(callback: ProgressCallback | None, event: dict) -> None:
    if callback is not None:
        callback(event)


def create_session_id() -> str:
    return f"session_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


def data_window_id(file: DownloadedFile) -> str:
    fingerprint = "|".join(
        (
            file.source,
            file.market,
            file.data_type,
            file.symbol,
            file.interval,
            file.year_month,
            file.start_time or "",
            file.end_time or "",
            file.sha256 or "",
        )
    )
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:10]
    compact_month = file.year_month.replace("-", "")
    return f"win_{file.source}_{file.market}_{file.symbol}_{file.interval}_{compact_month}_{digest}"


def link_or_copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def write_session_manifest(
    *,
    session_path: Path,
    summary: DownloadSummary,
    request: DownloadRequest,
    symbols: tuple[str, ...],
) -> None:
    manifest = {
        "session_id": summary.session_id,
        "source": "binance",
        "market": "spot",
        "data_type": "klines+aggTrades" if request.include_agg_trades else "klines",
        "data_layers": ["klines", "aggTrades"] if request.include_agg_trades else ["klines"],
        "interval": request.interval,
        "symbols": list(symbols),
        "start_month": request.start_month,
        "end_month": request.end_month,
        "target_file_count": summary.requested_months,
        "candidate_file_count": summary.candidate_months,
        "attempted_file_count": summary.attempted_files,
        "valid_file_count": summary.normalized_files + summary.skipped_existing,
        "window_count": len(summary.windows),
        "windows": summary.windows,
        "normalized_files": summary.normalized_files,
        "reused_files": summary.skipped_existing,
        "failed_files": summary.failed_files,
        "data_paths": {
            "klines": str(session_path / "data" / "klines"),
            "aggTrades": str(session_path / "data" / "aggTrades")
            if request.include_agg_trades
            else None,
        },
        "data_path": str(session_path / "data" / "klines"),
        "agg_trades_files": summary.agg_trades_normalized + summary.agg_trades_skipped_existing,
        "agg_trades_normalized": summary.agg_trades_normalized,
        "agg_trades_reused": summary.agg_trades_skipped_existing,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (session_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
