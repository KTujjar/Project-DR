// Camera chatbot and scene log, served by the CV service (relief-vision chat.py):
//   POST {cvUrl}/api/cameras/{id}/chat       {messages, site_name} -> {reply, used}
//   GET  {cvUrl}/api/cameras/{id}/scene-log  {enabled, notes: [{time, text}]} (newest first)
// CV-specific, so it lives outside the shared schemas.ts contracts.

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatAnswer {
  reply: string
  used: { image: boolean; minutes: number; scene_notes: number }
}

export interface SceneNote {
  time: string // ISO 8601
  text: string
}

export interface SceneLog {
  enabled: boolean
  notes: SceneNote[]
}

const cameraRoot = (cvUrl: string, cameraId: string) =>
  `${cvUrl.replace(/\/+$/, '')}/api/cameras/${encodeURIComponent(cameraId)}`

// The service puts a human-readable reason in `detail` (e.g. "Add an Anthropic API key…").
async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // not JSON
  }
  return `The camera assistant failed (${res.status}).`
}

export async function askCamera(
  cvUrl: string,
  cameraId: string,
  messages: ChatMessage[],
  siteName?: string,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): Promise<ChatAnswer> {
  const res = await fetchImpl(`${cameraRoot(cvUrl, cameraId)}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, site_name: siteName }),
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  return (await res.json()) as ChatAnswer
}

export async function fetchSceneLog(
  cvUrl: string,
  cameraId: string,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): Promise<SceneLog> {
  const res = await fetchImpl(`${cameraRoot(cvUrl, cameraId)}/scene-log`)
  if (!res.ok) throw new Error(await errorMessage(res))
  return (await res.json()) as SceneLog
}
