# OpenLCA Agent

An intelligent LangGraph-based agent for Life Cycle Assessment (LCA) workflows using OpenLCA software. This agent provides natural language interaction with OpenLCA databases and enables sophisticated product system modeling and environmental impact analysis.

## Features

### 🔍 Product Discovery & Research
- **Explore existing products**: Discover available processes, flows, and product systems in OpenLCA databases
- **Natural language search**: Find specific materials, products, or processes using conversational queries
- **Smart recommendations**: Get intelligent suggestions based on your requirements and context

### 🏗️ Product System Creation
- **Foundation creation**: Build complete product systems from scratch with atomic operations
- **Process conversion**: Transform existing processes into comprehensive product systems
- **Lifecycle modeling**: Create detailed product lifecycles with all necessary components

### ⚙️ Process Enhancement
- **Material addition**: Add materials, inputs, and exchanges to existing processes using natural language
- **Iterative refinement**: Support for ongoing process improvement and refinement
- **Batch operations**: Handle multiple material additions efficiently

### 📊 Environmental Impact Analysis
- **44+ impact methods**: Calculate environmental impacts using IPCC 2021, ReCiPe 2016, TRACI, USEtox, and many others
- **Fuzzy matching**: Intelligent method selection with partial name matching
- **Detailed results**: Comprehensive impact reports with units and categories
- **Historical tracking**: Maintain calculation history across sessions

### 🔄 Workflow Management
- **Complete LCA workflows**: Guide users from exploration to impact calculation
- **Approval processes**: Handle entity creation with human-in-the-loop approvals
- **Session persistence**: Maintain state across complex multi-step analyses
- **Clear guidance**: Provide actionable next steps and recommendations

## Installation

### Prerequisites
- Python 3.11 or higher
- OpenLCA software with IPC server running on `localhost:8080`
- OpenAI API key (for LLM functionality)

### Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd olca-agent
   ```

2. **Create and activate virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -e .
   ```
   
   **Important**: The `-e` flag creates an editable installation that links your source code to the Python environment. This is required for LangGraph to properly import the `olca_agent` module.

4. **Set up environment variables**:
   Create a `.env` file in the project root:
   ```bash
   OPENAI_API_KEY=your_openai_api_key_here
   LANGGRAPH_API_URL=your_langgraph_api_url_here  # Optional for cloud deployment
   ```

5. **Start OpenLCA IPC server**:
   - Launch OpenLCA software
   - Ensure IPC server is running on `localhost:8080`
   - Load your LCA database with impact methods

## Usage

### Basic Commands

#### Start the Agent
```bash
# Using LangGraph CLI (recommended)
langgraph dev

# Or run directly with Python
python -m olca_agent
```

#### Available Graph Configurations
- `olca_agent`: Standard development agent
- `olca_agent_dev`: Development environment with enhanced debugging
- `olca_agent_prod`: Production environment with optimized settings

### Example Workflows

#### 1. Explore Available Products
```python
# Discover existing concrete products
agent.invoke({"messages": [{"role": "user", "content": "explore concrete products"}]})
```

#### 2. Create Product System Foundation
```python
# Create a new product system from scratch
agent.invoke({"messages": [{"role": "user", "content": "create a product system for office desk"}]})
```

#### 3. Add Materials to Process
```python
# Add materials using natural language
agent.invoke({"messages": [{"role": "user", "content": "add 0.5kg of steel and 1kWh electricity to my process"}]})
```

#### 4. Calculate Environmental Impacts
```python
# Calculate impacts using specific method
agent.invoke({"messages": [{"role": "user", "content": "calculate impacts for product system abc-123 using IPCC 2021"}]})
```

### Advanced Usage

#### Custom Impact Methods
The agent supports 44+ impact assessment methods including:
- IPCC 2021 AR6 (default)
- ReCiPe 2016 (Midpoint and Endpoint)
- TRACI 2.1
- USEtox 2
- CML-IA baseline
- And many more...

#### Batch Operations
```python
# Add multiple materials at once
agent.invoke({"messages": [{"role": "user", "content": "add 2kg aluminum, 0.5kWh electricity, 0.1kg plastic to my process"}]})
```

## Architecture

### Core Components

- **LangGraph Integration**: Built on LangGraph for sophisticated state management and workflow orchestration
- **OpenLCA IPC**: Direct integration with OpenLCA software via IPC protocol
- **LLM-Powered**: Uses GPT-4o-mini for natural language understanding and material extraction
- **State Management**: Persistent session state with comprehensive tracking

### Key Tools

1. **`explore_available_products`**: Discover and search existing processes and product systems
2. **`create_product_system_foundation`**: Create complete product systems from scratch
3. **`create_product_system`**: Convert existing processes to product systems
4. **`search_exchanges_for_process`**: Add materials using natural language descriptions
5. **`calculate_product_system_impacts`**: Perform environmental impact calculations

### State Schema

The agent maintains comprehensive state including:
- Created flows and processes
- Current process exchanges
- Impact calculation history
- User preferences and session context

## Development

### Project Structure
```
olca-agent/
├── src/olca_agent/
│   ├── __init__.py          # Package initialization
│   ├── olca_graph.py        # Main LangGraph implementation
│   ├── tools.py             # OpenLCA integration tools
│   └── prompts.py           # Agent prompts and instructions
├── langgraph.json           # LangGraph configuration
├── pyproject.toml           # Project dependencies
└── README.md               # This file
```

### Adding New Features

1. **New Tools**: Add functions to `tools.py` with proper `@tool` decorators
2. **State Extensions**: Update `LCAAnalysisState` in `olca_graph.py`
3. **Prompt Updates**: Modify `prompts.py` for new capabilities
4. **Testing**: Ensure compatibility with OpenLCA IPC protocol

### Dependencies

- **Core**: `langgraph>=0.6.0`, `langchain>=0.2.14`
- **LLM**: `langchain-openai>=0.1.22`, `langchain-anthropic>=0.1.23`
- **OpenLCA**: `olca-schema>=2.4.0`, `olca-ipc`
- **Utilities**: `python-dotenv>=1.0.1`, `tavily-python>=0.7.11`

## Limitations

### What the Agent Cannot Do
- Complex statistical analyses or advanced data science operations
- Access external databases beyond OpenLCA
- Create custom impact assessment methods
- Real-time data collection or external API calls
- Generate custom reports or export formats
- Modify core OpenLCA software or database structure

### Requirements
- OpenLCA software must be running with IPC server
- Database must contain impact assessment methods
- Internet connection for LLM API calls
- Sufficient database permissions for entity creation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Troubleshooting

### Common Issues

#### ModuleNotFoundError: No module named 'olca_agent'
This error occurs when the package isn't properly installed in your Python environment.

**Solution**:
1. Ensure you're in a virtual environment: `source .venv/bin/activate`
2. Install the package in editable mode: `pip install -e .`
3. Verify installation: `python -c "from olca_agent.prompts import OLCA_AGENT_PROMPT; print('Import successful!')"`

#### LangGraph Server Import Errors
If LangGraph can't import your module, ensure:
1. The package is installed in the same Python environment where LangGraph is running
2. You're using the `-e` flag for editable installation
3. Your virtual environment is activated when starting the server

#### Environment Mismatch
If you have multiple Python environments (conda, venv, system), ensure LangGraph is using the same environment where you installed the package.

## Support

For issues and questions:
1. Check the OpenLCA documentation for database setup
2. Ensure IPC server is running on `localhost:8080`
3. Verify your OpenAI API key is correctly configured
4. Review the agent's capabilities and limitations
5. Check the troubleshooting section above for common issues