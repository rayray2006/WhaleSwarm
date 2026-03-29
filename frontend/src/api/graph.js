import service from './index'

export function generateOntology(formData) {
  return service.post('/graph/ontology/generate', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

export function buildGraph(data) {
  return service.post('/graph/build', data)
}

export function getProject(projectId) {
  return service.get(`/graph/project/${projectId}`)
}

export function getTask(taskId) {
  return service.get(`/graph/task/${taskId}`)
}

export function getGraph(graphId) {
  return service.get(`/graph/${graphId}`)
}

export function searchPolymarkets(query) {
  return service.post('/graph/polymarket-search', { query })
}

export function polymarketSetup(data) {
  return service.post('/graph/polymarket-setup', data, { timeout: 180000 })
}
