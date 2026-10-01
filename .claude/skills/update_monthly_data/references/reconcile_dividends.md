# Reference: dividend reconciliation

Runs for scope `dividends` and `all`. MOEX withdrew the ISS dividends endpoint in
2025-10 (`task 054`), so nothing arrives on its own: every payout is found via the
MOEX register export and closed from dohod / smart-lab / tbank / issuer filings.
This is the sharp-edged part of the update — go slow.

Assumes `data/tickers.json` is current. If running `dividends`-only and names may
have changed, run `momentum tickers refresh --force-refresh` first.

## Step 1 — ISS probe + curated fixes

```bash
momentum ingest dividends --force-refresh --months 3   # EXPECTED to exit 1 (task 054)
momentum corporate apply-conflicts                      # apply _conflicts_resolved.json
```

`ingest dividends` must print `ISS returned no dividends block for any of N tickers`
and exit 1. That is the designed loud failure, not a reason to stop the run — it is
kept only to notice if the endpoint ever comes back. If it suddenly fetches rows,
stop and tell the user.

`_gaps.json` is no longer a useful to-do list: with ISS gone it cannot tell a silent
source from a share that stopped paying.

## Step 1b — Which registers closed (MOEX export)

```bash
momentum corporate check-registers --since <first day of last month>
```

Lists register closings MOEX recorded that we have no payout for.

**Blind spot (`task 056`):** it keeps only `закрытие реестра` rows and drops
`закрытие реестра (рекомендуемая)` even after the date has passed. MOEX confirms
closings late — on 2026-10-01 all five September closings and LVHK 2026-06-15 were
still "рекомендуемая", and the report said `0 of 1048`. Until the task is fixed,
list the past-dated recommended rows by hand:

```bash
python -c "
import httpx,csv,io,datetime
t = httpx.get('https://web.moex.com/moex-web-icdb-api/api/v1/export/register-closing-dates/csv?language=1&separator=1', timeout=60).content.decode('cp1251')
today = datetime.date.today().isoformat()
for r in csv.DictReader(io.StringIO(t)):
    m,d,y = r['Дата события'][:10].split('/'); iso=f'{y}-{m}-{d}'
    if 'рекоменд' in r['Тип события'] and '2025-01-01' <= iso <= today: print(iso, r['Эмитент'][:90])" | sort
```

For each name, check its CSV: a row within a few days of the date means covered.

## Step 2 — Fill recent payouts (dohod + smart-lab, live)

1. Candidates = Step 1b output ∪ past-dated recommended rows ∪ the liquid universe
   (latest month of `data/momentum/curve_fit/scores.csv`, 100 names). The register
   export also misses whole payouts (`task 054` found 10), hence the universe sweep.
2. `momentum ingest fill-dividends -t A -t B ... --dry-run --force-refresh`.
   Default `--sources dohod,smartlab`. **`--force-refresh` is mandatory** — the
   cache has no TTL, so without it every payout declared since last month is
   invisible.
3. The CLI prints only counts, and most `new=` are old history (see the footgun
   below). To see the actual record dates, call the driver from the fresh cache:
   ```bash
   PYTHONPATH=src .venv/bin/python -c "
   import pathlib; import tickers as t
   from ingest.dividends.dohod import DohodFetcher
   from ingest.dividends.smartlab import SmartLabFetcher
   from ingest.dividends.fill import fill_dividends
   def nonet(u): raise RuntimeError(u)
   C = pathlib.Path('.fill_cache')
   fs = [DohodFetcher(nonet, cache_dir=C), SmartLabFetcher(nonet, cache_dir=C)]
   td = t.load(pathlib.Path('data/tickers.json')); tm = t.load_manual(pathlib.Path('data/tickers_manual.json'))
   for n in ['DIAS', 'HEAD']:
       r = fill_dividends(n, fetchers=fs, tickers_dict=td, tickers_manual=tm,
           prices_dir=pathlib.Path('data/prices_iss'), dividends_dir=pathlib.Path('data/dividends'),
           splits_dir=pathlib.Path('data/splits'))
       print(n, [(x['registry_close'], x['amount'], x['source']) for x in r.records if x['registry_close'] >= '2026-01-01'])"
   ```
   A `cache miss` for a ticker means that source 404'd for it (e.g. dohod has no
   YDEX page) — check that name by hand, it is not covered.
