import service from './index'

export function generateReport(data) {
  return service.post('/report/generate', data)
}

export function getReportStatus(reportId) {
  return service.get(`/report/${reportId}/status`)
}

export function getReport(reportId) {
  return service.get(`/report/${reportId}`)
}

export function conversation(reportId, data) {
  return service.post(`/report/${reportId}/conversation`, data)
}
