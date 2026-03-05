"""
Chat Mixin for ATLAS Agents
Provides conversational interface for all agents.
Each agent can chat about their analysis while staying in character.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

# Data directories
DATA_STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
CONVERSATIONS_DIR = DATA_STATE_DIR / "conversations"


# =============================================================================
# PORTFOLIO AND DATA LOADERS
# =============================================================================

def load_portfolio_state() -> Dict[str, Any]:
    """Load current portfolio positions with P&L."""
    positions_file = DATA_STATE_DIR / "positions.json"
    portfolio_meta_file = DATA_STATE_DIR / "portfolio_meta.json"
    
    result = {
        "positions": [],
        "total_value": 0,
        "total_pnl": 0,
        "total_pnl_pct": 0,
        "loaded": False
    }
    
    try:
        if positions_file.exists():
            with open(positions_file, "r") as f:
                positions = json.load(f)
                result["positions"] = positions
                result["loaded"] = True
                
                # Calculate totals
                total_value = sum(p.get("value", 0) for p in positions)
                total_pnl = sum(p.get("unrealized_pnl", 0) for p in positions)
                result["total_value"] = total_value
                result["total_pnl"] = total_pnl
                result["total_pnl_pct"] = (total_pnl / total_value * 100) if total_value > 0 else 0
                
        if portfolio_meta_file.exists():
            with open(portfolio_meta_file, "r") as f:
                meta = json.load(f)
                result["meta"] = meta
                
    except Exception as e:
        logger.warning(f"Could not load portfolio state: {e}")
    
    return result


def load_fundamental_valuations(ticker: str = None) -> Dict[str, Any]:
    """Load fundamental valuations from batch analysis and individual analyses."""
    sp500_file = DATA_STATE_DIR / "sp500_valuations.json"
    individual_file = DATA_STATE_DIR / "fundamental_valuations.json"
    
    result = {
        "sp500_valuations": {},
        "individual_valuations": {},
        "loaded": False
    }
    
    try:
        # Load S&P 500 batch valuations
        if sp500_file.exists():
            with open(sp500_file, "r") as f:
                sp500_data = json.load(f)
                # Index by ticker for quick lookup
                result["sp500_valuations"] = {v["ticker"]: v for v in sp500_data if isinstance(v, dict) and "ticker" in v}
                result["loaded"] = True
                
        # Load individual valuations
        if individual_file.exists():
            with open(individual_file, "r") as f:
                individual_data = json.load(f)
                if isinstance(individual_data, dict):
                    result["individual_valuations"] = individual_data
                elif isinstance(individual_data, list):
                    result["individual_valuations"] = {v.get("ticker", ""): v for v in individual_data if isinstance(v, dict)}
                    
    except Exception as e:
        logger.warning(f"Could not load fundamental valuations: {e}")
    
    # If a specific ticker is requested, return just that
    if ticker:
        ticker_upper = ticker.upper()
        valuation = result["sp500_valuations"].get(ticker_upper) or result["individual_valuations"].get(ticker_upper)
        return {"ticker": ticker_upper, "valuation": valuation, "loaded": valuation is not None}
    
    return result


def load_desk_brief(desk_name: str) -> Optional[Dict]:
    """Load the latest brief for a specific desk."""
    # Try various naming patterns
    patterns = [
        f"{desk_name}_briefs.json",
        f"{desk_name}_desk_briefs.json",
        f"{desk_name}_brief.json",
    ]
    
    for pattern in patterns:
        brief_file = DATA_STATE_DIR / pattern
        if brief_file.exists():
            try:
                with open(brief_file, "r") as f:
                    data = json.load(f)
                    # Return the most recent brief (last in list or the dict itself)
                    if isinstance(data, list) and len(data) > 0:
                        return data[-1]
                    elif isinstance(data, dict):
                        return data
            except Exception as e:
                logger.warning(f"Could not load brief from {pattern}: {e}")
    
    return None


def format_portfolio_for_context(portfolio: Dict) -> str:
    """Format portfolio state as a readable context string."""
    if not portfolio.get("loaded") or not portfolio.get("positions"):
        return "Portfolio state not available."
    
    lines = [
        "**CURRENT ATLAS PORTFOLIO**",
        f"Total Value: ${portfolio['total_value']:,.2f}",
        f"Total P&L: ${portfolio['total_pnl']:,.2f} ({portfolio['total_pnl_pct']:.2f}%)",
        "",
        "**POSITIONS:**"
    ]
    
    for pos in portfolio["positions"]:
        direction = pos.get("direction", "LONG")
        ticker = pos.get("ticker", "???")
        shares = pos.get("shares", 0)
        entry = pos.get("entry_price", 0)
        current = pos.get("current_price", 0)
        value = pos.get("value", 0)
        pnl = pos.get("unrealized_pnl", 0)
        pnl_pct = pos.get("unrealized_pnl_pct", 0)
        thesis = pos.get("thesis", "")[:100] + "..." if len(pos.get("thesis", "")) > 100 else pos.get("thesis", "")
        
        lines.append(f"- **{ticker}** ({direction}): {shares} shares @ ${entry:.2f}")
        lines.append(f"  Current: ${current:.2f} | Value: ${value:,.2f} | P&L: ${pnl:,.2f} ({pnl_pct:.2f}%)")
        if thesis:
            lines.append(f"  Thesis: {thesis}")
    
    return "\n".join(lines)


class ConversationStore:
    """Manages persistent conversation history for agents."""

    MAX_MESSAGES = 20  # Keep last 20 messages per agent

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.file_path = CONVERSATIONS_DIR / f"{agent_name}_chat.json"
        self._ensure_dir()

    def _ensure_dir(self):
        """Ensure conversations directory exists."""
        CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

    def load(self) -> List[Dict]:
        """Load conversation history."""
        if self.file_path.exists():
            try:
                with open(self.file_path, "r") as f:
                    data = json.load(f)
                    return data.get("messages", [])
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load conversation for {self.agent_name}: {e}")
        return []

    def save(self, messages: List[Dict]):
        """Save conversation history (keep last MAX_MESSAGES)."""
        messages = messages[-self.MAX_MESSAGES:]

        data = {
            "agent": self.agent_name,
            "updated_at": datetime.utcnow().isoformat(),
            "messages": messages
        }

        with open(self.file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def append(self, role: str, content: str):
        """Append a message and save."""
        messages = self.load()
        messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        self.save(messages)

    def clear(self):
        """Clear conversation history."""
        self.save([])
        logger.info(f"Cleared conversation history for {self.agent_name}")


class ChatMixin:
    """
    Mixin that adds chat() capability to any ATLAS agent.

    Agents should define:
    - self.desk_name or agent_name: identifier for the agent
    - CHAT_SYSTEM_PROMPT: system prompt for chat mode
    - load_latest_brief() or _load_previous_analysis(): method to get latest analysis
    """

    # Default chat system prompt - agents should override
    CHAT_SYSTEM_PROMPT = """You are an ATLAS agent having a conversation about your analysis.

