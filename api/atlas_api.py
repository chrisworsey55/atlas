"""
ATLAS API Server
Serves portfolio data, desk briefs, trades, and chat from PostgreSQL.
Also serves the dashboard UI.
"""
import os
import re
import json
from datetime import datetime, date, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import sessionmaker
import yfinance as yf

# Configure Flask with template and static folders
_api_dir = Path(__file__).parent
_atlas_dir = _api_dir.parent
template_dir = _atlas_dir / "templates"
static_dir = _atlas_dir / "static"

app = Flask(__name__, template_folder=str(template_dir), static_folder=str(static_dir))
CORS(app)

# Register chat routes blueprint
try:
    from api.chat_endpoints import register_chat_routes
    register_chat_routes(app)
except ImportError:
    # Fallback if running from different location
    try:
        from chat_endpoints import register_chat_routes
        register_chat_routes(app)
    except ImportError:
        print("Warning: Could not import chat_endpoints, chat routes disabled")

# Database connection
DATABASE_URL = os.getenv("ATLAS_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/valis")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

# Tracked funds for 13F
TRACKED_FUNDS = [
    "Berkshire Hathaway", "Pershing Square", "Duquesne", "Appaloosa", 
    "Soros Fund Management", "Bridgewater", "Renaissance Technologies",
    "Citadel", "Point72", "Tiger Global", "Coatue", "Lone Pine",
    "Viking Global", "Third Point", "Baupost", "Greenlight Capital"
]

def get_spy_data(start_date: str, end_date: str = None) -> list:
    """Fetch SPY data for benchmark comparison."""
    try:
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        spy = yf.Ticker("SPY")
        hist = spy.history(start=start_date, end=end)
        if hist.empty:
            return []
        
        # Rebase to 1,000,000
        first_close = hist['Close'].iloc[0]
        rebased = (hist['Close'] / first_close) * 1000000
        
        return [
            {"date": idx.strftime("%Y-%m-%d"), "value": round(val, 2)}
            for idx, val in rebased.items()
        ]
    except Exception as e:
        print(f"Error fetching SPY: {e}")
        return []

def get_spy_current() -> dict:
    """Get current SPY price and daily change."""
    try:
        spy = yf.Ticker("SPY")
        info = spy.info
        price = info.get('regularMarketPrice', info.get('previousClose', 0))
        prev = info.get('previousClose', price)
        change = ((price - prev) / prev * 100) if prev else 0
        return {"price": round(price, 2), "change": round(change, 2)}
    except Exception as e:
        print(f"Error fetching SPY current: {e}")
        return {"price": 0, "change": 0}

def time_ago(dt) -> str:
    """Convert datetime to '2 min ago' style string."""
    if not dt:
        return "unknown"
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())
    
    now = datetime.now()
    diff = now - dt
    
    if diff.days > 0:
        return f"{diff.days}d ago"
    elif diff.seconds >= 3600:
        return f"{diff.seconds // 3600}h ago"
    elif diff.seconds >= 60:
        return f"{diff.seconds // 60}m ago"
    else:
        return "just now"


# ============== PORTFOLIO ENDPOINTS ==============

@app.route('/api/portfolio/summary', methods=['GET'])
def portfolio_summary():
    """Get portfolio summary stats."""
    session = Session()
    try:
        # Get latest snapshot
        result = session.execute(text("""
            SELECT date, total_value, cash_balance, daily_return, cumulative_return,
                   sharpe_ratio, max_drawdown
            FROM atlas_portfolio_snapshots
            ORDER BY date DESC
            LIMIT 1
        """))
        row = result.fetchone()
        
        if not row:
            return jsonify({
                "empty": True,
                "message": "No portfolio data yet. Paper trading hasn't started."
            })
        
        snapshot = dict(row._mapping)
        
        # Get open positions count
        positions_result = session.execute(text("""
            SELECT COUNT(*) as count FROM atlas_trades WHERE exit_date IS NULL
        """))
        positions_count = positions_result.fetchone()[0]
        
        # Calculate total P&L
        starting_value = 1000000  # Starting capital
        total_value = snapshot.get('total_value', starting_value)
        total_pnl = total_value - starting_value
        total_pnl_pct = (total_pnl / starting_value) * 100
        
        # Get today's P&L
        daily_return = snapshot.get('daily_return', 0) or 0
        daily_pnl = total_value * (daily_return / 100) if daily_return else 0
        
        return jsonify({
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_return, 2),
            "cash_balance": round(snapshot.get('cash_balance', 0) or 0, 2),
            "positions_count": positions_count,
            "sharpe_ratio": round(snapshot.get('sharpe_ratio', 0) or 0, 2),
            "max_drawdown": round(snapshot.get('max_drawdown', 0) or 0, 2),
            "as_of": snapshot.get('date').isoformat() if snapshot.get('date') else None
        })
    except Exception as e:
        return jsonify({"error": str(e), "empty": True}), 500
    finally:
        session.close()


@app.route('/api/portfolio/chart', methods=['GET'])
def portfolio_chart():
    """Get portfolio value over time with SPY benchmark."""
    session = Session()
    try:
        # Get all snapshots
        result = session.execute(text("""
            SELECT date, total_value, cumulative_return
            FROM atlas_portfolio_snapshots
            ORDER BY date ASC
        """))
        rows = result.fetchall()
        
        if not rows:
            return jsonify({
                "empty": True,
                "message": "No portfolio snapshots yet.",
                "portfolio": [],
                "benchmark": []
            })
        
        portfolio = [
            {"date": row.date.isoformat(), "value": round(row.total_value, 2)}
            for row in rows
        ]
        
        # Get SPY benchmark for same period
        start_date = rows[0].date.isoformat()
        benchmark = get_spy_data(start_date)
        
        return jsonify({
            "portfolio": portfolio,
            "benchmark": benchmark,
            "start_date": start_date
        })
    except Exception as e:
        return jsonify({"error": str(e), "empty": True}), 500
    finally:
        session.close()


@app.route('/api/portfolio/positions', methods=['GET'])
def portfolio_positions():
    """Get current open positions."""
    session = Session()
    try:
        result = session.execute(text("""
            SELECT t.ticker, t.direction, t.shares, t.entry_price, t.entry_date,
                   c.name as company_name, c.sector,
                   th.confidence, db.signal_direction as latest_signal
            FROM atlas_trades t
            LEFT JOIN atlas_companies c ON t.ticker = c.ticker
            LEFT JOIN atlas_theses th ON t.thesis_id = th.id
            LEFT JOIN LATERAL (
                SELECT signal_direction FROM atlas_desk_briefs 
                WHERE company_id = c.id 
                ORDER BY analysis_date DESC LIMIT 1
            ) db ON true
            WHERE t.exit_date IS NULL
            ORDER BY (t.shares * t.entry_price) DESC
        """))
        
        positions = []
        for row in result:
            r = dict(row._mapping)
            # Would need current price from yfinance for real P&L
            positions.append({
                "ticker": r['ticker'],
                "company_name": r.get('company_name', r['ticker']),
                "sector": r.get('sector', 'Unknown'),
                "direction": r['direction'],
                "shares": r['shares'],
                "entry_price": r['entry_price'],
                "entry_date": r['entry_date'].isoformat() if r['entry_date'] else None,
                "entry_value": round(r['shares'] * r['entry_price'], 2),
                "confidence": r.get('confidence'),
                "latest_signal": r.get('latest_signal', 'NEUTRAL')
            })
        
        return jsonify({"positions": positions})
    except Exception as e:
        return jsonify({"error": str(e), "positions": []}), 500
    finally:
        session.close()


# ============== AGENT SWARM / BRIEFS ENDPOINTS ==============

