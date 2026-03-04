"""
ATLAS Web API
FastAPI server providing chat endpoints for all agents.
"""
import json
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import all agents
from agents.aschenbrenner_agent import AschenbrennerAgent
from agents.baker_agent import BakerAgent
from agents.ackman_agent import AckmanAgent
from agents.news_agent import NewsAgent
from agents.cio_agent import CIOAgent
from agents.adversarial_agent import AdversarialAgent
from agents.institutional_flow_agent import InstitutionalFlowAgent
from agents.sector_desk import (
    SemiconductorDesk,
    BiotechDesk,
    FinancialsDesk,
    EnergyDesk,
    ConsumerDesk,
    IndustrialsDesk,
)

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="ATLAS API",
    description="AI Trading, Logic & Analysis System - Agent Chat API",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ChatRequest(BaseModel):
    message: str
    agent: str = "cio"
    include_context: bool = True


class ChatResponse(BaseModel):
    agent: str
    response: dict
    timestamp: str


class AnalyzeRequest(BaseModel):
    ticker: str
    agent: str = "semiconductor"


# Agent registry
AGENT_REGISTRY = {
    # Superinvestor agents
    "cio": "CIO Unified",
    "druckenmiller": "Druckenmiller Macro",
    "aschenbrenner": "Aschenbrenner AI Infra",
    "baker": "Baker Deep Tech",
    "ackman": "Ackman Quality",
    # Specialist agents
    "news": "News & Geopolitical",
    "adversarial": "Adversarial Risk",
    "flow": "Institutional Flow",
    "fundamental": "Fundamental Valuation",
    # Sector desks
    "semiconductor": "Semiconductor Desk",
    "biotech": "Biotech Desk",
    "financials": "Financials Desk",
    "energy": "Energy Desk",
    "consumer": "Consumer Desk",
    "industrials": "Industrials Desk",
    "bond": "Bond Fixed Income",
}


def get_agent_instance(agent_name: str):
    """Get an agent instance by name."""
    agent_map = {
        "cio": CIOAgent,
        "aschenbrenner": AschenbrennerAgent,
        "baker": BakerAgent,
        "ackman": AckmanAgent,
        "news": NewsAgent,
        "adversarial": AdversarialAgent,
        "flow": InstitutionalFlowAgent,
        "semiconductor": SemiconductorDesk,
        "biotech": BiotechDesk,
        "financials": FinancialsDesk,
        "energy": EnergyDesk,
        "consumer": ConsumerDesk,
        "industrials": IndustrialsDesk,
    }

    if agent_name not in agent_map:
        return None

    return agent_map[agent_name]()


