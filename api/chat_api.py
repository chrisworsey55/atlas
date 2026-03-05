"""
ATLAS Chat API
Routes natural language queries to the appropriate agent and database queries.
"""
import re
import os
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

app = Flask(__name__)
CORS(app)

# Database connection
DATABASE_URL = os.getenv("ATLAS_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/valis")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

# Agent routing patterns
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

# Tracked funds for 13F
TRACKED_FUNDS = [
    "Berkshire Hathaway", "Pershing Square", "Duquesne", "Appaloosa", 
    "Soros Fund Management", "Bridgewater", "Renaissance Technologies",
    "Citadel", "Point72", "Tiger Global", "Coatue", "Lone Pine",
    "Viking Global", "Third Point", "Baupost", "Greenlight Capital"
]

def classify_intent(query: str) -> tuple[str, dict]:
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
    
    # Default to CIO for general questions
    return "cio", entities


def query_institutional_holdings(session, fund: str = None, ticker: str = None):
    """Query 13F institutional holdings."""
    query = """
        SELECT fund_name, ticker, company_name, shares, value, quarter, 
               change_type, change_pct, portfolio_pct, filing_date
        FROM atlas_institutional_holdings
        WHERE 1=1
    """
    params = {}
    
    if fund:
        query += " AND LOWER(fund_name) LIKE LOWER(:fund)"
        params['fund'] = f"%{fund}%"
    
    if ticker:
        query += " AND ticker = :ticker"
        params['ticker'] = ticker.upper()
    
    query += " ORDER BY filing_date DESC LIMIT 10"
    
    result = session.execute(text(query), params)
    return [dict(row._mapping) for row in result]


def query_desk_briefs(session, ticker: str = None, desk: str = None):
    """Query sector desk briefs."""
    query = """
        SELECT b.desk_name, b.analysis_date, b.signal_direction, b.confidence,
               b.cio_briefing, b.bull_case, b.bear_case, c.ticker, c.name
        FROM atlas_desk_briefs b
        JOIN atlas_companies c ON b.company_id = c.id
        WHERE 1=1
    """
    params = {}
    
    if ticker:
        query += " AND c.ticker = :ticker"
        params['ticker'] = ticker.upper()
    
    if desk:
        query += " AND LOWER(b.desk_name) LIKE LOWER(:desk)"
        params['desk'] = f"%{desk}%"
    
    query += " ORDER BY b.analysis_date DESC LIMIT 5"
    
    result = session.execute(text(query), params)
    return [dict(row._mapping) for row in result]


def query_trades(session, ticker: str = None):
    """Query CIO trade decisions."""
    query = """
        SELECT t.ticker, t.direction, t.entry_date, t.entry_price, t.shares,
               t.exit_date, t.exit_price, t.realized_pnl, t.realized_pnl_pct,
               t.entry_rationale, t.exit_rationale, t.adversarial_challenge,
               th.bull_case, th.bear_case, th.invalidation_criteria
        FROM atlas_trades t
        LEFT JOIN atlas_theses th ON t.thesis_id = th.id
        WHERE 1=1
    """
    params = {}
    
    if ticker:
        query += " AND t.ticker = :ticker"
        params['ticker'] = ticker.upper()
    
    query += " ORDER BY t.entry_date DESC LIMIT 10"
    
    result = session.execute(text(query), params)
    return [dict(row._mapping) for row in result]


def query_portfolio_risk(session):
    """Query current portfolio risk metrics."""
    # Get current positions
    positions_query = """
        SELECT ticker, shares, entry_price, 
               (shares * entry_price) as position_value
        FROM atlas_trades
        WHERE exit_date IS NULL
        ORDER BY position_value DESC
    """
    result = session.execute(text(positions_query))
    positions = [dict(row._mapping) for row in result]
    
    # Get crowding data
    crowding_query = """
        SELECT ticker, COUNT(DISTINCT fund_name) as fund_count
        FROM atlas_institutional_holdings
        WHERE quarter = (SELECT MAX(quarter) FROM atlas_institutional_holdings)
        GROUP BY ticker
        ORDER BY fund_count DESC
        LIMIT 10
    """
    crowding = session.execute(text(crowding_query))
    crowding_data = [dict(row._mapping) for row in crowding]
    
    return {"positions": positions, "crowding": crowding_data}


def format_institutional_response(data: list, fund: str = None, ticker: str = None) -> str:
    """Format institutional holdings data into a natural response."""
    if not data:
        if fund and ticker:
            return f"I don't have 13F data for {fund} holdings in {ticker} yet. The institutional flow scan may not have run, or they may not hold this position."
        elif fund:
            return f"I don't have 13F data for {fund} yet. The institutional flow scan hasn't completed for this fund."
        elif ticker:
            return f"I don't have institutional holdings data for {ticker} yet."
        return "I don't have institutional holdings data for this query."
    
    responses = []
    for row in data[:3]:  # Limit to top 3
        fund_name = row.get('fund_name', 'Unknown')
        ticker = row.get('ticker', 'N/A')
        shares = row.get('shares', 0)
        value = row.get('value', 0)
        quarter = row.get('quarter', 'N/A')
        change = row.get('change_type', 'UNCHANGED')
        change_pct = row.get('change_pct', 0) or 0
        
        if change == 'INCREASED':
            action = f"increased their position by {change_pct:.1f}%"
        elif change == 'DECREASED':
            action = f"decreased their position by {abs(change_pct):.1f}%"
        elif change == 'NEW':
            action = "initiated a new position"
        elif change == 'CLOSED':
            action = "closed their position"
        else:
            action = "maintained their position"
        
        responses.append(
            f"**{fund_name}** {action} in {ticker} during {quarter}. "
            f"Current holdings: {shares:,.0f} shares valued at ${value:,.0f}."
        )
    
    return "\n\n".join(responses)


