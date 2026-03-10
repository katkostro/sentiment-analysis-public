# Survey Sentiment Analysis Agent

AI-powered survey analysis using **Azure AI Foundry Agent** with **Azure AI Language** integration. Upload Excel/CSV files through a Streamlit web interface and get comprehensive sentiment analysis, key themes, and actionable recommendations.

## Features

- 📊 **Multi-column analysis** — Select 1-2 columns from Excel/CSV files
- 🤖 **AI-powered insights** — GPT-4o agent with Azure Language integration
- 💬 **Interactive chat** — Ask questions and get detailed analysis
- 📈 **Comprehensive metrics** — Sentiment distribution, themes, key phrases, entities
- 🔒 **Zero API keys** — All auth via managed identity
- ⚡ **Batch processing** — Analyzes up to 100 responses per file

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ User uploads │────►│  Streamlit UI    │────►│  Azure AI        │────►│  Foundry Agent   │
│ Excel / CSV  │     │  - File parsing  │     │  Language SDK    │     │  (GPT-4o)        │
│              │     │  - Column select │     │  - Sentiment     │     │  - Analysis      │
│              │     │  - Preview       │     │  - Key Phrases   │     │  - Insights      │
│              │     │                  │     │  - NER & PII     │     │  - Recommendations│
└─────────────┘     └──────────────────┘     └──────────────────┘     └──────────────────┘
```

### Tool Architecture: Dual-Mode Design

The agent supports two modes for calling Azure AI Language services:

**SDK Mode (Current)** — Function tools executed locally
- Agent calls Language analysis functions (`analyze_sentiment`, `extract_key_phrases`, etc.)
- Streamlit app intercepts tool calls and executes them using Azure Language SDK
- Uses managed identity for authentication
- **Status**: ✅ Working

**MCP Mode (Future)** — Direct MCP server integration
- Agent calls Language services via MCP protocol
- Requires Azure AI Agent Service to support Streamable HTTP transport
- **Status**: ⏸️ Blocked by transport incompatibility (Agent Service uses SSE, Language MCP requires POST)

Mode is controlled by `LANGUAGE_TOOL_MODE` environment variable (defaults to `sdk`).

## Project Structure

```
sentiment-analysis/
├── infra/
│   ├── main.bicep            # Infrastructure-as-Code
│   ├── main.parameters.json  # Parameter values
│   └── resources.bicep       # All Azure resources
├── src/
│   ├── app.py               # Streamlit web UI + file handling
│   ├── create_agent.py      # Agent provisioning (SDK/MCP modes)
│   ├── language_tools.py    # Language SDK function tool implementations
│   └── test_sdk.py          # End-to-end test for SDK mode
├── .env.example             # Environment variable template
├── azure.yaml               # Azure Developer CLI config
└── README.md                # This file
```

## Infrastructure

Provisioned by `infra/resources.bicep` — all resources use **managed identity**:

| Resource | Type | Purpose |
|---|---|---|
| **Azure AI Services** | `Microsoft.CognitiveServices/accounts` (AIServices) | Foundry host + project container |
| **Foundry Project** | `accounts/projects` | `sentiment-analysis` project |
| **GPT-4o** | `accounts/deployments` | Agent's LLM (50K TPM capacity) |
| **Azure AI Language** | `accounts` (TextAnalytics) | NLP APIs for sentiment, NER, key phrases, PII |

### Role Assignments

- AI Services → Language Service: `Cognitive Services User`
- Foundry Project → Language Service: `Cognitive Services User`

## Azure AI Language Capabilities

The agent has access to these Language SDK functions:

| Function | API | Description |
|---|---|---|
| `analyze_sentiment` | Sentiment Analysis | Document & sentence-level sentiment with confidence scores |
| `extract_key_phrases` | Key Phrase Extraction | Identify main topics and themes |
| `recognize_entities` | Named Entity Recognition | Detect people, places, organizations, dates |
| `detect_language` | Language Detection | Identify the language of text |
| `recognize_pii_entities` | PII Detection | Detect personal data (email, phone, SSN, etc.) |

All functions support batching up to 10 documents per call for efficiency.

## Prerequisites

- Azure subscription
- Azure CLI (`az`) or Azure Developer CLI (`azd`)
- Python 3.10+
- Appropriate Azure credits (GPT-4o deployment required)

## Quick Start

### 1. Deploy infrastructure

```powershell
# Authenticate
az login

