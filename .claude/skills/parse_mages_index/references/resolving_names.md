# Resolving a new name

When `mages_to_json.py` aborts with `unresolved names [...]`, classify each name and
add it to the right table at the top of `scripts/mages_to_json.py`, then re-run.

## Step 1 — share or not?

- **bond** → `OTHER_KIND[name] = "bond"`. Tells: `ОФЗ <digits>`, or a corporate
  issue code — `БО-`, `ЗО-`, `КЗО`, `П<n>Б<n>`, `00<n>Р-<n>`, a `…Р<n>R` / `…P<n>R`
  suffix. Watch the trap: `Сегежа` alone is the **equity** SGZH; `Сегежа3Р7R` /
  `Сегежа 002Р-05R` are **bonds**.
- **fx** → `"fx"`: `USD`, `EUR`, `CNY`.
- **fund** → `"fund"`: `LQDT` (money-market ETF) and similar funds.
- otherwise **share** → `SHARE_TO_TICKER` / `EXTERNAL` (below).

## Step 2 — find the ticker (shares)

Try the dictionary first; it is the source of truth for the price universe.

```bash
PYTHONPATH=src .venv/bin/python -c "import tickers as T,pathlib; \
d=T.load(pathlib.Path('data/tickers.json')); print(T.resolve_alias(d,'Самолёт'))"
```

- Non-null → already resolvable; you usually do not even need a table entry, but
  adding it to `SHARE_TO_TICKER` is harmless and makes intent explicit.
- Null → search the dict by substring to find the SECID, then add
  `"<raw_name>": "<SECID>"` to `SHARE_TO_TICKER`. The script will auto-add the blog
  name as a dict alias on the next run.

```bash
PYTHONPATH=src .venv/bin/python -c "import tickers as T,pathlib; \
d=T.load(pathlib.Path('data/tickers.json')); \
print([(s,e['canonical']) for s,e in d.items() if 'самол' in (e['canonical']+' '+' '.join(e.get('aliases',[]))).casefold()])"
```

- If the company trades on MOEX but is **not** in the dict (OTC / illiquid, no price
  history — e.g. Новошип `NOMP`/`NOMPP`, ВМТП `VMTP`, БЭСК ап `BESKP`): put it in
  `EXTERNAL`. Because its `canonical` resolves to null (no price series), the script
  routes it into `other` with `type="otc"` (keeping the ticker), so it stays out of
  `shares` and the weights. Confirm the exact MOEX ticker by web search — do not guess.

## Watch-outs

- Same company, many blog spellings → same SECID: `Т-Технологии`/`ТКС`/`Т-Банк` → `T`,
  `НоваБев`/`Белуга` → `BELU`, `Норильский никель`/`ГМК НорНикель` → `GMKN`,
  `ЛУКойл`/`ЛУКОЙЛ` → `LKOH`. Add every spelling you meet.
- The dict can be wrong. A real example caught here: `Аренадата` was mis-aliased on
  `DIAS` (Диасофт) — it is `DATA`. If `resolve_alias` returns a surprising SECID,
  verify the company, fix the table, and fix the dict alias.
- `ао`/`ап` are ordinary/preferred share classes — distinct SECIDs (`SBER`/`SBERP`,
  `BANE`/`BANEP`). Keep them separate.
