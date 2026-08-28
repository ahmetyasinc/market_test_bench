from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from market_test_bench.protocol import validate_decisions_directory

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


if __name__ == "__main__":
    app()
