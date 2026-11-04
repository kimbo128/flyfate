// Synthesized sound: Melanie's voice, the wing buzz while she thinks, pops and the verdict chime.
//
// Everything plays into one bus. The bus feeds the speakers (silent when muted) and a stream tap, so the video
// card (video.ts) records the sound even when the page is muted. The AudioContext starts on the first question
// (a user gesture).

let ctx: AudioContext | undefined
let bus: GainNode | undefined
let speakers: GainNode | undefined
let tap: MediaStreamAudioDestinationNode | undefined
let muted = (() => {
  try {
    return localStorage.getItem('fly-oracle-muted') === '1'
  } catch {
    return false
  }
})()
let buzz: { osc: OscillatorNode; gain: GainNode } | undefined

export const isMuted = () => muted

export function setMuted(value: boolean) {
  muted = value
  try {
    localStorage.setItem('fly-oracle-muted', value ? '1' : '0')
  } catch {
    /* storage blocked */
  }
  if (ctx && speakers) speakers.gain.setTargetAtTime(value ? 0 : 1, ctx.currentTime, 0.02)
}

function audio() {
  if (!ctx) {
    ctx = new AudioContext()
    bus = ctx.createGain()
    speakers = ctx.createGain()
    speakers.gain.value = muted ? 0 : 1
    tap = ctx.createMediaStreamDestination()
    bus.connect(speakers).connect(ctx.destination)
    bus.connect(tap)
  }
  if (ctx.state === 'suspended') void ctx.resume()
  return { a: ctx, out: bus! }
}

/** The sound as a track for the video recorder. Call from a user gesture, so the context may start. */
export function audioTrack() {
  try {
    audio()
    return tap?.stream.getAudioTracks()[0] ?? null
  } catch {
    return null
  }
}

function tone(freq: number, length: number, type: OscillatorType, volume: number, delay = 0, slide = 1) {
  const { a, out } = audio()
  const t = a.currentTime + delay
  const osc = a.createOscillator()
  const gain = a.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(freq, t)
  osc.frequency.exponentialRampToValueAtTime(freq * slide, t + length)
  gain.gain.setValueAtTime(volume, t)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + length)
  osc.connect(gain).connect(out)
  osc.start(t)
  osc.stop(t + length + 0.02)
}

// --- Melanie's voice ------------------------------------------------------------------------------------------
// Not words but a tiny creature's babble: one sung syllable per vowel group as the typewriter reaches it. Each
// vowel gets its own two formants (pitched up for a fly-sized throat), so "no" and "yes" sound different. A light
// wing-buzz vibrato rides on every syllable; the pitch drifts down over a sentence like speech does, questions
// rise at the end, and an exclamation mark lifts the whole sentence.

const FORMANTS: Record<string, [number, number]> = {
  a: [1250, 1900], e: [800, 2900], i: [560, 3400], o: [850, 1400], u: [600, 1250], y: [560, 3400],
}
const VOWEL = /[aeiouy]/i
const BASE = 560

function syllable(vowel: string, pitch: number, loud: number) {
  const { a, out } = audio()
  const t = a.currentTime
  const length = 0.13
  const osc = a.createOscillator()
  osc.type = 'sawtooth'
  // A little scoop into the note and a fall off it, like a sung syllable.
  osc.frequency.setValueAtTime(pitch * 1.1, t)
  osc.frequency.exponentialRampToValueAtTime(pitch, t + 0.04)
  osc.frequency.exponentialRampToValueAtTime(pitch * 0.92, t + length)
  const wings = a.createOscillator()
  const depth = a.createGain()
  wings.frequency.value = 23
  depth.gain.value = pitch * 0.025
  wings.connect(depth).connect(osc.frequency)
  const env = a.createGain()
  env.gain.setValueAtTime(0.0001, t)
  // Loud before the filters: the narrow formant bands keep only a small part of the sawtooth's energy.
  env.gain.exponentialRampToValueAtTime(0.6 * loud, t + 0.015)
  env.gain.exponentialRampToValueAtTime(0.0001, t + length)
  for (const f of FORMANTS[vowel] ?? FORMANTS.a) {
    const band = a.createBiquadFilter()
    band.type = 'bandpass'
    band.frequency.value = f
    band.Q.value = 5
    osc.connect(band).connect(env)
  }
  env.connect(out)
  osc.start(t)
  wings.start(t)
  osc.stop(t + length + 0.02)
  wings.stop(t + length + 0.02)
}

// Same word, same note: a stable pitch per word from its letters.
function wordPitch(word: string) {
  let h = 0
  for (const c of word.toLowerCase()) h = (h * 31 + c.charCodeAt(0)) % 997
  return 1 + ((h % 7) - 3) * 0.035
}

/** Called for each letter the typewriter reveals; sings when a new vowel group starts. */
export function voice(text: string, index: number) {
  const char = text[index]
  if (!char || !VOWEL.test(char) || VOWEL.test(text[index - 1] ?? '')) return
  // The sentence and word this vowel belongs to.
  const start = Math.max(text.lastIndexOf('.', index), text.lastIndexOf('!', index), text.lastIndexOf('?', index)) + 1
  const ends = ['.', '!', '?'].map((p) => text.indexOf(p, index)).filter((i) => i >= 0)
  const end = ends.length ? Math.min(...ends) : text.length
  const sentence = text.slice(start, end + 1)
  const progress = (index - start) / Math.max(1, end - start)
  const wordStart = text.lastIndexOf(' ', index) + 1
  const wordEnd = text.indexOf(' ', index)
  const word = text.slice(wordStart, wordEnd < 0 ? undefined : wordEnd)
  const lastWord = wordEnd < 0 || wordEnd >= end
  let pitch = BASE * wordPitch(word) * (1.08 - 0.16 * progress)
  if (sentence.endsWith('?') && lastWord) pitch *= 1.3
  if (sentence.endsWith('!')) pitch *= 1.12
  // Short answers like "Yes!" or "No." get said with conviction.
  const loud = start === 0 && word.length <= 4 && index === text.search(VOWEL) ? 1.4 : 1
  syllable(char.toLowerCase(), pitch, loud)
}

export const pop = (i = 0) => tone(520 + i * 140, 0.12, 'sine', 0.12, i * 0.09, 2.2)

export function chime() {
  ;[784, 988, 1175].forEach((f, i) => tone(f, 0.35, 'triangle', 0.09, i * 0.08))
}

export function startBuzz() {
  if (buzz) return
  const { a, out } = audio()
  const osc = a.createOscillator()
  const gain = a.createGain()
  const lfo = a.createOscillator()
  const depth = a.createGain()
  osc.type = 'sawtooth'
  osc.frequency.value = 190
  lfo.frequency.value = 23
  depth.gain.value = 14
  lfo.connect(depth).connect(osc.frequency)
  gain.gain.setValueAtTime(0.0001, a.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.018, a.currentTime + 0.2)
  osc.connect(gain).connect(out)
  osc.start()
  lfo.start()
  osc.onended = () => lfo.stop()
  buzz = { osc, gain }
}

export function stopBuzz() {
  if (!buzz || !ctx) return
  buzz.gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25)
  buzz.osc.stop(ctx.currentTime + 0.3)
  buzz = undefined
}