# Deploy with Azure Developer CLI
azd auth login
azd up
```

This provisions:
- Azure AI Services + Foundry Project
- GPT-4o deployment (50K TPM)
- Azure AI Language service
- Role assignments for managed identity

### 2. Configure environment

Copy `.env.example` to `.env` and fill in the values from deployment outputs:

```env
# Get these from: azd env get-values
AZURE_AI_SERVICES_ENDPOINT=https://...
AZURE_LANGUAGE_ENDPOINT=https://...
FOUNDRY_PROJECT_NAME=sentiment-analysis
GPT_DEPLOYMENT_NAME=gpt-4o

# Tool mode: sdk (default) or mcp (when transport is fixed)
LANGUAGE_TOOL_MODE=sdk
```

### 3. Create the agent

```powershell
python src/create_agent.py
```

This creates the agent in Azure AI Foundry and saves configuration to `agent_config.json`.

### 4. Run the Streamlit app

```powershell
# Load environment variables and start app
Get-Content .env | ForEach-Object { 
    if ($_ -match '^([^#][^=]+)=(.*)') { 
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim()) 
    } 
}
streamlit run src/app.py
```

Open http://localhost:8501 in your browser.

## Usage

### Analyzing Survey Files

1. **Upload File**
   - Click "Browse files" in the sidebar
   - Select an Excel (.xlsx, .xls) or CSV file
   - File is parsed automatically

2. **Select Columns**
   - Choose 1-2 columns to analyze
   - App auto-selects the most likely response column
   - Preview shows sample values from each selected column

3. **Analyze**
   - Click "Analyse File"
   - Agent processes up to 100 responses (first 100 if file is larger)
   - Results show:
     - Overall sentiment distribution (positive/negative/neutral)
     - Key themes and topics
     - Named entities (people, places, organizations)
     - Negative responses requiring attention
     - 3 actionable recommendations

### Multi-Column Analysis

When analyzing 2 columns, the agent will:
- Label responses with `[ColumnName]` prefix
- Identify patterns in each column separately
- Highlight differences in sentiment or themes between columns
- Note if certain columns have more negative feedback

### Chat Interface

After file analysis, you can:
- Ask follow-up questions about the results
- Request specific breakdowns (e.g., "show only negative responses")
- Get clarifications on themes or recommendations

## File Format Support

### Supported Formats

- **Excel**: `.xlsx` (Office Open XML, preferred)
- **Excel**: `.xls` (Legacy format, requires `xlrd`)
- **CSV**: UTF-8, Latin-1, or CP1252 encoding
- **HTML**: Tables in HTML files

### File Handling

- **DRM Detection**: Detects password-protected or DRM-encrypted Excel files
- **Column Detection**: Auto-selects columns with longest text (skips ID columns like "ID", "Code", "Date")
- **Encoding Fallback**: Tries UTF-8 → Latin-1 → CP1252 for CSV files
- **Size Limit**: Processes first 100 responses to avoid rate limits and long runtimes

## Authentication

All authentication uses **Azure Managed Identity** (`DefaultAzureCredential`):

- **No API keys** — `disableLocalAuth: true` on all cognitive services
- **Service-to-service** — RBAC role assignments grant permissions
- **Local development** — Falls back to Azure CLI or VS Code credentials

When running locally, ensure you're logged in:
```powershell
az login
```

## Error Handling

### Rate Limiting

- GPT-4o deployment capacity: 50K TPM (tokens per minute)
- App retries with exponential backoff on rate limit errors
- Parses retry-after from API responses
- Shows progress toasts in UI

### Run Management

- Cancels active runs before posting new messages (prevents "run is active" errors)
- 5-minute timeout for agent runs
- Polls run status with progressive backoff

### File Errors

- DRM-protected files: Shows user guidance to save unprotected copy
- Column detection failure: Shows all columns for manual selection
- Empty columns: Warns user before analysis

## Known Issues

### MCP Transport Incompatibility

**Issue**: Azure AI Agent Service uses SSE (Server-Sent Events) transport for MCP, but Azure Language MCP server requires Streamable HTTP (POST-only).

**Impact**: MCP mode (`LANGUAGE_TOOL_MODE=mcp`) is currently non-functional.

**Workaround**: SDK mode (`LANGUAGE_TOOL_MODE=sdk`) executes Language tools locally via the Python SDK.

**Resolution**: Waiting for Agent Service to add Streamable HTTP support (preview feature).

## Configuration

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `AZURE_AI_SERVICES_ENDPOINT` | Yes | AI Services endpoint (includes Foundry) |
| `AZURE_LANGUAGE_ENDPOINT` | Yes | Language service endpoint |
| `FOUNDRY_PROJECT_NAME` | No | Project name (default: `sentiment-analysis`) |
| `GPT_DEPLOYMENT_NAME` | No | GPT deployment name (default: `gpt-4o`) |
| `LANGUAGE_TOOL_MODE` | No | Tool mode: `sdk` or `mcp` (default: `sdk`) |

### Agent Configuration

`agent_config.json` is created by `create_agent.py` and contains:

```json
{
  "agent_id": "asst_...",
  "agent_name": "sentiment-analysis-agent",
  "endpoint": "https://...",
  "model": "gpt-4o",
  "tool_mode": "sdk"
}
```

## Testing

### Test SDK Mode

```powershell
python src/test_sdk.py
```

This runs an end-to-end test:
1. Creates a thread
2. Sends a test message
3. Waits for agent to call SDK tools
4. Executes tools locally
5. Returns results

Expected output: Sentiment analysis + key phrases for test text.

## Cost Considerations

### Azure Resources

- **Azure AI Services**: AI Services SKU
- **GPT-4o Deployment**: ~$0.03 per 1K input tokens, ~$0.06 per 1K output tokens
- **Language Service**: Standard tier, ~$2 per 1K text records

### Optimization Tips

- Process files in batches (app limits to 100 responses)
- Use multi-column analysis sparingly (doubles API calls)
- Monitor GPT-4o capacity (50K TPM deployed by default)
- Consider lower GPT capacity if budget-constrained (edit `infra/resources.bicep`)

## Development

### Project Stack

- **Frontend**: Streamlit 1.32+
- **Agent SDK**: `azure-ai-agents` 1.2.0b5
- **Language SDK**: `azure-ai-textanalytics` 5.3+
- **Auth**: `azure-identity` 1.15+
- **IaC**: Bicep + Azure Developer CLI

### Adding New Language Capabilities

1. Add function definition to `language_tools.py`:
   ```python
   TOOL_DEFINITIONS.append({
       "type": "function",
       "function": {
           "name": "your_function",
           "description": "...",
           "parameters": { ... }
       }
   })
   ```

2. Implement function in `TOOL_DISPATCH` dict

3. Update agent instructions in `create_agent.py`

4. Recreate agent: `python src/create_agent.py`

## Troubleshooting

### "No assistant found with id 'asst_...'"

**Cause**: Agent was deleted or `agent_config.json` is stale.

**Fix**: Recreate agent:
```powershell
python src/create_agent.py
```
Then restart Streamlit app.

### "Rate limit exceeded"

**Cause**: GPT-4o capacity (50K TPM) exceeded.

**Fix**: 
- App retries automatically with backoff
- Wait for rate limit window to reset
- Or increase capacity in `infra/resources.bicep` (edit `gptCapacity`)

### File Upload Issues

**Cause**: DRM protection, unsupported format, or encoding issues.

**Fix**:
- For DRM files: Save unprotected copy in Excel
- For encoding: Convert CSV to UTF-8
- For unsupported formats: Convert to .xlsx or .csv

### Agent Not Responding

**Cause**: Active run blocking the thread.

**Fix**: App auto-cancels active runs. If issue persists:
```powershell
# Create new conversation
# Click "🗑️ New Conversation" in sidebar
```

## License

MIT

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Test changes with `src/test_sdk.py`
4. Submit a pull request

## Support

For issues or questions:
- File an issue on GitHub
- Check Azure AI Foundry documentation
- Review Azure Language service docs
