import type { DataSource } from '../../types/schemas'
import { createMockSource } from './mockSource'

// VITE_DATA_SOURCE=mock|api picks the source. Only mock exists until the backend is ready.
function pickSource(): DataSource {
  const kind = import.meta.env.VITE_DATA_SOURCE ?? 'mock'
  if (kind !== 'mock') console.warn(`Data source "${kind}" not available yet, using mock`)
  return createMockSource()
}

export const dataSource: DataSource = pickSource()
