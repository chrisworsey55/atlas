#!/usr/bin/env python3
"""
SEC EDGAR Filing Monitor for tracked superinvestor funds.
Checks 13F quarterly holdings and Form 4 insider trades.
"""
import requests
import json
import argparse
import time
from pathlib import Path
from datetime import datetime

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
ALERTS_FILE = STATE_DIR / "filing_alerts.json"

HEADERS = {'User-Agent': 'GIC Research research@generalintelligencecapital.com'}

TRACKED_FUNDS = {
    'Situational Awareness LP': {'cik': None, 'agent': 'aschenbrenner', 'search': 'Situational Awareness'},
    'Duquesne Family Office': {'cik': '0001536411', 'agent': 'druckenmiller'},
    'Atreides Management': {'cik': None, 'agent': 'baker', 'search': 'Atreides Management'},
    'Pershing Square': {'cik': '0001336528', 'agent': 'ackman'},
    'Berkshire Hathaway': {'cik': '0001067983', 'agent': 'buffett'},
    'Bridgewater Associates': {'cik': '0001350694', 'agent': 'dalio'},
    'Tiger Global': {'cik': '0001167483', 'agent': 'tiger'},
    'Soros Fund Management': {'cik': '0001029160', 'agent': 'soros'},
}

# Default tickers - will be overridden by positions.json
PORTFOLIO_TICKERS = ['AVGO', 'BE', 'UNH', 'APO', 'ADBE', 'GOOG', 'CRM', 'STX']


def load_portfolio_tickers():
    """Load current portfolio tickers from positions.json"""
    global PORTFOLIO_TICKERS
    try:
        positions_file = STATE_DIR / 'positions.json'
        if positions_file.exists():
            with open(positions_file) as f:
                data = json.load(f)
            positions = data.get('positions', [])
            tickers = [p['ticker'] for p in positions if p.get('ticker') and p['ticker'] != 'BIL']
            if tickers:
                PORTFOLIO_TICKERS = tickers
                print(f"Loaded {len(tickers)} tickers from portfolio: {', '.join(tickers)}")
    except Exception as e:
        print(f"Warning: Could not load positions.json, using defaults: {e}")


def check_13f_filings():
    """Check for new 13F filings from tracked funds"""
    print("\nChecking 13F filings from tracked funds...")
    alerts = []

    for fund_name, info in TRACKED_FUNDS.items():
        cik = info.get('cik')
        if not cik:
            # Search by name for funds without known CIK
            search_term = info.get('search', fund_name)
            url = f"https://efts.sec.gov/LATEST/search-index?q=%22{search_term.replace(' ', '%20')}%22&forms=13F-HR&dateRange=custom&startdt=2026-01-01&enddt=2026-12-31"
        else:
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"

        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                data = response.json()
                recent_filings = data.get('filings', {}).get('recent', {})
                forms = recent_filings.get('form', [])
                dates = recent_filings.get('filingDate', [])
                accessions = recent_filings.get('accessionNumber', [])

                for i, (form, date) in enumerate(zip(forms, dates)):
                    if '13F' in str(form) and date >= '2026-01-01':
                        accession = accessions[i] if i < len(accessions) else None
                        alert = {
                            'fund': fund_name,
                            'agent': info['agent'],
                            'type': '13F-HR',
                            'date': date,
                            'accession': accession,
                            'summary': f'{fund_name} filed 13F on {date}',
                            'urgency': 'HIGH',
                            'detected_at': datetime.now().isoformat()
                        }
                        alerts.append(alert)
                        print(f"  FOUND: {fund_name} -- 13F filed {date}")
            time.sleep(0.5)  # Rate limiting
        except Exception as e:
            print(f"  Error checking {fund_name}: {e}")

    return alerts


def check_form4_insider_trades():
    """Check Form 4 insider trades for portfolio tickers"""
    print("\nChecking Form 4 insider trades for portfolio tickers...")
    print(f"  Monitoring: {', '.join(PORTFOLIO_TICKERS)}")
    alerts = []

    # Get current month for date filtering
    now = datetime.now()
    start_date = f"{now.year}-{now.month:02d}-01"
    end_date = f"{now.year}-{now.month:02d}-{now.day:02d}"

    for ticker in PORTFOLIO_TICKERS:
        url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=4&dateRange=custom&startdt={start_date}&enddt={end_date}"

        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                data = response.json()
                hits = data.get('hits', {}).get('hits', [])

                for hit in hits[:5]:  # Limit to 5 most recent
                    source = hit.get('_source', {})
                    filing_date = source.get('file_date', '')
                    entity = source.get('display_names', ['Unknown'])[0] if source.get('display_names') else 'Unknown'

                    if filing_date >= start_date:
                        alert = {
                            'ticker': ticker,
                            'type': 'Form 4',
                            'date': filing_date,
                            'entity': entity,
                            'summary': f'Insider trade in {ticker} by {entity} on {filing_date}',
                            'urgency': 'MEDIUM',
                            'detected_at': datetime.now().isoformat()
                        }
                        alerts.append(alert)
                        print(f"  FOUND: {ticker} -- Form 4 by {entity} on {filing_date}")
            time.sleep(0.5)  # Rate limiting
        except Exception as e:
            print(f"  Error checking {ticker}: {e}")

    return alerts


def run_monitor(filing_type='all'):
    """Run the filing monitor"""
    print(f"\n{'='*60}")
    print(f"ATLAS SEC FILING MONITOR -- {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # Load current portfolio tickers dynamically
    load_portfolio_tickers()

    all_alerts = []

    if filing_type in ['all', '13f']:
        all_alerts.extend(check_13f_filings())

    if filing_type in ['all', 'form4']:
        all_alerts.extend(check_form4_insider_trades())

    # Load existing alerts
    existing = []
    if ALERTS_FILE.exists():
        try:
            with open(ALERTS_FILE) as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            existing = []

    # Deduplicate based on fund/ticker + date + type
    existing_keys = {
        (a.get('fund', a.get('ticker', '')), a.get('date', ''), a.get('type', ''))
        for a in existing
    }
    new_alerts = [
        a for a in all_alerts
        if (a.get('fund', a.get('ticker', '')), a.get('date', ''), a.get('type', '')) not in existing_keys
    ]

    # Save updated alerts
    if new_alerts:
        existing.extend(new_alerts)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(ALERTS_FILE, 'w') as f:
            json.dump(existing, f, indent=2)
        print(f"\n{len(new_alerts)} NEW ALERTS saved to {ALERTS_FILE}")
        for alert in new_alerts:
            print(f"  - [{alert['urgency']}] {alert['summary']}")
    else:
        print(f"\nNo new filings detected.")

    print(f"Total alerts in database: {len(existing)}")
    print(f"{'='*60}\n")

    return new_alerts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ATLAS SEC Filing Monitor')
    parser.add_argument('--type', '-t', choices=['all', '13f', 'form4'], default='all',
                        help='Type of filings to check (default: all)')
    args = parser.parse_args()
    run_monitor(args.type)
