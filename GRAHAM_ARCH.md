# GRAHAM Phase 2 Architecture

Architecture date: 2026-05-05  
Repo: `/Users/chrisworsey/Desktop/atlas`  
Branch: `graham/v1`  
Status: architecture only; no implementation code written.

## FMP Rate-Limit Test Result

Tested:

```bash
curl -s -D /tmp/fmp_quote_headers.txt \
  -o /tmp/fmp_quote_body.json \
  'https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=ZTvemA5AKSI3e7DnITVXs3RyLY46G2Wx'
```

Result:

- HTTP status: `429`
- `Retry-After` header: not present
- Body:

```json
{
  "Error Message": "Limit Reach . Please upgrade your plan or visit our documentation for more details at https://site.financialmodelingprep.com/"
}
```

Interpretation: treat FMP as plan/quota-level unavailable for GRAHAM v1. The architecture must not depend on FMP for current prices or liquidity.

Polygon fallback test:

```bash
curl -s -D /tmp/poly_headers.txt \
  -o /tmp/poly_body.json \
  'https://api.polygon.io/v2/aggs/ticker/AAPL/prev?apiKey=Z50G_fKhrQmUWZ_9gCpN2XYeaNI99MYW'
```

Result: HTTP `200`, `status: OK`, previous daily bar returned for AAPL with close, volume, VWAP, and timestamp. The existing Polygon key works for at least single-symbol previous-close aggregate calls.

## Design Decision Summary

- SEC EDGAR is the primary source for universe, filing recency, SIC, XBRL facts, and filing text.
- `yfinance` is the primary price and liquidity source because it is installed, free, keyless, and returned prices/volume for tested OTC tickers.
- Polygon.io is the first fallback for price/volume because the existing key works.
- FMP is a last-resort/manual source only until the key or plan is fixed.
- GRAHAM imports and extends `data.edgar_client.EdgarClient` and `data.edgar_realtime_client.EDGARRealtimeClient`; it does not rebuild SEC access from scratch.
- The live SEC OTC universe is 2,027 unique OTC CIKs, not 10,000+.

## A. Price Source Decision

Primary: Yahoo Finance through `yfinance`.

Why:

- Installed locally: `yfinance 1.2.0`.
- No key.
- Supports tested OTC symbols from the SEC OTC list.
- Can return daily OHLCV history needed for average dollar volume.

Smoke test results:

| Symbol | Rows | Last close | Last volume |
| --- | ---: | ---: | ---: |
| AAPL | 5 | 276.83 | 46,638,000 |
| CYATY | 5 | 20.51 | 150,200 |
| RTNTF | 5 | 120.00 | 800 |
| DTEGY | 5 | 31.56 | 369,600 |

Fallback 1: Polygon.io.

- Existing key: `POLYGON_API_KEY=Z50G_fKhrQmUWZ_9gCpN2XYeaNI99MYW`.
- Confirmed working for `/v2/aggs/ticker/AAPL/prev`.
- Use daily aggregate range endpoint for 30 trading days where yfinance fails.

Fallback 2: FMP.

- Disabled by default because current key returns HTTP `429` with no retry guidance and an upgrade message.
- Only enable if future status check returns valid `/quote` and historical data.

Rejected as primary:

- Alpha Vantage: no configured key in `.env`; free limits are too tight for 2,027 symbols if daily history is needed.
- EDGAR price proxies: filings can include market price ranges, but those are stale, filing-date dependent, and not sufficient for a mandatory liquidity filter.

Price cache:

- `graham/cache/prices/{date}.json`
- One record per ticker:
  - `ticker`
  - `source`
  - `asof_date`
  - `last_price`
  - `market_cap`, if available
  - `avg_daily_volume_shares_30d`
  - `avg_daily_volume_dollars_30d`
  - `volume_days`
  - `data_quality`
  - `error`
- Refresh weekly for all current universe tickers.
- Reuse prior week cache if a source fails and the cached price is <= 10 calendar days old; mark `STALE_PRICE`.

Liquidity calculation:

- Pull 30 calendar days of daily OHLCV.
- Use actual returned trading days, normally about 20 to 22.
- Average dollar volume = mean of `close * volume`.
- Pass threshold: `avg_daily_volume_dollars_30d >= 25_000`.
- Build/exit capacity = `avg_daily_volume_dollars_30d * 0.20`.
- Days to build $500K = `ceil(500_000 / capacity)`.

