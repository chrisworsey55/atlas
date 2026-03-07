#!/usr/bin/env python3
"""
SEC EDGAR Filing Monitor for tracked superinvestor funds.
Checks 13F quarterly holdings and Form 4 insider trades.
"""
import requests
import json
import argparse
import time
import os
from pathlib import Path
from datetime import datetime

# Load environment variables
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

STATE_DIR = Path(__file__).parent.parent / "data" / "state"
ALERTS_FILE = STATE_DIR / "filing_alerts.json"

# Email configuration via Resend
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "re_QBTmTBP8_2mfiYdx81HUuJuyTLL7jiHrJ")
ALERT_TO = os.getenv("BRIEFING_TO", "chris@generalintelligencecapital.com")
# Use Resend's default sender until domain is verified
ALERT_FROM = "ATLAS Alerts <onboarding@resend.dev>"

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


def send_alert_email(alerts: list, to_email: str = None) -> bool:
    """Send email notification for new filing alerts via Resend API."""
    if not alerts:
        print("No alerts to email")
        return False

    to_email = to_email or ALERT_TO

    if not RESEND_API_KEY:
        print("RESEND_API_KEY not configured")
        return False

    # Count by type
    high_count = len([a for a in alerts if a.get('urgency') == 'HIGH'])

    if high_count > 0:
        subject = f"[ATLAS ALERT] {high_count} 13F Filings Detected"
    else:
        subject = f"[ATLAS] {len(alerts)} SEC Filing Alerts"

    # Group alerts by urgency
    high_alerts = [a for a in alerts if a.get('urgency') == 'HIGH']
    medium_alerts = [a for a in alerts if a.get('urgency') == 'MEDIUM']

    # Plain text version
    text_lines = [
        "ATLAS SEC FILING MONITOR",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "=" * 50,
        ""
    ]

    if high_alerts:
        text_lines.append("HIGH PRIORITY - 13F QUARTERLY FILINGS")
        text_lines.append("-" * 40)
        for alert in high_alerts:
            text_lines.append(f"  {alert['summary']}")
            if alert.get('fund'):
                text_lines.append(f"    Fund: {alert['fund']}")
        text_lines.append("")

    if medium_alerts:
        text_lines.append("MEDIUM PRIORITY - FORM 4 INSIDER TRADES")
        text_lines.append("-" * 40)
        for alert in medium_alerts:
            text_lines.append(f"  {alert['summary']}")
        text_lines.append("")

    text_lines.extend([
        "---",
        "View full details: https://meetvalis.com/atlas/agents",
        "",
        "ATLAS | General Intelligence Capital"
    ])

    text_body = "\n".join(text_lines)

    # HTML version
    html_body = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0a0a0f; color: #e5e5e5; padding: 20px;">
    <div style="max-width: 600px; margin: 0 auto; background: #12121a; padding: 20px; border-radius: 8px;">
        <h1 style="color: #00d4ff; margin-bottom: 5px;">ATLAS SEC Filing Monitor</h1>
        <p style="color: #888; margin-top: 0;">{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        <hr style="border-color: #333;">
    """

    if high_alerts:
        html_body += '<h2 style="color: #ff6b6b;">HIGH PRIORITY - 13F Quarterly Filings</h2>'
        html_body += '<ul style="list-style: none; padding: 0;">'
        for alert in high_alerts:
            html_body += f'''
            <li style="background: #1a1a2e; padding: 12px; margin: 8px 0; border-left: 4px solid #ff6b6b; border-radius: 4px;">
                <strong>{alert['summary']}</strong>
                {f"<br><span style='color: #888;'>Fund: {alert['fund']}</span>" if alert.get('fund') else ""}
            </li>'''
        html_body += '</ul>'

    if medium_alerts:
        html_body += '<h2 style="color: #ffd93d;">MEDIUM PRIORITY - Form 4 Insider Trades</h2>'
        html_body += '<ul style="list-style: none; padding: 0;">'
        for alert in medium_alerts[:10]:
            html_body += f'''
            <li style="background: #1a1a2e; padding: 12px; margin: 8px 0; border-left: 4px solid #ffd93d; border-radius: 4px;">
                {alert['summary']}
            </li>'''
        if len(medium_alerts) > 10:
            html_body += f'<li style="color: #888; padding: 8px;">... and {len(medium_alerts) - 10} more</li>'
        html_body += '</ul>'

    html_body += """
        <hr style="border-color: #333;">
        <p><a href="https://meetvalis.com/atlas/agents" style="color: #00d4ff;">View full details on ATLAS Dashboard</a></p>
        <p style="color: #666; font-size: 12px;">ATLAS | General Intelligence Capital</p>
    </div>
    </body>
    </html>
    """

    # Send via Resend API
    try:
        print(f"Sending email via Resend to {to_email}...")
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from": ALERT_FROM,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
                "text": text_body
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            print(f"Email sent successfully! ID: {data.get('id')}")
            return True
        else:
            print(f"Resend API error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"Email failed: {e}")
        return False


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


def run_monitor(filing_type='all', send_email_flag=False):
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

        # Send email notification if enabled
        if send_email_flag:
            print("\nSending email notification...")
            send_alert_email(new_alerts)
    else:
        print(f"\nNo new filings detected.")

    print(f"Total alerts in database: {len(existing)}")
    print(f"{'='*60}\n")

    return new_alerts


def send_test_email(to_email: str = None):
    """Send a test email to verify SMTP configuration."""
    test_alerts = [
        {
            'fund': 'TEST — Duquesne Family Office',
            'agent': 'druckenmiller',
            'type': '13F-HR',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'summary': 'TEST ALERT — This is a test of the ATLAS filing monitor email system',
            'urgency': 'HIGH',
            'detected_at': datetime.now().isoformat()
        },
        {
            'ticker': 'TEST',
            'type': 'Form 4',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'entity': 'Test Insider',
            'summary': 'TEST — Insider trade in TEST by Test Insider',
            'urgency': 'MEDIUM',
            'detected_at': datetime.now().isoformat()
        }
    ]

    print("\n" + "=" * 60)
    print("ATLAS SEC FILING MONITOR — TEST EMAIL")
    print("=" * 60)
    print(f"Sending test email to: {to_email or ALERT_TO}")

    success = send_alert_email(test_alerts, to_email)

    if success:
        print("\nTest email sent successfully! Check your inbox.")
    else:
        print("\nTest email FAILED. Check SMTP configuration.")

    return success


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ATLAS SEC Filing Monitor')
    parser.add_argument('--type', '-t', choices=['all', '13f', 'form4'], default='all',
                        help='Type of filings to check (default: all)')
    parser.add_argument('--email', '-e', action='store_true',
                        help='Send email notification for new alerts')
    parser.add_argument('--test-email', action='store_true',
                        help='Send a test email to verify SMTP configuration')
    parser.add_argument('--to', type=str, default=None,
                        help='Override recipient email address')
    args = parser.parse_args()

    if args.test_email:
        send_test_email(args.to)
    else:
        run_monitor(args.type, send_email_flag=args.email)
