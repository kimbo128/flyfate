import { applyFrame, resetFrames } from '../brain/activity'
import { askMock } from './mock'

// One measured line of the brain reading, computed by the simulation over the whole question and answer.
export type Reading = {
  region: number // index into the brain regions
  factor: number // how much more it rattled than usual (1.08 = 8 % more)
  active: number // its neurons that fired hard
  neurons: number // all its neurons
  types: [string, number][] // real MaleCNS cell types leading, with counts
}

export type OracleEvents = {
  // Called once per real graph step. `active` = neurons that changed clearly in this step.
  onStep: (phase: 'reading' | 'speaking', active: number) => void
  onToken: (text: string) => void
  // `id` is the answer's share link (/o/{id}); none for answers that aren't shared (serious topics, offline).
  onDone: (answer: string, reading: Reading[], id?: string) => void
  // Waiting behind other visitors; position 1 = next.
  onQueue?: (position: number) => void
  // Refused by a rate limit or a full queue: a message for the visitor and seconds until they can ask again.
  onLimit?: (message: string, retryAfter: number) => void
  onOffline?: () => void
}

type Step = { phase: 'reading' | 'speaking'; regions: number[]; beads: string; active: number; text?: string }

const decode = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))

export type SharedOracle = { id: string; question: string; answer: string; reading: Reading[] }

// A shared answer, for visitors arriving on /o/{id}.
export async function fetchShared(id: string): Promise<SharedOracle | null> {
  try {
    const res = await fetch(`/api/oracle/${encodeURIComponent(id)}`)
    return res.ok ? ((await res.json()) as SharedOracle) : null
  } catch {
    return null
  }
}

// The visitor shared this answer: only shared answers may be indexed by search engines.
export function markShared(id: string) {
  void fetch(`/api/oracle/${encodeURIComponent(id)}/shared`, { method: 'POST' }).catch(() => undefined)
}

export type SaveResult = { saved?: boolean; sent?: boolean; error?: string }

// Save an answer to the public archive. Logged in: saved at once. Otherwise an email with a confirmation link
// goes out, and the same link logs the person in.
export async function saveToArchive(id: string, email?: string): Promise<SaveResult> {
  try {
    const res = await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, email }),
    })
    const body = (await res.json()) as SaveResult
    return res.ok ? body : { error: body.error ?? 'Something went wrong. Please try again.' }
  } catch {
    return { error: "Couldn't reach Melanie just now. Please try again." }
  }
}

// Who is logged in (null: nobody), whether this answer is in their collection, and whether email links can go out.
export async function whoAmI(id?: string): Promise<{ user: { email: string } | null; saved?: boolean; mail?: boolean }> {
  try {
    const res = await fetch(`/api/me${id ? `?id=${encodeURIComponent(id)}` : ''}`)
    return res.ok ? await res.json() : { user: null }
  } catch {
    return { user: null }
  }
}

// Streams real graph frames from the simulation service; falls back to the mock when it is not running.
export function ask(question: string, events: OracleEvents) {
  resetFrames()
  let cancelMock: (() => void) | undefined
  let received = false
  const source = new EventSource(`/api/ask?q=${encodeURIComponent(question)}`)

  source.addEventListener('step', (e) => {
    received = true
    const step: Step = JSON.parse((e as MessageEvent).data)
    applyFrame(step.regions, decode(step.beads))
    events.onStep(step.phase, step.active)
    if (step.text) events.onToken(step.text)
  })
  source.addEventListener('queue', (e) => {
    received = true
    events.onQueue?.(JSON.parse((e as MessageEvent).data).position)
  })
  source.addEventListener('limit', (e) => {
    received = true
    source.close()
    const limit = JSON.parse((e as MessageEvent).data) as { message: string; retry_after: number }
    events.onLimit?.(limit.message, limit.retry_after)
  })
  source.addEventListener('done', (e) => {
    source.close()
    const done = JSON.parse((e as MessageEvent).data) as { answer: string; reading: Reading[]; id?: string }
    // A serious question gets its answer without any graph steps: speak it in one go.
    if (!received) {
      events.onStep('speaking', 0)
      events.onToken(done.answer)
    }
    received = true
    events.onDone(done.answer, done.reading, done.id ?? undefined)
  })
  source.onerror = () => {
    source.close()
    if (received) return
    events.onOffline?.()
    cancelMock = askMock(question, events)
  }
  return () => {
    source.close()
    cancelMock?.()
  }
}