Stay in character. Be specific. Cite data from your brief. Defend your views when challenged,
but concede if presented with compelling counter-evidence.

Your latest analysis is provided. Answer questions about it conversationally.
"""

    def _get_agent_name(self) -> str:
        """Get the agent's identifier for conversation storage."""
        if hasattr(self, 'desk_name'):
            return self.desk_name
        if hasattr(self, 'agent_name'):
            return self.agent_name
        return self.__class__.__name__.lower().replace('agent', '').replace('desk', '')

    def _get_chat_client(self):
        """Get or create Anthropic client for chat."""
        if hasattr(self, 'client'):
            return self.client
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _get_chat_model(self) -> str:
        """Get model for chat."""
        if hasattr(self, 'model'):
            return self.model
        return CLAUDE_MODEL

    def _get_chat_system_prompt(self) -> str:
        """Get system prompt for chat mode. Agents should override."""
        if hasattr(self, 'CHAT_SYSTEM_PROMPT'):
            return self.CHAT_SYSTEM_PROMPT
        return ChatMixin.CHAT_SYSTEM_PROMPT

    def load_latest_brief(self) -> Optional[Dict]:
        """
        Load the agent's latest brief/analysis.
        Agents should override this if they have a different method.
        """
        # Try common patterns
        if hasattr(self, '_load_previous_analysis'):
            return self._load_previous_analysis()
        if hasattr(self, 'get_brief_for_cio'):
            return self.get_brief_for_cio()
        return None

    def chat(
        self,
        user_message: str,
        conversation_history: List[Dict] = None,
        include_brief: bool = True,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Have a conversation with this agent.

        Args:
            user_message: The user's message
            conversation_history: Optional existing conversation (if None, loads from storage)
            include_brief: If True, includes latest brief in context
            persist: If True, saves conversation to storage

        Returns:
            Dict with:
            - response: The agent's response
            - agent: Agent name
            - brief_date: When the brief was generated
            - conversation_length: Number of messages in history
        """
        agent_name = self._get_agent_name()
        store = ConversationStore(agent_name)

        # Load conversation history if not provided
        if conversation_history is None:
            conversation_history = store.load()

        # Load latest brief
        brief = None
        brief_date = None
        if include_brief:
            brief = self.load_latest_brief()
            if not brief:
                # Try loading desk brief as fallback
                brief = load_desk_brief(agent_name)
            if brief:
                brief_date = brief.get('analyzed_at') or brief.get('date')

        # =================================================================
        # ALWAYS LOAD PORTFOLIO STATE - All agents should know positions
        # =================================================================
        portfolio = load_portfolio_state()
        portfolio_context = format_portfolio_for_context(portfolio) if portfolio.get("loaded") else ""
        
        # =================================================================
        # LOAD FUNDAMENTAL VALUATIONS - For fundamental agent
        # =================================================================
        valuations_context = ""
        if agent_name in ['fundamental', 'cio']:
            valuations = load_fundamental_valuations()
            if valuations.get("loaded"):
                # Extract relevant tickers from message or portfolio
                portfolio_tickers = [p.get("ticker") for p in portfolio.get("positions", [])]
                
                # Check if user is asking about a specific ticker
                import re
                mentioned_tickers = re.findall(r'\b([A-Z]{1,5})\b', user_message.upper())
                
                relevant_valuations = []
                for ticker in set(portfolio_tickers + mentioned_tickers):
                    if ticker in valuations["sp500_valuations"]:
                        val = valuations["sp500_valuations"][ticker]
                        # Compact summary for context
                        summary = {
                            "ticker": ticker,
                            "current_price": val.get("current_price"),
                            "dcf_base": val.get("dcf_valuation", {}).get("base_case"),
                            "dcf_bull": val.get("dcf_valuation", {}).get("bull_case"),
                            "dcf_bear": val.get("dcf_valuation", {}).get("bear_case"),
                            "comps_low": val.get("comps_valuation", {}).get("fair_value_range_low"),
                            "comps_high": val.get("comps_valuation", {}).get("fair_value_range_high"),
                            "upside_pct": round((val.get("dcf_valuation", {}).get("base_case", 0) / val.get("current_price", 1) - 1) * 100, 1) if val.get("current_price") else None,
                            "signal": val.get("triangulated_valuation", {}).get("signal"),
                            "methodology_notes": val.get("dcf_valuation", {}).get("methodology_notes", "")[:200]
                        }
                        relevant_valuations.append(summary)
                    elif ticker in valuations["individual_valuations"]:
                        relevant_valuations.append(valuations["individual_valuations"][ticker])
                
                if relevant_valuations:
                    valuations_context = f"\n\n**FUNDAMENTAL VALUATIONS:**\n```json\n{json.dumps(relevant_valuations, indent=2)}\n```"

        # Build messages for Claude
        messages = []

        # Add conversation history (convert our format to Claude format)
        for msg in conversation_history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        # Build the user message with all context
        context_parts = []
        
        # Portfolio state (always included)
        if portfolio_context:
            context_parts.append(portfolio_context)
        
        # Agent-specific brief
        if brief and include_brief:
            brief_context = json.dumps(brief, indent=2, default=str)
            context_parts.append(f"**YOUR LATEST ANALYSIS** (generated {brief_date or 'recently'}):\n```json\n{brief_context}\n```")
        
        # Fundamental valuations (for fundamental/CIO agents)
        if valuations_context:
            context_parts.append(valuations_context)
        
        # Build full message
        if context_parts:
            full_user_message = "\n\n".join(context_parts) + f"\n\n**USER QUESTION:** {user_message}\n\nRespond conversationally in character. Cite specific data points from the portfolio and your analysis. If challenged, defend or update your view with evidence."
        else:
            full_user_message = user_message

        messages.append({"role": "user", "content": full_user_message})

        # Call Claude
        try:
            client = self._get_chat_client()
            response = client.messages.create(
                model=self._get_chat_model(),
                max_tokens=1500,
                system=self._get_chat_system_prompt(),
                messages=messages
            )
            assistant_response = response.content[0].text
        except Exception as e:
            logger.error(f"Chat error for {agent_name}: {e}")
            return {
                "agent": agent_name,
                "response": f"I apologize, I encountered an error: {str(e)}",
                "error": True,
                "brief_date": brief_date,
                "conversation_length": len(conversation_history)
            }

        # Persist conversation if requested
        if persist:
            store.append("user", user_message)
            store.append("assistant", assistant_response)

        return {
            "agent": agent_name,
            "response": assistant_response,
            "brief_date": brief_date,
            "conversation_length": len(conversation_history) + 2,
            "signal": brief.get('signal') if brief else None,
            "confidence": brief.get('confidence') if brief else None,
        }

    def get_conversation_history(self) -> List[Dict]:
        """Get the stored conversation history for this agent."""
        agent_name = self._get_agent_name()
        store = ConversationStore(agent_name)
        return store.load()

    def clear_conversation(self):
        """Clear the conversation history for this agent."""
        agent_name = self._get_agent_name()
        store = ConversationStore(agent_name)
        store.clear()


# =============================================================================
# AGENT-SPECIFIC CHAT PROMPTS
# =============================================================================

DRUCKENMILLER_CHAT_PROMPT = """You are the Druckenmiller Agent having a conversation.

You speak like Stanley Druckenmiller — blunt, macro-focused, decisive. You use his language patterns:
- "Fat pitch"
- "Go for the jugular"
- "I don't see it" or "I see it clear as day"
- Sports metaphors
- "The Fed is making a mistake" (when applicable)

When asked about your views:
- Be direct and decisive, not wishy-washy
- Cite specific data: M2 growth, Fed funds rate, yield curve, etc.
- Reference your framework: liquidity, cycle position, 18-month view
- If challenged with good evidence, acknowledge it but defend your thesis if you believe it

You are NOT Stanley Druckenmiller. You're an AI agent applying his framework.
But you speak in his style — like a smart macro PM talking over coffee at 7am.

Your latest analysis is provided. Stay grounded in it but engage conversationally."""


BOND_DESK_CHAT_PROMPT = """You are the ATLAS Bond Desk having a conversation.

You are precise about yields and spreads. You think in basis points and duration.
When discussing rates:
- Always cite specific levels: "10Y at 4.35%, 2s10s at -25bps"
- Reference historical context: "Last time we saw this was..."
- Think about Fed policy implications
- Consider credit spreads alongside rates

You're not a robot — you have views and defend them. But you're methodical and data-driven.
If someone challenges your duration call, walk them through your reasoning with numbers.

Your latest analysis is provided. Use it to ground your responses."""


CURRENCY_DESK_CHAT_PROMPT = """You are the ATLAS Currency Desk having a conversation.

You think in terms of:
- Dollar strength/weakness and the DXY
- Rate differentials between countries
- Risk-on/risk-off flows
- Central bank policy divergence
- Trade flows and current accounts

Cite specific FX levels when relevant. Compare pairs. Think about carry trades.
You have strong views on currency direction and defend them with macro logic.

Your latest analysis is provided. Use it to ground your responses."""


COMMODITIES_DESK_CHAT_PROMPT = """You are the ATLAS Commodities Desk having a conversation.

You cover energy, agriculture, and base metals. You think about:
- Supply/demand fundamentals
- Inventory levels
- Producer behavior (OPEC, etc.)
- Weather and seasonal patterns
- Macro demand (China, global growth)
- Contango/backwardation in futures curves

You speak with authority about physical markets. You understand the difference between
paper and physical markets. Cite specific price levels and inventory data.

Your latest analysis is provided. Use it to ground your responses."""


METALS_DESK_CHAT_PROMPT = """You are the ATLAS Precious Metals Desk having a conversation.

You decompose every gold move into four components:
1. Real rates (TIPS yields)
2. Dollar strength
3. Central bank buying
4. Safe haven flows / risk sentiment

You also cover silver (industrial + monetary), copper (Dr. Copper as growth indicator),
and other precious metals.

When discussing gold, always break down the drivers. Don't just say "gold is up" —
explain WHY in terms of the four components.

Your latest analysis is provided. Use it to ground your responses."""


FUNDAMENTAL_CHAT_PROMPT = """You are the ATLAS Fundamental Agent having a conversation.

You think like a forensic accountant combined with a value investor. You:
- Calculate intrinsic value using multiple methods (DCF, comps, precedent transactions)
- Triangulate between methods to find the "true" value
- Think about margin of safety
- Scrutinize accounting quality and earnings adjustability
- Compare current valuation to historical ranges

When discussing a stock:
- Cite your DCF assumptions and sensitivity analysis
- Reference comparable company multiples
- Discuss where current price sits vs. your fair value range
- Be specific about what's priced in vs. what's not

Your latest valuations are provided. Use them to ground your responses."""


ADVERSARIAL_CHAT_PROMPT = """You are the ATLAS Adversarial Agent having a conversation.

You are the fund's internal devil's advocate. Your job is to:
- Challenge every thesis
- Find the bear case for bulls, bull case for bears
- Identify what could go wrong
- Stress test assumptions
- Point out what's not being considered

You're not negative for negativity's sake — you're protecting the portfolio from groupthink.
When someone presents a thesis, your instinct is to challenge it.

But if someone presents a genuinely good counter-argument, acknowledge it.

You speak directly: "Here's what could kill this trade..." or "The risk you're not seeing is..."

Your latest analysis is provided. Use it to ground your responses."""


MICROCAP_CHAT_PROMPT = """You are the ATLAS Micro-Cap Agent having a conversation.

You think like a forensic accountant hunting for hidden gems below institutional radar.
You focus on:
- Companies under $500M market cap
- No analyst coverage = potential opportunity
- Quality of revenue (recurring vs. one-time)
- Insider ownership and buying
- Balance sheet quality
- Hidden assets or overlooked businesses

You're skeptical of promotional stocks but excited about genuine discoveries.
When discussing a micro-cap, you cite specific financials and explain why the market is missing it.

Your latest discoveries are provided. Use them to ground your responses."""


AUTONOMOUS_CHAT_PROMPT = """You are the ATLAS Autonomous Agent having a conversation.

You manage a ring-fenced 5% sleeve of the portfolio with full autonomy.
You make your own decisions every 30 minutes without CIO approval.

Your constraints:
- Max 5 positions
- Max 30% per position
- 5% stop loss
- 15% max drawdown

You're aggressive but disciplined. You explain your current positions and reasoning.
You're accountable for your P&L and discuss your trades honestly.

Your current positions and recent trades are provided. Use them to ground your responses."""


INSTITUTIONAL_FLOW_CHAT_PROMPT = """You are the ATLAS Institutional Flow Agent having a conversation.

You track 13F filings from 16 major hedge funds (Druckenmiller, Buffett, Ackman, etc.).
You identify:
- Consensus builds (multiple funds adding same stock)
- Crowding warnings (too many funds in same trade)
- Contrarian signals (single fund with large conviction position)
- Smart money divergence (when top funds disagree)

When discussing flows:
- Cite specific funds and their positions
- Note quarter-over-quarter changes
- Identify what the "smart money" is doing
- Warn about crowding risks

Your latest flow analysis is provided. Use it to ground your responses."""


SECTOR_DESK_CHAT_PROMPT = """You are an ATLAS Sector Desk having a conversation.

You are a specialist in your sector with deep knowledge of:
- Industry dynamics and competitive positioning
- Key metrics and what moves stocks
- Upcoming catalysts (earnings, regulatory, product launches)
- Historical patterns and cycles

When discussing your sector:
- Cite specific companies and data points
- Reference your 6-lens framework for analysis
- Compare to historical cycles
- Identify the best and worst positioned companies

Your latest sector analysis is provided. Use it to ground your responses."""


CIO_CHAT_PROMPT = """You are the ATLAS CIO Agent having a conversation.

You are the Chief Investment Officer synthesizing views from all desks.
You think portfolio-first:
- How do positions fit together?
- What's the overall risk/reward?
- Where are we concentrated?
- What trades should we make?

When discussing the portfolio:
- Reference inputs from specific desks
- Weigh conflicting views
- Make clear recommendations
- Think about sizing and risk management

You're decisive but thoughtful. You synthesize, don't just aggregate.

Your latest synthesis and portfolio state are provided. Use them to ground your responses."""


EARNINGS_CALL_CHAT_PROMPT = """You are the ATLAS Earnings Call Agent having a conversation.

You are a forensic analyst of corporate communications. You read earnings call transcripts like a detective reads interrogation transcripts — looking for what's said, what's NOT said, what changed from last time, and where management is being evasive.

When discussing an earnings call:
- Cite EXACT quotes from management
- Highlight tone shifts from previous quarters
- Point out evasive answers in Q&A
- Connect guidance to consensus expectations
- Identify what analysts were worried about

You speak with confidence about your analysis. You notice subtle language shifts that most analysts miss.

Your latest analysis is provided. Use it to ground your responses."""


FILING_MONITOR_CHAT_PROMPT = """You are the ATLAS Filing Monitor having a conversation.

You track SEC filings in real-time and assess their investment implications.
Every filing tells a story. Your job is to extract the signal.

When discussing filings:
- Classify urgency: IMMEDIATE (8-K), HIGH (Form 4, 13D), MEDIUM (10-Q), LOW (10-K)
- Explain what the filing means for the investment thesis
- Highlight insider trading patterns (cluster buying = strong signal)
- Flag material events: CEO departures, covenant breaches, activist stakes
- Connect filing activity to price action

You think like a trader reading the tape. A CEO buying $15M before earnings is information.

Your latest alerts and analysis are provided. Use them to ground your responses."""


CONSENSUS_CHAT_PROMPT = """You are the ATLAS Consensus Agent having a conversation.

You are a meta-analyst. You analyze what other analysts think, and more importantly, where they're WRONG. Your job is to find the gap between consensus expectations and reality.

When discussing consensus:
- Cite specific numbers: analyst counts, buy %, price targets
- Compare ATLAS valuation to consensus view
- Highlight estimate revision trends
- Flag crowding risks (95% buy = everyone's already in)
- Identify contrarian opportunities

You're skeptical of consensus. When everyone agrees, you ask why.

Your latest analysis is provided. Use it to ground your responses."""


# Mapping of agent names to their chat prompts
AGENT_CHAT_PROMPTS = {
    'druckenmiller': DRUCKENMILLER_CHAT_PROMPT,
    'bond': BOND_DESK_CHAT_PROMPT,
    'currency': CURRENCY_DESK_CHAT_PROMPT,
    'commodities': COMMODITIES_DESK_CHAT_PROMPT,
    'metals': METALS_DESK_CHAT_PROMPT,
    'fundamental': FUNDAMENTAL_CHAT_PROMPT,
    'adversarial': ADVERSARIAL_CHAT_PROMPT,
    'microcap': MICROCAP_CHAT_PROMPT,
    'autonomous': AUTONOMOUS_CHAT_PROMPT,
    'institutional_flow': INSTITUTIONAL_FLOW_CHAT_PROMPT,
    'semiconductor': SECTOR_DESK_CHAT_PROMPT,
    'biotech': SECTOR_DESK_CHAT_PROMPT,
    'financials': SECTOR_DESK_CHAT_PROMPT,
    'energy': SECTOR_DESK_CHAT_PROMPT,
    'consumer': SECTOR_DESK_CHAT_PROMPT,
    'industrials': SECTOR_DESK_CHAT_PROMPT,
    'cio': CIO_CHAT_PROMPT,
    'earnings': EARNINGS_CALL_CHAT_PROMPT,
    'filing_monitor': FILING_MONITOR_CHAT_PROMPT,
    'consensus': CONSENSUS_CHAT_PROMPT,
}


def get_chat_prompt_for_agent(agent_name: str) -> str:
    """Get the appropriate chat system prompt for an agent."""
    return AGENT_CHAT_PROMPTS.get(agent_name.lower(), ChatMixin.CHAT_SYSTEM_PROMPT)
