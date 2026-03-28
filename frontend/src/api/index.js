import axios from 'axios'

const service = axios.create({
  baseURL: '/api',
  timeout: 300000,  // 5 minutes — LLM calls can be slow
})

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

export async function requestWithRetry(fn, maxRetries = 3, delay = 1000) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn()
    } catch (e) {
      if (i === maxRetries - 1) throw e
      await sleep(delay)
    }
  }
}

export default service
