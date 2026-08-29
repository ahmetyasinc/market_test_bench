from pathlib import Path

from market_test_bench.protocol import validate_decision_file


def test_valid_decision_file(tmp_path: Path) -> None:
    path = tmp_path / "window_001.csv"
    path.write_text(
        """timestamp,symbol,target_quantity
2024-01-01T00:00:00Z,BTC-USDT,0.0
2024-01-02T00:00:00Z,BTC-USDT,0.125
""",
        encoding="utf-8",
    )

    result = validate_decision_file(path)

    assert result.is_valid


def test_rejects_duplicate_timestamp_symbol(tmp_path: Path) -> None:
    path = tmp_path / "window_001.csv"
    path.write_text(
        """timestamp,symbol,target_quantity
2024-01-01T00:00:00Z,BTC-USDT,0.0
2024-01-01T00:00:00Z,BTC-USDT,0.125
""",
        encoding="utf-8",
    )

    result = validate_decision_file(path)

    assert not result.is_valid
    assert "duplicate" in result.errors[0]


def test_allows_header_only_decision_file_for_no_signal_strategy(tmp_path: Path) -> None:
    path = tmp_path / "decisions.csv"
    path.write_text("window_id,timestamp,symbol,target_quantity\n", encoding="utf-8")

    result = validate_decision_file(path)

    assert result.is_valid
    assert result.row_count == 0


def test_duplicate_check_includes_window_id_when_present(tmp_path: Path) -> None:
    path = tmp_path / "decisions.csv"
    path.write_text(
        """window_id,timestamp,symbol,target_quantity
window_a,2024-01-01T00:00:00Z,BTCUSDT,0.125
window_b,2024-01-01T00:00:00Z,BTCUSDT,0.0
""",
        encoding="utf-8",
    )

    result = validate_decision_file(path)

    assert result.is_valid


def test_rejects_duplicate_window_timestamp_symbol(tmp_path: Path) -> None:
    path = tmp_path / "decisions.csv"
    path.write_text(
        """window_id,timestamp,symbol,target_quantity
window_a,2024-01-01T00:00:00Z,BTCUSDT,0.125
window_a,2024-01-01T00:00:00Z,BTCUSDT,0.0
""",
        encoding="utf-8",
    )

    result = validate_decision_file(path)

    assert not result.is_valid
    assert result.issues[0].issue_code == "duplicate_decision_key"
