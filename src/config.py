"""Single source of truth for constants.

Any number in this module is a tunable parameter; copies in other modules
are forbidden (see CLAUDE.md and SPEC §2.3).
"""

from __future__ import annotations

# Dividend tax for RF-resident individuals.
DIVIDEND_TAX: float = 0.13

# Broker commission per trade side.
COMMISSION_PER_SIDE: float = 0.0005

# Curve-fit formula: (a·r(12-1) + b·r(6-1)) / σ(12).
CURVE_FIT_A: float = 0.9
CURVE_FIT_B: float = 0.1

# Split detector threshold (|daily return|).
SUSPICIOUS_RETURN_THRESHOLD: float = 0.30

# Skip days with microscopic turnover — a single trade at an absurd price
# can manufacture a "return" out of nothing.
MIN_DAILY_VALUE_FOR_DETECT: float = 100_000.0

# Sample stdev (n-1 denominator) for σ(12) — matches the author's methodology.
STDEV_DDOF: int = 1

# Number of consecutive monthly closes a ticker must have, ending at month t,
# to enter the universe of month t.
# 13 closes → 12 returns: 11 for r(12-1) skip-month + 1 current for σ(12).
UNIVERSE_MIN_MONTHLY_CLOSES: int = 13

# Universe liquidity selection: keep the N most liquid names by median monthly
# trading value over the 12-month window. A *relative* cut — stable name count
# across years, immune to ruble/market-scale drift (the implied ₽ threshold of
# the Nth name moves ~140× over 2013-2026).
UNIVERSE_TOP_N_LIQUID: int = 100

# Pending-inclusion block (display-only): a young liquid ticker (<13 closes, no
# q yet) gets a would-be-quartile estimate only once it has at least this many
# months since listing. Below it, too few points for a meaningful score.
PENDING_MIN_AGE_FOR_ESTIMATE: int = 6

# Default MOEX board for shares.
DEFAULT_BOARD: str = "TQBR"

# Lower bound of analysis window. Ingest is survivorship-free down to the
# ticker's listing date, but visualization and backtest start here.
# Changing this = recompute without re-ingest.
ANALYSIS_START_DATE: str = "2013-01-01"

# ISS client HTTP settings.
ISS_BASE_URL: str = "https://iss.moex.com/iss"
ISS_HTTP_TIMEOUT_SECONDS: float = 30.0
ISS_MAX_CONCURRENCY: int = 10

# Monthly dividend refresh merges only ISS rows whose registry_close lands in
# this trailing window. The ISS endpoint returns full history with near-dup rows
# (same payout, adjacent dates) that curation drops; a wider window keeps
# re-introducing them on every re-run. 0 = full history.
ISS_DIVIDEND_REFRESH_MONTHS: int = 3

# Incremental monthly recompute window: only this many trailing months are
# recomputed by default; older rows are copied as-is and protected by a
# baseline-hash gate. `momentum compute monthly --from-scratch` overrides.
INCREMENTAL_RECOMPUTE_MONTHS: int = 12

# When this many tickers drift in a single compute_monthly run, the gate
# treats the run as a mass-rebuild (e.g. post-ingest backfill) and the error
# message switches to a softer "rerun with --from-scratch" wording. Below
# the threshold, drift is treated as suspicious — likely a single missed
# split or dividend backfill — and worth manual inspection.
MASS_DRIFT_THRESHOLD: int = 10

# External dividend fill HTTP settings.
FILL_HTTP_TIMEOUT_SECONDS: float = 20.0
FILL_USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
