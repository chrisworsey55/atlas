"""
CIO Chat Router
Routes messages to appropriate agents and synthesizes responses.

Two modes:
1. CIO Chat (default) - unified conversation that routes to any agent or combines multiple
2. Agent Chat - direct conversation with a single agent
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MODEL_PREMIUM
from agents.chat_mixin import (
    ConversationStore,
    get_chat_prompt_for_agent,
    AGENT_CHAT_PROMPTS,
    load_portfolio_state,
    format_portfolio_for_context,
    load_fundamental_valuations,
    load_desk_brief,
)

logger = logging.getLogger(__name__)


# =============================================================================
# INTENT CLASSIFICATION RULES
# =============================================================================

INTENT_KEYWORDS = {
    'semiconductor': [
        'semiconductor', 'chip', 'nvda', 'nvidia', 'amd', 'avgo', 'broadcom',
        'intc', 'intel', 'foundry', 'ai chips', 'tsmc', 'taiwan semi',
        'asml', 'lam research', 'applied materials', 'gpu', 'cpu', 'datacenter',
        'memory', 'micron', 'mu', 'samsung', 'hynix', 'semi cycle',
    ],
    'biotech': [
        'biotech', 'pharma', 'pharmaceutical', 'fda', 'clinical', 'drug',
        'lly', 'eli lilly', 'pfe', 'pfizer', 'abbv', 'abbvie', 'mrk', 'merck',
        'jnj', 'johnson', 'gsk', 'bmy', 'bristol', 'amgn', 'amgen',
        'glp-1', 'obesity', 'pipeline', 'phase 3', 'approval',
    ],
    'financials': [
        'financials', 'banks', 'banking', 'insurance', 'xlf',
        'jpm', 'jpmorgan', 'bac', 'bank of america', 'wfc', 'wells fargo',
        'gs', 'goldman', 'ms', 'morgan stanley', 'c', 'citi',
        'loan', 'credit card', 'net interest', 'nim',
    ],
    'energy': [
        'energy', 'oil', 'gas', 'xle', 'xom', 'exxon', 'cvx', 'chevron',
        'oxy', 'occidental', 'cop', 'conocophillips', 'slb', 'schlumberger',
        'hal', 'halliburton', 'natural gas', 'lng', 'refining', 'upstream',
    ],
    'consumer': [
        'consumer', 'retail', 'spending', 'xly', 'xlp', 'amazon', 'amzn',
        'walmart', 'wmt', 'costco', 'cost', 'target', 'tgt', 'home depot', 'hd',
        'nike', 'nke', 'starbucks', 'sbux', 'mcd', 'mcdonalds',
        'discretionary', 'staples', 'consumption',
    ],
    'industrials': [
        'industrials', 'manufacturing', 'capex', 'xli', 'cat', 'caterpillar',
        'de', 'deere', 'ba', 'boeing', 'rtx', 'raytheon', 'hon', 'honeywell',
        'ge', 'general electric', 'ups', 'fedex', 'rails', 'union pacific',
        'infrastructure', 'construction',
    ],
    'bond': [
        'bond', 'bonds', 'treasury', 'treasuries', 'yield', 'yields',
        'tlt', 'ief', 'shy', 'tbt', 'duration', 'credit spread',
        'rate', 'rates', 'fixed income', '10 year', '10y', '2 year', '2y',
        'curve', 'yield curve', '2s10s', 'steepener', 'flattener',
        'high yield', 'investment grade', 'corporate bonds',
    ],
    'currency': [
        'currency', 'currencies', 'fx', 'forex', 'dollar', 'dxy',
        'yen', 'usd/jpy', 'usdjpy', 'euro', 'eur/usd', 'eurusd',
        'pound', 'gbp', 'cable', 'yuan', 'rmb', 'cny',
        'carry trade', 'rate differential',
    ],
    'commodities': [
        'commodity', 'commodities', 'oil price', 'crude', 'wti', 'brent',
        'natural gas', 'nat gas', 'uso', 'ung', 'copper', 'wheat', 'corn',
        'soybeans', 'agriculture', 'soft commodities', 'lumber',
    ],
    'metals': [
        'gold', 'silver', 'gld', 'slv', 'precious metal', 'precious metals',
        'mining', 'gdx', 'gdxj', 'platinum', 'palladium',
        'real rates', 'tips', 'inflation hedge',
    ],
    'druckenmiller': [
        'macro', 'fed', 'federal reserve', 'inflation', 'gdp', 'liquidity',
        'cycle', 'recession', 'economy', 'economic', 'm2', 'money supply',
        'druckenmiller', 'druck', 'top down', 'regime', 'fat pitch',
        'central bank', 'powell', 'fomc',
    ],
    'institutional_flow': [
        '13f', 'institutional', 'holdings', 'buffett', 'berkshire',
        'soros', 'tepper', 'ackman', 'flow', 'flows', 'hedge fund',
        'smart money', 'consensus', 'crowding', 'duquesne',
    ],
    'autonomous': [
        'autonomous', 'sleeve', 'independent', 'ring-fenced', 'auto trades',
    ],
    'microcap': [
        'micro-cap', 'microcap', 'small cap', 'smallcap', 'discovery',
        'overlooked', 'no coverage', 'hidden gem', 'undiscovered',
        'under $500m', 'nano cap',
    ],
    'fundamental': [
        'valuation', 'dcf', 'fair value', 'undervalued', 'overvalued',
        'intrinsic', 'p/e', 'pe ratio', 'ev/ebitda', 'multiple',
        'comps', 'comparable', 'margin of safety', 'worth',
    ],
    'adversarial': [
        'risk', 'what could go wrong', 'challenge', 'bear case',
        "devil's advocate", 'stress test', 'downside', 'attack',
        'critique', 'flaw', 'problem with',
    ],
    'cio': [
        'portfolio', 'position', 'p&l', 'pnl', 'allocation',
        'what should we do', 'trade', 'buy', 'sell', 'sizing',
        'exposure', 'rebalance', 'morning brief', 'briefing',
    ],
    'earnings': [
        'earnings call', 'transcript', 'earnings transcript', 'call transcript',
        'management tone', 'ceo said', 'cfo said', 'guidance',
        'conference call', 'earnings report', 'what did they say',
    ],
    'filing_monitor': [
        'filing', 'filings', 'sec filing', '8-k', '8k', 'form 4',
        'insider trade', 'insider trading', 'insider buy', 'insider sell',
        '13d', '13g', 'activist', 'material event', 'edgar',
    ],
    'consensus': [
        'analyst', 'analysts', 'wall street', 'consensus', 'price target',
        'estimate', 'estimates', 'upgrade', 'downgrade', 'rating',
        'buy rating', 'sell rating', 'revision', 'revisions',
    ],
}

# Compound queries that should involve multiple agents
COMPOUND_QUERY_PATTERNS = [
    # "Should we buy/sell X" -> fundamental + relevant sector + CIO
    (r'should we (buy|sell|add|trim|exit)\s+(\w+)', ['fundamental', 'cio']),

    # "What's our biggest risk" -> adversarial + CIO
    (r"(biggest|main|top)\s+risk", ['adversarial', 'cio']),

    # "Morning briefing" -> druckenmiller + CIO
    (r'morning brief', ['druckenmiller', 'cio']),

    # "Give me the overview" -> druckenmiller + CIO
    (r'(overview|summary|state of)', ['druckenmiller', 'cio']),
]


class CIOChatRouter:
    """
    Routes chat messages to appropriate agents and synthesizes responses.

    Two modes:
    1. Unified CIO chat - routes to relevant agents, synthesizes if multiple
    2. Direct agent chat - talks to a single agent
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.agents = {}  # Lazy-loaded agents
        self.cio_store = ConversationStore("cio")

    def _get_agent(self, agent_key: str):
        """Lazy-load an agent by key."""
        if agent_key in self.agents:
            return self.agents[agent_key]

        try:
            if agent_key == 'druckenmiller':
                from agents.druckenmiller_agent import DruckenmillerAgent
                self.agents[agent_key] = DruckenmillerAgent()

            elif agent_key == 'bond':
                from agents.bond_desk_agent import BondDeskAgent
                self.agents[agent_key] = BondDeskAgent()

            elif agent_key == 'currency':
                from agents.currency_desk_agent import CurrencyDeskAgent
                self.agents[agent_key] = CurrencyDeskAgent()

            elif agent_key == 'commodities':
                from agents.commodities_desk_agent import CommoditiesDeskAgent
                self.agents[agent_key] = CommoditiesDeskAgent()

            elif agent_key == 'metals':
                from agents.metals_desk_agent import MetalsDeskAgent
                self.agents[agent_key] = MetalsDeskAgent()

            elif agent_key == 'fundamental':
                from agents.fundamental_agent import FundamentalAgent
                self.agents[agent_key] = FundamentalAgent()

            elif agent_key == 'adversarial':
                from agents.adversarial_agent import AdversarialAgent
                self.agents[agent_key] = AdversarialAgent()

            elif agent_key == 'microcap':
                from agents.microcap_agent import MicrocapAgent
                self.agents[agent_key] = MicrocapAgent()

            elif agent_key == 'autonomous':
                from agents.autonomous_agent import AutonomousAgent
                self.agents[agent_key] = AutonomousAgent()

            elif agent_key == 'institutional_flow':
                from agents.institutional_flow_agent import InstitutionalFlowAgent
                self.agents[agent_key] = InstitutionalFlowAgent()

            elif agent_key == 'cio':
                from agents.cio_agent import CIOAgent
                self.agents[agent_key] = CIOAgent()

            elif agent_key in ['semiconductor', 'biotech', 'financials', 'energy', 'consumer', 'industrials']:
                from agents.sector_desk import get_desk
                self.agents[agent_key] = get_desk(agent_key)

            elif agent_key == 'earnings':
                from agents.earnings_call_agent import EarningsCallAgent
                self.agents[agent_key] = EarningsCallAgent()

            elif agent_key == 'filing_monitor':
                from agents.filing_monitor_agent import FilingMonitorAgent
                self.agents[agent_key] = FilingMonitorAgent()

            elif agent_key == 'consensus':
                from agents.consensus_agent import ConsensusAgent
                self.agents[agent_key] = ConsensusAgent()

            else:
                logger.warning(f"Unknown agent key: {agent_key}")
                return None

            return self.agents[agent_key]

        except ImportError as e:
            logger.error(f"Could not import agent {agent_key}: {e}")
            return None

    def classify_intent(self, message: str) -> List[str]:
        """
        Classify which agents should handle this message.
        Returns list of agent keys.
        """
        message_lower = message.lower()
        matched_agents = set()

        # Check compound query patterns first
        for pattern, agents in COMPOUND_QUERY_PATTERNS:
            if re.search(pattern, message_lower):
                matched_agents.update(agents)

        # Check keyword matches
        for agent_key, keywords in INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    matched_agents.add(agent_key)
                    break

        # If no matches, use CIO as fallback
        if not matched_agents:
            matched_agents.add('cio')

        # If we matched a sector, also consider adding fundamental for valuation questions
        sector_agents = {'semiconductor', 'biotech', 'financials', 'energy', 'consumer', 'industrials'}
        if matched_agents & sector_agents:
            # Check if it's a valuation/trade question
            if any(word in message_lower for word in ['valuation', 'buy', 'sell', 'worth', 'price target']):
                matched_agents.add('fundamental')

        return list(matched_agents)

    def _load_agent_brief(self, agent_key: str) -> Optional[Dict]:
        """Load the latest brief for an agent."""
        agent = self._get_agent(agent_key)
        if not agent:
            return None

        try:
            if hasattr(agent, 'load_latest_brief'):
                return agent.load_latest_brief()
            if hasattr(agent, '_load_previous_analysis'):
                return agent._load_previous_analysis()
            if hasattr(agent, 'get_brief_for_cio'):
                return agent.get_brief_for_cio()
        except Exception as e:
            logger.warning(f"Could not load brief for {agent_key}: {e}")

        return None

    def _chat_with_single_agent(
        self,
        agent_key: str,
        message: str,
        conversation_history: List[Dict] = None,
    ) -> Dict:
        """Chat with a single agent."""
        agent = self._get_agent(agent_key)
        brief = self._load_agent_brief(agent_key)
        brief_date = brief.get('analyzed_at', brief.get('date')) if brief else None

        # =================================================================
        # LOAD PORTFOLIO STATE - All agents should know current positions
        # =================================================================
        portfolio = load_portfolio_state()
        portfolio_context = format_portfolio_for_context(portfolio) if portfolio.get("loaded") else ""
        
        # =================================================================
        # LOAD FUNDAMENTAL VALUATIONS - For fundamental/CIO agents
        # =================================================================
        valuations_context = ""
        if agent_key in ['fundamental', 'cio']:
            valuations = load_fundamental_valuations()
            if valuations.get("loaded"):
                # Get portfolio tickers
                portfolio_tickers = [p.get("ticker") for p in portfolio.get("positions", [])]
                
                # Find tickers mentioned in the message
                mentioned_tickers = re.findall(r'\b([A-Z]{1,5})\b', message.upper())
                
                relevant_valuations = []
                for ticker in set(portfolio_tickers + mentioned_tickers):
                    if ticker in valuations["sp500_valuations"]:
                        val = valuations["sp500_valuations"][ticker]
                        # Create compact summary
                        dcf = val.get("dcf_valuation", {})
                        comps = val.get("comps_valuation", {})
                        current = val.get("current_price", 0)
                        base = dcf.get("base_case", 0)
                        
                        summary = {
                            "ticker": ticker,
                            "company": val.get("company_name", ""),
                            "sector": val.get("sector", ""),
                            "current_price": current,
                            "dcf_base_case": base,
                            "dcf_bull_case": dcf.get("bull_case"),
                            "dcf_bear_case": dcf.get("bear_case"),
                            "comps_range": f"${comps.get('fair_value_range_low', 0)}-${comps.get('fair_value_range_high', 0)}",
                            "upside_pct": round((base / current - 1) * 100, 1) if current > 0 and base > 0 else None,
                            "key_assumptions": dcf.get("key_assumptions", {}),
                            "methodology": dcf.get("methodology_notes", "")[:300]
                        }
                        relevant_valuations.append(summary)
                    elif ticker in valuations.get("individual_valuations", {}):
                        relevant_valuations.append(valuations["individual_valuations"][ticker])
                
                if relevant_valuations:
                    valuations_context = f"\n\n**FUNDAMENTAL VALUATIONS (from S&P 500 batch analysis):**\n```json\n{json.dumps(relevant_valuations, indent=2)}\n```"

        # Build messages
        messages = []
        if conversation_history:
            for msg in conversation_history:
                messages.append({"role": msg["role"], "content": msg["content"]})

        # Build comprehensive user message with all context
        context_parts = []
        
        # Always include portfolio state
        if portfolio_context:
            context_parts.append(portfolio_context)
        
        # Include agent's brief
        if brief:
            brief_json = json.dumps(brief, indent=2, default=str)
            context_parts.append(f"**YOUR LATEST ANALYSIS:**\n```json\n{brief_json}\n```")
        
        # Include valuations for relevant agents
        if valuations_context:
            context_parts.append(valuations_context)
        
        # Build full message
        if context_parts:
            user_content = "\n\n".join(context_parts) + f"\n\n**USER QUESTION:** {message}\n\nRespond conversationally in character. Cite specific data from the portfolio and your analysis. Use actual numbers when available."
        else:
            user_content = message

        messages.append({"role": "user", "content": user_content})

        # Get appropriate system prompt
        system_prompt = get_chat_prompt_for_agent(agent_key)

        # Call Claude
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1500,
                system=system_prompt,
                messages=messages
            )
            agent_response = response.content[0].text
        except Exception as e:
            logger.error(f"Chat error for {agent_key}: {e}")
            agent_response = f"Error communicating with {agent_key}: {str(e)}"

        return {
            "agent": agent_key,
            "response": agent_response,
            "brief_date": brief_date,
            "signal": brief.get('signal') if brief else None,
            "confidence": brief.get('confidence') if brief else None,
        }

    def _synthesize_responses(
        self,
        message: str,
        agent_responses: Dict[str, Dict],
        conversation_history: List[Dict] = None,
    ) -> str:
        """
        Synthesize responses from multiple agents into a unified CIO response.
        """
        # Build synthesis prompt
        synthesis_parts = [
            f"The user asked: {message}",
            "",
            "Here are the responses from the relevant agents:",
            ""
        ]

        for agent_key, response in agent_responses.items():
            synthesis_parts.append(f"### {agent_key.upper()} AGENT:")
            synthesis_parts.append(response.get('response', 'No response'))
            if response.get('signal'):
                synthesis_parts.append(f"Signal: {response['signal']} (Confidence: {response.get('confidence', 'N/A')})")
            synthesis_parts.append("")

        synthesis_parts.extend([
            "---",
            "",
            "As the CIO, synthesize these views into a single coherent answer.",
            "Note where agents agree and where they disagree.",
            "Give a clear recommendation.",
            "Be direct and decisive — you're the CIO making the call.",
        ])

        synthesis_prompt = "\n".join(synthesis_parts)

        # Build messages with history
        messages = []
        if conversation_history:
            for msg in conversation_history[-6:]:  # Last 6 messages for context
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": synthesis_prompt})

        # Call Claude for synthesis
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL_PREMIUM,  # Use premium for CIO synthesis
                max_tokens=2000,
                system=get_chat_prompt_for_agent('cio'),
                messages=messages
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            return f"Error synthesizing responses: {str(e)}"

    def route(
        self,
        message: str,
        conversation_history: List[Dict] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Route a message to appropriate agents and return response.

        Args:
            message: The user's message
            conversation_history: Optional existing conversation (loads from storage if None)
            persist: If True, saves conversation to storage

        Returns:
            Dict with:
            - response: The final response
            - agents_consulted: List of agent keys that were consulted
            - agent_briefs: Individual responses from each agent (if multiple)
            - routing_reason: Why these agents were selected
        """
        # Load conversation history if not provided
        if conversation_history is None:
            conversation_history = self.cio_store.load()

        # Classify intent
        agents_needed = self.classify_intent(message)
        logger.info(f"Routing to agents: {agents_needed}")

        if len(agents_needed) == 1:
            # Single agent can handle it
            agent_key = agents_needed[0]
            result = self._chat_with_single_agent(
                agent_key,
                message,
                conversation_history
            )

            final_response = result['response']
            agent_briefs = {agent_key: result}

        else:
            # Multiple agents needed — gather responses then synthesize
            agent_responses = {}
            for agent_key in agents_needed:
                # Don't pass full history to individual agents in multi-agent mode
                result = self._chat_with_single_agent(agent_key, message)
                agent_responses[agent_key] = result

            # Synthesize via CIO
            final_response = self._synthesize_responses(
                message,
                agent_responses,
                conversation_history
            )
            agent_briefs = agent_responses

        # Persist if requested
        if persist:
            self.cio_store.append("user", message)
            self.cio_store.append("assistant", final_response)

        return {
            "response": final_response,
            "agents_consulted": agents_needed,
            "agent_briefs": agent_briefs,
            "routing_reason": f"Keywords matched: {', '.join(agents_needed)}",
            "conversation_length": len(conversation_history) + 2,
        }

    def chat_direct(
        self,
        agent_name: str,
        message: str,
        conversation_history: List[Dict] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Chat directly with a specific agent (bypassing routing).

        Args:
            agent_name: The agent to chat with
            message: The user's message
            conversation_history: Optional existing conversation
            persist: If True, saves conversation to storage

        Returns:
            Dict with response and metadata
        """
        agent_key = agent_name.lower().replace(' ', '_').replace('-', '_')
        store = ConversationStore(agent_key)

        # Load history if not provided
        if conversation_history is None:
            conversation_history = store.load()

        result = self._chat_with_single_agent(
            agent_key,
            message,
            conversation_history
        )

        # Persist if requested
        if persist:
            store.append("user", message)
            store.append("assistant", result['response'])

        result['conversation_length'] = len(conversation_history) + 2
        return result

    def get_cio_history(self) -> List[Dict]:
        """Get CIO chat conversation history."""
        return self.cio_store.load()

    def clear_cio_history(self):
        """Clear CIO chat conversation history."""
        self.cio_store.clear()

    def get_agent_history(self, agent_name: str) -> List[Dict]:
        """Get conversation history for a specific agent."""
        agent_key = agent_name.lower().replace(' ', '_').replace('-', '_')
        store = ConversationStore(agent_key)
        return store.load()

    def clear_agent_history(self, agent_name: str):
        """Clear conversation history for a specific agent."""
        agent_key = agent_name.lower().replace(' ', '_').replace('-', '_')
        store = ConversationStore(agent_key)
        store.clear()

    def get_all_agent_statuses(self) -> Dict[str, Dict]:
        """Get status of all agents (latest brief date, signal, etc.)."""
        statuses = {}
        all_agents = list(INTENT_KEYWORDS.keys())

        for agent_key in all_agents:
            brief = self._load_agent_brief(agent_key)
            history = self.get_agent_history(agent_key)

            statuses[agent_key] = {
                "has_brief": brief is not None,
                "brief_date": brief.get('analyzed_at', brief.get('date')) if brief else None,
                "signal": brief.get('signal') if brief else None,
                "confidence": brief.get('confidence') if brief else None,
                "conversation_messages": len(history),
            }

        return statuses


# =============================================================================
# SPECIAL INTERACTION MODES
# =============================================================================

class DebateMode:
    """
    Facilitates debates between agents on a topic.
    Example: Should we buy NVDA? Get semiconductor bull vs adversarial bear.
    """

    def __init__(self, router: CIOChatRouter):
        self.router = router
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def debate(
        self,
        topic: str,
        agent_a: str,
        agent_b: str,
        rounds: int = 2
    ) -> Dict[str, Any]:
        """
        Have two agents debate a topic.

        Args:
            topic: The debate topic (e.g., "Should we buy NVDA?")
            agent_a: First agent (typically the bull)
            agent_b: Second agent (typically the adversarial)
            rounds: Number of back-and-forth rounds

        Returns:
            Dict with debate transcript and CIO verdict
        """
        transcript = []

        # Initial positions
        response_a = self.router.chat_direct(agent_a, topic, persist=False)
        transcript.append({
            "agent": agent_a,
            "round": 1,
            "position": response_a['response']
        })

        response_b = self.router.chat_direct(
            agent_b,
            f"Challenge this view: {response_a['response'][:500]}...\n\nOriginal topic: {topic}",
            persist=False
        )
        transcript.append({
            "agent": agent_b,
            "round": 1,
            "position": response_b['response']
        })

        # Additional rounds
        for round_num in range(2, rounds + 1):
            # Agent A responds to B's challenge
            counter_a = self.router.chat_direct(
                agent_a,
                f"Respond to this counter-argument: {response_b['response'][:500]}...",
                persist=False
            )
            transcript.append({
                "agent": agent_a,
                "round": round_num,
                "position": counter_a['response']
            })

            # Agent B responds
            counter_b = self.router.chat_direct(
                agent_b,
                f"Respond to this: {counter_a['response'][:500]}...",
                persist=False
            )
            transcript.append({
                "agent": agent_b,
                "round": round_num,
                "position": counter_b['response']
            })

            response_a, response_b = counter_a, counter_b

        # CIO verdict
        debate_summary = "\n\n".join([
            f"**{t['agent'].upper()} (Round {t['round']}):**\n{t['position']}"
            for t in transcript
        ])

        verdict_response = self.router.route(
            f"Based on this debate, what should we do?\n\n{debate_summary}",
            persist=False
        )

        return {
            "topic": topic,
            "agent_a": agent_a,
            "agent_b": agent_b,
            "transcript": transcript,
            "cio_verdict": verdict_response['response'],
        }


class WhatIfMode:
    """
    Allows asking agents hypothetical scenario questions.
    Example: "What if CPI comes in at 3.5%?"
    """

    def __init__(self, router: CIOChatRouter):
        self.router = router

    def what_if(
        self,
        scenario: str,
        agent_name: str = None
    ) -> Dict[str, Any]:
        """
        Ask an agent or the CIO about a hypothetical scenario.

        Args:
            scenario: The hypothetical scenario
            agent_name: Optional specific agent (uses CIO routing if None)

        Returns:
            Dict with the agent's updated view given the scenario
        """
        prompt = f"""HYPOTHETICAL SCENARIO: {scenario}

Given this hypothetical, update your view. Walk through:
1. How does this change the current picture?
2. What positions would you adjust?
3. What's the new risk/reward?

Be specific about numbers and trades."""

        if agent_name:
            return self.router.chat_direct(agent_name, prompt, persist=False)
        else:
            return self.router.route(prompt, persist=False)


class CrossExaminationMode:
    """
    Have the adversarial agent attack another agent's thesis.
    """

    def __init__(self, router: CIOChatRouter):
        self.router = router

    def cross_examine(
        self,
        target_agent: str,
    ) -> Dict[str, Any]:
        """
        Have the adversarial agent attack another agent's current thesis.

        Args:
            target_agent: The agent whose thesis to attack

        Returns:
            Dict with the attack and target's defense
        """
        # Get target's current brief
        brief = self.router._load_agent_brief(target_agent)
        if not brief:
            return {"error": f"No brief found for {target_agent}"}

        brief_summary = json.dumps(brief, indent=2, default=str)

        # Adversarial attack
        attack_prompt = f"""Attack this thesis from the {target_agent} agent:

```json
{brief_summary}
```

Systematically challenge every assumption. Find the fatal flaws.
What are they missing? What could kill this trade?"""

        attack = self.router.chat_direct('adversarial', attack_prompt, persist=False)

        # Target's defense
        defense_prompt = f"""The adversarial agent challenges your thesis:

{attack['response']}

Defend your view. Acknowledge valid points but explain why your thesis still holds (if it does).
If they've found a fatal flaw, acknowledge it."""

        defense = self.router.chat_direct(target_agent, defense_prompt, persist=False)

        return {
            "target_agent": target_agent,
            "target_brief": brief,
            "adversarial_attack": attack['response'],
            "target_defense": defense['response'],
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_router() -> CIOChatRouter:
    """Create and return a CIO Chat Router instance."""
    return CIOChatRouter()


def chat_with_cio(message: str) -> Dict:
    """Convenience function for CIO chat."""
    router = create_router()
    return router.route(message)


def chat_with_agent(agent_name: str, message: str) -> Dict:
    """Convenience function for direct agent chat."""
    router = create_router()
    return router.chat_direct(agent_name, message)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Chat Router")
    parser.add_argument("--message", "-m", type=str, help="Message to send")
    parser.add_argument("--agent", "-a", type=str, help="Specific agent to chat with")
    parser.add_argument("--test", action="store_true", help="Run test queries")
    args = parser.parse_args()

    router = CIOChatRouter()

    if args.test:
        print("\n" + "=" * 60)
        print("ATLAS Chat Router - Test Mode")
        print("=" * 60)

        test_queries = [
            "What's our biggest risk right now?",
            "Should we add more NVDA?",
            "Walk me through your inflation thesis",
            "Where do you see the 10-year yield in 6 months?",
        ]

        for query in test_queries:
            print(f"\n{'='*60}")
            print(f"QUERY: {query}")
            print("=" * 60)

            agents = router.classify_intent(query)
            print(f"Routed to: {agents}")

    elif args.message:
        if args.agent:
            print(f"\nChatting with {args.agent}...")
            result = router.chat_direct(args.agent, args.message)
        else:
            print("\nChatting with CIO...")
            result = router.route(args.message)

        print(f"\nAgents consulted: {result.get('agents_consulted', [args.agent])}")
        print(f"\nResponse:\n{result['response']}")

    else:
        print("Use --test for test mode or --message 'your question' to chat")
        print("Add --agent druckenmiller to chat with a specific agent")
