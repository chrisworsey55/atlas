"""
ATLAS Agent Prompts
System prompts for sector desk, flow, and synthesis agents.
"""
from .alpha_discovery_agent import (
    SYSTEM_PROMPT as ALPHA_DISCOVERY_SYSTEM_PROMPT,
    build_analysis_prompt as build_alpha_analysis_prompt,
    build_chat_prompt as build_alpha_chat_prompt,
)
