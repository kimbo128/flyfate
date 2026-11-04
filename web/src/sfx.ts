// Tiny synthesized sound effects. The AudioContext starts on the first question (a user gesture).

let ctx: AudioContext | undefined
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
  if (value) stopBuzz()
}

function audio() {
  if (muted) return undefined
  ctx ??= new AudioContext()
  if (ctx.state === 'suspended') void ctx.resume()
  return ctx
}

function tone(freq: number, length: number, type: OscillatorType, volume: number, delay = 0, slide = 1) {
  const a = audio()
  if (!a) return
  const t = a.currentTime + delay
  const osc = a.createOscillator()
  const gain = a.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(freq, t)
  osc.frequency.exponentialRampToValueAtTime(freq * slide, t + length)
  gain.gain.setValueAtTime(volume, t)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + length)
  osc.connect(gain).connect(a.destination)
  osc.start(t)
  osc.stop(t + length + 0.02)
}

// Dialogue voice: one short blip per letter, pitch wobbling around Melanie's voice.
export function blip(char: string) {
  if (!/[a-z0-9]/i.test(char)) return
  const step = (char.toLowerCase().charCodeAt(0) * 7) % 9
  tone(620 + step * 38, 0.045, 'square', 0.035)
}

export const pop = (i = 0) => tone(520 + i * 140, 0.12, 'sine', 0.12, i * 0.09, 2.2)

export function chime() {
  ;[784, 988, 1175].forEach((f, i) => tone(f, 0.35, 'triangle', 0.09, i * 0.08))
}

export function startBuzz() {
  const a = audio()
  if (!a || buzz) return
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
  osc.connect(gain).connect(a.destination)
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
