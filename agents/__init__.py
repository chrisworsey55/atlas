"""
ATLAS Agents
AI agents for investment research and analysis.
"""
from .sector_desk import (
    SectorDeskAgent,
    SemiconductorDesk,
    BiotechDesk,
    FinancialsDesk,
    EnergyDesk,
    ConsumerDesk,
    IndustrialsDesk,
    get_desk,
    run_semiconductor_analysis,
    run_biotech_analysis,
)
from .institutional_flow_agent import (
    InstitutionalFlowAgent,
    run_flow_analysis,
)
from .cio_agent import (
    CIOAgent,
    run_cio_synthesis,
)
from .adversarial_agent import (
    AdversarialAgent,
)
from .aschenbrenner_agent import (
    AschenbrennerAgent,
    run_aschenbrenner_chat,
)
from .baker_agent import (
    BakerAgent,
    run_baker_chat,
)
from .ackman_agent import (
    AckmanAgent,
    run_ackman_chat,
)
from .news_agent import (
    NewsAgent,
    run_news_scan,
    run_news_chat,
)
from .alpha_discovery_agent import (
    AlphaDiscoveryAgent,
    run_alpha_analysis,
    run_alpha_chat,
)

__all__ = [
    # Base classes
    "SectorDeskAgent",
    # Sector desks
    "SemiconductorDesk",
    "BiotechDesk",
    "FinancialsDesk",
    "EnergyDesk",
    "ConsumerDesk",
    "IndustrialsDesk",
    "get_desk",
    "run_semiconductor_analysis",
    "run_biotech_analysis",
    # Flow agent
    "InstitutionalFlowAgent",
    "run_flow_analysis",
    # CIO agent
    "CIOAgent",
    "run_cio_synthesis",
    # Adversarial agent
    "AdversarialAgent",
    # Superinvestor agents
    "AschenbrennerAgent",
    "run_aschenbrenner_chat",
    "BakerAgent",
    "run_baker_chat",
    "AckmanAgent",
    "run_ackman_chat",
    # News agent
    "NewsAgent",
    "run_news_scan",
    "run_news_chat",
    # Alpha discovery agent
    "AlphaDiscoveryAgent",
    "run_alpha_analysis",
    "run_alpha_chat",
]
