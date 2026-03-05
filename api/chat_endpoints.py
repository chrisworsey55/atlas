"""
ATLAS Chat API Endpoints
Flask routes for the chat system.

Endpoints:
- POST /api/atlas/chat - CIO unified chat
- POST /api/atlas/chat/<agent_name> - Direct agent chat
- GET /api/atlas/chat/<agent_name>/history - Get conversation history
- DELETE /api/atlas/chat/<agent_name>/history - Clear conversation
- GET /api/atlas/agents/status - Get all agent statuses
"""
import logging
from pathlib import Path

from flask import Blueprint, request, jsonify

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.chat_router import (
    CIOChatRouter,
    DebateMode,
    WhatIfMode,
    CrossExaminationMode,
)

logger = logging.getLogger(__name__)

# Create blueprint
chat_bp = Blueprint('chat', __name__, url_prefix='/api/atlas')

# Global router instance (lazy loaded)
_router = None


def get_router() -> CIOChatRouter:
    """Get or create the global router instance."""
    global _router
    if _router is None:
        _router = CIOChatRouter()
    return _router


# =============================================================================
# CIO UNIFIED CHAT
# =============================================================================

@chat_bp.route('/chat', methods=['POST'])
def cio_chat():
    """
    CIO unified chat endpoint.
    Routes to appropriate agents and synthesizes response.

    Request body:
    {
        "message": "What should we do today?",
        "persist": true  // optional, default true
    }

    Response:
    {
        "response": "...",
        "agents_consulted": ["druckenmiller", "bond", "cio"],
        "agent_briefs": {...},
        "routing_reason": "...",
        "conversation_length": 5
    }
    """
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Missing 'message' in request body"}), 400

        message = data['message']
        persist = data.get('persist', True)

        router = get_router()
        result = router.route(message, persist=persist)

        return jsonify(result)

    except Exception as e:
        logger.error(f"CIO chat error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# DIRECT AGENT CHAT
# =============================================================================

@chat_bp.route('/chat/<agent_name>', methods=['POST'])
def agent_chat(agent_name: str):
    """
    Direct agent chat endpoint.
    Talks to a single agent without routing.

    Request body:
    {
        "message": "Defend your TLT short thesis",
        "persist": true  // optional, default true
    }

    Response:
    {
        "agent": "druckenmiller",
        "response": "...",
        "signal": "AGGRESSIVE",
        "confidence": 0.85,
        "brief_date": "2026-03-03T01:39:00",
        "conversation_length": 3
    }
    """
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Missing 'message' in request body"}), 400

        message = data['message']
        persist = data.get('persist', True)

        router = get_router()
        result = router.chat_direct(agent_name, message, persist=persist)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Agent chat error for {agent_name}: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# CONVERSATION HISTORY
# =============================================================================

@chat_bp.route('/chat/<agent_name>/history', methods=['GET'])
def get_agent_history(agent_name: str):
    """
    Get conversation history for an agent.

    Response:
    {
        "agent": "druckenmiller",
        "messages": [
            {"role": "user", "content": "...", "timestamp": "..."},
            {"role": "assistant", "content": "...", "timestamp": "..."}
        ]
    }
    """
    try:
        router = get_router()

        if agent_name.lower() == 'cio':
            messages = router.get_cio_history()
        else:
            messages = router.get_agent_history(agent_name)

        return jsonify({
            "agent": agent_name,
            "messages": messages
        })

    except Exception as e:
        logger.error(f"Get history error for {agent_name}: {e}")
        return jsonify({"error": str(e)}), 500


@chat_bp.route('/chat/<agent_name>/history', methods=['DELETE'])
def clear_agent_history(agent_name: str):
    """
    Clear conversation history for an agent.

    Response:
    {
        "agent": "druckenmiller",
        "status": "cleared"
    }
    """
    try:
        router = get_router()

        if agent_name.lower() == 'cio':
            router.clear_cio_history()
        else:
            router.clear_agent_history(agent_name)

        return jsonify({
            "agent": agent_name,
            "status": "cleared"
        })

    except Exception as e:
        logger.error(f"Clear history error for {agent_name}: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# AGENT STATUS
# =============================================================================

@chat_bp.route('/agents/status', methods=['GET'])
def get_agents_status():
    """
    Get status of all agents (latest brief date, signal, conversation length).

    Response:
    {
        "agents": {
            "druckenmiller": {
                "has_brief": true,
                "brief_date": "2026-03-03T01:39:00",
                "signal": "AGGRESSIVE",
                "confidence": 0.85,
                "conversation_messages": 5
            },
            ...
        }
    }
    """
    try:
        router = get_router()
        statuses = router.get_all_agent_statuses()

        return jsonify({"agents": statuses})

    except Exception as e:
        logger.error(f"Get agents status error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# SPECIAL INTERACTION MODES
# =============================================================================

@chat_bp.route('/chat/debate', methods=['POST'])
def debate():
    """
    Have two agents debate a topic.

    Request body:
    {
        "topic": "Should we buy NVDA?",
        "agent_a": "semiconductor",
        "agent_b": "adversarial",
        "rounds": 2  // optional, default 2
    }

    Response:
    {
        "topic": "...",
        "agent_a": "semiconductor",
        "agent_b": "adversarial",
        "transcript": [...],
        "cio_verdict": "..."
    }
    """
    try:
        data = request.get_json()
        if not data or 'topic' not in data:
            return jsonify({"error": "Missing 'topic' in request body"}), 400

        topic = data['topic']
        agent_a = data.get('agent_a', 'fundamental')
        agent_b = data.get('agent_b', 'adversarial')
        rounds = data.get('rounds', 2)

        router = get_router()
        debate_mode = DebateMode(router)

        result = debate_mode.debate(topic, agent_a, agent_b, rounds)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Debate error: {e}")
        return jsonify({"error": str(e)}), 500


@chat_bp.route('/chat/whatif', methods=['POST'])
def what_if():
    """
    Ask about a hypothetical scenario.

    Request body:
    {
        "scenario": "What if CPI comes in at 3.5%?",
        "agent": "druckenmiller"  // optional, uses CIO routing if not specified
    }

    Response:
    {
        "agent": "druckenmiller",
        "response": "...",
        ...
    }
    """
    try:
        data = request.get_json()
        if not data or 'scenario' not in data:
            return jsonify({"error": "Missing 'scenario' in request body"}), 400

        scenario = data['scenario']
        agent = data.get('agent')

        router = get_router()
        whatif_mode = WhatIfMode(router)

        result = whatif_mode.what_if(scenario, agent)

        return jsonify(result)

    except Exception as e:
        logger.error(f"What-if error: {e}")
        return jsonify({"error": str(e)}), 500


@chat_bp.route('/chat/cross-examine/<target_agent>', methods=['POST'])
def cross_examine(target_agent: str):
    """
    Have the adversarial agent attack another agent's thesis.

    Response:
    {
        "target_agent": "druckenmiller",
        "target_brief": {...},
        "adversarial_attack": "...",
        "target_defense": "..."
    }
    """
    try:
        router = get_router()
        cross_exam = CrossExaminationMode(router)

        result = cross_exam.cross_examine(target_agent)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Cross-examination error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# REGISTRATION HELPER
# =============================================================================

def register_chat_routes(app):
    """Register chat blueprint with Flask app."""
    app.register_blueprint(chat_bp)
    logger.info("Registered ATLAS chat routes")


if __name__ == "__main__":
    # Test mode - run as standalone Flask app
    from flask import Flask

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    app = Flask(__name__)
    register_chat_routes(app)

    print("\n" + "=" * 60)
    print("ATLAS Chat API - Test Server")
    print("=" * 60)
    print("\nEndpoints:")
    print("  POST /api/atlas/chat - CIO unified chat")
    print("  POST /api/atlas/chat/<agent> - Direct agent chat")
    print("  GET  /api/atlas/chat/<agent>/history - Get history")
    print("  DELETE /api/atlas/chat/<agent>/history - Clear history")
    print("  GET  /api/atlas/agents/status - All agent statuses")
    print("  POST /api/atlas/chat/debate - Agent debate")
    print("  POST /api/atlas/chat/whatif - What-if scenarios")
    print("  POST /api/atlas/chat/cross-examine/<agent> - Cross examination")
    print("\n")

    app.run(debug=True, port=5001)
