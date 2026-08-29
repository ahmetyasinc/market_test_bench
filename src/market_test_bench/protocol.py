import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REQUIRED_DECISION_COLUMNS = ("timestamp", "symbol", "target_quantity")


@dataclass(frozen=True)
class ValidationIssue:
    file_name: str | None
    row_number: int | None
    issue_code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: tuple[str, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    row_count: int = 0


def validate_decision_file(
    path: Path,
    *,
    allowed_symbols: set[str] | None = None,
    allow_short: bool = True,
) -> ValidationResult:
    """Validate the initial file-based target-quantity decision protocol."""
    issues: list[ValidationIssue] = []

    if not path.exists():
        issue = _issue(path, None, "file_missing", f"{path} does not exist.")
        return ValidationResult(False, (issue.message,), (issue,))

    try:
        with path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            decisions = list(reader)
            columns = set(reader.fieldnames or ())
    except (OSError, UnicodeError, csv.Error) as exc:
        issue = _issue(path, None, "file_unreadable", f"{path} could not be read: {exc}")
        return ValidationResult(False, (issue.message,), (issue,))

    missing_columns = [col for col in REQUIRED_DECISION_COLUMNS if col not in columns]
    if missing_columns:
        issues.append(
            _issue(
                path,
                None,
                "missing_columns",
                f"{path} is missing required columns: {', '.join(missing_columns)}.",
            )
        )
        return ValidationResult(False, _messages(issues), tuple(issues), len(decisions))

    if not decisions:
        return ValidationResult(True, (), (), 0)

    seen_keys: set[tuple[str, str, str]] = set()
    normalized_allowed_symbols = (
        {_normalize_symbol(symbol) for symbol in allowed_symbols} if allowed_symbols is not None else None
    )
    for row_number, row in enumerate(decisions, start=2):
        timestamp = row["timestamp"]
        symbol = row["symbol"]
        window_id = row.get("window_id", "")

        if not _is_iso_timestamp(timestamp):
            issues.append(
                _issue(path, row_number, "invalid_timestamp", f"{path} row {row_number} contains an invalid timestamp.")
            )

        if normalized_allowed_symbols is not None and _normalize_symbol(symbol) not in normalized_allowed_symbols:
            issues.append(
                _issue(
                    path,
                    row_number,
                    "unknown_symbol",
                    f"{path} row {row_number} contains a symbol outside the selected session: {symbol}.",
                )
            )

        try:
            target_quantity = float(row["target_quantity"])
        except ValueError:
            issues.append(
                _issue(
                    path,
                    row_number,
                    "non_numeric_quantity",
                    f"{path} row {row_number} contains a non-numeric target quantity.",
                )
            )
            continue

        if target_quantity < 0 and not allow_short:
            issues.append(
                _issue(
                    path,
                    row_number,
                    "short_not_allowed",
                    f"{path} row {row_number} contains a negative target quantity while shorting is disabled.",
                )
            )

        key = (window_id, timestamp, symbol)
        if key in seen_keys:
            issues.append(
                _issue(
                    path,
                    row_number,
                    "duplicate_decision_key",
                    f"{path} contains duplicate window/timestamp/symbol decisions.",
                )
            )
        seen_keys.add(key)

    return ValidationResult(not issues, _messages(issues), tuple(issues), len(decisions))


def validate_decisions_directory(
    path: Path,
    *,
    allowed_symbols: set[str] | None = None,
    allow_short: bool = True,
) -> ValidationResult:
    if not path.exists():
        issue = ValidationIssue(None, None, "directory_missing", f"{path} does not exist.")
        return ValidationResult(False, (issue.message,), (issue,))

    files = sorted(path.glob("*.csv"))
    if not files:
        issue = ValidationIssue(None, None, "no_csv_files", f"{path} does not contain any CSV decision files.")
        return ValidationResult(False, (issue.message,), (issue,))

    errors: list[str] = []
    issues: list[ValidationIssue] = []
    row_count = 0
    for file_path in files:
        result = validate_decision_file(
            file_path,
            allowed_symbols=allowed_symbols,
            allow_short=allow_short,
        )
        errors.extend(result.errors)
        issues.extend(result.issues)
        row_count += result.row_count

    return ValidationResult(not errors, tuple(errors), tuple(issues), row_count)


def _is_iso_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _normalize_symbol(value: str) -> str:
    return value.upper().replace("-", "").replace("/", "").strip()


def _issue(path: Path, row_number: int | None, issue_code: str, message: str) -> ValidationIssue:
    return ValidationIssue(path.name, row_number, issue_code, message)


def _messages(issues: list[ValidationIssue]) -> tuple[str, ...]:
    return tuple(issue.message for issue in issues)
