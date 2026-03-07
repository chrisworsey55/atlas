#!/usr/bin/env python3
"""ATLAS email alert system using Resend"""
import resend
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

resend.api_key = os.getenv('RESEND_API_KEY')

FROM_EMAIL = "atlas@generalintelligencecapital.com"  # Or "onboarding@resend.dev" if domain not verified
TO_EMAIL = "chris@generalintelligencecapital.com"

def send_email(subject, html_body, text_body=None):
    """Send an email via Resend"""
    try:
        params = {
            "from": FROM_EMAIL,
            "to": [TO_EMAIL],
            "subject": subject,
            "html": html_body,
        }
        if text_body:
            params["text"] = text_body

        email = resend.Emails.send(params)
        print(f"Email sent: {subject} (ID: {email.get('id', 'unknown')})")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        # Try with Resend default sender if custom domain fails
        try:
            params["from"] = "ATLAS <onboarding@resend.dev>"
            email = resend.Emails.send(params)
            print(f"Email sent via fallback: {subject}")
            return True
        except Exception as e2:
            print(f"Email fallback also failed: {e2}")
            return False

def send_filing_alert(alerts):
    """Send SEC filing alert email"""
    subject = f"ATLAS FILING ALERT: {len(alerts)} new {'filing' if len(alerts) == 1 else 'filings'}"

    html = "<h2>ATLAS SEC Filing Monitor</h2>"
    for alert in alerts:
        urgency = alert.get('urgency', 'MEDIUM')
        color = '#ff4444' if urgency == 'HIGH' else '#ffaa00'

        if alert.get('type') == '13F-HR':
            html += f'<div style="border-left: 4px solid {color}; padding: 10px; margin: 10px 0;">'
            html += f'<strong>{alert["fund"]}</strong> filed {alert["type"]} on {alert["date"]}<br>'
            html += f'Agent: {alert.get("agent", "unknown")}<br>'
            html += f'Action: Check for position changes vs our portfolio</div>'
        else:
            html += f'<div style="border-left: 4px solid {color}; padding: 10px; margin: 10px 0;">'
            html += f'<strong>Insider trade: {alert.get("ticker")}</strong> — {alert.get("entity", "Unknown")}<br>'
            html += f'Filed: {alert.get("date")}</div>'

    html += '<br><a href="https://meetvalis.com/atlas/agents">View Dashboard</a>'

    return send_email(subject, html)

def send_daily_briefing(briefing_data):
    """Send morning briefing email"""
    subject = f"ATLAS Morning Briefing — {briefing_data.get('date', 'Today')}"

    snapshot = briefing_data.get('portfolio_snapshot', {})
    cio = briefing_data.get('cio_synthesis', {})
    news = briefing_data.get('news', [])

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px;">
        <h1 style="color: #00d4aa;">ATLAS Morning Briefing</h1>
        <p style="color: #888;">{briefing_data.get('date', '')}</p>

        <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px; margin: 15px 0;">
            <h3 style="color: #00d4aa; margin-top: 0;">Portfolio Snapshot</h3>
            <p style="font-size: 24px; margin: 5px 0;">
                Total P&L: <span style="color: {'#00ff88' if snapshot.get('total_pnl', 0) >= 0 else '#ff4444'}">
                ${snapshot.get('total_pnl', 0):,.2f} ({snapshot.get('total_pnl_pct', 0):.2f}%)</span>
            </p>
            <p>Positions: {snapshot.get('position_count', 0)} | Cash: {snapshot.get('cash_pct', 0):.1f}%</p>
        </div>

        <div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px; margin: 15px 0;">
            <h3 style="color: #00d4aa; margin-top: 0;">CIO Recommendation</h3>
            <p style="font-size: 18px;"><strong>{cio.get('stance', 'NEUTRAL')}</strong> — Conviction: {cio.get('conviction', 0)}%</p>
            <p>{cio.get('recommendation', 'No recommendation available')}</p>
        </div>
    """

    if news:
        html += '<div style="background: #1a1a2e; color: white; padding: 20px; border-radius: 8px; margin: 15px 0;">'
        html += '<h3 style="color: #00d4aa; margin-top: 0;">Overnight News</h3>'
        for n in news[:5]:
            urgency_color = '#ff4444' if n.get('urgency') == 'IMMEDIATE' else '#ffaa00' if n.get('urgency') == 'TODAY' else '#888'
            html += f'<p><span style="color: {urgency_color};">[{n.get("urgency", "INFO")}]</span> {n.get("headline", "")}</p>'
        html += '</div>'

    html += '<br><a href="https://meetvalis.com/atlas">Open Dashboard</a>'
    html += '</div>'

    return send_email(subject, html)

def send_urgent_alert(message, ticker=None):
    """Send an immediate urgent alert"""
    subject = f"ATLAS URGENT: {ticker + ' — ' if ticker else ''}{message[:50]}"
    html = f'<div style="border-left: 4px solid #ff4444; padding: 15px;"><h2 style="color: #ff4444;">URGENT ALERT</h2><p style="font-size: 18px;">{message}</p><br><a href="https://meetvalis.com/atlas">Open Dashboard</a></div>'
    return send_email(subject, html)


if __name__ == "__main__":
    # Test email
    send_email(
        "ATLAS TEST — Email System Working",
        "<h2>ATLAS Email Alerts Active</h2><p>If you're reading this, the email system is working.</p><p>You will receive:</p><ul><li>Daily briefing at 8am EST</li><li>SEC filing alerts when superinvestors file</li><li>Urgent alerts when news impacts portfolio</li></ul><br><a href='https://meetvalis.com/atlas'>Open Dashboard</a>",
    )
    print("Test email sent to chris@generalintelligencecapital.com — check your inbox")