def load_portfolio() -> dict:
    """Load current portfolio state."""
    try:
        portfolio_path = Path(__file__).parent.parent / "data" / "state" / "positions.json"
        with open(portfolio_path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load portfolio: {e}")
        return {}


def load_news_context() -> str:
    """Load current news context."""
    try:
        news_path = Path(__file__).parent.parent / "data" / "state" / "news_briefs.json"
        with open(news_path) as f:
            news = json.load(f)
            return news.get("24h_summary", "")
    except Exception as e:
        logger.warning(f"Could not load news: {e}")
        return ""


def load_fundamental_data() -> dict:
    """Load fundamental valuations."""
    try:
        fund_path = Path(__file__).parent.parent / "data" / "state" / "fundamental_valuations.json"
        with open(fund_path) as f:
            data = json.load(f)
            return data.get("valuations", {})
    except Exception as e:
        logger.warning(f"Could not load fundamental data: {e}")
        return {}


def load_sp500_screen() -> dict:
    """Load S&P 500 valuation screen."""
    try:
        sp500_path = Path(__file__).parent.parent / "data" / "state" / "sp500_valuations.json"
        with open(sp500_path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load S&P 500 data: {e}")
        return {}


@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "name": "ATLAS API",
        "version": "1.0.0",
        "agents": list(AGENT_REGISTRY.keys()),
        "endpoints": ["/api/atlas/chat", "/api/atlas/agents", "/api/atlas/portfolio"],
    }


@app.get("/api/atlas/agents")
async def list_agents():
    """List all available agents."""
    return {
        "agents": AGENT_REGISTRY,
        "categories": {
            "superinvestors": ["cio", "druckenmiller", "aschenbrenner", "baker", "ackman"],
            "specialists": ["news", "adversarial", "flow", "fundamental"],
            "sectors": ["semiconductor", "biotech", "financials", "energy", "consumer", "industrials", "bond"],
        }
    }


@app.get("/api/atlas/portfolio")
async def get_portfolio():
    """Get current portfolio state."""
    return load_portfolio()


@app.get("/api/atlas/news")
async def get_news():
    """Get current news brief."""
    try:
        news_path = Path(__file__).parent.parent / "data" / "state" / "news_briefs.json"
        with open(news_path) as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/atlas/chat")
async def chat(request: ChatRequest):
    """
    Chat with any ATLAS agent.

    Supported agents:
    - cio: CIO Unified (synthesizes all perspectives)
    - druckenmiller: Druckenmiller Macro (via CIO with macro focus)
    - aschenbrenner: Aschenbrenner AI Infrastructure
    - baker: Gavin Baker Deep Tech
    - ackman: Bill Ackman Quality Compounder
    - news: News & Geopolitical Intelligence
    - adversarial: Adversarial Risk Review
    - flow: Institutional Flow Analysis
    - fundamental: Fundamental Valuation
    - semiconductor: Semiconductor Desk
    - biotech: Biotech Desk
    - financials: Financials Desk
    - energy: Energy Desk
    - consumer: Consumer Desk
    - industrials: Industrials Desk
    """
    agent_name = request.agent.lower()

    if agent_name not in AGENT_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent: {agent_name}. Available: {list(AGENT_REGISTRY.keys())}"
        )

    logger.info(f"Chat request to {agent_name}: {request.message[:50]}...")

    try:
        # Handle special agents
        if agent_name == "cio":
            response = await chat_cio(request.message, request.include_context)
        elif agent_name == "druckenmiller":
            response = await chat_druckenmiller(request.message, request.include_context)
        elif agent_name == "fundamental":
            response = await chat_fundamental(request.message, request.include_context)
        elif agent_name == "flow":
            response = await chat_flow(request.message)
        elif agent_name in ["semiconductor", "biotech", "financials", "energy", "consumer", "industrials"]:
            response = await chat_sector_desk(agent_name, request.message)
        else:
            # Standard agents with chat() method
            agent = get_agent_instance(agent_name)
            if agent is None:
                raise HTTPException(status_code=500, detail=f"Failed to instantiate agent: {agent_name}")

            response = agent.chat(request.message, include_context=request.include_context)

        if response is None:
            raise HTTPException(status_code=500, detail="Agent returned no response")

        return ChatResponse(
            agent=agent_name,
            response=response,
            timestamp=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def chat_cio(message: str, include_context: bool = True) -> dict:
    """Handle CIO chat with synthesis of multiple perspectives."""
    import anthropic
    from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL_PREMIUM
    from agents.prompts.cio_agent import SYSTEM_PROMPT

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Load all context
    portfolio = load_portfolio() if include_context else {}
    news_context = load_news_context() if include_context else ""
    fundamental_data = load_fundamental_data() if include_context else {}

    # Build comprehensive prompt
    prompt_parts = [
        f"## DATE: {datetime.now().strftime('%Y-%m-%d')}",
        "",
    ]

    if portfolio:
        prompt_parts.extend([
            "## CURRENT ATLAS PORTFOLIO",
            f"Total Value: ${portfolio.get('total_value', 0):,.0f}",
            f"Cash: ${portfolio.get('cash', 0):,.0f} ({portfolio.get('cash_pct', 0):.1f}%)",
            "",
        ])
        if portfolio.get('positions'):
            prompt_parts.append("### Positions:")
            for pos in portfolio['positions']:
                pnl = pos.get('pnl_pct', 0)
                pnl_str = f"+{pnl:.1f}%" if pnl >= 0 else f"{pnl:.1f}%"
                prompt_parts.append(
                    f"- {pos['ticker']} ({pos['direction']}): {pos.get('allocation_pct', pos.get('size_pct', 0)):.1f}% | "
                    f"Entry ${pos['entry_price']:.2f} | Current ${pos['current_price']:.2f} | "
                    f"P&L {pnl_str} | {pos.get('thesis', '')}"
                )
            prompt_parts.append("")

    if news_context:
        prompt_parts.extend([
            "## NEWS CONTEXT",
            news_context,
            "",
        ])

    prompt_parts.extend([
        "## SUPERINVESTOR SYNTHESIS",
        "You must consider these perspectives:",
        "- DRUCKENMILLER: Top-down macro, concentrated bets, 1-6 month horizon",
        "- ASCHENBRENNER: AI infrastructure bottleneck thesis, extreme concentration",
        "- BAKER: Deep tech fundamental, product-level analysis",
        "- ACKMAN: Quality compounders, 3-5 year horizon, activist mindset",
        "",
        "## USER QUESTION",
        message,
        "",
        "Synthesize all perspectives and provide CIO-level guidance.",
    ])

    user_prompt = "\n".join(prompt_parts)

    response = client.messages.create(
        model=CLAUDE_MODEL_PREMIUM,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw_response = response.content[0].text

    try:
        if "```json" in raw_response:
            json_str = raw_response.split("```json")[1].split("```")[0]
        elif "```" in raw_response:
            json_str = raw_response.split("```")[1].split("```")[0]
        else:
            json_str = raw_response

        result = json.loads(json_str.strip())
        result["agent"] = "cio"
        result["generated_at"] = datetime.utcnow().isoformat()
        return result

    except json.JSONDecodeError:
        return {
            "agent": "cio",
            "raw_response": raw_response,
            "generated_at": datetime.utcnow().isoformat(),
        }


async def chat_druckenmiller(message: str, include_context: bool = True) -> dict:
    """Handle Druckenmiller-style macro chat."""
    import anthropic
    from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL

    DRUCKENMILLER_SYSTEM = """You are Stanley Druckenmiller, one of the greatest macro traders ever. You ran Duquesne Capital to 30%+ annualized returns over 30 years with no down years.

Your style:
- Top-down macro analysis first
- Concentrated positions when conviction is high
- Use leverage on best ideas
- Cut losses fast, let winners run
- Think in 1-6 month horizons
- Focus on liquidity cycles, credit conditions, and currency moves

Key phrases:
- "It's all about finding the fat pitch and swinging hard"
- "Earnings don't move the market, it's the Fed"
- "I don't play macro to be right 60% of the time, I play to make 4-5x my money when I'm right"
- "The best traders can change their minds instantly when new information arrives"

Always tie your analysis back to the macro environment. What's the Fed doing? What's happening in credit markets? Where is liquidity flowing?
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    portfolio = load_portfolio() if include_context else {}
    news_context = load_news_context() if include_context else ""

    prompt_parts = [f"## DATE: {datetime.now().strftime('%Y-%m-%d')}", ""]

    if portfolio:
        prompt_parts.extend([
            "## CURRENT PORTFOLIO",
            f"Total Value: ${portfolio.get('total_value', 0):,.0f}",
            f"Cash: ${portfolio.get('cash', 0):,.0f}",
            "",
        ])
        if portfolio.get('positions'):
            for pos in portfolio['positions']:
                pnl = pos.get('pnl_pct', 0)
                pnl_str = f"+{pnl:.1f}%" if pnl >= 0 else f"{pnl:.1f}%"
                prompt_parts.append(f"- {pos['ticker']}: {pos.get('allocation_pct', pos.get('size_pct', 0)):.1f}% | P&L {pnl_str}")
            prompt_parts.append("")

    if news_context:
        prompt_parts.extend(["## NEWS CONTEXT", news_context, ""])

    prompt_parts.extend(["## QUESTION", message])

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=DRUCKENMILLER_SYSTEM,
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}]
    )

    return {
        "agent": "druckenmiller",
        "response": response.content[0].text,
        "generated_at": datetime.utcnow().isoformat(),
    }


async def chat_fundamental(message: str, include_context: bool = True) -> dict:
    """Handle fundamental valuation chat with real data."""
    import anthropic
    from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL

    FUNDAMENTAL_SYSTEM = """You are a fundamental equity analyst focused on valuation. You use DCF, comparable multiples, and quality metrics to assess fair value.

Your framework:
- P/E, Forward P/E, PEG ratios
- EV/EBITDA for capital-intensive businesses
- FCF yield for quality assessment
- ROE and ROIC for competitive advantage
- Debt/Equity for balance sheet risk

Always cite specific numbers when they're provided. Be precise about valuations.
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    fundamental_data = load_fundamental_data() if include_context else {}
    sp500_data = load_sp500_screen() if include_context else {}

    prompt_parts = [f"## DATE: {datetime.now().strftime('%Y-%m-%d')}", ""]

    if fundamental_data:
        prompt_parts.extend(["## FUNDAMENTAL VALUATIONS"])
        for ticker, data in list(fundamental_data.items())[:10]:
            prompt_parts.append(
                f"- {ticker}: P/E {data.get('pe_ratio', 'N/A')}, "
                f"Fwd P/E {data.get('forward_pe', 'N/A')}, "
                f"PEG {data.get('peg_ratio', 'N/A')}, "
                f"FCF Yield {data.get('fcf_yield', 'N/A')}%, "
                f"Assessment: {data.get('assessment', 'N/A')}"
            )
        prompt_parts.append("")

    if sp500_data:
        prompt_parts.extend([
            "## S&P 500 VALUATION SCREEN",
            f"Median P/E: {sp500_data.get('sp500_median_pe', 'N/A')}",
            f"Median Forward P/E: {sp500_data.get('sp500_median_forward_pe', 'N/A')}",
            "",
        ])
        if sp500_data.get('undervalued_screen'):
            prompt_parts.append("Undervalued:")
            for stock in sp500_data['undervalued_screen'][:5]:
                prompt_parts.append(f"  - {stock['ticker']}: P/E {stock['pe']}, PEG {stock['peg']}")
        prompt_parts.append("")

    prompt_parts.extend(["## QUESTION", message])

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=FUNDAMENTAL_SYSTEM,
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}]
    )

    return {
        "agent": "fundamental",
        "response": response.content[0].text,
        "fundamental_data": fundamental_data,
        "generated_at": datetime.utcnow().isoformat(),
    }


