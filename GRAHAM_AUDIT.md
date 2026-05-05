# GRAHAM Phase 1 Audit

Audit date: 2026-05-05  
Repo audited: `/Users/chrisworsey/Desktop/atlas`  
Branch: `graham/v1`

## Executive Summary

No GRAHAM implementation exists yet. The repo has reusable EDGAR primitives in `data/edgar_client.py` and `data/edgar_realtime_client.py`, plus BDC-specific filing download/parsing scripts under `scripts/`. There is no existing OTC/pink sheet NCAV screener.

SEC EDGAR is feasible as the primary source. The official SEC ticker/exchange file currently contains 2,550 OTC ticker rows and 2,027 unique OTC CIKs. EDGAR full-text search over recent 10-K/10-Q filings confirms thousands of OTC/Pink-related filing hits in the last 18 months. A weekly run is feasible under the SEC 10 requests/second limit if GRAHAM uses the SEC bulk/nightly JSON files and local caching instead of fetching every CIK every week from scratch.

FMP is present in the repo and the provided key is configured, but live endpoint checks returned `Limit Reach` for all tested FMP endpoints. GRAHAM should treat FMP as optional/supplementary and cache aggressively, or use a fresh/higher-limit key before production.

## 1. Existing OTC/Pink Screener

Checked paths/patterns:

- `graham/`: not present.
- `valis/`, `par/`, `par.credit/` inside the atlas repo: not present.
- Existing screener references across `agents/`, `scripts/`, `api/`, `terminal/`, `data/`, `research/`.

Findings:

- No OTC/pink sheet NCAV screener exists.
- No existing `graham/` directory exists.
- Existing screeners are unrelated:
  - `agents/fundamental_batch.py`: broad fundamental valuation screen.
  - `agents/fundamental_agent.py`: ticker-level valuation and Graham-style prompt language, but not an OTC net-net engine.
  - `scripts/bdc_put_screener.py`: BDC put-option screener.
  - `scripts/build_universe.py` and `scripts/build_universe_v2.py`: listed-equity universe builders, not OTC NCAV.

Conclusion: Phase 3 should create a new `graham/` package rather than extending an existing OTC screener.

## 2. VALIS EDGAR Ingestion

Atlas repo:

- No `valis/` directory exists under `/Users/chrisworsey/Desktop/atlas`.

Nearby local VALIS project checked:

- `/Users/chrisworsey/valis/valis-autonomous`

Findings:

- VALIS has references to "SEC EDGAR check" in `chat_ai.py`, but no reusable EDGAR ingestion module was found.
- VALIS financial enrichment uses:
  - `financialdatasets.ai` for statements.
  - Alpha Vantage overview.
  - FMP `key-metrics`.
- No reusable 10-K/10-Q XBRL balance sheet extraction code was found in VALIS.

Conclusion: VALIS should not be the source for GRAHAM's EDGAR extraction. Reuse ATLAS `data/edgar_client.py` instead.

## 3. PAR / par.credit EDGAR Parsing

Atlas repo:

- No top-level `par/` or `par.credit/` directory exists.
- PAR-related scripts are present:
  - `scripts/expand_par_database.py`
  - `scripts/expand_par_v2.py`
  - `scripts/expand_par_v3.py`
  - `scripts/download_bdc_filings.py`
  - `scripts/extract_bdc_portfolios.py`

Nearby local PAR demo checked:

- `/Users/chrisworsey/park-lane-demo/par`

Findings:

- PAR code is BDC-specific and oriented around schedule-of-investments extraction from 10-K/10-Q HTML.
- `scripts/expand_par_database.py` includes useful filing-document discovery logic:
  - SEC browse-edgar Atom filing list.
  - Archive URL construction.
  - iXBRL viewer URL unwrapping.
  - BeautifulSoup HTML table parsing.
- `scripts/extract_bdc_portfolios.py` uses `edgartools` and XBRL for BDC portfolio investments.
- No generic XBRL balance sheet parser for NCAV was found in PAR.