@app.route('/api/briefs', methods=['GET'])
def get_briefs():
    """Get recent desk briefs for the activity feed."""
    limit = request.args.get('limit', 20, type=int)
    session = Session()
    try:
        result = session.execute(text("""
            SELECT b.id, b.desk_name, b.analysis_date, b.signal_direction, b.confidence,
                   b.cio_briefing, b.brief_json, c.ticker, c.name as company_name,
                   b.created_at
            FROM atlas_desk_briefs b
            JOIN atlas_companies c ON b.company_id = c.id
            ORDER BY b.created_at DESC, b.analysis_date DESC
            LIMIT :limit
        """), {"limit": limit})
        
        briefs = []
        for row in result:
            r = dict(row._mapping)
            brief_json = r.get('brief_json', {}) or {}
            
            briefs.append({
                "id": r['id'],
                "desk_name": r['desk_name'],
                "ticker": r['ticker'],
                "company_name": r.get('company_name', r['ticker']),
                "signal": r['signal_direction'],
                "confidence": round((r.get('confidence') or 0) * 100),
                "summary": r.get('cio_briefing') or brief_json.get('brief_for_cio', ''),
                "analysis_date": r['analysis_date'].isoformat() if r['analysis_date'] else None,
                "time_ago": time_ago(r.get('created_at') or r.get('analysis_date'))
            })
        
        return jsonify({"briefs": briefs})
    except Exception as e:
        return jsonify({"error": str(e), "briefs": []}), 500
    finally:
        session.close()


@app.route('/api/briefs/stats', methods=['GET'])
def briefs_stats():
    """Get brief statistics - count today, active agents."""
    session = Session()
    try:
        today = date.today()
        
        # Count briefs today
        count_result = session.execute(text("""
            SELECT COUNT(*) FROM atlas_desk_briefs WHERE analysis_date = :today
        """), {"today": today})
        briefs_today = count_result.fetchone()[0]
        
        # Count active desks (produced brief in last 7 days)
        desks_result = session.execute(text("""
            SELECT COUNT(DISTINCT desk_name) FROM atlas_desk_briefs 
            WHERE analysis_date >= :week_ago
        """), {"week_ago": today - timedelta(days=7)})
        active_desks = desks_result.fetchone()[0]
        
        return jsonify({
            "briefs_today": briefs_today,
            "active_agents": active_desks,
            "as_of": today.isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e), "briefs_today": 0, "active_agents": 0}), 500
    finally:
        session.close()


# ============== CIO DECISIONS / TRADES ENDPOINTS ==============

@app.route('/api/trades', methods=['GET'])
def get_trades():
    """Get trade decisions with thesis rationale."""
    limit = request.args.get('limit', 10, type=int)
    session = Session()
    try:
        result = session.execute(text("""
            SELECT t.id, t.ticker, t.direction, t.shares, t.entry_price, t.entry_date,
                   t.exit_price, t.exit_date, t.realized_pnl, t.realized_pnl_pct,
                   t.entry_rationale, t.adversarial_challenge, t.adversarial_response,
                   th.bull_case, th.bear_case, th.invalidation_criteria, th.confidence
            FROM atlas_trades t
            LEFT JOIN atlas_theses th ON t.thesis_id = th.id
            ORDER BY t.entry_date DESC
            LIMIT :limit
        """), {"limit": limit})
        
        trades = []
        for row in result:
            r = dict(row._mapping)
            status = "OPEN" if not r.get('exit_date') else "CLOSED"
            if r.get('adversarial_challenge') and not r.get('entry_date'):
                status = "VETOED"
            
            trades.append({
                "id": r['id'],
                "ticker": r['ticker'],
                "direction": r['direction'],
                "shares": r['shares'],
                "entry_price": r['entry_price'],
                "entry_date": r['entry_date'].isoformat() if r['entry_date'] else None,
                "exit_price": r.get('exit_price'),
                "exit_date": r['exit_date'].isoformat() if r.get('exit_date') else None,
                "realized_pnl": r.get('realized_pnl'),
                "realized_pnl_pct": r.get('realized_pnl_pct'),
                "status": status,
                "rationale": r.get('entry_rationale', ''),
                "bull_case": r.get('bull_case', ''),
                "bear_case": r.get('bear_case', ''),
                "invalidation": r.get('invalidation_criteria', ''),
                "adversarial_challenge": r.get('adversarial_challenge', ''),
                "adversarial_response": r.get('adversarial_response', ''),
                "confidence": round((r.get('confidence') or 0) * 100)
            })
        
        return jsonify({"trades": trades})
    except Exception as e:
        return jsonify({"error": str(e), "trades": []}), 500
    finally:
        session.close()


# ============== INSTITUTIONAL HOLDINGS ENDPOINTS ==============

@app.route('/api/holdings', methods=['GET'])
def get_holdings():
    """Get recent institutional holding changes."""
    limit = request.args.get('limit', 20, type=int)
    ticker = request.args.get('ticker')
    fund = request.args.get('fund')
    
    session = Session()
    try:
        query = """
            SELECT fund_name, ticker, company_name, shares, value, quarter,
                   change_type, change_pct, portfolio_pct, filing_date
            FROM atlas_institutional_holdings
            WHERE change_type IN ('NEW', 'INCREASED', 'DECREASED', 'CLOSED')
        """
        params = {"limit": limit}
        
        if ticker:
            query += " AND ticker = :ticker"
            params['ticker'] = ticker.upper()
        
        if fund:
            query += " AND LOWER(fund_name) LIKE LOWER(:fund)"
            params['fund'] = f"%{fund}%"
        
        query += " ORDER BY filing_date DESC LIMIT :limit"
        
        result = session.execute(text(query), params)
        
        holdings = []
        for row in result:
            r = dict(row._mapping)
            holdings.append({
                "fund_name": r['fund_name'],
                "ticker": r['ticker'],
                "company_name": r.get('company_name', r['ticker']),
                "shares": r['shares'],
                "value": r['value'],
                "quarter": r['quarter'],
                "change_type": r['change_type'],
                "change_pct": r.get('change_pct'),
                "portfolio_pct": r.get('portfolio_pct'),
                "filing_date": r['filing_date'].isoformat() if r.get('filing_date') else None,
                "time_ago": time_ago(r.get('filing_date'))
            })
        
        return jsonify({"holdings": holdings})
    except Exception as e:
        return jsonify({"error": str(e), "holdings": []}), 500
    finally:
        session.close()


# ============== COMPANY DEEP DIVE ENDPOINTS ==============

