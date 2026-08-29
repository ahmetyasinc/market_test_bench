# Strategy Output Protocol

MarketTestBench starts with a simple file-based protocol.

Each prepared data session contains a `manifest.json` file and one normalized market data file per
window. External strategies read the manifest and data files, then upload one or more decision CSV
files as a simulation.

## Target Quantity CSV

MarketTestBench standard initial cash = 10000 USDT. Strategy engines calculate sizing, stops,
partial closes, and order tracking against this fixed capital base.

Preferred columns:

```csv
window_id,timestamp,symbol,target_quantity,price
```

Example:

```csv
window_id,timestamp,symbol,target_quantity,price
win_binance_spot_BTCUSDT_1h_202401_abc123,2024-01-01T00:00:00Z,BTCUSDT,0.0,42200.0
win_binance_spot_BTCUSDT_1h_202401_abc123,2024-01-02T12:00:00Z,BTCUSDT,0.125,43150.5
win_binance_spot_BTCUSDT_1h_202401_abc123,2024-01-05T09:00:00Z,BTCUSDT,0.04,44010.2
win_binance_spot_BTCUSDT_1h_202401_abc123,2024-01-10T18:00:00Z,BTCUSDT,0.0,41880.0
```

## Rules

- `window_id` should match an exact window from the selected session manifest.
- Timestamps must be ISO-8601 compatible.
- Symbols should match the exact session symbol, for example `BTCUSDT`.
- `target_quantity` must be numeric.
- `price` must be numeric and greater than zero. It is the actual strategy fill price for the
  target quantity change.
- Positive quantities are long, negative quantities are short, and `0.0` is flat.
- Scenario settings may restrict quantities to long-only.
- Duplicate `window_id`, `timestamp`, and `symbol` rows are invalid.
- Missing timestamps keep the previous target quantity.
- Before the first decision event for a window and symbol, target quantity is `0.0`.
- A strategy with no signals may upload a CSV with only the header row.
- If a window has no decision rows, it is evaluated as flat.

## Current MVP Compatibility

The current validator accepts older session-level CSV files without `window_id` as long as they
contain `timestamp`, `symbol`, `target_quantity`, and `price`. New strategy templates and reporting work
should use `window_id`; final benchmark-run validation will make it mandatory.
