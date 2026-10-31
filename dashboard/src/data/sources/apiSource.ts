import type { DashboardSnapshot, DataSource, Dispatch } from '../../types/schemas'

// Talks to the team backend. Endpoints are listed in CLAUDE.md ("Expected endpoints").
// Any non-2xx response throws, so the store keeps the last good data and backs off.
export function createApiSource(baseUrl: string, fetchImpl: typeof fetch = (...args) => fetch(...args)): DataSource {
  const root = baseUrl.replace(/\/+$/, '')

  async function request(path: string, init?: RequestInit): Promise<Response> {
    const res = await fetchImpl(`${root}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
    if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status} ${res.statusText}`)
    return res
  }

  const post = async (path: string, body?: unknown) => {
    await request(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
  }

  return {
    async getSnapshot() {
      const res = await request('/api/snapshot')
      return (await res.json()) as DashboardSnapshot
    },
    approveDispatch: (id) => post(`/api/dispatches/${encodeURIComponent(id)}/approve`),
    cancelDispatch: (id) => post(`/api/dispatches/${encodeURIComponent(id)}/cancel`),
    createDispatch: (dispatch: Dispatch) => post('/api/dispatches', dispatch),
    sendText: (phone, body) => post('/api/messages', { phone, body }),
  }
}