## B. EDGAR Client Reuse

GRAHAM should import existing clients:

```python
from data.edgar_client import EdgarClient
from data.edgar_realtime_client import EDGARRealtimeClient
from config.settings import EDGAR_RATE_LIMIT, EDGAR_USER_AGENT
```

Reuse directly:

- `EdgarClient._rate_limit`
- `EdgarClient._get`
- `EdgarClient._get_text`
- `EdgarClient.download_filing_text`
- `EdgarClient.get_company_facts`
- `EDGARRealtimeClient.FULL_TEXT_SEARCH_URL`
- `EDGARRealtimeClient._get`
- `EDGARRealtimeClient._parse_search_result`

Extend rather than duplicate:

- Add `GrahamEdgarClient(EdgarClient)` in `graham/edgar.py`.
- Add `get_submissions_by_cik(cik)` because current `get_submissions` requires ticker lookup.
- Add `get_company_facts_by_cik(cik)` because current `get_company_facts` requires ticker lookup.
- Add `latest_10k_10q_by_filing_date(cik)` to select the latest filed 10-K/10-Q by `filingDate`, not period end.
- Add `fact_for_accession(companyfacts, tag, accession, unit)` to avoid look-ahead.
- Add HTML fallback wrapper using the PAR filing-document discovery pattern.

What `graham/` adds:

- OTC universe builder.
- Filing-date-correct XBRL fact selection.
- NCAV-specific tag extraction and validation.
- Shell/zombie filters.
- Price/liquidity cache.
- Candidate ranking.
- Memo prompt assembly and cache.
- Weekly output writer.
- Terminal API adapter.

What `graham/` must not do:

- Reimplement generic SEC request sessions.
- Bypass the existing EDGAR user-agent/rate-limit settings.
- Select facts only by latest period end.

## C. XBRL Coverage Estimate

Sample method:

- Source universe: SEC `company_tickers_exchange.json`, exchange `OTC`.
- Unique OTC CIKs: 2,027.
- Deterministic random sample: Python `random.seed(1956)`.
- Endpoint checked: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`.

Sample result:

| CIK | Result | Entity | NCAV core tags |
| --- | --- | --- | --- |
| 0001834607 | 404 | - | no |
| 0001437441 | 404 | - | no |
| 0002068427 | 404 | - | no |
| 0001753373 | 200 | M2I GLOBAL, INC. | yes |
| 0001823593 | 200 | TuSimple Holdings Inc. | yes |
| 0001851651 | 404 | - | no |
| 0000842180 | 200 | BANCO BILBAO VIZCAYA ARGENTARIA, S.A. | no |
| 0001865494 | 200 | IO Biotech, Inc. | yes |
| 0001537317 | 404 | - | no |
| 0001886362 | 200 | MOBILE GLOBAL ESPORTS INC. | yes |
| 0001516324 | 404 | - | no |
| 0000849997 | 200 | FEC RESOURCES INC. | no |
| 0002117702 | 404 | - | no |
| 0001978151 | 404 | - | no |
| 0001839886 | 404 | - | no |
| 0000937966 | 200 | ASML HOLDING NV | yes |
| 0001611983 | 200 | LIBERTY BROADBAND CORPORATION | partial; missing common shares |
| 0001830214 | 200 | GINKGO BIOWORKS HOLDINGS, INC. | yes |
| 0001711141 | 200 | Leef Brands, Inc. | yes |
| 0001384831 | 404 | - | no |

Coverage:

- Companyfacts endpoint exists: 10/20 = 50%.
- Any meaningful us-gaap facts: 9/20 = 45%.
- Core NCAV tags present directly (`AssetsCurrent`, `Liabilities`, and common shares): 7/20 = 35%.

Extrapolation:

- Across 2,027 OTC CIKs, expect about 900 to 1,050 to have a companyfacts endpoint.
- Expect about 700 to 850 to have directly usable NCAV XBRL.
- Active 10-K/10-Q filers should have higher coverage than the raw OTC list because stale ADRs and non-reporting tickers drop out earlier.
- HTML fallback is required for a meaningful fraction of OTC companies.

## D. Universe Builder

Starting source:

- `https://www.sec.gov/files/company_tickers_exchange.json`
- Select rows where `exchange == "OTC"`.
- Deduplicate by CIK.
- Preserve multiple tickers per CIK where present; choose the most liquid ticker after price pass.