@app.route('/api/company/<ticker>', methods=['GET'])
def company_deep_dive(ticker):
    """Get all data for a specific company."""
    ticker = ticker.upper()
    session = Session()
    try:
        # Company info
        company_result = session.execute(text("""
            SELECT id, ticker, name, sector, industry, market_cap
            FROM atlas_companies WHERE ticker = :ticker
        """), {"ticker": ticker})
        company = company_result.fetchone()
        
        if not company:
            return jsonify({"error": f"Company {ticker} not found", "empty": True}), 404
        
        company_data = dict(company._mapping)
        
        # All desk briefs for this company
        briefs_result = session.execute(text("""
            SELECT desk_name, analysis_date, signal_direction, confidence,
                   cio_briefing, bull_case, bear_case
            FROM atlas_desk_briefs
            WHERE company_id = :company_id
            ORDER BY analysis_date DESC
            LIMIT 20
        """), {"company_id": company_data['id']})
        
        briefs = [dict(row._mapping) for row in briefs_result]
        for b in briefs:
            if b.get('analysis_date'):
                b['analysis_date'] = b['analysis_date'].isoformat()
        
        # Institutional holdings
        holdings_result = session.execute(text("""
            SELECT fund_name, shares, value, quarter, change_type, change_pct
            FROM atlas_institutional_holdings
            WHERE ticker = :ticker
            ORDER BY quarter DESC, fund_name
            LIMIT 30
        """), {"ticker": ticker})
        
        holdings = [dict(row._mapping) for row in holdings_result]
        
        # Trades for this company
        trades_result = session.execute(text("""
            SELECT direction, shares, entry_price, entry_date, exit_price, exit_date,
                   realized_pnl, realized_pnl_pct, entry_rationale
            FROM atlas_trades
            WHERE ticker = :ticker
            ORDER BY entry_date DESC
        """), {"ticker": ticker})
        
        trades = [dict(row._mapping) for row in trades_result]
        for t in trades:
            if t.get('entry_date'):
                t['entry_date'] = t['entry_date'].isoformat()
            if t.get('exit_date'):
                t['exit_date'] = t['exit_date'].isoformat()
        
        # Latest thesis
        thesis_result = session.execute(text("""
            SELECT direction, confidence, bull_case, bear_case, catalyst,
                   invalidation_criteria, status, created_at
            FROM atlas_theses
            WHERE company_id = :company_id
            ORDER BY created_at DESC
            LIMIT 1
        """), {"company_id": company_data['id']})
        
        thesis = thesis_result.fetchone()
        thesis_data = dict(thesis._mapping) if thesis else None
        if thesis_data and thesis_data.get('created_at'):
            thesis_data['created_at'] = thesis_data['created_at'].isoformat()
        
        return jsonify({
            "company": company_data,
            "briefs": briefs,
            "holdings": holdings,
            "trades": trades,
            "thesis": thesis_data
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ============== CHAT ENDPOINT ==============

# Intent classification patterns
PATTERNS = {
    "institutional_flow": [
        r"(duquesne|berkshire|pershing|soros|bridgewater|renaissance|citadel|point72|tiger|coatue|lone pine|viking|third point|baupost|greenlight)",
        r"(13f|13-f|institutional|fund|hedge fund|holdings?|position)",
        r"(who owns|which funds|who bought|who sold|who increased|who decreased)",
    ],
    "sector_desk": [
        r"(semiconductor|biotech|pharma|financials?|energy|consumer|industrial|tech)",
        r"(desk|brief|analysis|view|outlook|thesis)",
        r"(what do you think|view on|outlook for|analysis of)",
    ],
    "cio": [
        r"(why did (we|you)|trade decision|rationale|bought|sold|position size)",
        r"(portfolio|allocation|weight)",
        r"(cio|chief investment)",
    ],
    "adversarial": [
        r"(risk|danger|concern|worry|crowding|correlation)",
        r"(biggest risk|main risk|top risk|portfolio risk)",
        r"(adversarial|devil.s advocate|bear case)",
    ],
}

def classify_intent(query: str) -> tuple:
    """Classify the query intent and extract entities."""
    query_lower = query.lower()
    entities = {}
    
    # Extract ticker
    ticker_match = re.search(r'\b([A-Z]{1,5})\b', query)
    if ticker_match:
        entities['ticker'] = ticker_match.group(1)
    
    # Extract fund name
    for fund in TRACKED_FUNDS:
        if fund.lower() in query_lower:
            entities['fund'] = fund
            break
    
    # Classify agent
    for agent, patterns in PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_lower):
                return agent, entities
    
    return "cio", entities


@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle natural language queries to agents."""
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    agent, entities = classify_intent(query)
    session = Session()
    
    try:
        if agent == "institutional_flow":
            # Query institutional holdings
            q = """
                SELECT fund_name, ticker, shares, value, quarter, change_type, change_pct, filing_date
                FROM atlas_institutional_holdings WHERE 1=1
            """
            params = {}
            
            if entities.get('fund'):
                q += " AND LOWER(fund_name) LIKE LOWER(:fund)"
                params['fund'] = f"%{entities['fund']}%"
            if entities.get('ticker'):
                q += " AND ticker = :ticker"
                params['ticker'] = entities['ticker']
            
            q += " ORDER BY filing_date DESC LIMIT 5"
            result = session.execute(text(q), params)
            rows = [dict(r._mapping) for r in result]
            
            if not rows:
                response = f"I don't have 13F data for this query yet. "
                if entities.get('fund'):
                    response += f"The institutional flow scan may not have processed {entities['fund']}'s filings."
                elif entities.get('ticker'):
                    response += f"No tracked funds have reported positions in {entities['ticker']}."
            else:
                parts = []
                for r in rows[:3]:
                    change = r.get('change_type', 'UNCHANGED')
                    change_pct = r.get('change_pct') or 0
                    action = {
                        'INCREASED': f"increased by {change_pct:.1f}%",
                        'DECREASED': f"decreased by {abs(change_pct):.1f}%",
                        'NEW': "initiated a new position",
                        'CLOSED': "closed their position"
                    }.get(change, "maintained their position")
                    
                    parts.append(f"**{r['fund_name']}** {action} in {r['ticker']} during {r['quarter']}. "
                                f"Holdings: {r['shares']:,.0f} shares (${r['value']:,.0f})")
                response = "\n\n".join(parts)
            
            agent_name = "Institutional Flow Agent"
            
        elif agent == "sector_desk":
            q = """
                SELECT b.desk_name, b.analysis_date, b.signal_direction, b.confidence,
                       b.cio_briefing, b.bull_case, b.bear_case, c.ticker
                FROM atlas_desk_briefs b
                JOIN atlas_companies c ON b.company_id = c.id
                WHERE 1=1
            """
            params = {}
            
            if entities.get('ticker'):
                q += " AND c.ticker = :ticker"
                params['ticker'] = entities['ticker']
            
            q += " ORDER BY b.analysis_date DESC LIMIT 3"
            result = session.execute(text(q), params)
            rows = [dict(r._mapping) for r in result]
            
            if not rows:
                response = f"I don't have desk briefs for this query yet. "
                if entities.get('ticker'):
                    response += f"The sector analysis hasn't run for {entities['ticker']}."
            else:
                parts = []
                for r in rows:
                    conf = (r.get('confidence') or 0) * 100
                    part = f"**{r['desk_name']}** ({r['analysis_date']}) — {r['signal_direction']} ({conf:.0f}%)\n"
                    if r.get('cio_briefing'):
                        part += f"{r['cio_briefing']}\n"
                    if r.get('bull_case'):
                        part += f"Bull: {r['bull_case']}\n"
                    if r.get('bear_case'):
                        part += f"Bear: {r['bear_case']}"
                    parts.append(part)
                response = "\n\n---\n\n".join(parts)
            
            agent_name = "Sector Desk"
            
        elif agent == "adversarial":
            # Portfolio risk analysis
            positions_q = """
                SELECT ticker, shares, entry_price FROM atlas_trades WHERE exit_date IS NULL
            """
            positions = [dict(r._mapping) for r in session.execute(text(positions_q))]
            
            crowding_q = """
                SELECT ticker, COUNT(DISTINCT fund_name) as fund_count
                FROM atlas_institutional_holdings
                WHERE quarter = (SELECT MAX(quarter) FROM atlas_institutional_holdings)
                GROUP BY ticker HAVING COUNT(DISTINCT fund_name) >= 8
                ORDER BY fund_count DESC LIMIT 5
            """
            crowding = [dict(r._mapping) for r in session.execute(text(crowding_q))]
            
            response = "**Portfolio Risk Assessment**\n\n"
            
            if positions:
                total = sum(p['shares'] * p['entry_price'] for p in positions)
                top = max(positions, key=lambda p: p['shares'] * p['entry_price'])
                top_pct = (top['shares'] * top['entry_price'] / total) * 100 if total else 0
                response += f"**Concentration:** Top position {top['ticker']} at {top_pct:.1f}% of portfolio\n\n"
            
            if crowding:
                response += "**Crowding Risk:** High institutional ownership detected:\n"
                for c in crowding:
                    response += f"- {c['ticker']}: {c['fund_count']} tracked funds\n"
                response += "\nHigh overlap increases correlation during market stress."
            else:
                response += "**Crowding Risk:** No significant crowding detected, or 13F data not yet loaded."
            
            agent_name = "Adversarial Agent"
            
        else:  # CIO
            q = """
                SELECT t.ticker, t.direction, t.entry_date, t.entry_price, t.shares,
                       t.entry_rationale, t.adversarial_challenge, th.bull_case
                FROM atlas_trades t
                LEFT JOIN atlas_theses th ON t.thesis_id = th.id
                WHERE 1=1
            """
            params = {}
            
            if entities.get('ticker'):
                q += " AND t.ticker = :ticker"
                params['ticker'] = entities['ticker']
            
            q += " ORDER BY t.entry_date DESC LIMIT 3"
            result = session.execute(text(q), params)
            rows = [dict(r._mapping) for r in result]
            
            if not rows:
                response = "I don't have trade records for this query. "
                if entities.get('ticker'):
                    response += f"We haven't made any trades in {entities['ticker']} yet."
            else:
                parts = []
                for r in rows:
                    part = f"**{r['direction']} {r['ticker']}** — {r['entry_date']}\n"
                    part += f"Entry: ${r['entry_price']:.2f} × {r['shares']:,} shares\n"
                    if r.get('entry_rationale'):
                        part += f"Rationale: {r['entry_rationale']}\n"
                    if r.get('adversarial_challenge'):
                        part += f"Adversarial: {r['adversarial_challenge']}"
                    parts.append(part)
                response = "\n\n---\n\n".join(parts)
            
            agent_name = "CIO Agent"
        
        return jsonify({
            "agent": agent_name,
            "response": response,
            "entities": entities
        })
        
    except Exception as e:
        return jsonify({
            "agent": "System",
            "response": f"Database error: {str(e)}. Tables may not exist yet — run the Alembic migration.",
            "error": str(e)
        }), 500
    finally:
        session.close()


# ============== MARKET DATA ENDPOINTS ==============

@app.route('/api/market/spy', methods=['GET'])
def spy_current():
    """Get current SPY price and daily change."""
    data = get_spy_current()
    return jsonify(data)


# ============== STATE FILE ENDPOINTS (JSON-based) ==============

import json
from pathlib import Path

# Find the data/state directory - works both locally (api/atlas_api.py) and on Azure (/opt/atlas/api.py)
_api_dir = Path(__file__).parent
STATE_DIR = _api_dir / "data" / "state"  # Azure: /opt/atlas/data/state
if not STATE_DIR.exists():
    STATE_DIR = _api_dir.parent / "data" / "state"  # Local: atlas/data/state


def load_state_file(filename: str) -> dict | list | None:
    """Load a JSON file from data/state/ directory."""
    filepath = STATE_DIR / filename
    if not filepath.exists():
        return None
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return None


@app.route('/api/atlas/portfolio', methods=['GET'])
def atlas_portfolio():
    """Get portfolio overview - positions, meta, and summary."""
    positions_data = load_state_file("positions.json") or {}
    positions = positions_data.get("positions", []) if isinstance(positions_data, dict) else positions_data
    meta = load_state_file("portfolio_meta.json") or {}
    pnl_history = load_state_file("pnl_history.json") or []

    # Get latest snapshot
    latest = pnl_history[-1] if pnl_history else {}

    # Separate position types
    active_trades = [p for p in positions if p.get('type') == 'ACTIVE_TRADE']
    autonomous = [p for p in positions if p.get('type') == 'AUTONOMOUS']
    cash_mgmt = [p for p in positions if p.get('type') == 'CASH_MANAGEMENT']

    # Calculate totals
    active_value = sum(p.get('value', 0) for p in active_trades)
    autonomous_value = sum(p.get('value', 0) for p in autonomous)
    cash_value = sum(p.get('value', 0) for p in cash_mgmt)
    total_value = latest.get('portfolio_value', meta.get('starting_value', 1000000))

    return jsonify({
        "meta": meta,
        "summary": {
            "total_value": round(total_value, 2),
            "active_value": round(active_value, 2),
            "autonomous_value": round(autonomous_value, 2),
            "cash_value": round(cash_value, 2),
            "total_pnl": round(latest.get('total_pnl', 0), 2),
            "active_pnl": round(latest.get('active_pnl', 0), 2),
            "autonomous_pnl": round(latest.get('autonomous_pnl', 0), 2),
            "position_count": len(positions),
            "active_count": len(active_trades),
            "autonomous_count": len(autonomous)
        },
        "positions": positions,
        "active_trades": active_trades,
        "autonomous": autonomous,
        "cash_management": cash_mgmt,
        "as_of": latest.get('date')
    })


@app.route('/api/atlas/positions', methods=['GET'])
def atlas_positions():
    """Get current positions with optional filtering."""
    positions_data = load_state_file("positions.json") or {}
    positions = positions_data.get("positions", []) if isinstance(positions_data, dict) else positions_data
    position_type = request.args.get('type')  # ACTIVE_TRADE, AUTONOMOUS, CASH_MANAGEMENT

    if position_type:
        positions = [p for p in positions if p.get('type') == position_type.upper()]

    return jsonify({"positions": positions, "count": len(positions)})


@app.route('/api/atlas/pnl', methods=['GET'])
def atlas_pnl():
    """Get P&L history over time."""
    pnl_history = load_state_file("pnl_history.json") or []
    meta = load_state_file("portfolio_meta.json") or {}

    # Latest metrics
    latest = pnl_history[-1] if pnl_history else {}

    return jsonify({
        "history": pnl_history,
        "latest": {
            "date": latest.get('date'),
            "total_pnl": round(latest.get('total_pnl', 0), 2),
            "active_pnl": round(latest.get('active_pnl', 0), 2),
            "autonomous_pnl": round(latest.get('autonomous_pnl', 0), 2),
            "portfolio_value": round(latest.get('portfolio_value', 0), 2),
            "position_count": latest.get('position_count', 0)
        },
        "inception_date": meta.get('inception_date'),
        "starting_value": meta.get('starting_value', 1000000)
    })


@app.route('/api/atlas/hurdle', methods=['GET'])
def atlas_hurdle():
    """Get hurdle rate tracking and alpha generation."""
    meta = load_state_file("portfolio_meta.json") or {}
    pnl_history = load_state_file("pnl_history.json") or []

    latest = pnl_history[-1] if pnl_history else {}
    starting_value = meta.get('starting_value', 1000000)
    current_value = latest.get('portfolio_value', starting_value)
    hurdle_rate_annual = meta.get('hurdle_rate_annual', 0.045)

    # Days since inception
    days_elapsed = latest.get('days_elapsed', 0)

    # Calculate hurdle return (pro-rated)
    hurdle_return = (hurdle_rate_annual / 365) * days_elapsed * starting_value
    actual_return = current_value - starting_value
    alpha = actual_return - hurdle_return

    # Calculate high water mark status
    hwm = meta.get('high_water_mark', starting_value)
    below_hwm = current_value < hwm
    drawdown_from_hwm = ((hwm - current_value) / hwm * 100) if hwm > 0 else 0

    return jsonify({
        "hurdle_rate_annual": hurdle_rate_annual,
        "hurdle_rate_daily": round(hurdle_rate_annual / 365 * 100, 4),
        "days_elapsed": days_elapsed,
        "hurdle_return_required": round(hurdle_return, 2),
        "actual_return": round(actual_return, 2),
        "alpha": round(alpha, 2),
        "alpha_pct": round((alpha / starting_value) * 100, 4) if starting_value > 0 else 0,
        "high_water_mark": hwm,
        "high_water_mark_date": meta.get('high_water_mark_date'),
        "below_hwm": below_hwm,
        "drawdown_from_hwm_pct": round(drawdown_from_hwm, 2),
        "performance_fee": meta.get('performance_fee', 0.2),
        "management_fee_annual": meta.get('management_fee_annual', 0.015)
    })


@app.route('/api/atlas/desks', methods=['GET'])
def atlas_desks():
    """Get all desk briefs summary."""
    desks = ['bond', 'currency', 'commodities', 'metals']
    desk_briefs = {}

    for desk in desks:
        filename = f"{desk}_desk_briefs.json"
        data = load_state_file(filename)
        if data:
            latest = data[-1] if isinstance(data, list) else data
            desk_briefs[desk] = {
                "signal": latest.get('signal'),
                "confidence": latest.get('confidence'),
                "brief": latest.get('brief_for_cio'),
                "analysis_date": latest.get('analysis_date'),
                "analyzed_at": latest.get('analyzed_at')
            }
        else:
            desk_briefs[desk] = None

    return jsonify({
        "desks": desk_briefs,
        "desk_count": len([d for d in desk_briefs.values() if d])
    })


@app.route('/api/atlas/desks/<desk_name>', methods=['GET'])
def atlas_desk_detail(desk_name):
    """Get detailed brief for a specific desk."""
    valid_desks = ['bond', 'currency', 'commodities', 'metals']

    if desk_name.lower() not in valid_desks:
        return jsonify({"error": f"Unknown desk: {desk_name}", "valid_desks": valid_desks}), 404

    filename = f"{desk_name.lower()}_desk_briefs.json"
    data = load_state_file(filename)

    if not data:
        return jsonify({"error": f"No data for {desk_name} desk", "desk": desk_name}), 404

    # Return all briefs (history) with latest first
    briefs = data if isinstance(data, list) else [data]
    briefs.sort(key=lambda x: x.get('analyzed_at', ''), reverse=True)

    return jsonify({
        "desk": desk_name,
        "briefs": briefs,
        "latest": briefs[0] if briefs else None,
        "count": len(briefs)
    })


@app.route('/api/atlas/macro', methods=['GET'])
def atlas_macro():
    """Get macro environment data from Druckenmiller agent context."""
    # Extract macro data from trades and positions
    trades = load_state_file("trades.json") or []
    bond_briefs = load_state_file("bond_desk_briefs.json") or []

    # Get macro signals from the latest trade
    latest_trade = trades[-1] if trades else {}
    signals = latest_trade.get('signals', {})

    # Get bond desk macro view
    latest_bond = bond_briefs[-1] if isinstance(bond_briefs, list) and bond_briefs else bond_briefs

    return jsonify({
        "liquidity_regime": signals.get('liquidity_regime', 'UNKNOWN'),
        "cycle_position": signals.get('cycle_position', 'UNKNOWN'),
        "fed_funds_rate": signals.get('fed_funds'),
        "m2_yoy": signals.get('m2_yoy'),
        "core_pce": signals.get('core_pce'),
        "gdp_growth": signals.get('gdp_growth'),
        "bond_desk": {
            "signal": latest_bond.get('signal') if latest_bond else None,
            "yield_curve": latest_bond.get('yield_curve', {}) if latest_bond else {},
            "fed_policy": latest_bond.get('fed_policy', {}) if latest_bond else {},
            "credit_spreads": latest_bond.get('credit_spreads', {}) if latest_bond else {},
            "inflation": latest_bond.get('inflation', {}) if latest_bond else {}
        },
        "data_sources": latest_trade.get('data_sources', []),
        "as_of": latest_trade.get('timestamp')
    })


@app.route('/api/atlas/autonomous', methods=['GET'])
def atlas_autonomous():
    """Get autonomous agent positions and decisions."""
    positions_data = load_state_file("positions.json") or {}
    positions = positions_data.get("positions", []) if isinstance(positions_data, dict) else positions_data
    pnl_history = load_state_file("pnl_history.json") or []

    # Filter to autonomous positions
    autonomous = [p for p in positions if p.get('type') == 'AUTONOMOUS']

    # Get latest P&L
    latest = pnl_history[-1] if pnl_history else {}

    # Sum autonomous P&L
    autonomous_pnl = sum(p.get('unrealized_pnl', 0) for p in autonomous)
    autonomous_value = sum(p.get('value', 0) for p in autonomous)

    return jsonify({
        "positions": autonomous,
        "count": len(autonomous),
        "total_value": round(autonomous_value, 2),
        "total_pnl": round(autonomous_pnl, 2),
        "pnl_pct": round((autonomous_pnl / autonomous_value * 100), 4) if autonomous_value > 0 else 0,
        "allocation_limit_pct": 15,  # 15% max for autonomous
        "current_allocation_pct": round((autonomous_value / 1000000 * 100), 2)
    })


@app.route('/api/atlas/microcap', methods=['GET'])
def atlas_microcap():
    """Get microcap desk analysis briefs."""
    briefs = load_state_file("microcap_briefs.json") or []

    if not isinstance(briefs, list):
        briefs = [briefs]

    # Sort by analysis date
    briefs.sort(key=lambda x: x.get('analyzed_at', ''), reverse=True)

    # Group by signal
    by_signal = {}
    for b in briefs:
        signal = b.get('signal', 'UNKNOWN')
        if signal not in by_signal:
            by_signal[signal] = []
        by_signal[signal].append({
            "ticker": b.get('ticker'),
            "company_name": b.get('company_name'),
            "market_cap": b.get('market_cap'),
            "confidence": b.get('confidence'),
            "brief": b.get('brief_for_cio'),
            "analyzed_at": b.get('analyzed_at')
        })

    return jsonify({
        "briefs": briefs,
        "count": len(briefs),
        "by_signal": by_signal,
        "latest": briefs[0] if briefs else None
    })


@app.route('/api/atlas/valuations', methods=['GET'])
def atlas_valuations():
    """Get fundamental valuation analyses."""
    valuations = load_state_file("fundamental_valuations.json") or []

    if not isinstance(valuations, list):
        valuations = [valuations]

    # Summary by verdict
    summary = {
        "UNDERVALUED": [],
        "FAIRLY VALUED": [],
        "OVERVALUED": []
    }

    for v in valuations:
        verdict = v.get('synthesis', {}).get('verdict', 'UNKNOWN')
        if verdict in summary:
            summary[verdict].append({
                "ticker": v.get('ticker'),
                "company_name": v.get('company_name'),
                "current_price": v.get('current_price'),
                "intrinsic_value": v.get('synthesis', {}).get('intrinsic_value_midpoint'),
                "upside_pct": v.get('synthesis', {}).get('upside_to_midpoint_pct'),
                "confidence": v.get('synthesis', {}).get('confidence'),
                "brief": v.get('brief_for_cio')
            })

    return jsonify({
        "valuations": valuations,
        "count": len(valuations),
        "summary": summary,
        "undervalued_count": len(summary.get('UNDERVALUED', [])),
        "latest_analysis": valuations[0].get('analysis_date') if valuations else None
    })


@app.route('/api/atlas/trades', methods=['GET'])
def atlas_trades_state():
    """Get trade history from state file."""
    trades = load_state_file("trades.json") or []

    if not isinstance(trades, list):
        trades = [trades]

    # Sort by timestamp
    trades.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    # Calculate stats
    open_trades = [t for t in trades if t.get('status') == 'OPEN']
    closed_trades = [t for t in trades if t.get('status') == 'CLOSED']

    total_pnl = sum(t.get('unrealized_pnl', 0) + t.get('realized_pnl', 0) for t in trades)

    return jsonify({
        "trades": trades,
        "count": len(trades),
        "open_count": len(open_trades),
        "closed_count": len(closed_trades),
        "total_pnl": round(total_pnl, 2),
        "by_agent": {
            agent: len([t for t in trades if t.get('agent') == agent])
            for agent in set(t.get('agent', 'Unknown') for t in trades)
        }
    })


@app.route('/api/atlas/agents', methods=['GET'])
def atlas_agents():
    """Get status of all ATLAS agents."""
    # Load state files to determine agent activity
    positions_data = load_state_file("positions.json") or {}
    positions = positions_data.get("positions", []) if isinstance(positions_data, dict) else positions_data
    trades = load_state_file("trades.json") or []
    bond = load_state_file("bond_desk_briefs.json") or []
    currency = load_state_file("currency_desk_briefs.json") or []
    commodities = load_state_file("commodities_desk_briefs.json") or []
    metals = load_state_file("metals_desk_briefs.json") or []
    microcap = load_state_file("microcap_briefs.json") or []
    valuations = load_state_file("fundamental_valuations.json") or []

    def get_latest_date(data):
        if not data:
            return None
        items = data if isinstance(data, list) else [data]
        if not items:
            return None
        return items[-1].get('analyzed_at') or items[-1].get('timestamp') or items[-1].get('analysis_date')

    # Helper to check agent_source (lowercase matching)
    def has_agent(agent_name):
        return any(p.get('agent_source', '').lower() == agent_name.lower() for p in positions)

    def count_agent_positions(agent_name):
        return len([p for p in positions if p.get('agent_source', '').lower() == agent_name.lower()])

    agents = {
        "druckenmiller": {
            "name": "Druckenmiller Macro Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('druckenmiller') else "IDLE",
            "last_activity": get_latest_date([t for t in trades if t.get('agent', '').lower() == 'druckenmiller']),
            "positions": count_agent_positions('druckenmiller'),
            "description": "Macro-focused agent using FRED data to trade rates, currencies, commodities"
        },
        "aschenbrenner": {
            "name": "Aschenbrenner AI Infra Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('aschenbrenner') else "IDLE",
            "last_activity": get_latest_date([t for t in trades if t.get('agent', '').lower() == 'aschenbrenner']),
            "positions": count_agent_positions('aschenbrenner'),
            "description": "Tracks Leopold Aschenbrenner's AI infrastructure thesis - power, data centers, chips"
        },
        "fundamental": {
            "name": "Fundamental Valuation Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('fundamental') else "IDLE",
            "last_activity": get_latest_date(valuations),
            "positions": count_agent_positions('fundamental'),
            "description": "DCF and comps-based valuation screening across S&P 500"
        },
        "baker": {
            "name": "Baker Deep Tech Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('baker') else "IDLE",
            "positions": count_agent_positions('baker'),
            "description": "Tracks Baker Brothers concentrated biotech bets from 13F filings"
        },
        "ackman": {
            "name": "Ackman Activist Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('ackman') else "IDLE",
            "positions": count_agent_positions('ackman'),
            "description": "Tracks Bill Ackman's Pershing Square concentrated positions"
        },
        "news": {
            "name": "News Sentiment Agent",
            "type": "DATA_AGENT",
            "status": "ACTIVE",
            "description": "Real-time news monitoring and sentiment analysis for portfolio tickers"
        },
        "autonomous": {
            "name": "Autonomous Execution Agent",
            "type": "AUTONOMOUS",
            "status": "ACTIVE" if any(p.get('type') == 'AUTONOMOUS' for p in positions) else "IDLE",
            "last_activity": get_latest_date([p for p in positions if p.get('type') == 'AUTONOMOUS']),
            "positions": len([p for p in positions if p.get('type') == 'AUTONOMOUS']),
            "description": "Executes high-conviction sector desk signals autonomously (15% max allocation)"
        },
        "bond_desk": {
            "name": "Bond Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if bond else "IDLE",
            "last_activity": get_latest_date(bond),
            "latest_signal": bond[-1].get('signal') if isinstance(bond, list) and bond else None,
            "description": "Analyzes rates, credit spreads, Fed policy, inflation expectations"
        },
        "currency_desk": {
            "name": "Currency Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if currency else "IDLE",
            "last_activity": get_latest_date(currency),
            "latest_signal": currency[-1].get('signal') if isinstance(currency, list) and currency else None,
            "description": "G10 and EM currency analysis using rate differentials and flows"
        },
        "commodities_desk": {
            "name": "Commodities Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if commodities else "IDLE",
            "last_activity": get_latest_date(commodities),
            "latest_signal": commodities[-1].get('signal') if isinstance(commodities, list) and commodities else None,
            "description": "Energy, agriculture, and soft commodities analysis"
        },
        "metals_desk": {
            "name": "Metals Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if metals else "IDLE",
            "last_activity": get_latest_date(metals),
            "latest_signal": metals[-1].get('signal') if isinstance(metals, list) and metals else None,
            "description": "Precious and industrial metals using real rates and dollar correlation"
        },
        "microcap_desk": {
            "name": "Microcap Analysis Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if microcap else "IDLE",
            "last_activity": get_latest_date(microcap),
            "briefs_count": len(microcap) if isinstance(microcap, list) else (1 if microcap else 0),
            "description": "Deep value screening in <$500M market cap space"
        },
        "fundamental_desk": {
            "name": "Fundamental Valuation Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if valuations else "IDLE",
            "last_activity": get_latest_date(valuations),
            "valuations_count": len(valuations) if isinstance(valuations, list) else (1 if valuations else 0),
            "description": "DCF, comps, SOTP valuations for position sizing"
        },
        "semiconductor_desk": {
            "name": "Semiconductor Desk",
            "type": "SECTOR_DESK",
            "status": "DATABASE",
            "description": "Semiconductor cycle, AI demand, inventory analysis"
        },
        "biotech_desk": {
            "name": "Biotech Desk",
            "type": "SECTOR_DESK",
            "status": "DATABASE",
            "description": "FDA catalysts, pipeline, M&A analysis"
        },
        "institutional_flow": {
            "name": "Institutional Flow Agent",
            "type": "DATA_AGENT",
            "status": "DATABASE",
            "description": "13F analysis, hedge fund positioning, crowding signals"
        },
        "risk_manager": {
            "name": "Risk Manager Agent",
            "type": "RISK",
            "status": "PENDING",
            "description": "Portfolio risk validation, correlation checks, position limits"
        },
        "adversarial": {
            "name": "Adversarial Agent",
            "type": "RISK",
            "status": "PENDING",
            "description": "Devil's advocate on every trade thesis"
        },
        "cio": {
            "name": "CIO Agent",
            "type": "DECISION",
            "status": "PENDING",
            "description": "Final portfolio allocation and trade decisions"
        }
    }

    return jsonify({
        "agents": agents,
        "counts": {
            "total": len(agents),
            "active": len([a for a in agents.values() if a.get('status') == 'ACTIVE']),
            "database": len([a for a in agents.values() if a.get('status') == 'DATABASE']),
            "pending": len([a for a in agents.values() if a.get('status') == 'PENDING']),
            "idle": len([a for a in agents.values() if a.get('status') == 'IDLE'])
        }
    })


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "ATLAS API"})


# ============== HTML DASHBOARD ROUTES ==============

@app.route('/atlas')
@app.route('/atlas/')
def dashboard_portfolio():
    """Portfolio dashboard - landing page."""
    positions_data = load_state_file("positions.json") or {}
    raw_positions = positions_data.get("positions", []) if isinstance(positions_data, dict) else positions_data
    portfolio_value = positions_data.get("portfolio_value", 1000000) if isinstance(positions_data, dict) else 1000000
    meta = load_state_file("portfolio_meta.json") or {}
    pnl_history = load_state_file("pnl_history.json") or []

    # Transform positions to include computed fields for the template
    positions = []
    total_pnl = 0
    for p in raw_positions:
        entry_price = p.get('entry_price', 0) or 0
        current_price = p.get('current_price', entry_price) or entry_price
        shares = p.get('shares', 0) or 0
        direction = p.get('direction', 'LONG')

        # Calculate value and P&L
        value = shares * current_price
        if direction == 'SHORT':
            unrealized_pnl = (entry_price - current_price) * shares
        else:
            unrealized_pnl = (current_price - entry_price) * shares
        unrealized_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        if direction == 'SHORT':
            unrealized_pnl_pct = -unrealized_pnl_pct

        total_pnl += unrealized_pnl

        # Determine position type based on agent_source
        agent_source = p.get('agent_source', 'manual')
        if agent_source == 'manual':
            pos_type = 'ACTIVE_TRADE'
        elif agent_source in ['autonomous', 'auto']:
            pos_type = 'AUTONOMOUS'
        else:
            pos_type = 'ACTIVE_TRADE'

        # BIL (cash equivalent) is always CASH_MANAGEMENT
        if p.get('ticker') == 'BIL':
            pos_type = 'CASH_MANAGEMENT'

        positions.append({
            'ticker': p.get('ticker'),
            'direction': direction,
            'shares': shares,
            'entry_price': entry_price,
            'current_price': current_price,
            'value': value,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pnl_pct': unrealized_pnl_pct,
            'allocation_pct': p.get('allocation_pct', 0),
            'thesis': p.get('thesis'),
            'agent': p.get('agent_source', 'manual'),
            'type': pos_type,
            'confidence': (p.get('conviction', 0) or 0) / 100,  # Convert 0-100 to 0-1
            'stop_loss': p.get('stop_loss'),
            'target': p.get('target'),
            'invalidation': p.get('invalidation'),
            'date_opened': p.get('date_opened'),
        })

    # Get latest snapshot
    latest = pnl_history[-1] if pnl_history else {}

    # Separate position types
    active_trades = [p for p in positions if p.get('type') == 'ACTIVE_TRADE']
    autonomous = [p for p in positions if p.get('type') == 'AUTONOMOUS']

    # Calculate summary
    summary = {
        "total_value": portfolio_value,
        "total_pnl": total_pnl,
        "active_pnl": sum(p['unrealized_pnl'] for p in active_trades),
        "autonomous_pnl": sum(p['unrealized_pnl'] for p in autonomous),
        "position_count": len(positions),
        "active_count": len(active_trades),
        "autonomous_count": len(autonomous),
    }

    # Calculate hurdle/alpha
    starting_value = meta.get('starting_value', 1000000)
    current_value = summary['total_value']
    hurdle_rate_annual = meta.get('hurdle_rate_annual', 0.045)
    days_elapsed = latest.get('days_elapsed', 1)
    hurdle_return = (hurdle_rate_annual / 365) * days_elapsed * starting_value
    actual_return = current_value - starting_value
    alpha = actual_return - hurdle_return

    hurdle = {
        "hurdle_return": hurdle_return,
        "actual_return": actual_return,
        "alpha": alpha,
    }

    return render_template(
        'portfolio.html',
        active_page='portfolio',
        positions=positions,
        meta=meta,
        pnl_history=pnl_history,
        summary=summary,
        hurdle=hurdle
    )


@app.route('/atlas/agents')
def dashboard_agents():
    """Agent swarm dashboard."""
    # Load state files to determine agent activity
    positions_data = load_state_file("positions.json") or {}
    positions = positions_data.get("positions", []) if isinstance(positions_data, dict) else positions_data
    trades = load_state_file("trades.json") or []
    bond = load_state_file("bond_desk_briefs.json") or []
    currency = load_state_file("currency_desk_briefs.json") or []
    commodities = load_state_file("commodities_desk_briefs.json") or []
    metals = load_state_file("metals_desk_briefs.json") or []
    microcap = load_state_file("microcap_briefs.json") or []
    valuations = load_state_file("fundamental_valuations.json") or []

    def get_latest_date(data):
        if not data:
            return None
        items = data if isinstance(data, list) else [data]
        if not items:
            return None
        return items[-1].get('analyzed_at') or items[-1].get('timestamp') or items[-1].get('analysis_date')

    # Helper to check agent_source (lowercase matching)
    def has_agent(agent_name):
        return any(p.get('agent_source', '').lower() == agent_name.lower() for p in positions)

    def count_agent_positions(agent_name):
        return len([p for p in positions if p.get('agent_source', '').lower() == agent_name.lower()])

    agents = {
        "druckenmiller": {
            "name": "Druckenmiller Macro Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('druckenmiller') else "IDLE",
            "last_activity": get_latest_date([t for t in trades if t.get('agent', '').lower() == 'druckenmiller']),
            "positions": count_agent_positions('druckenmiller'),
            "description": "Macro-focused agent using FRED data to trade rates, currencies, commodities"
        },
        "aschenbrenner": {
            "name": "Aschenbrenner AI Infra Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('aschenbrenner') else "IDLE",
            "last_activity": get_latest_date([t for t in trades if t.get('agent', '').lower() == 'aschenbrenner']),
            "positions": count_agent_positions('aschenbrenner'),
            "description": "Tracks Leopold Aschenbrenner's AI infrastructure thesis - power, data centers, chips"
        },
        "fundamental": {
            "name": "Fundamental Valuation Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('fundamental') else "IDLE",
            "last_activity": get_latest_date(valuations),
            "positions": count_agent_positions('fundamental'),
            "description": "DCF and comps-based valuation screening across S&P 500"
        },
        "baker": {
            "name": "Baker Deep Tech Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('baker') else "IDLE",
            "positions": count_agent_positions('baker'),
            "description": "Tracks Baker Brothers concentrated biotech bets from 13F filings"
        },
        "ackman": {
            "name": "Ackman Activist Agent",
            "type": "ACTIVE_TRADER",
            "status": "ACTIVE" if has_agent('ackman') else "IDLE",
            "positions": count_agent_positions('ackman'),
            "description": "Tracks Bill Ackman's Pershing Square concentrated positions"
        },
        "news": {
            "name": "News Sentiment Agent",
            "type": "DATA_AGENT",
            "status": "ACTIVE",
            "description": "Real-time news monitoring and sentiment analysis for portfolio tickers"
        },
        "autonomous": {
            "name": "Autonomous Execution Agent",
            "type": "AUTONOMOUS",
            "status": "ACTIVE" if any(p.get('type') == 'AUTONOMOUS' for p in positions) else "IDLE",
            "last_activity": get_latest_date([p for p in positions if p.get('type') == 'AUTONOMOUS']),
            "positions": len([p for p in positions if p.get('type') == 'AUTONOMOUS']),
            "description": "Executes high-conviction sector desk signals autonomously (15% max allocation)"
        },
        "bond_desk": {
            "name": "Bond Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if bond else "IDLE",
            "last_activity": get_latest_date(bond),
            "latest_signal": bond[-1].get('signal') if isinstance(bond, list) and bond else None,
            "description": "Analyzes rates, credit spreads, Fed policy, inflation expectations"
        },
        "currency_desk": {
            "name": "Currency Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if currency else "IDLE",
            "last_activity": get_latest_date(currency),
            "latest_signal": currency[-1].get('signal') if isinstance(currency, list) and currency else None,
            "description": "G10 and EM currency analysis using rate differentials and flows"
        },
        "commodities_desk": {
            "name": "Commodities Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if commodities else "IDLE",
            "last_activity": get_latest_date(commodities),
            "latest_signal": commodities[-1].get('signal') if isinstance(commodities, list) and commodities else None,
            "description": "Energy, agriculture, and soft commodities analysis"
        },
        "metals_desk": {
            "name": "Metals Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if metals else "IDLE",
            "last_activity": get_latest_date(metals),
            "latest_signal": metals[-1].get('signal') if isinstance(metals, list) and metals else None,
            "description": "Precious and industrial metals using real rates and dollar correlation"
        },
        "microcap_desk": {
            "name": "Microcap Analysis Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if microcap else "IDLE",
            "last_activity": get_latest_date(microcap),
            "briefs_count": len(microcap) if isinstance(microcap, list) else (1 if microcap else 0),
            "description": "Deep value screening in <$500M market cap space"
        },
        "fundamental_desk": {
            "name": "Fundamental Valuation Desk",
            "type": "SECTOR_DESK",
            "status": "ACTIVE" if valuations else "IDLE",
            "last_activity": get_latest_date(valuations),
            "valuations_count": len(valuations) if isinstance(valuations, list) else (1 if valuations else 0),
            "description": "DCF, comps, SOTP valuations for position sizing"
        },
        "semiconductor_desk": {
            "name": "Semiconductor Desk",
            "type": "SECTOR_DESK",
            "status": "DATABASE",
            "description": "Semiconductor cycle, AI demand, inventory analysis"
        },
        "biotech_desk": {
            "name": "Biotech Desk",
            "type": "SECTOR_DESK",
            "status": "DATABASE",
            "description": "FDA catalysts, pipeline, M&A analysis"
        },
        "institutional_flow": {
            "name": "Institutional Flow Agent",
            "type": "DATA_AGENT",
            "status": "DATABASE",
            "description": "13F analysis, hedge fund positioning, crowding signals"
        },
        "risk_manager": {
            "name": "Risk Manager Agent",
            "type": "RISK",
            "status": "PENDING",
            "description": "Portfolio risk validation, correlation checks, position limits"
        },
        "adversarial": {
            "name": "Adversarial Agent",
            "type": "RISK",
            "status": "PENDING",
            "description": "Devil's advocate on every trade thesis"
        },
        "cio": {
            "name": "CIO Agent",
            "type": "DECISION",
            "status": "PENDING",
            "description": "Final portfolio allocation and trade decisions"
        }
    }

    counts = {
        "total": len(agents),
        "active": len([a for a in agents.values() if a.get('status') == 'ACTIVE']),
        "database": len([a for a in agents.values() if a.get('status') == 'DATABASE']),
        "pending": len([a for a in agents.values() if a.get('status') == 'PENDING']),
        "idle": len([a for a in agents.values() if a.get('status') == 'IDLE'])
    }

    # Get desk briefs for display
    desks = {}
    for desk_name in ['bond', 'currency', 'commodities', 'metals']:
        data = load_state_file(f"{desk_name}_desk_briefs.json")
        if data:
            latest = data[-1] if isinstance(data, list) else data
            desks[desk_name] = {
                "signal": latest.get('signal'),
                "confidence": latest.get('confidence'),
                "brief": latest.get('brief_for_cio'),
                "analyzed_at": latest.get('analyzed_at'),
                "analysis_date": latest.get('analysis_date')
            }

    return render_template(
        'agents.html',
        active_page='agents',
        agents=agents,
        counts=counts,
        desks=desks
    )


@app.route('/atlas/decisions')
def dashboard_decisions():
    """CIO decisions / trades dashboard."""
    # Use positions.json as primary source - it has all current positions with entry_price
    positions_data = load_state_file("positions.json") or {}
    raw_positions = positions_data.get("positions", []) if isinstance(positions_data, dict) else positions_data
    trades_raw = load_state_file("trades.json") or []

    if not isinstance(raw_positions, list):
        raw_positions = [raw_positions] if raw_positions else []

    # Build trades list from positions with computed P&L fields
    trades = []
    for pos in raw_positions:
        entry_price = pos.get("entry_price", 0) or 0
        current_price = pos.get("current_price", entry_price) or entry_price
        shares = pos.get("shares", 0) or 0
        direction = pos.get("direction", "LONG")

        # Calculate value and P&L
        value = shares * current_price
        if direction == "SHORT":
            unrealized_pnl = (entry_price - current_price) * shares
        else:
            unrealized_pnl = (current_price - entry_price) * shares
        unrealized_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        if direction == "SHORT":
            unrealized_pnl_pct = -unrealized_pnl_pct

        trade = {
            "id": pos.get("id"),
            "ticker": pos.get("ticker"),
            "direction": direction,
            "shares": shares,
            "entry_price": entry_price,
            "entry_date": pos.get("date_opened"),  # Use date_opened from positions.json
            "current_price": current_price,
            "value": value,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "stop_loss": pos.get("stop_loss"),
            "target": pos.get("target"),
            "thesis": pos.get("thesis"),
            "invalidation": pos.get("invalidation"),
            "time_horizon": pos.get("time_horizon"),
            "confidence": (pos.get("conviction", 0) or 0) / 100,
            "agent": pos.get("agent_source", "manual"),
            "type": "ACTIVE_TRADE" if pos.get("ticker") != "BIL" else "CASH_MANAGEMENT",
            "status": pos.get("status", "OPEN"),
        }

        # Get signals from trades.json if available
        for t in trades_raw if isinstance(trades_raw, list) else [trades_raw]:
            if t.get("ticker") == pos.get("ticker"):
                trade["signals"] = t.get("signals")
                break

        trades.append(trade)

    # Sort by entry_date (most recent first), handle None values
    trades.sort(key=lambda x: x.get('entry_date') or '', reverse=True)

    # Summary
    trades_summary = {
        "count": len(trades),
        "open_count": len([t for t in trades if t.get('status') == 'OPEN']),
        "closed_count": len([t for t in trades if t.get('status') == 'CLOSED']),
        "total_pnl": sum(t.get('unrealized_pnl', 0) + t.get('realized_pnl', 0) for t in trades),
        "by_agent": {}
    }

    for t in trades:
        agent = t.get('agent', 'Unknown')
        trades_summary['by_agent'][agent] = trades_summary['by_agent'].get(agent, 0) + 1

    return render_template(
        'decisions.html',
        active_page='decisions',
        trades=trades,
        trades_summary=trades_summary
    )


@app.route('/atlas/chat')
def dashboard_chat():
    """Chat UI dashboard."""
    return render_template(
        'chat.html',
        active_page='chat'
    )


@app.route('/atlas/company/<ticker>')
def dashboard_company(ticker):
    """Company deep dive page."""
    ticker = ticker.upper()

    # Load positions to find if we have this company
    positions_data = load_state_file("positions.json") or {}
    positions = positions_data.get("positions", []) if isinstance(positions_data, dict) else positions_data
    position = next((p for p in positions if p.get('ticker') == ticker), None)

    # Load any desk briefs mentioning this ticker
    briefs = []
    for desk_name in ['semiconductor', 'biotech', 'bond', 'currency', 'commodities', 'metals', 'microcap', 'fundamental']:
        filename = f"{desk_name}_desk_briefs.json" if desk_name != 'fundamental' else "fundamental_valuations.json"
        if desk_name == 'microcap':
            filename = "microcap_briefs.json"

        data = load_state_file(filename)
        if data:
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get('ticker') == ticker:
                    briefs.append({
                        "desk_name": desk_name.title() + " Desk",
                        "analysis_date": item.get('analysis_date') or item.get('analyzed_at', '')[:10] if item.get('analyzed_at') else '',
                        "signal_direction": item.get('signal'),
                        "confidence": item.get('confidence'),
                        "cio_briefing": item.get('brief_for_cio'),
                        "bull_case": item.get('bull_case'),
                        "bear_case": item.get('bear_case')
                    })

    # Company info
    company = {
        "ticker": ticker,
        "name": position.get('company_name') if position else ticker,
        "sector": None,
        "industry": None,
        "market_cap": None
    }

    # Try to get more info from yfinance (optional)
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info
        company["name"] = info.get('longName') or info.get('shortName') or ticker
        company["sector"] = info.get('sector')
        company["industry"] = info.get('industry')
        company["market_cap"] = info.get('marketCap')
    except:
        pass

    return render_template(
        'company.html',
        active_page='company',
        company=company,
        position=position,
        briefs=briefs,
        holdings=[],  # Could populate from DB
        trades=[],    # Could populate from DB
        thesis=None   # Could populate from DB
    )


# ============== BRIEFING ENDPOINTS ==============

# Find the briefings directory
BRIEFINGS_DIR = STATE_DIR / "briefings"
if not BRIEFINGS_DIR.exists():
    BRIEFINGS_DIR = _api_dir.parent / "data" / "state" / "briefings"


@app.route('/api/atlas/briefing/latest')
def get_latest_briefing():
    """Return the most recent briefing JSON."""
    try:
        if not BRIEFINGS_DIR.exists():
            return jsonify({"error": "No briefings directory"}), 404

        files = sorted([f for f in BRIEFINGS_DIR.iterdir() if f.suffix == '.json'], reverse=True)
        if not files:
            return jsonify({"error": "No briefings yet"}), 404

        latest = files[0]
        with open(latest) as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/atlas/briefing/<date_str>')
def get_briefing_by_date(date_str):
    """Return briefing for specific date."""
    try:
        path = BRIEFINGS_DIR / f"{date_str}.json"
        if path.exists():
            with open(path) as f:
                return jsonify(json.load(f))
        return jsonify({"error": f"No briefing for {date_str}"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/atlas/briefing/list')
def list_briefings():
    """List all available briefing dates."""
    try:
        if not BRIEFINGS_DIR.exists():
            return jsonify({"dates": []})

        files = sorted([f for f in BRIEFINGS_DIR.iterdir() if f.suffix == '.json'], reverse=True)
        dates = [f.stem for f in files]
        return jsonify({"dates": dates})
    except Exception as e:
        return jsonify({"error": str(e), "dates": []}), 500


@app.route('/api/atlas/briefing/<date_str>/pdf')
def download_briefing_pdf(date_str):
    """Generate and download PDF for a specific briefing."""
    from flask import send_file
    try:
        path = BRIEFINGS_DIR / f"{date_str}.json"
        if not path.exists():
            return jsonify({"error": f"No briefing for {date_str}"}), 404

        with open(path) as f:
            data = json.load(f)

        # Generate PDF
        try:
            from agents.daily_briefing import generate_briefing_pdf
            pdf_path = generate_briefing_pdf(data)
            if pdf_path:
                return send_file(
                    pdf_path,
                    as_attachment=True,
                    download_name=f'ATLAS_Briefing_{date_str}.pdf',
                    mimetype='application/pdf'
                )
            return jsonify({"error": "PDF generation failed"}), 500
        except ImportError:
            return jsonify({"error": "reportlab not installed for PDF generation"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/atlas/briefing/generate', methods=['POST'])
def generate_briefing():
    """Trigger briefing generation (admin endpoint)."""
    try:
        from agents.daily_briefing import run_briefing

        data = request.json or {}
        send_email = data.get('send', False)
        is_eod = data.get('eod', False)

        briefing = run_briefing(send=send_email, is_eod=is_eod)

        if briefing:
            return jsonify({
                "success": True,
                "date": briefing.get("date"),
                "positions_count": len(briefing.get("positions", [])),
                "news_count": len(briefing.get("overnight_news", [])),
            })
        return jsonify({"error": "Briefing generation failed"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============== BRIEFING DASHBOARD ROUTE ==============

@app.route('/atlas/briefing')
def dashboard_briefing():
    """Briefing dashboard page."""
    # Load latest briefing
    briefing = None
    briefing_dates = []

    try:
        if BRIEFINGS_DIR.exists():
            files = sorted([f for f in BRIEFINGS_DIR.iterdir() if f.suffix == '.json'], reverse=True)
            briefing_dates = [f.stem for f in files[:30]]  # Last 30 briefings

            if files:
                with open(files[0]) as f:
                    briefing = json.load(f)
    except Exception as e:
        print(f"Error loading briefing: {e}")

    return render_template(
        'briefing.html',
        active_page='briefing',
        briefing=briefing,
        briefing_dates=briefing_dates
    )


# Redirect root to atlas dashboard
@app.route('/')
def root_redirect():
    from flask import redirect
    return redirect('/atlas')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8003, debug=True)
