# Design Notes

MarketTestBench is built around a file-based protocol rather than an embedded strategy API.

## Principles

- Strategy-agnostic by default
- Randomized market window generation
- Regime-aware evaluation
- Reproducible benchmark runs through scenario metadata and seeds
- Machine-readable reports
- Clear separation between data preparation, strategy execution, and evaluation

## Main Objects

```text
Universe -> Scenario -> Window -> Decision -> Evaluation -> Report
```

The current implementation covers data sessions, window identity, classification, decision upload,
and validation. Scenario-based sampling, execution simulation, and reporting are planned next
steps.

## Universe

A universe describes the available data space:

- asset class
- symbols
- venue or data source
- timeframe
- earliest and latest allowed timestamps

## Data Session

A data session is the current implemented preparation unit. It records downloaded and normalized
market files, stores a manifest, and assigns stable data-specific `window_id` values.

Each session window includes:

- `window_id`
- symbol
- interval
- start and end timestamps
- row count
- normalized data path

## Scenario

A scenario describes how benchmark windows should be sampled:

- number of windows
- bars per window
- context bars
- target regime distribution
- fee and slippage assumptions
- long-only or long/short constraints

Scenario-based sampling is still planned. Until it is implemented, each accepted monthly kline file
acts as one session window.

## Window

A window is one sampled market period. It contains a context range and a tradable range.

The context range can be used by external strategies for indicators, features, or model state. Scores are calculated only on the tradable range.

## Decision

A decision file contains target quantities over time for a specific window.

The preferred decision format is a sparse CSV with:

```csv
window_id,timestamp,symbol,target_quantity,price
```

The current MVP validates uploaded decision files and stores simulation metadata. Execution
simulation and metrics are not implemented yet.

## Evaluation

Evaluation will replay target-quantity decision events over the selected market windows. The
strategy-provided `price` is treated as the actual fill price. Evaluation owns fees, portfolio
accounting, and risk metrics.

The first evaluation implementation should produce deterministic machine-readable outputs under
each simulation's `results/` directory.

## Report

A report aggregates evaluation outputs across all windows and market regimes.

Planned report outputs include:

- overall performance metrics
- per-window metrics
- regime-aware performance summaries
- equity curves
- trade and turnover summaries