4. **Footgun — never bulk-apply dohod.** With no date scope it drags in dohod's
   *entire* history (dozens of records per name). Rows that restate stored payouts
   collapse and rows that disagree are reported as conflicts, but dohod restates
   some tickers to today's share count and not others, so on a split name every
   pre-split payout shows up as a conflict with a round ×10/×100 ratio. That ratio
   is the diagnosis, not a disagreement. For each candidate:
   - Keep only records dated in the current window (this year / last few months).
   - **Verify approval, not just the number.** Aggregators list the board
     *recommendation*; the AGM can cut it or fail to meet. LVHK 2026-06-15: dohod
     and smart-lab both said 0.1889, the issuer filing said 0.16. SVET/SVETP
     2026-06: smart-lab listed a dividend whose AGM never took place. When sources
     disagree, or only one carries it, read the issuer's «Начисленные доходы»
     filing (disclosure.1prime.ru / e-disclosure.ru). Pages that need JS or a login
     can't be read with curl — ask the user to open them and paste the text.
   - Check the ticker's CSV: if the payout is already there under another
     source/date, **skip it** (duplicate). A `yahoo_ex_div` row holds an
     **ex-dividend** date, a `tbank_reestr` row a **registry close** date — equal
     amounts 1–2 days apart are one payout (POSI 28.08 at 05-15 vs 05-17).
   - **Exclude future record dates** (> today): declared-but-unpaid dividends must
     not enter total-return until the date passes.
5. Names tbank serves arrive in Step 3 — don't `augment` them here or they
   duplicate. Record the rest in `data/dividends/_conflicts_resolved.json`, appended
   surgically to the tail:
   - Verified missing payout → `augment` (`source: manual_disclosure`; `reason`
     names the sources that agree). The 7-day / 1% near-dup guard prevents
     double-counting.
   - Phantom (stored or offered, never declared) → `drop` with
     `match: {amount, source}`. **Never `ignore` a phantom**: `ignore` only
     silences conflicts, and a row we don't store reaches fill as `new` and gets
     written (`task 057`). A `drop` is idempotent: `apply-conflicts` removes the row
     every time a fill run brings it back.
   - Source disagrees with a stored, verified row → `ignore` with
     `match: {source}` and `registry_close`, so it stops being reported.
6. `momentum corporate apply-conflicts`; confirm each change landed in its CSV.

⏸ **Checkpoint:** present verified adds, drops, skipped duplicates, and excluded
future-dated records; get the user's nod before the cascade.

## Step 3 — tbank fold-in (cascade)

`scripts/backfill/cascade_merge_dividends.py`. Cache-based, **stateless** (re-derives
the full cache-vs-CSV diff every run) and **source-order sensitive** — so it MUST be
windowed and future-guarded, or it re-opens settled history and books unpaid
dividends.

1. Refresh the tbank cache first (yahoo is a frozen snapshot — leave it):
   ```bash
   SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
     python scripts/backfill/fetch_tbank_dividends.py --refresh   # ~6 min, 2 req/s
   ```
   tbank.ru serves a certificate chained to the Минцифры `Russian Trusted Root CA`.
   It must be installed in the system store (`raw_sources/certs/`,
   `update-ca-certificates`), and `SSL_CERT_FILE` points httpx at that store —
   by default httpx trusts only `certifi`. Without it every request fails with
   `CERTIFICATE_VERIFY_FAILED` and shows as `net_err`.
   Run in the background and monitor. A snapshot is overwritten only on a successful
   fetch. Delisted names are skipped (`--full` overrides). A handful of 404s is
   normal. On mass `net_err`, read `.fill_cache/tbank/_failures.json` for the reason,
   then stop and escalate.
2. Windowed dry-run:
   ```bash
   python scripts/backfill/cascade_merge_dividends.py --sources tbank --months 6
   ```
   Read `validate_with_raw/reports/cascade_dryrun.md` and `cascade_conflicts.json`.
   The script already drops candidates with a **future** record date and, with
   `--months N`, records older than the window.
3. Interpret with suspicion — "clean_new" only means "no same-(year-month)
   collision"; it does **not** rule out a cross-month duplicate (same amount shifted
   a quarter). Eyeball each proposed record against its CSV neighbours.
4. `>1%` same-month conflicts are **not** auto-merged — they go to
   `cascade_conflicts.json` for manual resolution into `_conflicts_resolved.json`.
   Genuinely-clean past-dated records → re-run with `--apply`, then check the dates
   in `git diff data/dividends`. A no-op is a valid outcome.
5. **The cascade covers only names tbank serves** (liquid names; small caps 404).
   Whatever Step 2 found and tbank lacks needs its own `augment`, or it is silently
   dropped. Real runs: 2026-08 VTBR and NKHP fell through this gap; 2026-10 tbank
   carried YDEX/DIAS/HEAD/OZPH but not GEMA/LVHK.

⏸ **Checkpoint:** present the cascade findings and the apply decision before
recomputing.

## Why the ceremony (context that keeps you honest)

- The cascade has no memory of "already decided" beyond the ignore list in
  `_conflicts_resolved.json`, which was curated for the yahoo→tbank ordering.
  Changing `--sources` or dropping `--months` reshuffles the whole candidate graph
  and manufactures spurious "new" conflicts. Keep the window; use `tbank` for a
  monthly pull.
- Brokers and aggregators list future-declared and board-recommended dividends. A
  blind `--apply` or augment would book them as realized — the future-date guard
  and the approval check exist because real runs surfaced both.
