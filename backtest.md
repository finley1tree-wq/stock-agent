# Backtest — generated 2026-09-07

$400 deployed every week under the live guardrails (max 40% per ticker, min $5, at most 4 buys per deploy). Buy-and-hold, no selling. This tests the **signal rules**, not Claude's judgement.

## Read this first

- UNSTABLE: the best strategy differs by window (2y->momentum_1w, 5y->contrarian_1m). Do not treat the ranking as a rule; it is noise-dominated.
- SELECTION BIAS: the watchlist was chosen in 2026 already knowing which themes had run (nuclear, defense, gold). Every strategy beats SPY here largely because of the ticker list, not the rule. Treat 'vs SPY' as meaningless.
- NO SELLING and no transaction costs are modelled; the live agent may sell.
- Claude's judgement is NOT replayed — only the mechanical signal rules are.

## 2-year window — 2024-09-05 → 2026-09-04

| Strategy | Return | vs SPY | Profit | Max drawdown | Buys |
|---|---:|---:|---:|---:|---:|
| momentum_1w | +31.38% | +22.64% | $+13,177.90 | 22.3% | 412 |
| momentum_1m | +27.51% | +18.77% | $+11,552.20 | 20.7% | 400 |
| equal_weight | +24.40% | +15.66% | $+10,248.08 | 11.8% | 420 |
| contrarian_1m | +23.62% | +14.88% | $+9,920.07 | 12.9% | 400 |
| sector_rotate | +22.27% | +13.53% | $+9,352.42 | 24.9% | 278 |
| etf_default | +20.33% | +11.59% | $+8,538.45 | 10.2% | 420 |
| spy_only | +8.74% | +0.00% | $+3,668.94 | 4.1% | 105 |

**Does momentum predict?**

| Bucket | Next 1 week | Next 1 month |
|---|---:|---:|
| high momentum | +1.59% (hit 52%, n=276) | +5.05% (hit 57%, n=276) |
| low momentum | +0.60% (hit 54%, n=276) | +2.73% (hit 56%, n=276) |

**Sectors over this window**

| Sector | Avg total return |
|---|---:|
| nuclear | +282.46% |
| defense | +137.93% |
| gold | +114.52% |
| index | +39.15% |
| real estate | +11.26% |

## 5-year window — 2021-09-07 → 2026-09-04

| Strategy | Return | vs SPY | Profit | Max drawdown | Buys |
|---|---:|---:|---:|---:|---:|
| contrarian_1m | +172.25% | +148.83% | $+179,833.84 | 30.0% | 1024 |
| momentum_1w | +147.68% | +124.26% | $+154,180.78 | 29.0% | 1036 |
| momentum_1m | +140.40% | +116.98% | $+146,577.47 | 27.2% | 1024 |
| sector_rotate | +110.48% | +87.06% | $+115,337.95 | 34.5% | 738 |
| equal_weight | +79.82% | +56.40% | $+83,332.03 | 19.8% | 1044 |
| etf_default | +65.99% | +42.57% | $+68,891.83 | 13.5% | 1044 |
| spy_only | +23.42% | +0.00% | $+24,446.90 | 5.8% | 261 |

**Does momentum predict?**

| Bucket | Next 1 week | Next 1 month |
|---|---:|---:|
| high momentum | +0.90% (hit 58%, n=729) | +2.81% (hit 56%, n=729) |
| low momentum | +0.52% (hit 54%, n=729) | +2.32% (hit 57%, n=729) |

**Sectors over this window**

| Sector | Avg total return |
|---|---:|
| nuclear | +269.63% |
| defense | +212.46% |
| gold | +148.58% |
| index | +74.11% |
| real estate | +12.09% |

Past performance says nothing about the future. This is a prior, not a promise.