def format_desk_brief_response(data: list, ticker: str = None) -> str:
    """Format desk brief data into a natural response."""
    if not data:
        if ticker:
            return f"I don't have desk briefs for {ticker} yet. The sector analysis hasn't run for this company."
        return "I don't have desk briefs for this query."
    
    responses = []
    for row in data[:2]:  # Limit to top 2
        desk = row.get('desk_name', 'Unknown')
        date = row.get('analysis_date', 'N/A')
        signal = row.get('signal_direction', 'NEUTRAL')
        confidence = row.get('confidence', 0) or 0
        briefing = row.get('cio_briefing', '')
        bull = row.get('bull_case', '')
        bear = row.get('bear_case', '')
        
        response = f"**{desk} Desk** ({date}) — {signal} ({confidence*100:.0f}% confidence)\n\n"
        if briefing:
            response += f"{briefing}\n\n"
        if bull:
            response += f"**Bull case:** {bull}\n"
        if bear:
            response += f"**Bear case:** {bear}"
        
        responses.append(response)
    
    return "\n\n---\n\n".join(responses)


def format_trade_response(data: list, ticker: str = None) -> str:
    """Format trade decisions into a natural response."""
    if not data:
        if ticker:
            return f"We haven't made any trades in {ticker} yet."
        return "I don't have trade data for this query."
    
    responses = []
    for row in data[:2]:
        ticker = row.get('ticker', 'N/A')
        direction = row.get('direction', 'LONG')
        entry_date = row.get('entry_date', 'N/A')
        entry_price = row.get('entry_price', 0)
        shares = row.get('shares', 0)
        rationale = row.get('entry_rationale', 'No rationale recorded')
        adversarial = row.get('adversarial_challenge', '')
        
        response = f"**{direction} {ticker}** — Entered {entry_date} at ${entry_price:.2f} ({shares:,.0f} shares)\n\n"
        response += f"**Rationale:** {rationale}\n"
        if adversarial:
            response += f"\n**Adversarial challenge:** {adversarial}"
        
        # Add P&L if closed
        if row.get('exit_date'):
            pnl = row.get('realized_pnl', 0) or 0
            pnl_pct = row.get('realized_pnl_pct', 0) or 0
            response += f"\n\n**Outcome:** Closed at ${row['exit_price']:.2f} — P&L: ${pnl:,.0f} ({pnl_pct:+.1f}%)"
        
        responses.append(response)
    
    return "\n\n---\n\n".join(responses)


def format_risk_response(data: dict) -> str:
    """Format risk assessment into a natural response."""
    positions = data.get('positions', [])
    crowding = data.get('crowding', [])
    
    response = "**Portfolio Risk Assessment**\n\n"
    
    # Position concentration
    if positions:
        total_value = sum(p.get('position_value', 0) for p in positions)
        top_position = positions[0] if positions else None
        if top_position and total_value > 0:
            top_pct = (top_position['position_value'] / total_value) * 100
            response += f"**Top position:** {top_position['ticker']} at {top_pct:.1f}% of portfolio\n\n"
    
    # Crowding risk
    if crowding:
        high_crowding = [c for c in crowding if c.get('fund_count', 0) >= 10]
        if high_crowding:
            response += "**Crowding risk:** The following positions are held by 10+ tracked funds:\n"
            for c in high_crowding[:5]:
                response += f"- {c['ticker']}: {c['fund_count']} funds\n"
            response += "\nHigh institutional ownership increases correlation risk during market stress."
        else:
            response += "**Crowding risk:** No significant crowding detected in current positions."
    else:
        response += "I don't have current crowding data. The 13F scan may not have completed."
    
    return response


@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat queries by routing to appropriate agent/database."""
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    # Classify intent
    agent, entities = classify_intent(query)
    
    session = Session()
    try:
        if agent == "institutional_flow":
            results = query_institutional_holdings(
                session, 
                fund=entities.get('fund'),
                ticker=entities.get('ticker')
            )
            response = format_institutional_response(
                results,
                fund=entities.get('fund'),
                ticker=entities.get('ticker')
            )
            agent_name = "Institutional Flow Agent"
            
        elif agent == "sector_desk":
            # Try to identify which desk
            desk = None
            query_lower = query.lower()
            for d in ['semiconductor', 'biotech', 'financials', 'energy', 'consumer', 'industrials']:
                if d in query_lower:
                    desk = d
                    break
            
            results = query_desk_briefs(
                session,
                ticker=entities.get('ticker'),
                desk=desk
            )
            response = format_desk_brief_response(results, entities.get('ticker'))
            agent_name = f"{desk.title() if desk else 'Sector'} Desk"
            
        elif agent == "adversarial":
            results = query_portfolio_risk(session)
            response = format_risk_response(results)
            agent_name = "Adversarial Agent"
            
        else:  # CIO
            results = query_trades(session, ticker=entities.get('ticker'))
            response = format_trade_response(results, entities.get('ticker'))
            agent_name = "CIO Agent"
        
        return jsonify({
            "agent": agent_name,
            "response": response,
            "entities": entities,
            "query": query
        })
        
    except Exception as e:
        return jsonify({
            "agent": "System",
            "response": f"Error querying database: {str(e)}. The database may not be set up or the tables may not exist yet.",
            "error": str(e)
        }), 500
    finally:
        session.close()


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "ATLAS Chat API"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8003, debug=True)
