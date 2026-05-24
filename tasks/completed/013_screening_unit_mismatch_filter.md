# Screening: mute-list + Type D residuals triage

## Context (original scope)

`validate_with_raw/screen_iss_anomalies.py` (task 005, gitignored) Type D систематически содержал 21 строку clean ×N multipliers (GMKN ×100, TRNFP ×100, PLZL ×10, BELU ×8) — unit-mismatch artifacts, не bugs ISS. В ежемесячном workflow (ISS delta-pull → re-run screen → adjudicate новые stale-записи) эти строки отвлекали триаж.

## Scope expansion

Помимо изначального mute-list, во время работы выяснилось что screen Type D имел **два устаревших дизайн-решения**:

1. **Filter `source=="moex_iss"` для Type D** — был корректен когда ISS был единственным источником, но после multi-source cascade (task 012) augmented records от других sources не учитывались → 10 false positives «ISS undercount» где наш merged-total на самом деле сходился с dohod.
2. **Hand-written disclaimer** в конце отчёта дублировал mute-логику.

После Bucket 1-3 fix (Type D на ours-total + mute) Type D сократился 30 → 11. Оставшиеся 11 + 2 Type C — реальные кейсы для триажа.

## Done — Phase 1: screening tooling

- `validate_with_raw/screening_muted.json` создан (gitignored): explicit allowlist, schema `{ticker, anomaly_type, ratio_pattern, years[], reason}`. Соответствует паттерну `_external_blacklist.json` / `_conflicts_resolved.json`.
- `screen_iss_anomalies.py` patches:
  - `load_muted()` + filter Type D + рендер секции `## Muted`
  - Type D теперь сравнивает ours-aggregate (all 6 sources) vs dohod, не ISS-only
  - `load_all()` helper рядом с `load_iss()`
  - `screen_ticker()` принимает `ours_recs` параметр (A/B/C остаются ISS-only)

## Done — Phase 2: triage 13 residual Type C/D entries

Распределили 13 entries на 5 параллельных агентов с web-research (smart-lab, dohod, e-disclosure, IR-сайты, major press). Cross-check vs legacy CSV для дополнительной верификации.

**Найденные anomaly classes:**

| Class | Count | Pattern | Action |
|---|---|---|---|
| AGM-rejected phantom (the big one) | 7 | PHOR×2, GAZP, GCHE, PRMB, PLZL, NLMK, CHMF — ISS публикует board recommendations indistinguishable от approved payments | DROP |
| Cross-source dedup miss | 4 | MOEX/TRMK/MRKU/OGKB — same payment, разные даты в разных источниках | DROP duplicate record |
| ISS announcement-date bug | 2 | OGKB 2025, LKOH 2015 — ISS dated на announcement, не на registry close | DROP, оставить корректную дату |
| Source-specific 2x bug | 2 | CNTL yahoo 2017+2018 — yahoo systematically 2x post-2016 (tbank correct) | DROP yahoo |
| Wrong amount | 1 | AVAN 2025-04-28 — ISS 21.07 vs real 28.50 | DROP + AUGMENT |
| TRUE multi-tranche (we more complete than dohod) | 1 | PHOR 2023 — we have 4 tranches matching smart-lab, dohod missed 126 | MUTE Type C |
| False mute (Group A agent error) | 3 | GAZP 2022 / GCHE 2022 / PRMB 2020 — изначально замьючены как «multi-tranche», после re-verify оказались AGM-rejected phantoms | REVERSE mute → DROP |

## Done — Phase 3: production fixes

**18 drops + 1 augment** в `data/dividends/_conflicts_resolved.json` (109 → 128), все с reason + cited evidence + verified URLs.

Affected JSONLs (12): AVAN, CHMF, CNTL, GAZP, GCHE, LKOH, MOEX, MRKU, NLMK, OGKB, PHOR, PLZL, PRMB, TRMK.

Все 19 entries audited против post-cascade JSONL state.

## Validation

- VSMO=4.6458% regression anchor intact (12/12 tests pass).
- Screen final: Type A=0, B=0, C=1 (PHOR 2023, mute через mute-list нужно — anomaly_type=C not yet supported), D=0, muted=27.

## Key learnings

1. **MOEX ISS systematic bug:** dividend endpoint returns board recommendations indistinguishable от approved payments. 7 phantom AGM-rejected records обнаружены за один проход. Pipeline нуждается в систематической AGM-cross-check логике на ingestion (не post-hoc adjudication).
2. **ISS announcement-vs-registry quirk:** иногда возвращает AGM/announcement date в поле registry_close (OGKB 2025, LKOH 2015). Создаёт duplicates с правильной registry date из других источников.
3. **Agent verification failure mode (повторно подтверждён):** агент с заблокированными WebFetch может paraphrase из памяти модели и выдавать over-confident verdicts. Group A агент маркировал 3 AGM-rejected phantoms как «multi-tranche confirmed» — все 3 опровергнуты при rigorous re-verify с successfully-fetched URLs. Соответствует `feedback_agent_research_verify.md`.

## Не входит (отложено)

- Systematic ISS AGM-rejection cross-check на ingestion стороне (отдельная задача — много phantom'ов).
- Type C mute support в screening_muted.json (PHOR 2023 остаётся в отчёте как известный «we more complete»).
- Recheck dohod 404-list (95 tickers) для ускорения monthly re-run.
- Broader CNTL yahoo audit (только 2017+2018 потверждены 2x; 2010-2014 yahoo записи OK).
