import type { DataSource } from '../../types/schemas'
import { createMockSource } from './mockSource'

// VITE_DATA_SOURCE=mock|api picks the source. Only mock exists until the backend is ready.
function pickSource(): { source: DataSource; triggerDemoEvent?: () => void } {
  const kind = import.meta.env.VITE_DATA_SOURCE ?? 'mock'
  if (kind !== 'mock') console.warn(`Data source "${kind}" not available yet, using mock`)
  const mock = createMockSource()
  return { source: mock, triggerDemoEvent: mock.triggerDemoEvent }
}

const picked = pickSource()

export const dataSource: DataSource = picked.source
// Only the mock can stage the demo event; undefined for real APIs.
export const triggerDemoEvent = picked.triggerDemoEvent
