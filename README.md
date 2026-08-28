# MarketTestBench

MarketTestBench is an open-source, strategy-agnostic benchmark for testing trading strategy outputs across randomized market windows and labeled market regimes.

It does not define or run your strategy. Your strategy can be a Python script, a machine learning model, an AI agent, a notebook, a Rust binary, or a completely external system. As long as it can read benchmark windows and write target-position files, it can be evaluated.

## Why

Most backtests are tied to fixed datasets and fixed assumptions. That makes results easy to overfit and hard to compare.

MarketTestBench is designed around a different idea:

> Generate diverse market test windows, classify their regimes, collect external strategy outputs, and evaluate robustness across changing market conditions.

## Core Workflow

```text
1. Prepare randomized market windows
2. Classify each window by market regime
3. User runs any external strategy on the generated data
4. Strategy writes target-position decision files
5. MarketTestBench simulates execution and reports performance by regime
```

## Strategy Output Protocol

The first supported protocol is file-based. For each generated market window, a strategy writes a CSV file containing target portfolio weights:

```csv
timestamp,symbol,target_weight
2024-01-01T00:00:00Z,BTC-USDT,0.0
2024-01-02T12:00:00Z,BTC-USDT,1.0
2024-01-05T09:00:00Z,BTC-USDT,0.4
2024-01-10T18:00:00Z,BTC-USDT,0.0
```

Meaning:

- `target_weight = 1.0`: fully long
- `target_weight = 0.0`: flat or cash
- `target_weight = -1.0`: fully short, if the scenario allows shorting
- Missing timestamps keep the previous target weight
- If no decision is provided, the position is considered flat

The benchmark owns execution assumptions such as fill price, fees, slippage, portfolio accounting, and risk metrics.

## Planned Concepts

- **Universe**: the available market data space, such as symbols, venues, timeframes, and date range.
- **Scenario**: the benchmark protocol, including window count, bar count, sampling rules, and target regime distribution.
- **Window**: a single sampled market period with context and tradable ranges.
- **Decision**: the external strategy output for a window.
- **Report**: aggregated metrics across all windows and market regimes.

## Example Repository Flow

```bash
# Prepare test windows from a scenario
market-test-bench prepare scenarios/crypto_mixed.yaml --out runs/test_001

# Run your own strategy however you want
python my_strategy.py --manifest runs/test_001/manifest.json --output runs/test_001/decisions

# Evaluate the generated decision files
market-test-bench evaluate runs/test_001
```

## Status

This project is in early design and implementation. The first goal is a minimal, reliable benchmark core:

- randomized window generation
- regime labeling
- file-based strategy output protocol
- target-weight evaluation
- regime-aware performance reports

## License

Apache-2.0