async def chat_flow(message: str) -> dict:
    """Handle institutional flow chat."""
    agent = InstitutionalFlowAgent()
    flow_data = agent.analyze(use_ai=False)

    import anthropic
    from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL

    FLOW_SYSTEM = """You are an institutional flow analyst tracking hedge fund 13F filings. You identify consensus builds, crowding risks, and contrarian opportunities by analyzing what the best investors are buying and selling.

Focus on:
- Consensus builds (multiple funds accumulating)
- Crowding warnings (too many funds in same trade)
- Contrarian signals (solo conviction positions)
- Changes from prior quarter
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt_parts = [
        f"## INSTITUTIONAL FLOW DATA",
        "",
    ]

    if flow_data.get('consensus_builds'):
        prompt_parts.append("### Consensus Builds:")
        for item in flow_data['consensus_builds'][:5]:
            prompt_parts.append(f"- {item.get('ticker', 'N/A')}: {item.get('funds_accumulating', [])}")
        prompt_parts.append("")

    if flow_data.get('crowding_warnings'):
        prompt_parts.append("### Crowding Warnings:")
        for item in flow_data['crowding_warnings'][:5]:
            prompt_parts.append(f"- {item.get('ticker', 'N/A')}: {item.get('funds_holding', '?')} funds")
        prompt_parts.append("")

    prompt_parts.extend(["## QUESTION", message])

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=FLOW_SYSTEM,
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}]
    )

    return {
        "agent": "flow",
        "response": response.content[0].text,
        "flow_data": flow_data,
        "generated_at": datetime.utcnow().isoformat(),
    }


async def chat_sector_desk(desk_name: str, message: str) -> dict:
    """Handle sector desk chat."""
    import anthropic
    from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL

    portfolio = load_portfolio()

    # Import desk prompts
    desk_systems = {
        "semiconductor": "You are a senior semiconductor analyst. Focus on cycle positioning, AI demand, pricing power, inventory dynamics, and competitive position.",
        "biotech": "You are a senior biotech analyst. Focus on FDA catalysts, pipeline value, patent cliffs, cash runway, and M&A potential.",
        "financials": "You are a senior financials analyst. Focus on NII, credit quality, capital ratios, fee income, and regulatory environment.",
        "energy": "You are a senior energy analyst. Focus on commodity prices, production costs, reserves, capex discipline, and energy transition.",
        "consumer": "You are a senior consumer analyst. Focus on same-store sales, brand strength, pricing power, channel mix, and consumer sentiment.",
        "industrials": "You are a senior industrials analyst. Focus on backlog, capacity utilization, input costs, end-market exposure, and infrastructure spending.",
    }

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt_parts = [f"## DATE: {datetime.now().strftime('%Y-%m-%d')}", ""]

    if portfolio:
        prompt_parts.extend([
            "## CURRENT PORTFOLIO",
        ])
        for pos in portfolio.get('positions', []):
            prompt_parts.append(f"- {pos['ticker']}: {pos.get('allocation_pct', pos.get('size_pct', 0)):.1f}%")
        prompt_parts.append("")

    prompt_parts.extend(["## QUESTION", message])

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=desk_systems.get(desk_name, "You are a sector analyst."),
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}]
    )

    return {
        "agent": desk_name,
        "response": response.content[0].text,
        "generated_at": datetime.utcnow().isoformat(),
    }


@app.post("/api/atlas/analyze")
async def analyze(request: AnalyzeRequest):
    """Run analysis on a specific ticker."""
    agent_name = request.agent.lower()
    ticker = request.ticker.upper()

    logger.info(f"Analysis request: {ticker} via {agent_name}")

    try:
        agent = get_agent_instance(agent_name)
        if agent is None:
            raise HTTPException(status_code=400, detail=f"Unknown agent: {agent_name}")

        if hasattr(agent, 'analyze'):
            result = agent.analyze(ticker)
        else:
            raise HTTPException(status_code=400, detail=f"Agent {agent_name} does not support analyze()")

        return {
            "ticker": ticker,
            "agent": agent_name,
            "analysis": result,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/atlas/news/scan")
async def scan_news():
    """Trigger a news scan."""
    agent = NewsAgent()
    result = agent.scan()
    return result


# Run with: uvicorn web.api:app --host 0.0.0.0 --port 8003 --reload
if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    uvicorn.run(app, host="0.0.0.0", port=8003)
