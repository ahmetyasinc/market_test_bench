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

## Universe

A universe describes the available data space:

- asset class
- symbols
- venue or data source
- timeframe
- earliest and latest allowed timestamps

## Scenario

A scenario describes how benchmark windows should be sampled:

- number of windows
- bars per window
- context bars
- target regime distribution
- fee and slippage assumptions
- long-only or long/short constraints

## Window

A window is one sampled market period. It contains a context range and a tradable range.

The context range can be used by external strategies for indicators, features, or model state. Scores are calculated only on the tradable range.

## Decision

A decision file contains target weights over time for a specific window.

MarketTestBench handles order generation, fills, costs, portfolio accounting, and metrics.
