// azd entry point — creates the resource group and deploys all resources
targetScope = 'subscription'

@description('Name of the azd environment (used to derive resource group name)')
@minLength(3)
@maxLength(64)
param environmentName string

@description('Azure region for all resources')
@metadata({
  azd: {
    type: 'location'
  }
})
param location string

@description('GPT model to deploy as the agent backbone')
param gptModelName string = 'gpt-4o'

@description('GPT model version')
param gptModelVersion string = '2024-11-20'

@description('Capacity (TPM in thousands) for the GPT deployment')
param gptCapacity int = 10

@description('Enable Microsoft Fabric OneLake connection as data source')
param enableFabric bool = false

@description('Fabric OneLake endpoint URL (required when enableFabric = true)')
param fabricOneLakeEndpoint string = ''

var tags = {
  'azd-env-name': environmentName
  project: 'sentiment-analysis'
}

var resourceGroupName = 'rg-${environmentName}'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  scope: rg
  name: 'sentiment-analysis-resources'
  params: {
    baseName: environmentName
    location: location
    gptModelName: gptModelName
    gptModelVersion: gptModelVersion
    gptCapacity: gptCapacity
    tags: tags
    enableFabric: enableFabric
    fabricOneLakeEndpoint: fabricOneLakeEndpoint
  }
}

// ─── Outputs (consumed by azd as env vars) ──────────────────────────────────

output AZURE_AI_SERVICES_ENDPOINT string = resources.outputs.aiServicesEndpoint
output AZURE_LANGUAGE_ENDPOINT string = resources.outputs.languageEndpoint
output AZURE_FOUNDRY_PROJECT_ENDPOINT string = resources.outputs.foundryProjectEndpoint
output AZURE_GPT_DEPLOYMENT_NAME string = resources.outputs.gptDeploymentName
output AZURE_RESOURCE_GROUP string = rg.name
