from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from market_test_bench.binance import BinanceDataManager, DownloadRequest
from market_test_bench.catalog import Catalog
from market_test_bench.protocol import validate_decisions_directory
from market_test_bench.workspace import open_workspace

app = typer.Typer(help="MarketTestBench command line interface.")
console = Console()


@app.command()
def prepare(
    scenario: Annotated[Path, typer.Argument(help="Path to a scenario YAML file.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output run directory.")],
) -> None:
    """Prepare randomized benchmark windows from a scenario file."""
    console.print("[yellow]prepare is not implemented yet.[/yellow]")
    console.print(f"Scenario: {scenario}")
    console.print(f"Output: {out}")


@app.command()
def evaluate(
    run_dir: Annotated[
        Path,
        typer.Argument(help="Prepared run directory containing manifest and decisions."),
    ],
) -> None:
    """Evaluate decision files for a prepared benchmark run."""
    decisions_dir = run_dir / "decisions"
    result = validate_decisions_directory(decisions_dir)

    if result.is_valid:
        console.print("[green]Decision files look valid.[/green]")
        return

    console.print("[red]Decision files are invalid.[/red]")
    for error in result.errors:
        console.print(f"- {error}")
    raise typer.Exit(code=1)


@app.command()
def download(
    symbols: Annotated[
        str | None,
        typer.Option(
            "--symbols",
            help="Comma-separated symbols, for example BTCUSDT,ETHUSDT. Omit when using --volume-preset.",
        ),
    ] = None,
    volume_preset: Annotated[
        str | None,
        typer.Option("--volume-preset", help="One of top_10, top_30, top_100."),
    ] = None,
    interval: Annotated[str, typer.Option("--interval", help="Binance kline interval.")] = "1h",
    start_month: Annotated[str, typer.Option("--start-month", help="YYYY-MM.")] = "2020-01",
    end_month: Annotated[str, typer.Option("--end-month", help="YYYY-MM.")] = "2026-01",
    month_count: Annotated[int, typer.Option("--month-count", help="Must be at least 100.")] = 100,
    seed: Annotated[int, typer.Option("--seed", help="Deterministic random seed.")] = 42,
    workers: Annotated[int, typer.Option("--workers", help="Parallel download workers.")] = 4,
    include_agg_trades: Annotated[
        bool,
        typer.Option("--include-agg-trades", help="Download aggTrades for every accepted kline file."),
    ] = False,
    workspace: Annotated[Path | None, typer.Option("--workspace", help="Workspace path.")] = None,
) -> None:
    """Download, validate, normalize, classify, and store Binance monthly market data as Parquet."""
    opened_workspace = open_workspace(workspace)
    catalog = Catalog(opened_workspace)
    manager = BinanceDataManager(opened_workspace, catalog)
    request = DownloadRequest(
        symbols=tuple(item.strip().upper() for item in symbols.split(",")) if symbols else (),
        volume_preset=volume_preset,
        interval=interval,
        start_month=start_month,
        end_month=end_month,
        month_count=month_count,
        seed=seed,
        workers=workers,
        include_agg_trades=include_agg_trades,
    )
    summary = manager.download_dataset(request)
    console.print("[green]Dataset download completed.[/green]")
    console.print(f"Workspace: {opened_workspace.root}")
    console.print(f"Normalized files: {summary.normalized_files}")
    console.print(f"Skipped existing files: {summary.skipped_existing}")
    console.print(f"aggTrades files: {summary.agg_trades_normalized + summary.agg_trades_skipped_existing}")
    console.print(f"Failed files: {summary.failed_files}")


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8787,
    workspace: Annotated[Path | None, typer.Option("--workspace", help="Workspace path.")] = None,
) -> None:
    """Start the local MarketTestBench dashboard."""
    import uvicorn

    if workspace is not None:
        import os

        os.environ["MARKET_TEST_BENCH_HOME"] = str(workspace)

    uvicorn.run("market_test_bench.server.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
