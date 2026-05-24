# Q1–Q4 — pipeline vs author, as of 2026-03-31

Author's snapshot from `raw_sources/info.txt` header (published by t.me/kpd_investments) vs our `data/computed/curve_fit/holdings/2026-03.json`. **Discrepancies are expected — the author has a fixed universe (~170 tickers), while ours is survivorship-free and recomputed every month.** Matching the top of Q1/Q4 is the main signal that the momentum chain is correct.

## Summary

| Q | \|ours\| | \|author\| | overlap | union | **Jaccard** | threshold |
|---|---:|---:|---:|---:|---:|---:|
| Q1 | 33 | 34 | 25 | 42 | **0.595** | ≥ 0.5 |
| Q2 | 32 | 34 | 22 | 44 | **0.500** | ≥ 0.3 |
| Q3 | 32 | 34 | 23 | 43 | **0.535** | ≥ 0.3 |
| Q4 | 32 | 32 | 23 | 41 | **0.561** | ≥ 0.5 |

## Q1

**Common (25)**: AKRN, EUTR, GMKN, LENT, LSNGP, MDMG, MOEX, MRKC, MRKP, MRKU, MRKV, MRKZ, MSRS, MTSS, PHOR, PLZL, RTKMP, SBER, SBERP, T, TGKA, TRNFP, VKCO, VTBR, YDEX

**Only in ours (8)**: MGKL, NMTP, PMSB, PMSBP, RUAL, SELG, SVETP, UGLD

**Only in author (9)**: CNRU, JNOSP, LEAS, OGKB, OKEY, OZON, SFIN, TNSE, WTCM

## Q2

**Common (22)**: BELU, ELFV, ENPG, FEES, FESH, GEMC, HYDR, IRAO, MAGN, MBNK, MRKY, MSNG, NVTK, PIKK, POSI, PRMD, RTKM, SNGSP, SPBE, UPRO, VSMO, ZAYM

**Only in ours (10)**: CARM, ELMT, IVAT, LEAS, LSNG, MRKS, OGKB, OZPH, SVET, TGKN

**Only in author (12)**: BSPB, HEAD, HIMCP, MFGSP, MGNT, MRKK, NMTP, RAGR, RUAL, SELG, TGKB, UGLD

## Q3

**Common (23)**: AFKS, AFLT, CBOM, CHMF, FLOT, GAZP, GCHE, LSRG, NKHP, NLMK, RKKE, RNFT, ROSN, SGZH, SIBN, SNGS, SVAV, SVCB, TATN, TATNP, TRMK, VSEH, X5

**Only in ours (9)**: BSPB, BSPBP, DATA, GECO, HEAD, NKNCP, RAGR, ROLO, SFIN

**Only in author (11)**: BANEP, DVEC, KRKNP, MGTSP, MVID, RENI, ROST, TTLK, UNKL, UTAR, YKEN

## Q4

**Common (23)**: ABIO, ALRS, APTK, AQUA, ASTR, BLNG, DELI, DIAS, GTRK, HNFG, KMAZ, LKOH, LNZL, LNZLP, MSTT, MTLR, MTLRP, RBCM, SMLT, SOFL, UNAC, UWGN, WUSH

**Only in ours (9)**: ABRD, BANE, BANEP, IRKT, LIFE, MGNT, MVID, RASP, RENI

**Only in author (9)**: CHMK, CNTLP, ETLN, FIXR, GAZA, KAZT, KZOS, NKNC, NKNCP

