#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Deploy the Sentiment Analysis Foundry agent infrastructure and create the agent.

.DESCRIPTION
  Uses Azure Developer CLI (azd) to provision infrastructure and then creates
  the Foundry agent. Equivalent to running:
    azd up
    python src/create_agent.py

.PARAMETER EnvironmentName
  azd environment name. Default: sentiment-analysis

.PARAMETER Location
  Azure region. Default: eastus2
#>

param(
    [string]$EnvironmentName = "sentiment-analysis",
    [string]$Location = "eastus2"
)

$ErrorActionPreference = "Stop"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Sentiment Analysis Agent - Deployment" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# ─── 1. Provision with azd ──────────────────────────────────────────────────

Write-Host "1/3  Provisioning infrastructure with azd ..." -ForegroundColor Yellow
azd env new $EnvironmentName --no-prompt 2>$null
azd env set AZURE_LOCATION $Location
azd up --no-prompt
Write-Host "     Done.`n" -ForegroundColor Green

# ─── 2. Write .env from azd outputs ────────────────────────────────────────

Write-Host "2/3  Writing .env from azd outputs ..." -ForegroundColor Yellow
$aiEndpoint    = azd env get-value AZURE_AI_SERVICES_ENDPOINT
$langEndpoint  = azd env get-value AZURE_LANGUAGE_ENDPOINT
$gptDeployment = azd env get-value AZURE_GPT_DEPLOYMENT_NAME

@"
AZURE_AI_SERVICES_ENDPOINT=$aiEndpoint
AZURE_LANGUAGE_ENDPOINT=$langEndpoint
FOUNDRY_PROJECT_NAME=sentiment-analysis
GPT_DEPLOYMENT_NAME=$gptDeployment
DATA_SOURCE=local
"@ | Set-Content -Path .env -Encoding utf8
Write-Host "     .env file written.`n" -ForegroundColor Green

# ─── 3. Create Foundry Agent ────────────────────────────────────────────────

Write-Host "3/3  Creating Foundry agent ..." -ForegroundColor Yellow
pip install -r src/requirements.txt -q
# Load .env into current session
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
    }
}
python src/create_agent.py
Write-Host "`n     Done.`n" -ForegroundColor Green

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Deployment Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "`nTo chat with the agent:" -ForegroundColor White
Write-Host "  python src/chat_with_agent.py" -ForegroundColor Gray
Write-Host "`nTo analyse a file:" -ForegroundColor White
Write-Host "  python src/chat_with_agent.py --file 'Survey Samples.xlsx'" -ForegroundColor Gray
Write-Host "`nTo run all Language capabilities on a file:" -ForegroundColor White
Write-Host "  python src/sentiment_agent.py 'Survey Samples.xlsx' --all-capabilities" -ForegroundColor Gray
Write-Host "`nAvailable capabilities: sentiment, key-phrases, entities, pii," -ForegroundColor Gray
Write-Host "  entity-linking, language-detection, abstractive-summary, extractive-summary" -ForegroundColor Gray
Write-Host "`nTo switch to Fabric OneLake: set DATA_SOURCE=fabric in .env" -ForegroundColor Gray
