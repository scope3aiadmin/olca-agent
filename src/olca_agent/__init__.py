"""OpenLCA Agent - A LangGraph-based system for intelligent Life Cycle Assessment.

This package provides natural language interaction with OpenLCA software
through a sophisticated agent architecture with proper state management
and database persistence.
"""
from .olca_graph import (
    LCAAnalysisState,
    create_olca_agent,
    olca_agent,
    olca_agent_dev,
    olca_agent_prod,
)

__version__ = "1.0.0"
__author__ = "OpenLCA Agent Team"

__all__ = [
    "LCAAnalysisState",
    "create_olca_agent",
    "olca_agent",
    "olca_agent_dev",
    "olca_agent_prod",
]
