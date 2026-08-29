# MarketTestBench

MarketTestBench is an open-source, strategy-agnostic benchmark for testing trading strategy outputs across market windows and labeled market regimes.

It does not define or run your strategy. Your strategy can be a Python script, a machine learning model, an AI agent, a notebook, a Rust binary, or a completely external system. As long as it can read benchmark windows and write target-position files, it can be evaluated.

## Why

Most backtests are tied to fixed datasets and fixed assumptions. That makes results easy to overfit and hard to compare.

MarketTestBench is designed around a different idea:

> Generate diverse market test windows, classify their regimes, collect external strategy outputs, and evaluate robustness across changing market conditions.

## Core Workflow

```text
1. Download and normalize market data into a local data session
2. Assign stable `window_id` values and classify each window by market regime
3. User runs any external strategy on the generated session data
4. Strategy writes sparse target-quantity decision files
5. MarketTestBench validates and stores the simulation upload
6. MarketTestBench will simulate execution and report performance by regime
```

## Strategy Output Protocol

The first supported protocol is file-based. A strategy writes sparse CSV decision events containing target base-asset quantities:

```csv
window_id,timestamp,symbol,target_quantity,price
win_binance_spot_BTCUSDT_1h_202401_abc123,2024-01-01T00:00:00Z,BTCUSDT,0.0,42200.0
win_binance_spot_BTCUSDT_1h_202401_abc123,2024-01-02T12:00:00Z,BTCUSDT,0.125,43150.5
win_binance_spot_BTCUSDT_1h_202401_abc123,2024-01-05T09:00:00Z,BTCUSDT,0.04,44010.2
win_binance_spot_BTCUSDT_1h_202401_abc123,2024-01-10T18:00:00Z,BTCUSDT,0.0,41880.0
```

Meaning:

- `window_id`: the exact window identifier from the session manifest
- `target_quantity = 0.125`: target net base-asset quantity after the event
- `price = 43150.5`: actual strategy fill price for that target quantity change
- Positive quantities are long, negative quantities are short if the scenario allows shorting, and `0.0` is flat
- Missing timestamps keep the previous target quantity
- If no decision is provided, the position is considered flat

The strategy owns fill price assumptions such as spread, slippage, and order execution. The
benchmark owns fees, portfolio accounting, and risk metrics.

## Planned Concepts

- **Universe**: the available market data space, such as symbols, venues, timeframes, and date range.
- **Scenario**: the benchmark protocol, including window count, bar count, sampling rules, and target regime distribution.
- **Window**: a single sampled market period with context and tradable ranges.
- **Decision**: the external strategy output for a window.
- **Report**: aggregated metrics across all windows and market regimes.

## Example Repository Flow

```bash
# Install the project in a virtual environment
python -m pip install -e .

# Download, normalize, classify, and store a data session
market-test-bench download --symbols BTCUSDT,ETHUSDT --interval 1h --month-count 100

# Or start the local dashboard
market-test-bench serve
```

## Status

This project is in early design and implementation. The current MVP supports:

- Binance monthly kline download
- optional Binance aggTrades download
- normalized Parquet session storage
- stable data-specific `window_id` generation
- regime labeling
- file-based strategy output protocol
- simulation upload storage
- decision CSV validation

Planned next steps:

- stricter `window_id` and timestamp-range validation
- target-quantity execution simulation
- machine-readable performance reports
- regime-aware performance summaries

## License

Apache-2.0
