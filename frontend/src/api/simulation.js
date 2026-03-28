import service from './index'

export function getEntities(graphId) {
  return service.get(`/simulation/entities/${graphId}`)
}

export function createSimulation(data) {
  return service.post('/simulation/create', data)
}

export function prepareSimulation(data) {
  return service.post('/simulation/prepare', data)
}

export function prepareStatus(data) {
  return service.post('/simulation/prepare/status', data)
}

export function startSimulation(data) {
  return service.post('/simulation/start', data)
}

export function stopSimulation(data) {
  return service.post('/simulation/stop', data)
}

export function getRunStatus(simulationId) {
  return service.get(`/simulation/${simulationId}/run-status`)
}

export function getProfiles(simulationId) {
  return service.get(`/simulation/${simulationId}/profiles`)
}

export function getConfig(simulationId) {
  return service.get(`/simulation/${simulationId}/config`)
}

export function getPosts(simulationId, params) {
  return service.get(`/simulation/${simulationId}/posts`, { params })
}
