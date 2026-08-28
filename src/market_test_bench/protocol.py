import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REQUIRED_DECISION_COLUMNS = ("timestamp", "symbol", "target_weight")


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: tuple[str, ...] = ()


def validate_decision_file(path: Path) -> ValidationResult:
    """Validate the initial file-based target-weight decision protocol."""
    errors: list[str] = []

    if not path.exists():
        return ValidationResult(False, (f"{path} does not exist.",))

    try:
        with path.open(newline="", encoding="utf-8") as csv_file:
            decisions = list(csv.DictReader(csv_file))
    except (OSError, UnicodeError, csv.Error) as exc:
        return ValidationResult(False, (f"{path} could not be read: {exc}",))

    if not decisions:
        return ValidationResult(False, (f"{path} does not contain any decisions.",))

    columns = set(decisions[0])
    missing_columns = [col for col in REQUIRED_DECISION_COLUMNS if col not in columns]
    if missing_columns:
        errors.append(f"{path} is missing required columns: {', '.join(missing_columns)}.")
        return ValidationResult(False, tuple(errors))

    seen_keys: set[tuple[str, str]] = set()
    for row_number, row in enumerate(decisions, start=2):
        timestamp = row["timestamp"]
        symbol = row["symbol"]

        if not _is_iso_timestamp(timestamp):
            errors.append(f"{path} row {row_number} contains an invalid timestamp.")

        try:
            target_weight = float(row["target_weight"])
        except ValueError:
            errors.append(f"{path} row {row_number} contains a non-numeric target weight.")
            continue

        if target_weight < -1.0 or target_weight > 1.0:
            errors.append(
                f"{path} row {row_number} contains a target weight outside the [-1.0, 1.0] range."
            )

        key = (timestamp, symbol)
        if key in seen_keys:
            errors.append(f"{path} contains duplicate timestamp/symbol decisions.")
        seen_keys.add(key)

    return ValidationResult(not errors, tuple(errors))


def validate_decisions_directory(path: Path) -> ValidationResult:
    if not path.exists():
        return ValidationResult(False, (f"{path} does not exist.",))

    files = sorted(path.glob("*.csv"))
    if not files:
        return ValidationResult(False, (f"{path} does not contain any CSV decision files.",))

    errors: list[str] = []
    for file_path in files:
        result = validate_decision_file(file_path)
        errors.extend(result.errors)

    return ValidationResult(not errors, tuple(errors))


def _is_iso_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True
