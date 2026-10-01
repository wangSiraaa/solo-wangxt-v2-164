// 后端金额一律为字符串；所有展示/加总在前端也用 decimal.js，杜绝 JS 浮点误差。
// 例：0.1 + 0.2 在 Number 下是 0.30000000000000004，Decimal 下严格 0.3。
import Decimal from 'decimal.js'

export function d(value) {
  return new Decimal(value === null || value === undefined || value === '' ? '0' : value)
}

export function cny(value) {
  return '¥' + d(value).toFixed(2)
}

export function sumBy(list, key) {
  return list.reduce((acc, item) => acc.plus(d(item[key])), new Decimal('0'))
}

async function request(url, options = {}) {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const body = await resp.json()
  if (!resp.ok && body.error) {
    const err = new Error(body.error.message || '请求失败')
    err.payload = body
    throw err
  }
  return body
}

export const api = {
  airports: () => request('/api/airports/'),
  flights: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== '' && v != null),
    ).toString()
    return request(`/api/flights/${qs ? `?${qs}` : ''}`)
  },
  fares: () => request('/api/fares/'),
  fareVersions: (id) => request(`/api/fares/${id}/versions/`),
  quote: (segments) =>
    request('/api/quote/', { method: 'POST', body: JSON.stringify({ segments }) }),
  rebook: (pnr, changes) =>
    request('/api/rebook/', { method: 'POST', body: JSON.stringify({ pnr, changes }) }),
}
