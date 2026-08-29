# Strategy Output Protocol

MarketTestBench starts with a simple file-based protocol.

Each prepared benchmark run contains a manifest and one data file per market window. External strategies read those files and write decisions into a `decisions/` directory.

## Target Quantity CSV

MarketTestBench standard initial cash = 10000 USDT. Strategy engines calculate sizing, stops,
partial closes, and order tracking against this fixed capital base.

Required columns:

```csv
timestamp,symbol,target_quantity
```

Example:

```csv
timestamp,symbol,target_quantity
2024-01-01T00:00:00Z,BTC-USDT,0.0
2024-01-02T12:00:00Z,BTC-USDT,0.125
2024-01-05T09:00:00Z,BTC-USDT,0.04
2024-01-10T18:00:00Z,BTC-USDT,0.0
```

## Rules

- Timestamps must be ISO-8601 compatible.
- `target_quantity` must be numeric.
- Positive quantities are long, negative quantities are short, and `0.0` is flat.
- Scenario settings may restrict quantities to long-only.
- Duplicate `timestamp` and `symbol` rows are invalid.
- Missing timestamps keep the previous target quantity.
- A missing decision file means flat exposure for that window only if the scenario explicitly allows it.
