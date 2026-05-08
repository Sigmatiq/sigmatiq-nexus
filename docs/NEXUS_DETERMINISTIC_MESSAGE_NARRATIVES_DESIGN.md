# Nexus Deterministic Message Narratives Design

## Purpose

Add short trader-readable summaries and explanations to existing Nexus messages while keeping Nexus deterministic, fast, testable, and non-LLM-driven.

Nexus should publish facts first. Narratives should explain those facts using templates, reason codes, and data-quality flags. Rich natural-language expansion can happen later in the chat/API layer.

## Design Decision

Do not create a new message type for per-message summaries.

Add narrative fields inside existing Nexus messages:

- `OPTION_MARKET_CONTEXT`
- `PARTICIPANT_FLOW_CONTEXT`
- `WINDOW_VIEW`
- `INTERMEDIATE`
- `BET`
- `BLOCKED`
- `LIQUIDATE`

Reason:

- the explanation stays attached to the exact facts that generated it
- subscribers do not need a second stream to reconstruct context
- persistence remains simpler
- no race between raw data and explanation messages
- tests can assert deterministic output from fixed inputs

A separate message type is only appropriate later for cross-window or cross-symbol narratives, such as `MORNING_STORY_SO_FAR`.

## Non-Goals

Nexus v1 narrative generation must not:

- call an LLM
- choose strikes, entries, exits, or position size
- use persuasive execution language
- claim true retail/institution/dealer intent beyond the available data
- override data-quality or freshness warnings
- hide raw fields behind prose

## Standard Field Contract

All narrative-bearing messages must include:

```json
{
  "narrative_version": "1.0"
}
```

Context messages must include `summary` and `narrative`:

```json
{
  "narrative_version": "1.0",
  "summary": "Call premium dominated, but bid-side ambiguity lowers confidence.",
  "narrative": {
    "headline": "Bullish-looking flow, low confidence",
    "what_happened": [
      "Call premium was 2.1x put premium.",
      "Top contract was SPY 2026-05-08 560C.",
      "Aggressor coverage was weak."
    ],
    "what_it_means": [
      "The completed window leans bullish on premium, but execution-side ambiguity makes the read fragile."
    ],
    "caveats": [
      "Opening/closing status is unavailable.",
      "This is not a trade recommendation."
    ],
    "reason_codes": [
      "CALL_PREMIUM_DOMINANCE",
      "BID_SIDE_AMBIGUOUS"
    ]
  }
}
```

Lifecycle messages must include `reason_summary`:

```json
{
  "narrative_version": "1.0",
  "reason_summary": "Blocked because required option quote data was stale."
}
```

Do not add additional prose field names in v1. Avoid `explanation`, `blocked_reason_text`, or other aliases unless a later API version explicitly introduces them.

## Required Fields By Message Type

| Message | Required narrative fields |
| --- | --- |
| `OPTION_MARKET_CONTEXT` | `narrative_version`, `summary`, `narrative` |
| `PARTICIPANT_FLOW_CONTEXT` | `narrative_version`, `summary`, `narrative` |
| `WINDOW_VIEW` | `narrative_version`, `summary`, `reason_summary` |
| `INTERMEDIATE` | `narrative_version`, `reason_summary` |
| `BET` | `narrative_version`, `reason_summary` |
| `BLOCKED` | `narrative_version`, `reason_summary` |
| `LIQUIDATE` | `narrative_version`, `reason_summary` |

If a source field is missing or degraded, still emit the narrative fields. The text should say the read is unavailable, degraded, thin, stale, or unknown.

## Message-Specific Guidance

### OPTION_MARKET_CONTEXT

Use for pricing and contract activity explanation.

Example topics:

- cheap side vs costly side
- most traded contract
- spread quality
- quote freshness
- pricing lag
- whether the window is usable or noisy

### PARTICIPANT_FLOW_CONTEXT

Use for participant-like and strategy-shape explanation.

Example topics:

- premium bias
- aggressor bias
- directional read
- small-lot-like flow
- block-like or sweep-like activity
- dominant strategy shape
- dealer-inferred pressure, if available
- data-quality caveats

Required caveats when applicable:

- `Opening/closing status is unavailable.`
- `Participant labels are inferred from trade shape, not true account identity.`
- `Dealer pressure is unknown because dealer context is unavailable.`

### WINDOW_VIEW

Use `summary` plus `reason_summary`.

Example:

```json
{
  "narrative_version": "1.0",
  "summary": "Window classified as CHOP.",
  "reason_summary": "This strategy reads the completed window as CHOP because call and put premium were balanced and no aggressive side dominated."
}
```

### INTERMEDIATE

Use `reason_summary` to explain why a candidate was promoted to intermediate state.

Example:

```json
{
  "narrative_version": "1.0",
  "reason_summary": "Candidate identified from ask-side put flow in the completed 10:00-10:30 window."
}
```

### BET

Use `reason_summary` only. Avoid persuasive trade language.

Example:

```json
{
  "narrative_version": "1.0",
  "reason_summary": "Final paper signal emitted because the strategy rule passed and required quote checks were fresh."
}
```

### BLOCKED

Use `reason_summary` only.

Example:

```json
{
  "narrative_version": "1.0",
  "reason_summary": "Blocked because option quote data was stale and the lead contract could not be priced safely."
}
```

