import { useProgress } from '@react-three/drei'
import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type Ref } from 'react'
import { brain, focusRegion, highlight, type Phase } from './brain/activity'
import { GROUPS, aboutRoi, cellFamily, groupOf, plainName, roiLabel } from './brain/regions'
import { Scene } from './brain/Scene'
import { ask, fetchOthers, fetchShared, markShared, saveToArchive, whoAmI, type OtherQuestion, type Reading }
  from './oracle/client'
import { chime, isMuted, pop, setMuted, startBuzz, stopBuzz, voice } from './sfx'
import { cancelClip, finishClip, setClipText, startClip, videoType } from './video'

const EXAMPLES = ['Should I text them back?', 'Pizza or sushi tonight?', 'Is it time to quit my job?', 'Should I adopt a cat?']
const NEURONS = 166700
const CHARS_PER_SECOND = 38
// The video card keeps recording this long once the verdict is on screen.
const VIDEO_HOLD_MS = 3500
// The maker's credit: subtle, and tagged so the blog's own analytics see where visitors came from.
const AUTHOR_URL = 'https://arturmarkus.com/?utm_source=flyfate&utm_medium=referral&utm_campaign=credit'
const REPO_URL = 'https://github.com/kimbo128/flyfate'

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  useEffect(() => {
    const m = matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduced(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return reduced
}

// One region of the brain reading, in plain words with the scientific terms alongside.
function describe(r: Reading) {
  const roi = brain.names[r.region]
  const percent = Math.round((r.factor - 1) * 100)
  const types = r.types.map(([name]) => name)
  const family = types.length ? cellFamily(types[0]) : undefined
  // "24 of its 648 neurons fired hard. Led by TuBu07 and TuBu09 cells, neurons that carry the sky view to the compass."
  const fired = r.active
    ? `${r.active.toLocaleString('en')} of its ${r.neurons.toLocaleString('en')} neurons fired hard.`
    : `All ${r.neurons.toLocaleString('en')} of its neurons buzzed a little harder together.`
  const led = types.length ? ` Led by ${types.join(' and ')} cells${family ? `, ${family}` : ''}.` : ''
  return {
    roi,
    plain: plainName(roi),
    label: roiLabel(roi),
    group: groupOf(roi),
    about: aboutRoi(roi),
    buzz: percent > 0 ? `+${percent}%` : '±0%',
    measured: fired + led,
  }
}

// 75 -> "1:15", 4000 -> "1 h 7 min"
function formatWait(seconds: number) {
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)} h ${Math.ceil((seconds % 3600) / 60)} min`
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

// A shared answer's page: /o/{id}
const SHARED_PATH = /^\/o\/([0-9A-Za-z]{6,16})\/?$/

type Service = 'checking' | 'warming' | 'ready' | 'offline'

// The service sleeps when nobody asks, and needs a while on its very first start (it fetches the fly data).
// Poll until it's up. A sleeping service may answer the first requests with a 502 while it wakes, so errors
// count as waking for up to a minute; only then (e.g. a static preview) fall back to the offline demo.
const WAKE_ATTEMPTS = 20

function useBrainService() {
  const [service, setService] = useState<Service>('checking')
  useEffect(() => {
    let timer = 0
    let failures = 0
    const check = async () => {
      try {
        const res = await fetch('/api/health')
        const body = (await res.json()) as { ready: boolean; stage: string }
        if (body.ready) return setService('ready')
        if (body.stage === 'failed') return setService('offline')
        setService('warming')
      } catch {
        if (++failures >= WAKE_ATTEMPTS) return setService('offline')
        setService('warming')
      }
      timer = window.setTimeout(check, 3000)
    }
    void check()
    return () => clearTimeout(timer)
  }, [])
  return service
}

export default function App() {
  const reducedMotion = useReducedMotion()
  // Loading screen until the brain model and data are in. 'ready' flips once the scene has mounted.
  const { progress, active: loading } = useProgress()
  const [ready, setReady] = useState(false)
  const service = useBrainService()
  const loaded = ready && !loading && (service === 'ready' || service === 'offline')
  const [phase, setPhaseState] = useState<Phase>('idle')
  const [question, setQuestion] = useState('')
  const [draft, setDraft] = useState('')
  const [answer, setAnswer] = useState('')
  const [typed, setTyped] = useState(0)
  const [streamDone, setStreamDone] = useState(false)
  const [active, setActive] = useState(0)
  const [reading, setReading] = useState<Reading[]>([])
  // Brain tour: which line of the reading the camera has flown to (-1 = none).
  const [tour, setTourState] = useState(-1)
  const tourPanel = useRef<HTMLElement>(null)
  const [offline, setOffline] = useState(false)
  // Place in the queue while other visitors' questions run, and a message when a limit kicked in.
  const [inLine, setInLine] = useState(0)
  const [notice, setNotice] = useState<{ message: string; until: number } | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const waitSeconds = notice ? Math.max(0, Math.ceil((notice.until - now) / 1000)) : 0
  const [muted, setMutedState] = useState(isMuted)
  const [shared, setShared] = useState<'' | 'link' | 'copied'>('')
  // Saving to the archive: the email form is open; who is logged in; whether this answer is in their collection.
  const [saving, setSaving] = useState(false)
  const [user, setUser] = useState<{ email: string } | null>(null)
  const [collected, setCollected] = useState(false)
  // Whether the server can send email links; without, saving is only offered to people already logged in.
  const [mailReady, setMailReady] = useState(false)
  // The current answer's share link id, and whether this visit arrived through someone's shared link.
  const [shareId, setShareId] = useState<string | null>(null)
  // The 9:16 video of this answer (video.ts): recorded while Melanie thinks, ready shortly after the verdict.
  const [video, setVideo] = useState<File | null>(null)
  const [makingVideo, setMakingVideo] = useState(false)
  // A few questions other people asked, on the start page (fresh pick each time Melanie is waiting).
  const [others, setOthers] = useState<OtherQuestion[]>([])
  const [fromLink, setFromLink] = useState(() => SHARED_PATH.test(location.pathname))
  const cancel = useRef<() => void>(undefined)
  const input = useRef<HTMLInputElement>(null)
  const about = useRef<HTMLDialogElement>(null)
  const [placeholder] = useState(() => EXAMPLES[Math.floor(Math.random() * EXAMPLES.length)])

  const setPhase = (p: Phase) => {
    brain.phase = p
    setPhaseState(p)
    if (p !== 'verdict') setTour(-1)
  }

  function setTour(i: number) {
    setTourState(i)
    focusRegion(i >= 0 && reading[i] ? reading[i].region : -1)
  }

  useEffect(() => () => cancel.current?.(), [])

  // Countdown while a rate limit is active.
  useEffect(() => {
    if (!notice) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [notice])

  // Typewriter: reveal the streamed answer letter by letter, with Melanie's voice (one syllable per vowel group).
  useEffect(() => {
    if (typed >= answer.length) return
    const id = window.setTimeout(() => {
      voice(answer, typed)
      setTyped((n) => n + 1)
    }, reducedMotion ? 0 : 1000 / CHARS_PER_SECOND)
    return () => clearTimeout(id)
  }, [typed, answer, reducedMotion])

  // Verdict once the stream is complete and every letter is on screen. The address bar becomes the share link,
  // so copying the URL shares this answer too.
  useEffect(() => {
    if (!streamDone || typed < answer.length || phase !== 'speaking') return
    highlight(reading.map((r) => r.region))
    setPhase('verdict')
    chime()
    reading.forEach((_, i) => pop(i))
    if (shareId) history.replaceState(null, '', `/o/${shareId}`)
    void finishClip(VIDEO_HOLD_MS, `flyfate-${shareId ?? 'answer'}`).then((file) => {
      setVideo(file)
      setMakingVideo(false)
    })
  }, [streamDone, typed, answer, phase, reading, shareId])

  // Arriving on a shared link: show that verdict straight away, once the brain is there to light up.
  useEffect(() => {
    if (!loaded || !fromLink) return
    const id = location.pathname.match(SHARED_PATH)?.[1]
    if (!id) return
    let gone = false
    void fetchShared(id).then((found) => {
      if (gone) return
      if (!found) {
        history.replaceState(null, '', '/')
        setFromLink(false)
        return
      }
      setQuestion(found.question)
      setAnswer(found.answer)
      setTyped(found.answer.length)
      setReading(found.reading)
      setShareId(found.id)
      highlight(found.reading.map((r) => r.region))
      setPhase('verdict')
    })
    return () => {
      gone = true
    }
  }, [loaded, fromLink])

  useEffect(() => {
    if (phase !== 'idle' || !loaded) return
    let gone = false
    void fetchOthers().then((found) => {
      if (!gone) setOthers(found)
    })
    return () => {
      gone = true
    }
  }, [phase, loaded])

  // On each verdict: who is logged in, and whether this answer is already in their collection.
  useEffect(() => {
    if (phase !== 'verdict' || !shareId) return
    let gone = false
    void whoAmI(shareId).then((me) => {
      if (gone) return
      setUser(me.user)
      setMailReady(Boolean(me.mail))
      setCollected(Boolean(me.saved))
    })
    return () => {
      gone = true
      setSaving(false)
    }
  }, [phase, shareId])

  // The tab title follows the page, like the server-rendered one does for crawlers.
  useEffect(() => {
    document.title = phase === 'verdict' && question
      ? `“${question}” Melanie the fruit fly says: ${answer.trim()}`
      : 'FlyFate: ask a real fruit fly brain'
  }, [phase, question, answer])

  // On the tour, the panel takes keyboard focus and Escape leaves it.
  useEffect(() => {
    if (tour < 0) return
    tourPanel.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setTour(-1)
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  })

  // Browser back from a verdict to the start page.
  useEffect(() => {
    const onPop = () => {
      if (SHARED_PATH.test(location.pathname)) return
      cancel.current?.()
      setFromLink(false)
      setPhase('idle')
    }
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  }, [])

  function submit(e: FormEvent) {
    e.preventDefault()
    const q = draft.trim()
    if (!q || waitSeconds > 0) {
      input.current?.focus()
      return
    }
    setQuestion(q)
    setAnswer('')
    setTyped(0)
    setStreamDone(false)
    setShared('')
    setShareId(null)
    setFromLink(false)
    setActive(0)
    setReading([])
    setNotice(null)
    setInLine(0)
    setVideo(null)
    startClip()
    setMakingVideo(videoType() !== null)
    setPhase('reading')
    startBuzz()
    cancel.current = ask(q, {
      onQueue: setInLine,
      onLimit: (message, retryAfter) => {
        // Back to the question box, question kept, with a clear notice and a countdown.
        stopBuzz()
        cancelClip()
        setMakingVideo(false)
        setNow(Date.now())
        setNotice({ message, until: Date.now() + retryAfter * 1000 })
        setPhase('idle')
      },
      onStep: (p, n) => {
        setInLine(0)
        setActive(n)
        if (p === 'speaking' && brain.phase === 'reading') {
          stopBuzz()
          setPhase('speaking')
        }
      },
      onToken: (t) => setAnswer((a) => a + t),
      onDone: (_, measured, id) => {
        setReading(measured)
        setShareId(id ?? null)
        setStreamDone(true)
      },
      onOffline: () => setOffline(true),
    })
  }

  // Someone else's question from the start page: show Melanie's verdict on it, like arriving on its link.
  function openOther(id: string) {
    history.pushState(null, '', `/o/${id}`)
    setFromLink(true)
  }

  function again() {
    cancel.current?.()
    stopBuzz()
    cancelClip()
    setVideo(null)
    setMakingVideo(false)
    setDraft('')
    setFromLink(false)
    if (location.pathname !== '/') history.pushState(null, '', '/')
    setPhase('idle')
    requestAnimationFrame(() => input.current?.focus())
  }

  const shareUrl = shareId ? `${location.origin}/o/${shareId}` : location.origin

  // The native share sheet where there is one (phones), else copy the link with a line of text.
  async function share() {
    const text = `I asked a real fruit fly brain: "${question}" Melanie said: "${answer.trim()}"`
    if (shareId) markShared(shareId)
    try {
      if (navigator.share) {
        await navigator.share({ title: 'FlyFate', text, url: shareUrl })
        return
      }
      await navigator.clipboard.writeText(`${text} ${shareUrl}`)
      setShared('copied')
    } catch {
      /* share sheet closed */
    }
  }

  // Phones: straight into the share sheet (TikTok, Instagram, WhatsApp). Elsewhere: a download.
  async function saveVideo() {
    if (!video) return
    if (shareId) markShared(shareId)
    if (matchMedia('(pointer: coarse)').matches && navigator.canShare?.({ files: [video] })) {
      try {
        await navigator.share({ files: [video], title: 'FlyFate', text: shareUrl })
      } catch {
        /* share sheet closed */
      }
      return
    }
    const url = URL.createObjectURL(video)
    const link = document.createElement('a')
    link.href = url
    link.download = video.name
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  async function copyLink() {
    if (shareId) markShared(shareId)
    try {
      await navigator.clipboard.writeText(shareUrl)
      setShared('link')
    } catch {
      /* clipboard blocked */
    }
  }

  function toggleSound() {
    setMuted(!muted)
    setMutedState(!muted)
  }

  // Logged in: one tap saves. Otherwise the email form opens. Already saved: a way to the collection.
  async function archiveIt() {
    if (!shareId) return
    if (!user) {
      setSaving(true)
      return
    }
    const result = await saveToArchive(shareId)
    if (result.saved) {
      setCollected(true)
      chime()
    }
  }
  const archiveButton = collected
    ? <a className="button soft" href="/me">In your collection</a>
    : user || mailReady ? <button className="soft" onClick={archiveIt}>Save to archive</button> : null

  const words = answer.slice(0, typed).split(' ').length
  // The decision type: named after the brain system of the region that stood out most.
  const kind = phase === 'verdict' && reading.length ? groupOf(brain.names[reading[0].region]) : null
  const focus = tour >= 0 && reading[tour] ? reading[tour].region : -1

  // What the video card shows over the brain: the same words as on screen.
  useEffect(() => {
    setClipText({
      question,
      answer: answer.slice(0, typed),
      kind: kind && { title: kind.kind.title, line: kind.kind.line, color: kind.color },
      stickers: phase === 'verdict' ? reading.map((r) => {
        const line = describe(r)
        return { text: `${line.plain} ${line.buzz}`, color: line.group.color }
      }) : [],
    })
  })

  return (
    <>
      <Scene reducedMotion={reducedMotion} talking={phase === 'speaking' ? words : 0} focus={focus}
        onReady={() => setReady(true)} />
      <div className="shell" data-phase={phase} data-tour={tour >= 0 || undefined}>
        <header className="bar">
          {/* The wordmark thinks along: each letter is its own toy (styles.css, keyed to the phase). */}
          <span className="mark">
            <span className="sr">FlyFate</span>
            {'FlyFate'.split('').map((c, i) => (
              <span key={i} aria-hidden style={{ '--i': i } as CSSProperties}>{c}</span>
            ))}
          </span>
          <nav className="tools">
            <a className="button chip" href="/answers">Answers</a>
            <button className="chip" onClick={toggleSound} aria-pressed={!muted}>{muted ? 'Sound off' : 'Sound on'}</button>
            <button className="chip" onClick={() => about.current?.showModal()}><span className="long">How it works</span><span className="short">About</span></button>
          </nav>
        </header>

        <main className="stage">
          {phase !== 'idle' && <p className="you" key={question}>{question}</p>}

          <section className="dialog" aria-live="polite">
            <span className="nametag">Melanie</span>

            {phase === 'idle' && !loaded && (
              <>
                <p className="say">Waking up my brain…</p>
                <div className="meter" role="progressbar" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100}>
                  <div className="meter-fill" style={{ width: `${service === 'warming' ? 100 : progress}%` }} />
                </div>
                {service === 'warming' && (
                  <p className="meter-label">I was napping. Waking up all 166,700 neurons takes a few seconds.</p>
                )}
              </>
            )}

            {phase === 'idle' && loaded && (
              <>
                {notice && waitSeconds > 0 ? (
                  <div className="notice" role="status">
                    <strong>{notice.message}</strong>
                    <span>You can ask again in {formatWait(waitSeconds)}.</span>
                  </div>
                ) : (
                  <p className="say">
                    {notice ? "I'm rested! Ask away." : "Hi, I'm Melanie! Ask me anything and my brain will decide."}
                  </p>
                )}
                <form className="ask" onSubmit={submit}>
                  <label className="sr" htmlFor="q">Your question</label>
                  <input
                    id="q" ref={input} value={draft} onChange={(e) => setDraft(e.target.value)}
                    placeholder={placeholder} maxLength={160} autoComplete="off" autoFocus
                  />
                  <button type="submit" className="big" disabled={waitSeconds > 0}>
                    {waitSeconds > 0 ? formatWait(waitSeconds) : 'Ask'}
                  </button>
                </form>
                {others.length > 0 && (
                  <nav className="others" aria-label="Questions others asked">
                    <p>Others asked</p>
                    <ul>
                      {others.map((o) => (
                        <li key={o.id}>
                          <button className="other" onClick={() => openOther(o.id)}
                            style={{ '--tint': GROUPS.find((g) => g.kind.id === o.kind)?.color ?? '#ffc83d' } as CSSProperties}>
                            {o.question}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </nav>
                )}
              </>
            )}

            {phase === 'reading' && inLine > 0 && (
              <>
                <p className="say">You're number {inLine} in line! I'm still buzzing through someone else's question.</p>
                <p className="meter-label">One brain, one question at a time. It only takes a few seconds each.</p>
              </>
            )}

            {phase === 'reading' && inLine === 0 && (
              <>
                <p className="say">Hmm, let me think…</p>
                <div className="meter" role="img" aria-label={`${active.toLocaleString('en')} neurons buzzing`}>
                  <div className="meter-fill" style={{ width: `${Math.min(100, (active / NEURONS) * 100 * 2)}%` }} />
                </div>
                <p className="meter-label"><strong>{active.toLocaleString('en')}</strong> of my {NEURONS.toLocaleString('en')} neurons are buzzing</p>
              </>
            )}

            {(phase === 'speaking' || phase === 'verdict') && (
              <p className="say answer">
                {/* Each word pops in as it starts; the typewriter still fills it letter by letter. */}
                {answer.slice(0, typed).split(/(\s+)/).map((part, i) =>
                  /^\s*$/.test(part) ? part : <span className="word" key={i}>{part}</span>)}
                {phase === 'speaking' && <span className="caret" />}
              </p>
            )}

            {phase === 'verdict' && (
              <>
                {kind && (
                  <div className="kind" style={{ '--tint': kind.color } as CSSProperties}>
                    <strong className="kind-title">{kind.kind.title}</strong>
                    <span className="kind-line">{kind.kind.line}</span>
                  </div>
                )}
                {tour >= 0 && reading[tour] ? (
                  <TourStop
                    ref={tourPanel} reading={reading} index={tour}
                    onGo={(i) => {
                      pop(i)
                      setTour(i)
                    }}
                    onClose={() => setTour(-1)}
                  />
                ) : reading.length > 0 && (
                  <>
                    <ul className="stickers" aria-label="Brain reading">
                      {reading.map((r, i) => {
                        const line = describe(r)
                        return (
                          <li key={r.region} style={{ '--tint': line.group.color, '--i': i } as CSSProperties}>
                            <button onClick={() => {
                              pop(i)
                              setTour(i)
                            }}>
                              <span className="plain">{line.plain} <b className="buzz">{line.buzz}</b></span>
                              <span className="sci">{line.label}</span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                    <p className="hint">Tap a sticker to fly into Melanie's brain.</p>
                  </>
                )}
                {tour >= 0 ? null : saving && shareId ? (
                  <SaveForm id={shareId} onClose={() => setSaving(false)} />
                ) : fromLink ? (
                  <div className="actions">
                    <button className="big" onClick={again}>Ask Melanie yourself</button>
                    <button className="soft" onClick={share}>{shared === 'copied' ? 'Copied!' : 'Share'}</button>
                    {shareId && archiveButton}
                  </div>
                ) : (
                  <div className="actions">
                    <button className="big" onClick={share}>{shared === 'copied' ? 'Copied!' : 'Share'}</button>
                    {shareId && (
                      <>
                        {archiveButton}
                        <button className="soft" onClick={copyLink}>{shared === 'link' ? 'Link copied!' : 'Copy link'}</button>
                        {/* The card as an image, for stories and chats that don't unfurl links. */}
                        <a className="button soft" href={`/o/${shareId}.jpg`} download={`flyfate-${shareId}.jpg`}
                          onClick={() => markShared(shareId)}>Save card</a>
                        {video ? <button className="soft" onClick={saveVideo}>Save video</button>
                          : makingVideo && <button className="soft" disabled>Making video…</button>}
                      </>
                    )}
                    <button className="soft" onClick={again}>Ask again</button>
                  </div>
                )}
              </>
            )}

            {offline && phase !== 'idle' && (
              <p className="demo">Demo mode: the brain service isn't running, so this activity is made up.</p>
            )}
          </section>
        </main>
        <p className="credit">
          A project by <a href={AUTHOR_URL} target="_blank" rel="noopener">AI Unfiltered</a>
          {' · '}<a href={REPO_URL} target="_blank" rel="noopener">★ Star on GitHub</a>
        </p>
      </div>

      <dialog ref={about} className="about" onClick={(e) => e.target === about.current && about.current?.close()}>
        <h2>How it works</h2>
        <p>
          Melanie's brain is the real wiring diagram of a male fruit fly: 166,700 neurons and 25.6 million
          connections, mapped by the MaleCNS project. Every word of your question flows through all of them, one
          step per word.
        </p>
        <p>
          What lights up is where that step shakes things up more than in the rest of the brain. Each bead is one real
          neuron, placed where its synapses are, and pops up when it rattles hard. The sparks follow the strongest real
          connections between brain regions.
        </p>
        <p>
          The words come from a small language model, LFM2.5 by Liquid AI. A tiny trained add-on (278,528 numbers)
          reads the fly brain's activity after every word and nudges which word comes next. It changes about one
          word in a hundred. Does the fly make the answers better? Barely, and no more than the same add-on without
          the fly brain. It's just more fun this way. Same question, same answer.
        </p>
        <p>
          The brain reading is measured: the regions that rattled most unusually over your question and the answer,
          compared with how they behave across many other questions, and the real cell types (as named by the MaleCNS
          team) that led. The decision type is named after the brain system of the region that stood out most. The
          differences are small, a few percent. It tells you what the wiring did, not what Melanie thinks.
        </p>
        <p className="fine">
          Language model: LFM2.5-1.2B-Instruct, LFM Open License v1.0. Fly model: FLM by nftechie, MIT. Brain data:
          MaleCNS v1.0, FlyEM / HHMI Janelia, University of Cambridge, MRC LMB and Google Research, CC BY 4.0.
          {' '}<a href="/how-it-works">More questions answered</a>. Visits are counted without cookies.
        </p>
        <p className="fine">
          A project by <a href={AUTHOR_URL} target="_blank" rel="noopener">AI Unfiltered</a>, a blog about AI from a
          developer's view. The code is open: <a href={REPO_URL} target="_blank" rel="noopener">★ FlyFate on GitHub</a>.
        </p>
        <form method="dialog"><button className="big">Got it</button></form>
      </dialog>
    </>
  )
}

type TourStopProps = {
  ref: Ref<HTMLElement>
  reading: Reading[]
  index: number
  onGo: (index: number) => void
  onClose: () => void
}

// One stop of the brain tour: the region the camera flew to, what it does, and what was measured there.
function TourStop({ ref, reading, index, onGo, onClose }: TourStopProps) {
  const line = describe(reading[index])
  const last = index === reading.length - 1
  return (
    <section className="tour" ref={ref} tabIndex={-1} aria-label="Brain tour" aria-live="polite"
      style={{ '--tint': line.group.color } as CSSProperties} key={index}>
      <div className="tour-top">
        <span className="tour-step">{index + 1} of {reading.length}</span>
        <button className="chip" onClick={onClose} aria-label="Leave the brain tour">Close</button>
      </div>
      <h2>{line.plain} <b className="buzz">{line.buzz}</b></h2>
      <p className="sci">{line.label}, part of the {line.group.name.toLowerCase()}</p>
      <p className="tour-about">{line.about}</p>
      <p className="measured">{line.measured}</p>
      <div className="actions">
        {index > 0 && <button className="soft" onClick={() => onGo(index - 1)}>Previous</button>}
        <button className="big" onClick={() => (last ? onClose() : onGo(index + 1))}>
          {last ? 'Back to Melanie' : 'Next region'}
        </button>
      </div>
    </section>
  )
}

// Saving to the archive without an account yet: an email gets a confirmation link, which also makes the account.
function SaveForm({ id, onClose }: { id: string; onClose: () => void }) {
  const [email, setEmail] = useState('')
  const [state, setState] = useState<'form' | 'sending' | 'sent'>('form')
  const [error, setError] = useState('')
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => field.current?.focus(), [])

  async function send(e: FormEvent) {
    e.preventDefault()
    setState('sending')
    setError('')
    const result = await saveToArchive(id, email.trim())
    if (result.sent) {
      setState('sent')
      chime()
    } else {
      setState('form')
      setError(result.error ?? 'Something went wrong. Please try again.')
    }
  }

  if (state === 'sent') {
    return (
      <section className="save" aria-live="polite">
        <h2>Check your inbox!</h2>
        <p>Tap the link in the email to put this answer in the archive. It also opens your own collection.</p>
        <div className="actions"><button className="soft" onClick={onClose}>Done</button></div>
      </section>
    )
  }
  return (
    <form className="save" onSubmit={send}>
      <h2>Save to the archive</h2>
      <p>The answer goes public in Melanie's archive. We email you a link to confirm, and that link is your login
        too, no password.</p>
      <div className="ask">
        <label className="sr" htmlFor="email">Your email</label>
        <input id="email" ref={field} type="email" required autoComplete="email" maxLength={200}
          placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <button type="submit" className="big" disabled={state === 'sending'}>
          {state === 'sending' ? 'Sending…' : 'Send link'}
        </button>
      </div>
      {error && <p className="save-error" role="alert">{error}</p>}
      <p className="save-fine">
        Only the question and the answer go public, never your email.{' '}
        <button type="button" className="link" onClick={onClose}>Cancel</button>
      </p>
    </form>
  )
}
