# Reference: dividend reconciliation

Runs for scope `dividends` and `all`. ISS lags real payouts by months, so each
cycle a few recent dividends are missing and must be closed from other sources.
This is the sharp-edged part of the update — go slow.

Assumes `data/tickers.json` is current. If running `dividends`-only and names may
have changed, run `momentum tickers refresh --force-refresh` first.

## Step 1 — ISS dividends + curated fixes

```bash
momentum ingest dividends --force-refresh --months 3   # trailing 3-month merge
                                                        # window; wider re-introduces
                                                        # ISS near-duplicates
momentum corporate apply-conflicts                      # apply _conflicts_resolved.json
```

`ingest dividends` regenerates `data/dividends/_gaps.json` (per-(ticker, year)).
"no_record_for_year" ≠ "ISS is late" — many names simply do not pay that year;
only dohod/disclosure tells you what is actually missing.

## Step 2 — Recent lagging payouts (dohod, live)

1. Cross the 2025–2026 gaps with the liquid universe (proxy: the latest month of
   `data/momentum/curve_fit/scores.csv`, 100 names) to get candidate tickers.
2. `momentum ingest fill-dividends -t A -t B ... --dry-run` on those names. Read the
   **actual record dates**, not the `new=` counts.
3. **Footgun — never bulk-apply dohod.** With no date scope it drags in dohod's
   *entire* history (dozens of records per name), and its cross-source dedup is
   leaky — it re-proposes a payout already stored from another source when the two
   differ only in trailing precision or by a day, so it *looks* new but is a
   duplicate. So for each candidate the dry-run surfaces:
   - Keep only records dated in the current window (this year / last few months).
   - **Verify online** — disclosure / smart-lab / dohod must agree on record date
     and amount.
   - Check the ticker's CSV: if the payout is already there under another
     source/date, **skip it** (duplicate).
   - **Exclude future record dates** (> today): declared-but-unpaid dividends must
     not enter total-return until the date passes.
4. Add each verified, past-dated, genuinely-missing payout as one `augment` to
   `data/dividends/_conflicts_resolved.json`:
   ```json
   {"ticker":"<TICKER>","registry_close":"<YYYY-MM-DD>","action":"augment",
    "add":{"amount":<amount>,"currency":"RUB","source":"skill_fill_disclosure"},
    "reason":"<what/when + which sources agree + why ISS lacks it>",
    "resolved_at":"<today>"}
   ```
   Append surgically (edit the file's tail); don't rewrite the whole array. `augment`
   has a 7-day / 1% near-dup guard, so it will not double-count.
5. `momentum corporate apply-conflicts`; confirm each new row landed in its CSV.

⏸ **Checkpoint:** present verified adds, skipped duplicates, and excluded
future-dated records; get the user's nod before the cascade.

## Step 3 — yahoo / tbank catalog fold-in (cascade)

`scripts/backfill/cascade_merge_dividends.py`. Cache-based, **stateless** (re-derives
the full cache-vs-CSV diff every run) and **source-order sensitive** — so it MUST be
windowed and future-guarded, or it re-opens settled history and books unpaid
dividends.

1. Refresh the tbank cache first (yahoo is a frozen snapshot — leave it):
   ```bash
   python scripts/backfill/fetch_tbank_dividends.py --refresh   # ~10 min, 2 req/s
   ```
   Run in the background and monitor. Overwrites a snapshot only on a successful
   fetch; a network miss or 404 keeps the old one. Many 404s are normal (tbank
   covers a subset of names). On mass `net_err`, stop and escalate.
2. Windowed dry-run:
   ```bash
   python scripts/backfill/cascade_merge_dividends.py --sources tbank --months 6
   ```
   Read `validate_with_raw/reports/cascade_dryrun.md` and `cascade_conflicts.json`.
   The script already drops candidates with a **future** record date and, with
   `--months N`, records older than the window.
3. Interpret with suspicion — "clean_new" only means "no same-(year-month)
   collision"; it does **not** rule out a cross-month duplicate (same amount shifted
   a quarter, e.g. an interim reprinted). Eyeball each proposed record against its
   CSV neighbours before trusting it.
4. `>1%` same-month conflicts are **not** auto-merged — they go to
   `cascade_conflicts.json` for manual resolution into `_conflicts_resolved.json`.
   Genuinely-clean past-dated records → re-run with `--apply`. If nothing survives
   scrutiny, apply nothing — a no-op is a valid, common outcome.

⏸ **Checkpoint:** present the cascade findings and the apply decision before
recomputing.

## Why the ceremony (context that keeps you honest)

- The cascade has no memory of "already decided" beyond the manual ignore list in
  `_conflicts_resolved.json`, which was curated for the yahoo→tbank ordering.
  Changing `--sources` or dropping `--months` reshuffles the whole candidate graph
  and manufactures spurious "new" conflicts. Keep the window; prefer `tbank` for a
  monthly pull.
- Brokers list future-declared dividends (record date next month). A blind
  `--apply` would inject them as realized — the future-date guard exists precisely
  because a real run surfaced dozens of such records for liquid names in a single
  month.
