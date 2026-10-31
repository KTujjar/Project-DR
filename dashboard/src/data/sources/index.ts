import type { DataSource } from '../../types/schemas'
import { createApiSource } from './apiSource'
import { createMockSource } from './mockSource'

// VITE_DATA_SOURCE=mock|api picks the source; nothing else in the app changes.
function pickSource(): { source: DataSource; triggerDemoEvent?: () => void } {
  const kind = import.meta.env.VITE_DATA_SOURCE ?? 'mock'
  if (kind === 'api') {
    const baseUrl = import.meta.env.VITE_API_BASE_URL
    if (!baseUrl) throw new Error('VITE_DATA_SOURCE=api needs VITE_API_BASE_URL (see .env.example)')
    return { source: createApiSource(baseUrl) }
  }
  if (kind !== 'mock') console.warn(`Unknown VITE_DATA_SOURCE "${kind}", using mock`)
  const mock = createMockSource()
  return { source: mock, triggerDemoEvent: mock.triggerDemoEvent }
}

const picked = pickSource()

export const dataSource: DataSource = picked.source
// Only the mock can stage the demo event; undefined for real APIs.
export const triggerDemoEvent = picked.triggerDemoEvent
