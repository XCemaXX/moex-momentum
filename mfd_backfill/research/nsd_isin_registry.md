# NSD / ISIN registry — Russia

Note: WebFetch was denied in the research session — URLs were validated via WebSearch snippets only, not direct hits. Spot-check before relying.

## 1. Is NSD the Russian NNA? Yes.

NSD (НРД, MOEX Group) has been ANNA's member for Russia since 1999 and allocates ISIN/CFI/FISN to all Russian-issued securities.
Source: https://www.nsd.ru/en/services/depozitariy/prisvoenie-identifikatsionnykh-kodov/prisvoenie-identifikatsionnykh-kodov-cfi-isin-fisn/

## 2. Public lookup: isin.ru (operated by NSD)

Free web UI, no auth, covers RU instruments including delisted (ISINs are permanent — not purged after delisting).
- RU instruments: https://www.isin.ru/ru/ru_isin/db/  (en: /en/ru_isin/db/)
- Foreign instruments: https://www.isin.ru/ru/foreign_isin/db/
- Form accepts ISIN, name (RU), state-registration number, INN. Returns issuer name + CFI + reg-number. Does **NOT** return MOEX SECID.

Smoke-test (via search snippets):
- URKA = RU0007661302 (cbonds, banki.ru, nsddata references)
- SCON = RU000A0DM8R7 (delisted 2012-09-28, record still resolvable)
- MFON, OMSB — not confirmed via search; needs direct isin.ru query

## 3. Programmatic access — API NSD via nsddata.ru

- Endpoint shape: `https://nsddata.ru/api/get/<product>?apikey=<key>`, JSON in/out
- Demo key `"demo"` for evaluation; production requires signed agreement
- 2-week free trial, then paid. Reference-data product covers ISIN/CFI/FISN + issuer attributes; valuation products priced separately (corp eurobonds ~24k RUB/month)
- SDK: https://github.com/NSDDeveloper/nsddata_api
- Docs: https://www.nsd.ru/en/services/informatsionnye-servisy/api-nsd/ , https://nsddata.ru/en/products/2
- Rate limits not in snippets

## 4. ISIN → MOEX SECID

Neither NSD nor isin.ru exposes SECID — that's a MOEX-side ticker, outside ANNA scope. For delisted SECIDs the only authoritative source remains MOEX ISS history endpoints. Use isin.ru only for ISIN ↔ issuer-name resolution.

## 5. Alternatives

- OpenSanctions mirror of NSD ISIN allocations (bulk, free, CC-BY): https://www.opensanctions.org/datasets/ru_nsd_isin/
- cbonds.ru ISIN pages (free header read): https://cbonds.ru/stocks/RU0007661302/
- CBR — no public ISIN registry. Out.

## Recommendation

Pull the OpenSanctions `ru_nsd_isin` dump (free, complete) for the ISIN → issuer-name layer; cross-validate the 1900 mfd.ru ISINs against it offline. Hit isin.ru web form manually only for residuals. Skip paid API NSD unless streaming corporate actions are needed.
