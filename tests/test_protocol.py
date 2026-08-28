from pathlib import Path

from market_test_bench.protocol import validate_decision_file


def test_valid_decision_file(tmp_path: Path) -> None:
    path = tmp_path / "window_001.csv"
    path.write_text(
        """timestamp,symbol,target_weight
2024-01-01T00:00:00Z,BTC-USDT,0.0
2024-01-02T00:00:00Z,BTC-USDT,1.0
""",
        encoding="utf-8",
    )

    result = validate_decision_file(path)

    assert result.is_valid


def test_rejects_duplicate_timestamp_symbol(tmp_path: Path) -> None:
    path = tmp_path / "window_001.csv"
    path.write_text(
        """timestamp,symbol,target_weight
2024-01-01T00:00:00Z,BTC-USDT,0.0
2024-01-01T00:00:00Z,BTC-USDT,1.0
""",
        encoding="utf-8",
    )

    result = validate_decision_file(path)

    assert not result.is_valid
    assert "duplicate" in result.errors[0]
