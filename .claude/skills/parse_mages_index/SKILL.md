---
name: parse_mages_index
description: >-
  Use to ingest or update an "Индекс Магов" (Index of Mages) portfolio record.
  Trigger on any request to: add/parse/ingest a new mages-index entry; recognize
  ("распознай") a mages доля%/акция shares table and compute shares-only percentages;
  regenerate or write `data/mages/*.json`; extend the mages ticker dictionary
  ("словарь"); or refresh the mages `matching_report`. Also trigger when the user
  just drops a mages-index screenshot or new txt plus a period (month/year or
  YYYY-MM) and a source link (smart-lab / VK / teletype) and asks to "make json" or
  "оформи как обычно" — even without naming the skill. Do NOT trigger for unrelated
  mages work: building HTML/GitHub-Pages pages, equity curves or charts, renaming
  raw_sources files, running tests, generic broker-PDF OCR, or authoring a new skill.
---

# parse_mages_index

Ingest one Индекс Магов table image → `data/mages/<YYYY-Qn>.json`.

The model (you) does the OCR — vision is not scriptable. A bundled Python script
does the deterministic rest: classify, ticker-match, re-normalize, write JSON,
extend the dictionary, rebuild the report. Keep that split: transcribe faithfully,
let the script compute.

## Inputs

- **image path** — the screenshot of the composition table.
- **period** — `YYYY-MM`, the quarter start the snapshot is *for*. The series is
  quarterly; months are always `01/04/07/10` (Jan→Q1, Apr→Q2, Jul→Q3, Oct→Q4).
- **source URL** — smart-lab post, VK article, or teletype page. If the user only
  says "ВК" with no link, ask for the exact URL — never invent a slug.

## Layout (paths relative to repo root)

- `raw_sources/mages_index/` — inputs: `mages_index_<YYYY-MM>[_recNN].{png,jpg}` +
  matching `.txt` (your OCR) + `sources.json` (period → URL).
- `data/mages/` — outputs: `<YYYY-Qn>.json` + `matching_report.md`.
- script: `scripts/mages_to_json.py` (inside this skill).

## Workflow

### 1. OCR the image into a txt

Read the image. Find **the** composition table — a tall, narrow two-column block:
header `доля, %` and `акция`, rows like `16,53%  Сбербанк ао`, often ending with
`100,0%  Итого Индекс Магов`. Ignore everything else in the post (pie charts,
per-manager matrices, photos, the "на 5 лет" comparison panel).

Write it to `raw_sources/mages_index/mages_index_<YYYY-MM>[_recNN].txt`, exactly:

```
доля, %	акция
16,53%	Сбербанк ао
7,64%	ВТБ
...
100,0%	Итого Индекс Магов
```

Rules that matter:
- Tab-separated. Transcribe **every** row, in image order. Do not reorder or round.
- Keep names exactly as shown (Russian, `OZON`/`CNY` Latin as printed), keep the
  comma decimal (`4,79%`) and the `%`.
- Keep the `Итого` row if present (the script ignores it; it is audit). If the
  image has no total row, just end on the last stock — do not fabricate one.
- Flag uncertain cells to the user: bond codes (`Сегежа3Р7R`, `Айдеко БО-01`),
  `Р`(Cyrillic) vs `P`(Latin), `ё` vs `е`. Accuracy here is the whole game — a
  wrong digit silently corrupts the weights.

Also copy the image itself into `raw_sources/mages_index/` under the same stem, so
the source picture lives next to its transcription.

### 2. Register the source

Add `"<YYYY-MM>": "<URL>"` to `raw_sources/mages_index/sources.json`. Merge — do
not drop existing entries.

### 3. Run the script

```
python .claude/skills/parse_mages_index/scripts/mages_to_json.py
```

It is batch + idempotent: rebuilds all quarters, the report, and dictionary
aliases. It prints per-quarter share/other counts and Σpct; sanity-check that
shares + other ≈ 100% for the new quarter.

### 4. Resolve any unmapped names

If the script aborts with `unresolved names [...]`, each new name needs a home.
Decide share vs non-share, then add it to the right table in `scripts/mages_to_json.py`
and re-run. See `references/resolving_names.md` for how to classify and find a ticker.

The script already reuses names resolved in earlier `data/mages/*.json`, so a name
seen before never re-prompts.

### 5. Review before declaring done

Show the user the new `data/mages/<YYYY-Qn>.json` and the rows for the new names in
`data/mages/matching_report.md`. Call out any matches you were unsure of and any
cell you flagged in step 1 — the OCR is the only un-checkable link in the chain, so
it gets an explicit human look.

## Output shape

```json
{
  "quarter": "2024-Q3",
  "period": "2024-07",
  "source": "https://...",
  "shares": [
    {"ticker": "SNGS", "canonical": "Сургнфгз", "raw_name": "Сургутнефтегаз ао",
     "pct": 9.68, "pct_shares_only": 10.54}
  ],
  "other": [
    {"raw_name": "ОФЗ 26238", "pct": 5.71, "type": "bond"},
    {"ticker": "NOMPP", "raw_name": "Новошип ап", "pct": 2.1, "type": "otc"}
  ]
}
```

- `shares` — investable equities only. `pct` is the raw weight from the image;
  `pct_shares_only` is re-normalized so shares alone sum to 100% (everything in
  `other` removed from the base). Every share here has a non-null `canonical`.
- `other` — non-investable instruments, kept as-is, never re-normalized: `raw_name`,
  `pct`, `type`. `bond`/`fx`/`fund` have no ticker; `otc` is a real share with no
  price series (`canonical` would be null) — it keeps its `ticker` for audit but is
  excluded from the weights, since we cannot build a curve for it.