Conclusion: PAR parsing code is useful as a fallback pattern for HTML filing download and table discovery, but not as the primary NCAV engine.

## 4. Existing FMP Usage and Key Check

Configured key:

- `.env`: `FMP_API_KEY=ZTvemA5AKSI3e7DnITVXs3RyLY46G2Wx`
- `config/settings.py`: loads `FMP_API_KEY` from environment.

Current repo FMP clients/endpoints:

- `agents/market_data.py`
  - Base: `https://financialmodelingprep.com/stable`
  - Endpoint: `/quote?symbol={symbol}&apikey=...`
- `agents/backtest_loop.py`
  - Base: `https://financialmodelingprep.com/stable`
  - Fallback base: `https://financialmodelingprep.com/api/v3`
  - Endpoint observed: `/api/v3/profile/{ticker}`
  - Internal limit comment: 250/day.
- `scripts/bdc_put_screener.py`
  - `/stable/quote?symbol={ticker}`
  - `/api/v3/stock_option_chain/{ticker}`
- `data/transcript_client.py`
  - `/api/v3/earning_call_transcript/{ticker}` style transcript access.
- `data/consensus_client.py`
  - FMP API v3 for analyst/consensus fallbacks.
- `data/earnings_client.py`
  - FMP API v3 for earnings/estimate fallbacks.
- Nearby VALIS:
  - `/api/v3/key-metrics/{ticker}`

Live checks performed:

- `https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey=...`
- `https://financialmodelingprep.com/api/v3/profile/AAPL?apikey=...`
- `https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=...`
- `https://financialmodelingprep.com/api/v3/historical-price-full/AAPL?serietype=line&apikey=...`
- `https://financialmodelingprep.com/api/v3/financial-statement-symbol-lists?apikey=...`

Result for all tested FMP endpoints:

```json
{
  "Error Message": "Limit Reach . Please upgrade your plan or visit our documentation for more details at https://site.financialmodelingprep.com/"
}
```

Conclusion: The key is recognized by FMP but is currently over its limit or below the required plan for these calls. It does not currently return usable price/profile/historical data for GRAHAM.

## 5. SEC EDGAR Bulk/API Availability and Rate Limit

Confirmed SEC endpoints:

- `https://efts.sec.gov/LATEST/search-index`
  - Live check returned recent 10-K/10-Q search results and aggregations.
- `https://data.sec.gov/submissions/CIK0000320193.json`
  - Live check returned Apple submissions metadata, tickers, exchanges, SIC, and recent filings.
- `https://www.sec.gov/files/company_tickers_exchange.json`
  - Live check returned SEC ticker, CIK, name, and exchange associations.

Official SEC API facts:

- SEC says `data.sec.gov` hosts RESTful JSON APIs and requires no authentication/API key.
- SEC submissions endpoint format: `https://data.sec.gov/submissions/CIK##########.json`.
- SEC company facts endpoint format: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`.
- SEC says a bulk ZIP is available for all JSON structures and is republished nightly at about 3:00 a.m. ET.
- SEC company ticker/exchange file is available at `https://www.sec.gov/files/company_tickers_exchange.json`.
- SEC maximum access rate is 10 requests/second. SEC says this applies regardless of the number of machines used, and excessive automated access may be temporarily rate-limited.

Sources:

- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC EDGAR data access and ticker/exchange files: https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm
- SEC 10 requests/second announcement: https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits
- SEC webmaster FAQ rate-limit guidance: https://www.sec.gov/about/webmaster-frequently-asked-questions

Conclusion: EDGAR supports GRAHAM's required primary data path. Use `company_tickers_exchange.json` for OTC universe seeding, `submissions` for filing recency and metadata, `companyfacts` for NCAV facts, and bulk/nightly JSON where possible.

## 6. OTC/Pink SEC Filer Universe Estimate

Measurement 1: SEC ticker/exchange file.