Pipeline:

1. Seed 2,027 OTC CIKs from SEC ticker/exchange file.
2. Fetch submissions metadata for each CIK.
3. Keep companies with 10-K/10-Q filed in the last 18 months.
4. Exclude SIC `6770` blank checks immediately.
5. Flag/review SIC `6199` and `6726`; exclude if shell evidence also present.
6. Pull latest annual revenue from XBRL or filing fallback.
7. Exclude zero revenue for 2+ consecutive years.
8. Exclude negative equity before NCAV calculation.
9. Exclude no employees listed where employee data is available.
10. Fetch price/liquidity.
11. Keep only average dollar volume >= $25K.

Estimated funnel:

| Stage | Estimate |
| --- | ---: |
| SEC OTC unique CIKs | 2,027 |
| Filed 10-K/10-Q in last 18 months | 1,200 to 1,800 |
| Revenue > 0 | 800 to 1,100 |
| Ex-shell/blank/zombie | 650 to 950 |
| Price available | 500 to 800 |
| Liquidity >= $25K ADV | 250 to 450 |
| Directly calculable NCAV via XBRL | 150 to 275 |
| Passing `price < 0.67x NCAV` | 20 to 80 |
| Final investable memo universe | 20 to 50 |

Cache:

- `graham/cache/universe_{date}.json`
- `graham/cache/submissions/{cik}.json`
- `graham/cache/companyfacts/{cik}.json`
- `graham/cache/filings/{cik}_{accession}.html`
- Weekly refresh replaces the dated universe cache, but CIK-level caches retain prior data with freshness metadata.

## E. NCAV Calculator

Primary extraction:

- Use SEC companyfacts endpoint through `GrahamEdgarClient.get_company_facts_by_cik`.
- Select the most recent 10-K or 10-Q by `filingDate` from submissions.
- Extract only facts whose `accn` matches that accession, where available.
- Use `filed`, `form`, `fy`, `fp`, `end`, and `frame` metadata for auditability.

Tags:

- Current assets:
  - `us-gaap:AssetsCurrent`
- Total liabilities:
  - `us-gaap:Liabilities`
  - fallback: `us-gaap:LiabilitiesCurrent + us-gaap:LongTermDebtNoncurrent + other liabilities` only if clearly reconstructable; flag `LIABILITIES_RECONSTRUCTED`.
- Shares outstanding:
  - `us-gaap:CommonStockSharesOutstanding`
  - fallback: `dei:EntityCommonStockSharesOutstanding`
- Revenue:
  - `us-gaap:Revenues`
  - `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`
- Equity:
  - `us-gaap:StockholdersEquity`
  - `us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`

Formula:

- `NCAV = Current Assets - Total Liabilities`
- `NCAV per share = NCAV / Shares Outstanding`
- `Price / NCAV = Current Price / NCAV per share`
- `Discount % = (1 - Price / NCAV) * 100`

Fallback extraction:

- Download the latest filing HTML via existing `download_filing_text` plus PAR-style archive document discovery.
- Use BeautifulSoup table extraction.
- Search balance-sheet tables for labels near:
  - current assets
  - total liabilities
  - shares outstanding
  - stockholders' equity
- If fallback is used, mark `data_quality_flag=HTML_FALLBACK`.
- If still incomplete, mark `MANUAL_REVIEW` and skip automated ranking.

Preferred stock and off-balance-sheet handling:

- Preferred stock does not change NCAV directly unless it is redeemable or liability-classified.
- Redeemable preferred stock is treated as liability-like where disclosed in XBRL/filing tables.
- Off-balance-sheet obligations are memo risk items, not NCAV formula inputs, unless recognized as liabilities.
- Any company with material going-concern warnings, large lease obligations, or contingent liabilities is flagged for memo emphasis.

Staleness:

- `is_stale=True` if latest filing date is older than 6 months.
- Exclude from primary screen if older than 18 months.
- Include stale but calculable names only in manual review output, not top candidate ranking.

## F. Price and Liquidity Layer

Data flow:

1. For each ticker in the SEC OTC universe, call yfinance for 30 calendar days of daily data.
2. If yfinance returns no rows or zero price, call Polygon daily aggregates.
3. If Polygon fails, try FMP only if the key has passed a health check during this run.
4. Cache each ticker's data-quality status.

Ticker selection for multi-ticker CIKs:

