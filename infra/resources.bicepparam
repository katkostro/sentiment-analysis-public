using 'main.bicep'

param baseName = 'sentiment'
param location = 'eastus2'
param gptModelName = 'gpt-4o'
param gptModelVersion = '2024-11-20'
param gptCapacity = 10
param tags = {
  project: 'sentiment-analysis'
  environment: 'dev'
}
