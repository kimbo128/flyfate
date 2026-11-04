import { GROUPS } from '../brain/regions'
import { mockStep } from '../brain/activity'
import type { OracleEvents } from './client'

// Offline stand-in when the simulation service is not running (e.g. a static preview).
// The brain activity here is made up; the real one comes from inference/server.py.

const ANSWERS = [
  'Yes! Do it before you talk yourself out of it.',
  'Nope. I smelled trouble and turned around.',
  'Start smaller than you think, then double it.',
]

function hash(s: string) {
  let h = 2166136261
  for (const c of s.toLowerCase().trim()) h = Math.imul(h ^ c.charCodeAt(0), 16777619)
  return h >>> 0
}

export function askMock(question: string, events: OracleEvents) {
  const h = hash(question)
  const focus = [h % GROUPS.length, (h >>> 4) % GROUPS.length, (h >>> 9) % GROUPS.length]
  const answer = ANSWERS[h % ANSWERS.length]
  const timers: number[] = []
  let t = 0
  const at = (fn: () => void, delay: number) => timers.push(window.setTimeout(fn, (t += delay)))

  for (let i = 0; i < Math.round(question.length / 4) + 8; i++) at(() => {
    mockStep(focus, 0.4)
    events.onStep('reading', 2000 + Math.round(Math.random() * 9000))
  }, 55)
  for (const word of answer.split(/(?<=\s)/)) at(() => {
    mockStep(focus, 0.7)
    events.onStep('speaking', 4000 + Math.round(Math.random() * 12000))
    events.onToken(word)
  }, 140)
  // No reading offline: it would be made up.
  at(() => events.onDone(answer, []), 300)
  return () => timers.forEach(clearTimeout)
}
