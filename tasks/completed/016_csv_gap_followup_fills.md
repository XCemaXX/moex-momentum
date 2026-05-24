# Pre-2014 CSV gap follow-up — agent-driven fills

## Context

Task 012 (Phase 4) закрыл cascade pull через ISS → dohod → Yahoo → tbank. На входе: 1368/1611 (84.9%) cells покрыты, 243 cells residual. Cascade исчерпан — дальше требуется manual disclosure pull.

Полный per-cell дамп → `validate_with_raw/csv_gap_cells.json` (regen: `validate_with_raw/regen_csv_gap_report.py`).

## Scope confirmed during planning

- **Class A no-file (18 tickers / 122 cells)**: 8 USD-payers (quasi-Russian Cyprus/Jersey HQ) + 10 delisted RUB-payers — все need universe extension. 3 missing из tickers.json: QIWI, GLTR, OKEY → добавлены вручную с canonical/delisted_after.
- **Class B month-gap (37 tickers / 122 cells)**: MDMG (13), VTBR (9), NKHP (7) и хвост singletons.
- **USD-payer FX**: pipeline `corporate/apply.py` уже drops non-RUB, поэтому manual_disclosure RUB-записи будут use'аться, USD coexist. User decision: pull RUB equivalents через web sources.
- **Acceptance**: target 100% coverage (был ~93% potential; 100% реально через explicit acks for hard residuals).

## Phase 0 — Universe extension

- Added 3 missing tickers (QIWI/GLTR/OKEY) в tickers.json с canonical + delisted_after.
- Touched пустые JSONLs для всех 18 no-file tickers (apply_conflicts silently skip если файл не существует).

## Phase 1 — Wave dispatch (16 agents, 4 waves)

Распределение по тикерам с программно-сгенерированными per-cell таблицами (lesson learned, см. ниже).

| Wave | Agents | Coverage |
|---|---|---|
| 1 | POLY(21), QIWI(23), GLTR+RAGR+OKEY(42), ETLN+OBUV+GEMC+T(21), MDMG(13) | 98 augment / 22 ack |
| 2 v1 (corrupted brief) | DGBZP+KBTK+MSSB, RSTI+RSTIP, BEGY+MMBM+TAER+VSMZ+YKEN | discarded — re-dispatched |
| 2 v2 (corrected) | те же 3 батча | 40 augment / 0 ack |
| 2 | VTBR(9), NKHP(7) | 16 augment / 0 ack |
| 3 | URKA+DSKY, PRTK+VZRZ+ROSB, OGKB+GCHE+IRGZ+RTKMP, TATN+TATNP+MFGSP+RASP+TGKA, MSNG+POSI+PHOR+AQUA+MSRS+PLZL | 40 augment / 8 ack |
| 4 | NKNC+NKNCP+LNZL+TRMK+MRKV+UPRO+MRKY+PIKK+GTRK+RTKM | 9 augment / 1 ack |

**Итого agent-output:** 204 augments + 30 acknowledges (после фильтрации hallucinated-brief acks и user overrides).

## Phase 2 — Anomaly triage (10 categories)

Re-verified each anomaly против live repo state перед apply. User-driven decisions:

| Class | Count | Action |
|---|---|---|
| AGM-rejected phantom (board recommendations published as approved) | OGKB×2, PHOR×1 | acknowledge — no real payment |
| Year-typo в reference CSV | QIWI 2016-03→2017-03, POSI 2025-05→2024-05, GTRK 2016-06→2019-06 | augment real event + ack legacy ym |
| Net-vs-gross divergence (GLTR 41.78 vs 44.85) | 1 | augment gross (config.py tax_rate constant authoritative) |
| Source divergence (POLY 13.29 vs 16.75, 26%) | 1 | augment smart-lab gross |
| Multi-event aggregation в reference CSV | MDMG 28.27 = 18.50+9.80 | augment 2 records on separate registries |
| Pre-split nominal в reference CSV | PLZL 26.23 → 2.623 | augment post-split scaled |
| Approximate dates (agent gave AGM-cycle estimate) | KBTK×2, DGBZP×1, MRKY×1 | augment + ack month-shift |
| Already in pipeline | MSNG 2026-03 vs ISS 2025-07 | trust ISS, ack as duplicate |
| Redomicile predecessors (HEAD/X5/FIXR) | 11 cells | acknowledge — pipeline policy |
| FX-mismatch USD-payers not closeable | 0 (all replaced by manual_disclosure RUB) | — |

## Phase 3 — Apply + report tooling

- `data/dividends/_conflicts_resolved.json`: 128 → 332 entries (+204 augments).
- `validate_with_raw/legacy_gap_acknowledged.json` создан (gitignored — QA-only): 47 entries (per-cell ticker/ym/amount_legacy/reason/acknowledged_at).
- `apply_conflicts_to_universe()` applied: 204 changes across 48 tickers.
- `regen_csv_gap_report.py` updated:
  - `MATCH_WINDOW_MONTHS = 1` — soft-match для end-of-month vs early-next-month convention divergence
  - Loads `validate_with_raw/legacy_gap_acknowledged.json` и выводит acked-cells в отдельную секцию
  - Fixed bug: `currency=None` теперь treated as RUB (was excluding null-currency yahoo records от matching)

## Validation

- **Coverage: 1567/1611 (97.3%) matched + 44 acknowledged = 1611/1611 (100%).**
- No-file tickers: 0. Month-level gaps: 0.
- VSMO=4.6458% regression anchor intact.
- `pytest`: 267/267 pass.

## Key learnings

1. **Hand-typed cell data is unreliable** (the dispatcher's own self-error mode). Wave 2 v1 briefs hallucinated ym+amount values that no source matched — три агента wasted на impossible matching. Lesson: ALWAYS dump cell data programmatically from `csv_gap_cells.json`, even when the brief is short. Soft-affirmed: `feedback_agent_research_verify.md` applies to dispatcher's own input prep, не только agent outputs.
2. **Reference CSV не source-of-truth**, just gap flag. ALL 10 anomaly classes traced to reference CSV defects (typos, phantoms, aggregations, FX-mismatch, pre-split nominal). Real values from IR/smart-lab/dohod via verified fetches.
3. **USD-payer architecture already correct**: `corporate/apply.py` drops non-RUB, so manual_disclosure RUB augments coexist with USD ISS records cleanly. No FX-harmonization needed.
4. **Month-window tolerance >= ±1 month** essential для legacy-end-of-month vs real-early-next-month convention. Без него ~30 cells false-classified as gaps.

## Не входит (deferred)

- Systematic ISS AGM-rejection cross-check на ingestion (см. также task 013 same finding).
- FX-harmonization (USD-payer auto-convert) — out of scope per task spec.
- Tax-handling policy review (config.py tax_rate authority).

## Дополнительно

- Per `feedback_idempotent_no_rm.md`: операции идемпотентны через `apply_conflicts_to_universe` — repeat-run = 0 changes.
- Per user reminder: production `_conflicts_resolved.json` reasons не упоминают reference CSV / QA tooling — ссылаются только на web sources (smart-lab, dohod, IR, AGM minutes). Acknowledged-cells file держим в `validate_with_raw/` (QA-only, не нужен production scripts).
