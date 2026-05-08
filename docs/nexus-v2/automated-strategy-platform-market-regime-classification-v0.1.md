# Automated Strategy Platform: Market Regime Classification v0.1

**Status:** Supporting specification  
**Supports:** Automated Strategy Platform Requirements v1.3  
**Purpose:** Define minimum market-regime labels for strategy catalog performance and policy review screens.

---

## 1. Core Principle

Strategy performance should not be shown as one undifferentiated number when behavior differs by market regime.

Regime labels must be deterministic, versioned, and reproducible from stored market data.

---

## 2. Required Regime Dimensions

MVP catalog should support at least:

```text
trend_regime
volatility_regime
intraday_structure_regime
liquidity_regime
```

---

## 3. Trend Regime

Inputs:

```text
underlying_close
20-day moving average
50-day moving average
50-day moving average slope
```

Initial labels:

```text
BULL_TREND: close > 50DMA and 50DMA slope > 0
BEAR_TREND: close < 50DMA and 50DMA slope < 0
SIDEWAYS: otherwise
```

---

## 4. Volatility Regime

Inputs:

```text
VIX for index/ETF strategies where available
20-day realized volatility
52-week realized volatility percentile
```

Initial labels:

```text
LOW_VOL: realized vol percentile <= 30
NORMAL_VOL: realized vol percentile > 30 and < 70
HIGH_VOL: realized vol percentile >= 70
```

For SPY/QQQ/IWM, VIX or index volatility context may be added as a secondary field.

---

## 5. Intraday Structure Regime

Inputs:

```text
ADX or trend-strength proxy
VWAP relationship
opening range break/failure
range_pct
close_location_pct
```

Initial labels:

```text
TRENDING_INTRADAY
CHOPPY_INTRADAY
REVERSAL_INTRADAY
UNKNOWN
```

If required inputs are missing, use `UNKNOWN` rather than guessing.

---

## 6. Liquidity Regime

Inputs:

```text
option spread_pct
option volume
open interest
quote age
underlying dollar volume
```

Initial labels:

```text
LIQUID
NORMAL
THIN
UNUSABLE
```

---

## 7. Catalog Display Requirements

Catalog pages must show:

```text
Overall paper/backtest performance
Performance by trend_regime
Performance by volatility_regime
Performance by intraday_structure_regime when available
Sample size per regime
Insufficient-history labels where sample size is too small
```

Minimum sample rule:

```text
If regime sample size < 30 events, show INSUFFICIENT_HISTORY instead of strong conclusions.
```

---

## 8. Versioning

Any change to regime thresholds, formulas, or inputs must increment:

```text
regime_model_version
```

Strategy performance records must store the regime labels and model version used at evaluation time.

