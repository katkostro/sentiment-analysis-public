"""
Create and register the Sentiment Analysis agent in Azure AI Foundry.

Supports two tool modes controlled by LANGUAGE_TOOL_MODE in .env:

  sdk  (default) — Agent calls Azure AI Language via function tools that the
                   app intercepts and executes locally using the Python SDK.
                   Works today with managed identity. Switch to this when
                   the MCP transport issue is unresolved.

  mcp            — Agent calls Language via the MCP server (requires the
                   Foundry Agent Service to support Streamable HTTP transport,
                   currently in preview and using SSE which is incompatible
                   with the Language MCP server's POST-only endpoint).

Run after deploying infrastructure:
  azd provision --environment sentiment-analysis-mcp

Then:
  python src/create_agent.py
"""

from __future__ import annotations

import os
import json
import sys

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import McpTool, ToolSet, MCPToolResource, FunctionTool

# ─── Configuration ───────────────────────────────────────────────────────────

AI_SERVICES_ENDPOINT = os.environ["AZURE_AI_SERVICES_ENDPOINT"]
LANGUAGE_ENDPOINT = os.environ["AZURE_LANGUAGE_ENDPOINT"]
FOUNDRY_PROJECT = os.environ.get("FOUNDRY_PROJECT_NAME", "sentiment-analysis")
GPT_DEPLOYMENT = os.environ.get("GPT_DEPLOYMENT_NAME", "gpt-4o")

# sdk  → function tools executed locally via Language SDK (works today)
# mcp  → Language MCP server (requires Agent Service Streamable HTTP support)
TOOL_MODE = os.environ.get("LANGUAGE_TOOL_MODE", "sdk").lower()

LANGUAGE_MCP_URL = (
    f"{AI_SERVICES_ENDPOINT.rstrip('/')}/language/mcp?api-version=2025-11-15-preview"
)

# ─── System prompts ───────────────────────────────────────────────────────────

_COMMON_INSTRUCTIONS = """
Data sources:
- Survey responses pre-extracted from Excel/CSV files by the UI

When you receive survey responses:
- You will receive a numbered list of text responses already extracted from the file
- The user has already selected the correct column(s) and prepared the data
- If analyzing multiple columns, responses will be labeled like "[ColumnName] response text"
- Call the Language analysis tools on the responses (batch up to 10 at a time)
- DO NOT attempt to read files yourself - the responses are already provided as text
- Provide a comprehensive summary of the analysis results

When analyzing multiple columns:
- Consider each column separately when identifying patterns
- Note any differences in sentiment or themes between columns
- Highlight if certain columns have more negative feedback

When presenting results:
- Always show the overall sentiment distribution first
- Surface key phrases and entities as recurring themes
- Highlight any strongly negative responses requiring attention
- Flag any PII found and suggest redaction
- Provide actionable recommendations based on the analysis
- Include confidence scores and explain what they mean
"""

AGENT_SYSTEM_PROMPT_SDK = (
    """You are a Survey Analysis Agent powered by Azure AI Language (SDK function tools).

You have access to these language analysis functions:
- analyze_sentiment      — sentiment (positive/neutral/negative) + opinion mining
- extract_key_phrases    — identify main topics and themes
- recognize_entities     — find people, places, organisations, dates
- recognize_pii_entities — detect and redact personal data
- detect_language        — identify the language of each response

Always batch multiple documents into a single function call (up to 10 per call).
"""
    + _COMMON_INSTRUCTIONS
)

AGENT_SYSTEM_PROMPT_MCP = (
    """You are a Survey Analysis Agent powered by Azure AI Language via MCP.

You have direct access to all Azure AI Language capabilities as MCP tools:
- Sentiment Analysis with opinion mining (document & sentence level)
- Key Phrase Extraction — identify main topics and themes
- Named Entity Recognition (NER) — find people, places, organisations, dates
- PII Detection — detect and flag personal data for redaction
- Language Detection — identify the language of each response
"""
    + _COMMON_INSTRUCTIONS
)


# ─── Agent builders ───────────────────────────────────────────────────────────

def _build_sdk_agent(client: AIProjectClient) -> object:
    """Create agent with Language SDK function tools."""
    from language_tools import TOOL_DEFINITIONS  # local import to avoid SDK dep at top

    # raw_function_defs is a list of {type, function {...}} dicts
    raw_function_defs = TOOL_DEFINITIONS

    return client.agents.create_agent(
        model=GPT_DEPLOYMENT,
        name="sentiment-analysis-agent",
        instructions=AGENT_SYSTEM_PROMPT_SDK,
        tools=raw_function_defs,
        tool_resources=None,
    )


def _build_mcp_agent(client: AIProjectClient) -> object:
    """Create agent with Language MCP server."""
    toolset = ToolSet()
    toolset.add(McpTool(server_label="azure_language", server_url=LANGUAGE_MCP_URL))

    resources = toolset.resources
    resources["mcp"] = [
        MCPToolResource(
            server_label="azure_language",
            headers={},
            require_approval="never",
        )
    ]
    return client.agents.create_agent(
        model=GPT_DEPLOYMENT,
        name="sentiment-analysis-agent",
        instructions=AGENT_SYSTEM_PROMPT_MCP,
        tools=toolset.definitions,
        tool_resources=resources,
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    endpoint = f"{AI_SERVICES_ENDPOINT.rstrip('/')}/api/projects/{FOUNDRY_PROJECT}"
    print(f"Connecting to Foundry project: {endpoint}")
    print(f"Tool mode:                     {TOOL_MODE.upper()}")
    if TOOL_MODE == "mcp":
        print(f"Language MCP server:           {LANGUAGE_MCP_URL}")

    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=endpoint, credential=credential)

    if TOOL_MODE == "mcp":
        agent = _build_mcp_agent(client)
    else:
        # Add src/ to path so language_tools is importable
        sys.path.insert(0, os.path.dirname(__file__))
        agent = _build_sdk_agent(client)

    print("\n✅ Agent created successfully!")
    print(f"   Agent ID:   {agent.id}")
    print(f"   Agent Name: {agent.name}")
    print(f"   Model:      {agent.model}")
    print(f"   Tool mode:  {TOOL_MODE}")

    config = {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "model": agent.model,
        "endpoint": endpoint,
        "tool_mode": TOOL_MODE,
    }
    with open("agent_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print("\n📄 Agent config saved to agent_config.json")


if __name__ == "__main__":
    main()
