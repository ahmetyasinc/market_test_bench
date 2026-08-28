# Strategy Output Protocol

MarketTestBench starts with a simple file-based protocol.

Each prepared benchmark run contains a manifest and one data file per market window. External strategies read those files and write decisions into a `decisions/` directory.

## Target Weight CSV

Required columns:

```csv
timestamp,symbol,target_weight
```

Example:

```csv
timestamp,symbol,target_weight
2024-01-01T00:00:00Z,BTC-USDT,0.0
2024-01-02T12:00:00Z,BTC-USDT,1.0
2024-01-05T09:00:00Z,BTC-USDT,0.4
2024-01-10T18:00:00Z,BTC-USDT,0.0
```

## Rules

- Timestamps must be ISO-8601 compatible.
- `target_weight` must be numeric.
- The default allowed range is `-1.0` to `1.0`.
- Scenario settings may restrict weights to long-only.
- Duplicate `timestamp` and `symbol` rows are invalid.
- Missing timestamps keep the previous target weight.
- A missing decision file means flat exposure for that window only if the scenario explicitly allows it.
