// Adapter for the local Python text feature. This is separate from the team's
// snapshot API: a community report is not an inventory or dispatch transaction.

export interface RelayInterpretation {
  purposes: string[]
  needs: { item: string | null; quantity: number | null; unit: string | null }[]
  location: string | null
  access_barriers: string[]
  delivery_report: string | null
  responder_summary: string
  unanswered_questions: string[]
  evidence: { message_id: string; quote: string }[]
}

export interface RelayCase {
  id: string
  conversation_id: string
  original_message: string
  community_reply: string
  created_at: string
  status: string
  mode: 'preview' | 'live'
  review_required: boolean
  clarifying_questions: string[]
  interpretation: RelayInterpretation
  sources: { id: string; title: string; answer: string; updated_at: string }[]
  schema_version?: number
  sender_name?: string
  contact?: string
  reported_location?: string
  channel?: 'web' | 'demo'
  processing_status?: 'processing' | 'ready' | 'unavailable'
  review_status?: 'new' | 'needs_information' | 'replied'
  suggested_reply?: string
  reply_text?: string | null
  reply_sent_at?: string | null
  updated_at?: string
  analysis_error?: string | null
}

export interface RelayHealth {
  mode: 'preview' | 'live'
  model: string | null
  examples: { label: string; text: string }[]
  inbox_version?: number
}

export interface IntakeMessage {
  conversation_id: string
  sender_name: string
  text: string
  contact?: string
  reported_location?: string
  channel?: 'web' | 'demo'
}

export interface ThreadMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  created_at: string
  kind?: string
}

export function mergeCommunityInbox(current: RelayCase[], incoming: RelayCase[]): RelayCase[] {
  const latest = new Map<string, RelayCase>()
  for (const item of [...current, ...incoming]) {
    const old = latest.get(item.conversation_id)
    if (!old || item.created_at > old.created_at
      || (item.id === old.id && (item.updated_at ?? item.created_at) >= (old.updated_at ?? old.created_at))) {
      latest.set(item.conversation_id, item)
    }
  }
  return [...latest.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 100)
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((v) => typeof v === 'string')
const nullableString = (value: unknown) => value === null || typeof value === 'string'

export function isRelayCase(value: unknown): value is RelayCase {
  if (!isRecord(value) || !isRecord(value.interpretation)) return false
  const p = value.interpretation
  return ['id', 'conversation_id', 'original_message', 'community_reply', 'created_at', 'status'].every((key) => typeof value[key] === 'string')
    && (value.mode === 'preview' || value.mode === 'live')
    && typeof value.review_required === 'boolean'
    && strings(value.clarifying_questions)
    && strings(p.purposes) && strings(p.access_barriers) && strings(p.unanswered_questions)
    && nullableString(p.location) && nullableString(p.delivery_report)
    && typeof p.responder_summary === 'string'
    && Array.isArray(p.needs) && p.needs.every((n) => isRecord(n) && nullableString(n.item) && nullableString(n.unit)
      && (n.quantity === null || (typeof n.quantity === 'number' && Number.isInteger(n.quantity) && n.quantity > 0)))
    && Array.isArray(p.evidence) && p.evidence.every((e) => isRecord(e) && typeof e.message_id === 'string' && typeof e.quote === 'string')
    && Array.isArray(value.sources) && value.sources.every((s) => isRecord(s)
      && ['id', 'title', 'answer', 'updated_at'].every((key) => typeof s[key] === 'string'))
}

// A poll that began before a submission must not hide the newly returned card.
export function mergeRelayCases(current: RelayCase[], incoming: RelayCase[]): RelayCase[] {
  const byId = new Map(current.map((entry) => [entry.id, entry]))
  incoming.forEach((entry) => byId.set(entry.id, entry))
  return [...byId.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 100)
}

export function createRelayTextApi(baseUrl = '/relay-api', fetchImpl: typeof fetch = (...args) => fetch(...args)) {
  const root = baseUrl.replace(/\/+$/, '')

  async function request(path: string, init?: RequestInit): Promise<unknown> {
    let response: Response
    try {
      response = await fetchImpl(`${root}${path}`, init)
    } catch {
      throw new Error('Cannot reach the text service. Start the Python backend on port 8000, then retry.')
    }
    let data: unknown
    try {
      data = await response.json()
    } catch {
      throw new Error('The text service returned a non-JSON response. Check the backend and development proxy.')
    }
    if (!response.ok) {
      throw new Error(isRecord(data) && typeof data.detail === 'string' ? data.detail : `Text service error (${response.status}).`)
    }
    return data
  }

  return {
    async inbox(): Promise<RelayCase[]> {
      const data = await request('/inbox')
      if (!isRecord(data) || !Array.isArray(data.items) || !data.items.every((item) => isRelayCase(item) && item.schema_version === 2)) {
        throw new Error('Update the Python text backend to enable the shared community inbox.')
      }
      return data.items as RelayCase[]
    },
    async intake(message: IntakeMessage): Promise<RelayCase> {
      const data = await request('/intake', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(message) })
      if (!isRelayCase(data)) throw new Error('The message receipt was not valid. Check the text service.')
      return data
    },
    async thread(conversationId: string): Promise<ThreadMessage[]> {
      const data = await request(`/conversations/${encodeURIComponent(conversationId)}`)
      if (!isRecord(data) || !Array.isArray(data.messages) || !data.messages.every((item) => isRecord(item)
        && typeof item.id === 'string' && typeof item.text === 'string' && typeof item.created_at === 'string'
        && (item.role === 'user' || item.role === 'assistant'))) {
        throw new Error('The conversation could not be loaded.')
      }
      return data.messages as ThreadMessage[]
    },
    async reply(caseId: string, text: string, awaitingInformation = false): Promise<RelayCase> {
      const data = await request(`/inbox/${encodeURIComponent(caseId)}/reply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, awaiting_information: awaitingInformation }),
      })
      if (!isRelayCase(data)) throw new Error('The reply result was not valid.')
      return data
    },
    async retry(caseId: string): Promise<RelayCase> {
      const data = await request(`/inbox/${encodeURIComponent(caseId)}/retry`, { method: 'POST' })
      if (!isRelayCase(data)) throw new Error('The retry result was not valid.')
      return data
    },
    async health(): Promise<RelayHealth> {
      const data = await request('/health')
      if (!isRecord(data) || (data.mode !== 'preview' && data.mode !== 'live') || !nullableString(data.model)
        || !Array.isArray(data.examples) || !data.examples.every((e) => isRecord(e) && typeof e.label === 'string' && typeof e.text === 'string')) {
        throw new Error('Unexpected text-service health response. Use the Relay text backend.')
      }
      return data as unknown as RelayHealth
    },
    async cases(conversationId: string): Promise<RelayCase[]> {
      const data = await request(`/requests?conversation_id=${encodeURIComponent(conversationId)}`)
      if (!isRecord(data) || !Array.isArray(data.items) || !data.items.every(isRelayCase)) {
        throw new Error('The text service returned an invalid responder card.')
      }
      return data.items
    },
    async send(conversationId: string, text: string): Promise<RelayCase> {
      const data = await request('/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: conversationId, text }),
      })
      if (!isRelayCase(data)) throw new Error('The text service returned an invalid responder card.')
      return data
    },
  }
}