- Fetch all tickers.
- Keep the ticker with the highest 30-day average dollar volume.
- Store alternates in `alternate_tickers`.

Delisted/suspended handling:

- No recent price bars: `NO_PRICE`, exclude.
- Zero or near-zero volume for most days: `ILLIQUID`, exclude.
- Large stale gap between latest price bar and run date: `STALE_PRICE`, exclude from top 50.
- Corporate action anomalies: preserve raw bars and adjusted bars where source provides both.

## G. Ranking and Filtering

Hard filters:

- Latest 10-K/10-Q filed within 18 months.
- Not SIC `6770`.
- Revenue > 0 in most recent annual filing.
- No two-year zero-revenue pattern.
- Equity >= 0 before NCAV screen.
- `Current Assets > Total Liabilities`.
- `NCAV per share > 0`.
- `Price / NCAV < 0.67`.
- Average dollar volume >= $25K.

Ranking:

- Primary sort: `price_to_ncav` ascending.
- Secondary sort: NCAV quality tier: HIGH, MEDIUM, LOW.
- Tertiary sort: filing recency.
- Quaternary sort: liquidity.

NCAV quality:

- HIGH: cash + receivables > total liabilities.
- MEDIUM: current assets > total liabilities, but inventory-heavy or mixed-quality current assets.
- LOW: current assets barely exceed liabilities or data is incomplete/fallback-heavy.

Output universe:

- Full passing list in `screener_{date}.json`.
- Top 50 for memo generation.
- Top 40 for portfolio candidates report.

## H. Diligence Agent

Memo inputs:

- NCAV result.
- Latest filing metadata and filing URL.
- Balance sheet facts.
- Income statement facts for the latest three annual periods where available.
- Business description excerpt from latest 10-K Item 1.
- Risk factor excerpt from latest 10-K/10-Q Item 1A.
- Liquidity calculation.

LLM call:

- One call per top 50 candidate.
- Use Anthropic Message Batches API for memo analysis sections.
- Cache key: `graham/cache/memos/{cik}_{filing_date}.json`.
- If filing date and extracted financials hash are unchanged, reuse cached memo.

Cost estimate:

- Use Claude Sonnet batch pricing from Anthropic docs: $1.50 per MTok input and $7.50 per MTok output, 50% off standard API pricing.
- Expected per memo:
  - Input: 6,000 to 10,000 tokens.
  - Output: 700 to 1,200 tokens.
- Top 50 batch:
  - Input: 300,000 to 500,000 tokens = $0.45 to $0.75.
  - Output: 35,000 to 60,000 tokens = $0.26 to $0.45.
  - Total: about $0.71 to $1.20 per weekly full memo run.
- Add 25% cushion for retries/longer filings: $0.90 to $1.50/week.

Source:

- Anthropic Batch API pricing: https://docs.anthropic.com/en/docs/build-with-claude/batch-processing

Conclusion: Top 50 memos are safely below the $5/week threshold. No need to reduce to top 20 on cost grounds.

## I. Portfolio Construction Output

GRAHAM is a sourcing engine, not an automated trader.

Portfolio candidate logic:

- Produce top 40 candidates grouped by NCAV quality.
- Show equal-weight reference sizing for 30 to 40 positions.
- Show NCAV-discount-weighted reference sizing as an analytical column only.
- Cap sector exposure at 20%.
- Cap single position at the lower of:
  - 3.33% for a 30-position book.
  - 2.50% for a 40-position book.
  - 10-day build capacity at 20% of ADV.
- Flag any $500K position taking more than 20 trading days to build.

No orders, no execution, no portfolio mutation.

## J. Cron and Output Structure

Weekly run:

- Sunday 02:00 UTC.
- `graham/run.py --mode full`.

Modes:

- `full`: refresh universe, prices, NCAV, memos, outputs.
- `refresh`: reuse universe, refresh prices and NCAV.
- `memos`: regenerate memo files from latest screener.
- `status`: show last run stats; no external API calls.

Outputs:

- `graham/output/screener_{date}.json`
- `graham/output/memos/{ticker}_{date}.md`
- `graham/output/portfolio_candidates_{date}.md`
- `graham/output/weekly_summary_{date}.txt`

Status file:

- `graham/output/latest_status.json`
- Contains last run time, universe count, active count, passing count, memo count, failures, and source health.

## K. ATLAS Terminal Integration

API:

