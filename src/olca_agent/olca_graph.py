import os  # noqa: D100
from typing import Annotated, Any, Dict, List, NotRequired, Optional, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Load environment variables
load_dotenv()

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent

from olca_agent.prompts import OLCA_AGENT_PROMPT
from olca_agent.tools import (
    calculate_product_system_impacts,
    create_product_system,
    create_product_system_foundation,
    explore_available_products,
    search_exchanges_for_process,
)


# Simplified state schema for OLCA agent
class LCAAnalysisState(TypedDict):
    """Simplified state schema for OLCA agent."""
    
    # Core LangGraph state (required by create_react_agent)
    messages: Annotated[List, add_messages]
    remaining_steps: int  # Required by create_react_agent
    
    # OLCA-specific state (optional - will be initialized with defaults if not provided)
    created_flows: NotRequired[List[str]]  # UUIDs of created flows
    created_processes: NotRequired[List[str]]  # UUIDs of created processes
    current_process_exchanges: NotRequired[List[Dict[str, Any]]]  # Exchange data being built
    process_building_stage: NotRequired[Optional[str]]  # "foundation", "exchanges", "complete"
    
    # Impact calculation state (optional)
    calculated_impacts: NotRequired[List[Dict[str, Any]]]  # History of impact calculations
    preferred_impact_method: NotRequired[Optional[str]]  # User's preferred impact method
    
    # Error handling (optional)
    critical_error: NotRequired[Optional[bool]]


def create_olca_agent():
    """Create OLCA agent using modern create_react_agent pattern."""
    # Define the model
    model = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.1,
    )
    
    # Define tools
    tools = [
        explore_available_products,
        create_product_system_foundation,
        create_product_system,
        search_exchanges_for_process,
        calculate_product_system_impacts,
    ]

    # Create the agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        state_schema=LCAAnalysisState,
        prompt=OLCA_AGENT_PROMPT,
        checkpointer=InMemorySaver() if not os.getenv("LANGGRAPH_API_URL") else None,
    )
    
    return agent


# Create the agent instance
olca_agent = create_olca_agent()


# For backward compatibility, create aliases
olca_agent_dev = olca_agent
olca_agent_prod = olca_agent