- Source: `https://www.sec.gov/files/company_tickers_exchange.json`
- Rows: 10,358
- Unique CIKs: 7,995
- OTC ticker rows: 2,550
- Unique OTC CIKs: 2,027
- Other exchange row counts:
  - Nasdaq: 4,271
  - NYSE: 3,279
  - OTC: 2,550
  - CBOE: 28
  - `null`: 230

Measurement 2: EDGAR full-text search, recent 10-K/10-Q activity.

- Endpoint: `https://efts.sec.gov/LATEST/search-index`
- Date range used: 2024-11-04 through 2026-05-04, matching the 18-month active-filer window from the user-supplied run date.
- Query: forms `10-K,10-Q`
- Result: at least 10,000 recent 10-K/10-Q filing hits across all SEC filers.
- Query: forms `10-K,10-Q` plus text phrase `OTC`
- Result: 5,694 filing hits.
- Query: forms `10-K,10-Q` plus text phrases `OTCQX OR OTCQB OR Pink`
- Result: 3,775 filing hits.

Important caveat:

- EDGAR full-text search returns filing hits, not unique traded companies, and filing text references to "OTC" can include non-OTC contexts. The SEC ticker/exchange file is the cleaner starting point for current OTC-traded SEC filers.

Working estimate for Phase 2:

- Current SEC-mapped OTC universe: about 2,000 unique CIKs.
- Active 10-K/10-Q OTC filer universe after 18-month recency filter: likely 1,200 to 1,800 CIKs.
- After shell/blank/zombie, revenue, and liquidity filters: likely a few hundred candidates before NCAV filtering.
- Passing `price < 0.67x NCAV`: likely tens, not hundreds, in normal market conditions.

Weekly feasibility:

- Worst case, refreshing `submissions` and `companyfacts` for 2,027 OTC CIKs is about 4,054 SEC API requests.
- At 10 requests/second theoretical max, that is about 7 minutes of pure request time. With conservative 5 requests/second, retries, and caching, the weekly EDGAR pass should complete in 15 to 30 minutes.
- With nightly bulk JSON and change detection, the weekly incremental run should be materially smaller.
- The bigger operational constraint is FMP plan/rate limit for price and liquidity checks, not SEC EDGAR.

## Reusable Components

Use directly or adapt:

- `data/edgar_client.py`
  - `EdgarClient`
  - SEC User-Agent handling.
  - 10 requests/second throttle.
  - ticker-to-CIK mapping.
  - `get_recent_filings`
  - `download_filing_text`
  - `get_company_facts`
  - `get_key_financials`
- `data/edgar_realtime_client.py`
  - EDGAR full-text search client patterns.
  - Search result parsing.
- `scripts/expand_par_database.py`
  - Archive document discovery.
  - iXBRL viewer URL unwrapping.
  - BeautifulSoup fallback pattern.
- `scripts/download_bdc_filings.py`
  - Clean `data.sec.gov/submissions/CIK##########.json` filing-list pattern.
- `agents/market_data.py`
  - FMP quote wrapper pattern, but not sufficient for OTC liquidity because it lacks historical dollar-volume calculation.

Do not reuse as primary NCAV logic:

- VALIS financial enrichment: no EDGAR/XBRL statement extraction.
- PAR BDC parser: too BDC-specific.
- `data/edgar_client.py.get_key_financials`: useful but too naive for NCAV because it selects latest facts by period end, not by filing date/accession, which can introduce look-ahead or amendment errors.

## Phase 2 Implications

Architecture should require:

- SEC-first universe seed from `company_tickers_exchange.json`, not FMP.
- Filing-date based data selection, not period-date based selection.
- Companyfacts extraction that selects facts tied to the most recent filed 10-K/10-Q accession.
- Local cache for ticker/exchange, submissions, companyfacts, price/liquidity, NCAV results, and memo calls.
- FMP key/rate-limit guardrails before relying on weekly price/liquidity refresh.
- Fallback price/liquidity plan if FMP remains limited.

## Stop Point

Phase 1 audit is complete. No GRAHAM implementation code has been written.
