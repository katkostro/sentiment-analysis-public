// Provisions an Azure AI Foundry project for sentiment analysis
// Resources: AI Services (Foundry), Project, GPT-4o deployment, AI Language
// All service-to-service auth uses managed identity (no API keys)
// Data source: local files (default) or Microsoft Fabric OneLake (set enableFabric = true)

targetScope = 'resourceGroup'

// ─── Parameters ─────────────────────────────────────────────────────────────

@description('Base name used to derive resource names')
@minLength(3)
param baseName string

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('GPT model to deploy as the agent backbone')
param gptModelName string = 'gpt-4o'

@description('GPT model version')
param gptModelVersion string = '2024-11-20'

@description('Capacity (TPM in thousands) for the GPT deployment')
param gptCapacity int = 50

@description('Tags applied to every resource')
param tags object = {}

@description('Enable Microsoft Fabric OneLake connection as data source (requires Fabric workspace)')
param enableFabric bool = false

@description('Fabric OneLake endpoint URL (required when enableFabric = true)')
param fabricOneLakeEndpoint string = ''

// ─── Derived names ──────────────────────────────────────────────────────────

var uniqueSuffix = uniqueString(resourceGroup().id, baseName)
var aiServicesName = '${baseName}-ais-${uniqueSuffix}'
var languageName = '${baseName}-lang-${uniqueSuffix}'
var projectName = 'sentiment-analysis'

// ─── Well-known role definition IDs ─────────────────────────────────────────

var roles = {
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
}

// ─── Azure AI Services account (hosts the Foundry project) ─────────────────

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: aiServicesName
  location: location
  tags: tags
  kind: 'AIServices'
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: aiServicesName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true // enforce managed identity, no API keys
    allowProjectManagement: true
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

// ─── Foundry Project ────────────────────────────────────────────────────────

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: aiServices
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Sentiment Analysis Agent'
    description: 'AI Foundry project that hosts an agent for analysing survey sentiment using Azure AI Language.'
  }
}

// ─── GPT-4o Model Deployment (agent backbone) ──────────────────────────────

resource gptDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiServices
  name: 'gpt-4o'
  sku: {
    name: 'GlobalStandard'
    capacity: gptCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: gptModelName
      version: gptModelVersion
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// ─── Azure AI Language (Text Analytics / Sentiment) ────────────────────────

resource languageService 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: languageName
  location: location
  tags: tags
  kind: 'TextAnalytics'
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'S'
  }
  properties: {
    customSubDomainName: languageName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true // enforce managed identity, no API keys
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

// ─── Project connection to Language service (AAD / managed identity) ───────

resource languageConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: foundryProject
  name: 'language-sentiment'
  properties: {
    authType: 'AAD'
    category: 'CognitiveService'
    target: languageService.properties.endpoint
    useWorkspaceManagedIdentity: true
    metadata: {
      Kind: 'AIServices'
      ApiType: 'azure'
      ResourceId: languageService.id
    }
  }
}

// ─── Fabric OneLake connection (opt-in) ────────────────────────────────────
// Flip enableFabric = true and provide fabricOneLakeEndpoint to connect
// Source Data → Fabric OneLake → Fabric Data Agent → this Foundry Agent

resource fabricConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = if (enableFabric) {
  parent: foundryProject
  name: 'fabric-onelake'
  properties: {
    authType: 'AAD'
    category: 'AzureOneLake'
    target: fabricOneLakeEndpoint
    useWorkspaceManagedIdentity: true
    metadata: {
      Kind: 'AzureOneLake'
      ApiType: 'azure'
    }
  }
}

// ─── Role assignments ──────────────────────────────────────────────────────

// AI Services identity → Cognitive Services User on Language service
resource aiServicesLanguageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(languageService.id, aiServices.id, roles.cognitiveServicesUser)
  scope: languageService
  properties: {
    principalId: aiServices.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      roles.cognitiveServicesUser
    )
  }
}

// Foundry Project identity → Cognitive Services User on Language service
resource projectLanguageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(languageService.id, foundryProject.id, roles.cognitiveServicesUser)
  scope: languageService
  properties: {
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      roles.cognitiveServicesUser
    )
  }
}

// ─── Outputs ────────────────────────────────────────────────────────────────

@description('AI Services endpoint')
output aiServicesEndpoint string = aiServices.properties.endpoint

@description('Foundry project endpoint for agent API calls')
output foundryProjectEndpoint string = '${aiServices.properties.endpoint}api/projects/${projectName}'

@description('AI Language endpoint for sentiment analysis')
output languageEndpoint string = languageService.properties.endpoint

@description('Fabric OneLake enabled')
output fabricEnabled bool = enableFabric

@description('Resource group name')
output resourceGroupName string = resourceGroup().name

@description('GPT deployment name')
output gptDeploymentName string = gptDeployment.name
