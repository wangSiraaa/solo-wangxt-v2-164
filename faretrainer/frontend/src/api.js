// 极简 API 封装。后端是 DRF JSON，全部接口只读或在沙箱内写培训数据。
const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.note || data.failure_reason
      || `HTTP ${res.status}`)
    err.payload = data
    err.status = res.status
    throw err
  }
  return data
}

export const api = {
  airports: () => request('/airports/'),
  flights: () => request('/flights/'),
  fares: () => request('/fares/'),
  taxes: () => request('/taxes/'),
  versions: () => request('/rule-versions/'),
  price: (payload) => request('/quotes/price/', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  issue: (quoteId) => request(`/quotes/${quoteId}/issue_training/`, {
    method: 'POST',
  }),
  tickets: () => request('/tickets/'),
  change: (payload) => request('/changes/quote/', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  commit: (changeId) => request(`/changes/${changeId}/commit/`, {
    method: 'POST',
  }),
}
