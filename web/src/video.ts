// The video card: a 9:16 clip of one answer for TikTok, Reels and Shorts, recorded in the browser.
//
// While Melanie thinks and answers, the scene hands every rendered frame of the real 3D brain to feed() (see
// Scene.tsx). We crop around the brain, lay the question, the answer and the verdict over it in the site's look,
// draw it all onto a 720x1280 canvas and record that canvas with MediaRecorder. Nothing leaves the device.
import { palette } from './palette'

export type ClipText = {
  question: string
  answer: string
  kind: { title: string; line: string; color: string } | null
  stickers: { text: string; color: string }[]
}

const W = 720
const H = 1280
const FPS = 30
const BRAIN = 760 // the brain's square on the card
const GRAPE_SOFT = '#5a4f8a'
const DISPLAY = "'Bagel Fat One', 'Arial Rounded MT Bold', sans-serif"
const UI = "'M PLUS Rounded 1c', 'Arial Rounded MT Bold', 'Segoe UI', sans-serif"
// MP4 first: that is what TikTok and Instagram take. Firefox only records WebM.
const TYPES = ['video/mp4;codecs=avc1.42E01E', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm']

let canvas: HTMLCanvasElement | null = null
let ctx: CanvasRenderingContext2D | null = null
let crop: HTMLCanvasElement | null = null
let recorder: MediaRecorder | null = null
let chunks: Blob[] = []
let text: ClipText = { question: '', answer: '', kind: null, stickers: [] }
let lastDraw = 0
let finishing: Promise<File | null> | null = null

export function videoType() {
  if (typeof MediaRecorder === 'undefined' || !HTMLCanvasElement.prototype.captureStream) return null
  return TYPES.find((t) => MediaRecorder.isTypeSupported(t)) ?? null
}

export const recording = () => recorder !== null && recorder.state === 'recording'

/** Starts a new clip (and drops any unfinished one). Does nothing where the browser can't record. */
export function startClip() {
  cancelClip()
  const type = videoType()
  if (!type) return
  void document.fonts?.load(`64px ${DISPLAY}`)
  void document.fonts?.load(`800 32px ${UI}`)
  canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  ctx = canvas.getContext('2d')
  crop = document.createElement('canvas')
  crop.width = crop.height = BRAIN
  chunks = []
  recorder = new MediaRecorder(canvas.captureStream(FPS), { mimeType: type, videoBitsPerSecond: 5_000_000 })
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
  // No timeslice: one piece at the end gives an MP4 whose header knows the clip's length (with slices, players
  // showed 4 s for an 8 s clip).
  recorder.start()
}

export function setClipText(next: ClipText) {
  text = next
}

/** One rendered frame of the scene. (x, y) is the brain's centre and r its half-width, in canvas pixels. */
export function feed(source: HTMLCanvasElement, x: number, y: number, r: number) {
  if (!recording() || !ctx || !crop) return
  const now = performance.now()
  if (now - lastDraw < 1000 / FPS - 2) return
  lastDraw = now
  // The brain, cut out of the scene as a square around it with soft edges, so it sits on the card's own sky.
  const side = r * 2.5
  const c = crop.getContext('2d')!
  c.globalCompositeOperation = 'source-over'
  c.clearRect(0, 0, BRAIN, BRAIN)
  c.drawImage(source, x - side / 2, y - side / 2, side, side, 0, 0, BRAIN, BRAIN)
  c.globalCompositeOperation = 'destination-in'
  const fade = c.createRadialGradient(BRAIN / 2, BRAIN / 2, BRAIN * 0.3, BRAIN / 2, BRAIN / 2, BRAIN / 2)
  fade.addColorStop(0, 'rgba(0,0,0,1)')
  fade.addColorStop(1, 'rgba(0,0,0,0)')
  c.fillStyle = fade
  c.fillRect(0, 0, BRAIN, BRAIN)
  draw(ctx, crop)
}

/** Records `holdMs` more (the verdict on screen), then returns the clip. */
export function finishClip(holdMs: number, name: string): Promise<File | null> {
  if (finishing) return finishing
  const active = recorder
  if (!active) return Promise.resolve(null)
  finishing = new Promise((resolve) => {
    window.setTimeout(() => {
      if (recorder !== active || active.state !== 'recording') return resolve(null)
      active.onstop = async () => {
        const type = active.mimeType.split(';')[0]
        let blob = new Blob(chunks, { type })
        if (type === 'video/mp4' && blob.size) blob = new Blob([fixMp4Duration(await blob.arrayBuffer())], { type })
        recorder = null
        finishing = null
        resolve(blob.size ? new File([blob], `${name}.${type.includes('mp4') ? 'mp4' : 'webm'}`, { type }) : null)
      }
      active.stop()
    }, holdMs)
  })
  return finishing
}

export function cancelClip() {
  const active = recorder
  recorder = null
  finishing = null
  if (active && active.state !== 'inactive') {
    active.onstop = null
    active.stop()
  }
}

// Chrome's MP4 recorder writes the track length (mdhd) in milliseconds although the track counts in its own
// timescale (30000 per second), so players showed 0.2 s or a few seconds for an 8 s clip. The movie length (mvhd)
// is right: copy it over, converted. Box layout per ISO/IEC 14496-12.
function fixMp4Duration(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  const kind = (at: number) => String.fromCharCode(...bytes.subarray(at + 4, at + 8))
  let movie: { scale: number; duration: number } | null = null
  const walk = (start: number, end: number) => {
    for (let at = start; at + 8 <= end;) {
      const size = view.getUint32(at)
      if (size < 8 || at + size > end) return
      const k = kind(at)
      const body = at + 8
      const v1 = bytes[body] === 1
      if (k === 'moov' || k === 'trak' || k === 'mdia') walk(body, at + size)
      else if (k === 'mvhd') {
        movie = v1
          ? { scale: view.getUint32(body + 20), duration: Number(view.getBigUint64(body + 24)) }
          : { scale: view.getUint32(body + 12), duration: view.getUint32(body + 16) }
      } else if (k === 'mdhd' && movie) {
        const scale = view.getUint32(body + (v1 ? 20 : 12))
        const duration = Math.round((movie.duration * scale) / movie.scale)
        if (v1) view.setBigUint64(body + 24, BigInt(duration))
        else if (duration <= 0xffffffff) view.setUint32(body + 16, duration)
      }
      at += size
    }
  }
  walk(0, bytes.length)
  return buffer
}

// --- Drawing ---------------------------------------------------------------------------------------------------

function draw(g: CanvasRenderingContext2D, brainImage: HTMLCanvasElement) {
  const sky = g.createLinearGradient(0, 0, 0, H)
  sky.addColorStop(0, palette.skyTop)
  sky.addColorStop(1, palette.skyBottom)
  g.fillStyle = sky
  g.fillRect(0, 0, W, H)
  g.fillStyle = 'rgba(255,255,255,0.45)'
  for (let y = 13; y < H; y += 26) for (let x = 13; x < W; x += 26) g.fillRect(x, y, 2, 2)

  // Header: the wordmark and what this is.
  outlined(g, 'FlyFate', W / 2, 92, `66px ${DISPLAY}`, '#fff', 11)
  g.font = `800 25px ${UI}`
  g.fillStyle = palette.grape
  g.textAlign = 'center'
  g.fillText('I asked a real fruit fly brain', W / 2, 140)

  g.font = `800 31px ${UI}`
  const qLines = wrap(g, text.question, 600).slice(0, 3)
  const qHeight = qLines.length * 40 + 30

  // Melanie's card from the bottom up, so a long answer pushes into the brain, not off the card.
  g.font = `800 36px ${UI}`
  const aLines = wrap(g, text.answer, 600).slice(0, 5)
  g.font = `800 23px ${UI}`
  const rows = stickerRows(g, text.stickers)
  const verdict = text.kind ? 140 + rows.length * 58 + (rows.length ? 12 : 0) : 0
  const cardHeight = 70 + Math.max(1, aLines.length) * 46 + verdict
  const cardTop = H - 104 - cardHeight

  // The brain fills the space between the question and the card; question and card are drawn over its edges.
  const brainTop = Math.min(168 + qHeight - 30, cardTop - BRAIN + 150)
  g.drawImage(brainImage, (W - BRAIN) / 2, brainTop)

  // The question, as the dark speech bubble from the app.
  g.font = `800 31px ${UI}`
  g.textAlign = 'center'
  pill(g, (W - 640) / 2, 168, 640, qHeight, 24, palette.grape)
  g.fillStyle = '#fff'
  qLines.forEach((line, i) => g.fillText(line, W / 2, 168 + 44 + i * 40))

  pill(g, 30, cardTop + 6, W - 60, cardHeight, 34, palette.grape)
  pill(g, 30, cardTop, W - 60, cardHeight, 34, '#fff', palette.grape, 5)
  g.save()
  g.translate(78, cardTop + 2)
  g.rotate(-0.05)
  pill(g, -14, -26, 164, 50, 25, palette.flyRed, palette.grape, 4)
  outlined(g, 'Melanie', 68, 12, `30px ${DISPLAY}`, '#fff', 6)
  g.restore()

  g.textAlign = 'left'
  g.fillStyle = palette.grape
  g.font = `800 36px ${UI}`
  aLines.forEach((line, i) => g.fillText(line, 64, cardTop + 76 + i * 46))

  if (text.kind) {
    let y = cardTop + 76 + aLines.length * 46 + 40
    g.textAlign = 'left'
    outlined(g, text.kind.title, 64, y, `56px ${DISPLAY}`, text.kind.color, 10, 'left')
    y += 44
    g.font = `700 25px ${UI}`
    g.fillStyle = GRAPE_SOFT
    g.fillText(text.kind.line, 64, y)
    y += 24
    g.font = `800 23px ${UI}`
    for (const row of rows) {
      let x = 64
      for (const s of row) {
        const w = g.measureText(s.text).width + 32
        pill(g, x, y + 4, w, 46, 16, palette.grape)
        pill(g, x, y, w, 46, 16, tint(s.color), palette.grape, 3)
        g.fillStyle = palette.grape
        g.fillText(s.text, x + 16, y + 31)
        x += w + 12
      }
      y += 58
    }
  }

  // Where to go: the one line that matters on a video.
  g.textAlign = 'center'
  g.font = `800 29px ${UI}`
  g.fillStyle = palette.grape
  g.fillText('Ask her yourself at flyfate.com', W / 2, H - 46)
}

function outlined(g: CanvasRenderingContext2D, s: string, x: number, y: number, font: string, fill: string,
  stroke: number, align: CanvasTextAlign = 'center') {
  g.font = font
  g.textAlign = align
  g.lineJoin = 'round'
  g.lineWidth = stroke
  g.strokeStyle = palette.grape
  g.fillStyle = palette.grape
  g.fillText(s, x, y + 5) // the drop shadow of the site's display type
  g.strokeText(s, x, y + 5)
  g.strokeText(s, x, y)
  g.fillStyle = fill
  g.fillText(s, x, y)
}

function pill(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number, fill: string,
  stroke?: string, width = 0) {
  g.beginPath()
  g.roundRect(x, y, w, h, r)
  g.fillStyle = fill
  g.fill()
  if (stroke) {
    g.lineWidth = width
    g.strokeStyle = stroke
    g.stroke()
  }
}

// The sticker colour, lightened like the app's stickers (30% colour on white).
function tint(hex: string) {
  const n = parseInt(hex.slice(1), 16)
  const mix = (c: number) => Math.round(c * 0.3 + 255 * 0.7)
  return `rgb(${mix(n >> 16)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`
}

// The stickers in rows that fit the card (at most two rows).
function stickerRows(g: CanvasRenderingContext2D, stickers: ClipText['stickers']) {
  const rows: ClipText['stickers'][] = []
  let x = Infinity
  for (const s of stickers) {
    const w = g.measureText(s.text).width + 32
    if (x + w > W - 60) {
      if (rows.length === 2) break
      rows.push([])
      x = 64
    }
    rows[rows.length - 1].push(s)
    x += w + 12
  }
  return rows
}

function wrap(g: CanvasRenderingContext2D, s: string, width: number) {
  const lines: string[] = []
  let line = ''
  for (const word of s.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word
    if (line && g.measureText(next).width > width) {
      lines.push(line)
      line = word
    } else line = next
  }
  if (line) lines.push(line)
  return lines
}