- Add `/api/graham`.
- Endpoint reads latest `graham/output/screener_*.json`.
- No external API calls from terminal request path.
- If missing, return:
  - `status: NOT_RUN`
  - `message: GRAHAM has not produced a screener output yet`

F8 INTEL panel:

- Read `/api/graham`.
- Show section below 13F/Congressional filings:

```text
GRAHAM NET-NET SCREEN
Last run: {date} | Universe: {n} | Passing: {n}
TICKER  PRICE  NCAV   DISC%  QUALITY  VOL($K)
...
Full report: graham/output/portfolio_candidates_{date}.md
```

Only top 10 rows render in terminal. Full report remains markdown.

## L. Weekly Cost and Runtime Estimate

EDGAR:

- Universe seed: 1 request for `company_tickers_exchange.json`.
- Submissions: up to 2,027 requests for full refresh.
- Companyfacts: up to 2,027 requests for full NCAV refresh.
- Filing HTML fallback: estimate 100 to 300 requests, only for incomplete XBRL and candidates near threshold.
- Total worst-case SEC calls: about 4,155 to 4,355.
- At 10 requests/second theoretical: about 7.0 to 7.3 minutes.
- At conservative 5 requests/second plus retries: about 15 to 25 minutes.

Price:

- yfinance batch/download calls: group tickers into batches where practical; expected 20 to 60 network calls.
- Polygon fallback: estimate 50 to 250 calls depending on yfinance failures.
- FMP: 0 by default.
- Price API dollar cost: $0 expected for yfinance; Polygon cost depends on plan but existing key works.

LLM:

- Top 50 memos via Claude Sonnet batch.
- Estimated weekly cost: $0.90 to $1.50 including cushion.
- If no filing changes, cache reuse should reduce weekly LLM cost materially, often close to $0.

Total weekly runtime:

- Universe/submissions/companyfacts: 15 to 25 minutes conservative.
- Price/liquidity: 5 to 20 minutes, dominated by yfinance/Polygon retries.
- NCAV calculation and filtering: < 2 minutes local.
- Filing text fallback/excerpts: 5 to 15 minutes for candidates and incomplete data.
- Memo batch submission: minutes to batch completion; design for asynchronous wait up to 24 hours, but typical should be much shorter.
- End-to-end normal run: 30 to 60 minutes.
- End-to-end worst case with many fallbacks/retries: 90 minutes.

Total weekly dollar cost:

- SEC: $0.
- yfinance: $0.
- Polygon: $0 incremental assumed with existing key, subject to account plan.
- FMP: $0 because disabled.
- LLM: $0.90 to $1.50.
- Expected total: <$2/week.

## M. Rate Limiting Strategy

EDGAR:

- Centralize all SEC calls through `GrahamEdgarClient`, subclassing `EdgarClient`.
- Preserve `EDGAR_RATE_LIMIT = 10`.
- Use a token-bucket or bounded async semaphore set to 8 requests/second for cushion.
- Add exponential backoff for 429/403/5xx.
- Respect `Retry-After` if SEC ever returns it.
- Cache CIK-level responses and use conditional refresh by age.

Concurrency:

- Separate queues:
  - `sec_queue`: max 8 req/sec.
  - `price_queue`: source-specific throttles.
  - `llm_queue`: batch submission only.
- No direct HTTP calls outside these clients.
- Every external response writes a cache entry with source, timestamp, and status.

Avoiding weekly limit problems:

- Use SEC bulk/nightly JSON files where available.
- Refresh `company_tickers_exchange.json` weekly.
- Refresh submissions for all active OTC CIKs weekly.
- Refresh companyfacts only when:
  - latest filing accession changed,
  - cached facts are missing,
  - previous result was incomplete,
  - or monthly full validation is due.
- Reuse memo cache unless filing date or extracted facts hash changes.

## N. Implementation Layout for Later Phases

Planned files:

```text
graham/
  __init__.py
  run.py
  config.py
  models.py
  edgar.py
  universe.py
  xbrl.py
  price.py
  ncav.py
  filters.py
  ranking.py
  filings.py
  memo.py
  outputs.py
  terminal_api.py
  backtest_hook.py
  cache/
  output/
```

The implementation should keep GRAHAM self-contained while importing shared EDGAR and config modules from the existing ATLAS codebase.

## Stop Point

Phase 2 architecture is complete. No GRAHAM implementation code has been written.