### LIQUIDATE

Use `reason_summary` tied to the liquidation trigger.

Example:

```json
{
  "narrative_version": "1.0",
  "reason_summary": "Liquidation context emitted because the tracked contract crossed the configured loss threshold."
}
```

## Template Rules

Narratives must be produced from stable reason codes and known fields.

Recommended implementation:

```text
raw facts + reason codes + quality flags
  -> narrative builder
  -> deterministic summary/narrative fields
```

Create one pure module:

```text
src/sigmatiq_nexus/narratives.py
```

Suggested functions:

- `build_option_market_context_narrative(payload) -> dict`
- `build_participant_flow_context_narrative(payload) -> dict`
- `build_window_view_narrative(payload) -> dict`
- `build_lifecycle_reason_summary(payload) -> dict`

The builder should never mutate the input payload in place unless explicitly documented.

## Deterministic Formatting Rules

To keep tests and audits stable:

- `narrative_version` starts at `1.0`.
- Percentages use one decimal place.
- Ratios use one decimal place.
- Dollar amounts use compact whole-dollar formatting unless cents are material.
- Contract lists are sorted by premium descending, then trade count descending, then raw symbol ascending.
- Reason codes are emitted in stable priority order, not discovery order.
- Missing numeric fields render as `unknown` in prose when material to the sentence.
- Empty arrays are allowed for `what_happened`, `what_it_means`, and `caveats` only when the message itself is unavailable or malformed.
- Fixed payload input must produce byte-equivalent narrative output, excluding enclosing payload timestamp fields.

## Language Guardrails

Use cautious language:

- `suggests`
- `leans`
- `appears`
- `in this completed window`
- `low confidence`
- `data is degraded`
- `not a trade recommendation`

Prefer participant-shape wording in prose:

- `small-lot-like flow`
- `block-like activity`
- `sweep-like activity`
- `clustered activity`
- `participant-like read`

Avoid identity claims in prose:

- `retail is buying`
- `institutions are selling`
- `dealers are betting`

Avoid persuasive or predictive phrases:

- `buy this`
- `sell this`
- `enter now`
- `take this trade`
- `short this`
- `guaranteed`
- `will move`

Banned-phrase tests should validate generated template output, not arbitrary raw payload strings. Use phrase-level checks rather than raw substring bans so valid text such as `short-dated options`, `sell-side quote`, or `buy/sell spread` does not fail incorrectly.

## Data-Quality Behavior

Narratives must reflect data quality mechanically.

If data quality is `thin`:

- summary starts with `Thin window:`
- `what_it_means` must avoid directional conviction
- caveats include insufficient sample size

If data quality is `degraded`:

- summary starts with `Degraded read:`
- caveats include the degraded source
- directional words like `bullish` or `bearish` may only appear with `appears`, `leans`, or `suggests`

If data quality is `stale`:

- summary starts with `Stale read:`
- caveats include stale-source details
- `what_it_means` must say this should not be treated as current state

If data quality is `unknown`:

- summary starts with `Unknown read:`
- narrative should explain which required fields were unavailable

Examples:

- `Thin window: not enough trades for a strong read.`
- `Degraded read: aggressor side was missing for most prints.`
- `Stale read: this should not be treated as current market state.`
- `Unknown read: required option-flow fields were unavailable.`

## Persistence And API Impact

Because narratives are embedded in existing messages:

- Redis keys do not change
- Pub/Sub channels do not change
- persistence worker should store the fields as part of existing payload JSON
- typed persistence columns are not required for v1
- future APIs can expose summaries without joining another stream

If typed audit/search over narratives becomes important later, add derived columns separately.

## Testing Requirements

Unit tests should cover:

- call-heavy participant flow produces cautious summary
- bid-side ambiguity lowers confidence and appears in caveats
- missing dealer context adds dealer caveat
- degraded quality changes summary wording mechanically
- stale quality changes summary wording mechanically
- blocked message produces clear reason summary
- no generated template includes banned persuasive phrases
- phrase-level banned checks do not reject valid phrases such as `short-dated options`
- fixed payload produces deterministic output
- required narrative fields are present for each message type

Integration tests should cover:

- `OPTION_MARKET_CONTEXT` includes `narrative_version`, `summary`, and `narrative` after publishing
- `PARTICIPANT_FLOW_CONTEXT` includes `narrative_version`, `summary`, and `narrative` after publishing
- lifecycle messages include `narrative_version` and `reason_summary`
- persistence event payload contains the same narrative fields

## Recommended Implementation Order

1. Add pure `narratives.py` with deterministic formatting and banned-phrase tests.
2. Add narratives to `PARTICIPANT_FLOW_CONTEXT` first.
3. Add narratives to `OPTION_MARKET_CONTEXT` second.
4. Add compact summaries to `BLOCKED`, `BET`, `INTERMEDIATE`, and `LIQUIDATE`.
5. Add `WINDOW_VIEW` `summary` and `reason_summary`.
6. Expose narrative fields through `sigmatiq-api` endpoints without recomputation.
7. Let the chat/MCP layer use these deterministic fields as grounding for richer answers.

## Open Questions

- Should the API expose a `narrative_level=none|summary|full` query option?
- Should banned phrase validation run in CI for all generated templates?
- Should future typed persistence include `summary` for search and audit dashboards?
