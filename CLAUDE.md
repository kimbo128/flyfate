# FlyFate (flyfate.com)

Fun-Projekt: Man fragt Melanie, eine Fruchtfliege. Jedes Token laeuft durch das echte MaleCNS-Connectom (FLM),
und ein 3D-Fliegenhirn im Cozy-Toy-Look zeigt live, wo es rattert. Design hat Prioritaet.
Markenname ist **FlyFate** (frueher "Fly Oracle"); interne Namen (Repo, Ordner, Railway, Python-Paket) heissen
noch `fly-oracle`/`fly_oracle_inference`.

## Stack
- `web/`: Vite + React 19 + TypeScript, React Three Fiber (Three.js), drei
- `inference/`: Python 3.12+ mit uv, FastAPI. Basis: [nftechie/flm](https://github.com/nftechie/flm)
  (geklont nach `$FLY_ORACLE_HOME/vendor/flm`, gitignored)

## Teilen (wichtigster Viral-Faktor) und SEO
- Jede Antwort hat einen stabilen Link `/o/{id}` (id aus Frage + `share.VERSION`; gleiche Frage, gleicher Link).
  `VERSION` erhoehen, wenn Modell/Prompt/Adapter die Antworten aendern.
- `/o/{id}`: server-gerendert (`share.render_page`) mit Title, Description, Canonical, OG, Twitter-Card,
  JSON-LD `QAPage` und lesbarem Inhalt in `#root`. `/` ebenso (`WebApplication`).
- `/o/{id}.jpg` und `/card.jpg`: 1200x630-Karte (Pillow, `share.render_card`), Cache auf dem Volume.
  `CARD_VERSION` erhoehen nach Design-Aenderungen (og:image traegt `?v=`).
- Index/Sitemap/Archiv nur fuer Antworten, die jemand aktiv geteilt oder per E-Mail gespeichert hat (`POST /api/oracle/{id}/shared`, zeichnet
  dabei gleich die Karte) und die sauber sind (`share.PROFANE`). Fragen stellen bleibt privat (`noindex`), Teilen
  macht oeffentlich.
- Archiv (`archive.py`, eigenes Server-HTML ohne 3D/JS): `/answers` (neueste zuerst, `?page=`), `/answers/{typ}`
  pro Entscheidungstyp mit Erklaerung, Suche `?q=` (LIKE ueber Frage + Antwort, `noindex`). JSON-LD
  `CollectionPage` + `BreadcrumbList`, Typ-Seiten in der Sitemap. Vite leitet `/answers` im Dev an 8000 weiter.
- Konten ohne Passwort (`accounts.py`): "Save to archive" unter jeder Antwort -> E-Mail -> Link (Resend,
  24 h mehrfach gueltig; ein Klick auf `/auth` speichert und loggt ein, kein Extra-Button - User-Wunsch. Mehrfach
  gueltig, weil Mail-Scanner jeden Link vorab oeffnen und einen Einmal-Link verbrauchen wuerden) -> Antwort `saved=1`
  (oeffentlich im Archiv, wenn sauber) + Konto + Session-Cookie `ff_session` (1 Jahr). Eingeloggt speichert ein Klick.
  `/me` = eigene Sammlung bzw. Login-Formular, `/login`, `/logout`. Tokens/Sessions nur als SHA-256 gespeichert,
  Limits 3 Links/10 Min pro Adresse, 10/h pro IP. Ohne `RESEND_API_KEY` landet der Link im Server-Log (Dev).
  Absender `MAIL_FROM` (Standard melanie@flyfate.com). Resend: flyfate.com verifiziert (eu-west-1);
  DNS bei Hostinger: TXT `resend._domainkey`, MX + TXT `send`, CNAME `rsend`, TXT `_dmarc`. `RESEND_API_KEY` als
  Railway-Variable und lokal in `.env`. Live-Test mit Empfaenger `delivered@resend.dev`.
- Entscheidungstyp (Schlagzeile, Karte, Archiv): Gruppe der Region, die in der Lesung am meisten heraussticht
  (`share.decision`, App: `groupOf(reading[0])`); Spalte `kind` in `oracles.db` (beim Start nachgetragen).
- `PUBLIC_URL` (Railway-Variable) setzt die Basis fuer Canonical/OG/Sitemap, sobald flyfate.com verbunden ist.
- `/how-it-works` (`about.py`): ausfuehrliche Erklaerung + FAQ als Server-HTML mit JSON-LD `FAQPage`, in der
  Sitemap, verlinkt von Startseite, Archiv-Footer und "How it works"-Dialog. Fakten dort mit dem Dialog synchron halten.
- Eigene Besucherzaehlung (`stats.py`, User-Entscheid statt Plausible/Umami): nur Tagessummen in `oracles.db`
  (Tabelle `stats`), keine Cookies, keine IPs, keine Fragen. Besucher = Hash aus IP + Browser mit taeglich neuem
  Salz nur im Speicher. Gezaehlt: HTML-Seitenaufrufe (Middleware), Herkunft als Plattform aus fester Liste
  (`stats.PLATFORMS`: erst `?ref=`/`?utm_source=`, z. B. `flyfate.com/?ref=hn`, dann Referrer-Domain, sonst
  "Other sites"), Link-Vorschauen pro Plattform (Kartenabrufe), Crawler, Geraet, Events
  `ask`/`share`/`save`/`limited`/`serious`. Puffer im Speicher, alle 60 s geschrieben.
  `/stats` (`?days=`) ist **oeffentlich** (User-Entscheid): darum nie Freitext von Besuchern speichern oder zeigen
  (Referrer-Spam, `?ref=` beliebig) und bei "Most viewed answers" nur oeffentliche Antworten (`indexable`).
- Kartenkunst: `?snapshot`-Ansicht der App screenshotten (900x760, Faktor 2, transparent), dann
  `uv run python scripts/build_card_art.py <png>` -> `assets/card-hero.png`, `web/public/icon-*.png`.
  Schriften: `scripts/build_card_fonts.py` (Google Fonts, OFL, auf Latein + Griechisch reduziert).
- `web/public/brain/legend.json`, gemeinsam fuer App, Karten und Seiten: Gruppen (Farbe, Entscheidungstyp,
  Erklaerung), Fach- und Klartextnamen pro Region mit einem Satz, was sie tut, Klartext fuer Zelltyp-Familien.
  Texte vorsichtig formulieren ("known for", "helps"), nichts erfinden.

## Deployment (Railway)
- Projekt `fly-oracle`, Service `fly-oracle`, Environment `production`
- Repo ist oeffentlich (MIT, README fuer Besucher). Nichts Privates in Code, Doku oder Commits.
- Google Search Console: TXT `google-site-verification=...` auf `@` (nicht loeschen), Sitemap eingereicht.
- README-Medien in `docs/media/`: echte Aufnahmen mit GPU (Playwright headed, nicht headless).
- Live: https://flyfate.com. Registriert bei GoDaddy, Nameserver bei Hostinger, Zone per Hostinger-MCP
  (`dns_records_list`/`_update`; Loeschen geht ueber das MCP nicht, der Filter kommt nicht an -> hPanel).
  Records: `@` ALIAS -> `g1h3np3h.up.railway.app`, `www` CNAME -> `ako61mco.up.railway.app`, TXT `_railway-verify`
  und `_railway-verify.www`. Beide in Railway verifiziert mit Zertifikat (`railway domain status <domain>`).
  Die App leitet www per 301 auf flyfate.com. `PUBLIC_URL=https://flyfate.com` ist gesetzt.
  Railway-URL: https://fly-oracle-production.up.railway.app
- Karten-Cache liegt unter `/data/cards`, Schluessel id + `CARD_VERSION` + Domain.
- Ein Docker-Service (`Dockerfile`): FastAPI liefert API und `web/dist`. Volume `fly-oracle-volume` auf `/data`
  (`FLY_ORACLE_HOME=/data`). Erster Start holt die Laufzeitdaten (~1,3 GB Download, ~460 MB bleiben), danach sofort.
- Deploy: `railway up --detach --service fly-oracle` IMMER aus der Repo-Wurzel (dort verlinkt). Aus `web/`
  heraus hat Railway einmal nur das Frontend als statische Seite gebaut und die API abgeschaltet.
  Nach dem Deploy pruefen: `curl .../api/health` muss JSON liefern, nicht HTML.
  In Git Bash Pfade mit `MSYS_NO_PATHCONV=1` setzen, sonst wird `/data` zu einem Windows-Pfad.
- Schutz (`inference/.../guard.py`, im Speicher, eine Instanz): Warteschlange (max. 50), pro IP 20 Fragen/10 Min
  und 150/Tag, global 20000/Tag, ernste Themen bekommen einen Hinweis statt der Fliege. Die Schlange haelt nur
  Lesen + Generieren (~1 s); das Abspielen der Antwort laeuft danach ausserhalb (`server.speak`).
- TODO vor 2026-12-01: `railway.json` (Config as Code) laeuft aus. `railway config migrate` benennt den Service
  falsch und kennt Volume/Restart-Policy nicht: erst `--service fly-oracle`, Plan pruefen, dann anwenden.

## Daten (gross, nicht in git)
- Laufzeit (`inference/.../runtime.py`, laeuft beim Serverstart): FLM-Code, Graph via FLMs Skript,
  LFM2.5-Tokenizer, nur die Embedding-Tabelle (Range-Request) und das offizielle Q4_K_M-GGUF (731 MB, gepinnt)
  nach `$FLY_ORACLE_HOME`.
- Adapter-Training (einmalig, lokal, ~11 Min CPU): FLMs `scripts/train_conversation.py` in eigener venv
  (`vendor/flm/.venv`, FLMs `requirements.txt` mit torch), Modell nach `vendor/flm/cache/lfm25-1.2b`, Korpus
  `everyday-conversations` nach `vendor/flm/cache/corpus`, `FLM_CPU_THREADS=8`. Ergebnis
  `runs/conversation-v2/adapter.safetensors` -> als `inference/assets/adapter.npz` (Keys `input`, `output`) ins Repo.
  Testergebnis (24 zurueckgehaltene Gespraeche): Perplexitaet 3,807 ohne, 3,716 mit Fliege, 3,718 Kontrolle
  ohne Fliegenhirn, 3,802 mit vertauschten Neuronen.
- Lokal liegt alles unter `$FLY_ORACLE_HOME` (Standard: `inference/`). In Worktrees
  `FLY_ORACLE_HOME=C:/Coding/FlyOracle/inference` setzen, damit nichts doppelt geladen wird.
- `uv run python scripts/build_brain_assets.py`: ROI-Meshes (Gehirn + Bauchmark) -> `web/public/brain/brain.glb`,
  `regions.json` (inkl. Transform nm -> Szene). Meshes werden voxelisiert und neu trianguliert (sonst Splitter).
- `uv run python scripts/prepare_data.py`: braucht die 3-GB-Synapsentabelle; erzeugt `inference/assets/brain_map.npz`
  (Neuron -> Region, Perlen, Zelltypen; im Repo), `beads.bin`, `wiring.json`. Koordinaten in 8-nm-Voxeln!
  Nur noetig, wenn Meshes oder Zuordnung sich aendern. Braucht `regions.json` aus dem Schritt davor.
- `uv run python scripts/calibrate_reading.py` (~10 Min CPU): misst Mittel und Streuung pro Region ueber 145 echte
  Fragen + Antworten -> `inference/assets/reading_baseline.npz` (im Repo). Die Lesung rangiert nach Abweichung
  von dieser Basis (z-Wert), zeigt aber +% gegenueber dem Mittel. Mit 3 Beispielfragen als Basis gewann der
  Pilzkoerper 60 % der Lesungen, kalibriert ~21 % und alle 13 Typen kommen vor. Neu laufen lassen, wenn Graph,
  Prompt, Modell oder Regionszuordnung sich aendern.

## Befehle
- Frontend: `cd web; npm install`, `npm run dev` (Proxy `/api` -> 127.0.0.1:8000), `npm run build`, `npm run lint`
- Simulator: `cd inference; uv sync`, dann `uv run uvicorn fly_oracle_inference.server:app --port 8000`
- Ohne laufenden Simulator faellt das Frontend auf `src/oracle/mock.ts` zurueck (mit "Demo mode"-Hinweis)

## Aufbau
- `inference/.../sim.py`: FLMs `Reservoir.step` mit LFM2.5-Embeddings (bf16, ohne torch, im RAM),
  Systemprompt einmal vorgerechnet. Anzeige = Zustandsaenderung pro Token, relativ zum Rest des Gehirns
  (FLMs Eingabe streut jedes Token zufaellig ueber alle Neuronen, absolut rattert immer alles). ~26 ms/Schritt CPU.
- `inference/.../server.py`: `GET /api/ask?q=` als SSE (`meta`, `step` pro Token, `done`). Lese-Frames live,
  Antwort am Stueck generiert (keine Sperre ueber yield), dann im Takt ausgespielt.
- `inference/.../oracle.py`: LFM2.5 (GGUF, llama.cpp) + FLM-Adapter in numpy, Logit-Korrektur `delta @ E^T`
  (gebundene Ausgabeschicht), RMS exakt ueber Gram-Matrix, Korrektur nur fuer die Top-1024-Kandidaten.
  LFM2 ist hybrid (Faltung + Attention): Praefix-Zustand per `save_state`/`load_state`, KV-Trimmen geht nicht.
  Seed aus der Frage: gleiche Frage, gleiche Antwort. Systemprompt + Beispiele in `sim.py`.
- `inference/scripts/ask.py`: Fragen gegen einen laufenden Server stellen (`--url` fuer live)
- `web/src/brain/activity.ts`: geteilter Hirnzustand, pro Frame gelesen, kein React-State
- `web/src/brain/Brain.tsx`: Toon-Regionen (wackeln/bouncen bei Aktivitaet), echte Neuronen als Perlen, Funken
- `web/src/brain/Fly.tsx`: Maskottchen Melanie (prozedural)
- `web/src/oracle/client.ts`: EventSource-Client; `web/src/sfx.ts`: synthetisierte Sounds

## Design (Cozy-Toy)
- Farben: Traube #2e2457 (Text, Konturen), Fliegenrot #ef4537, Sonne #ffc83d, Himmel #a8dbff -> #ffe3c7.
  Bonbonfarben pro Hirnregion in `regions.ts`. `styles.css` und `palette.ts` synchron halten.
- Schrift: Bagel Fat One (Logo, Namensschild), M PLUS Rounded 1c (UI). UI-Sprache Englisch.
- Dialogbox mit Schreibmaschine + Piepsern, gedrueckte Buttons, Sticker fuer die Hirn-Lesung.
- Verdict: Entscheidungstyp als gestempelte Schlagzeile in der Gruppenfarbe, Sticker mit Klartext + Fachname.
  Sticker antippen = Hirn-Tour (`brain.focus`): Kamera fliegt hin, Rest des Gehirns wird Glas (Huellen-Kontur aus,
  sonst grauer Nebel), Region schlaegt wie ein Herz, ihre echten Neuronen funkeln, Namensschild (drei `Html`),
  Melanie fliegt als Fuehrerin daneben, Panel mit Erklaerung und Messung, Weiter/Zurueck, Escape schliesst.

## Daten und Lizenzen
- MaleCNS v1.0 (FlyEM / HHMI Janelia u. a.), CC BY 4.0: Quelle nennen (steht im "How it works"-Dialog)
- LFM2.5-1.2B: LFM Open License v1.0, kommerziell frei unter 10 Mio. USD Jahresumsatz
- Die FLM-Autoren finden keinen Beleg, dass das Connectom die Antworten verbessert. Das offen sagen.
- Nicht verwenden: Forks mit Windows-ZIP-Downloads (toy0916000, Kaifshaikh2892), vermutlich Malware

## Konventionen
- Secrets nur in `.env` (nie committen) bzw. in Railway-Variablen.
- Screenshots vom Playwright-MCP landen in `.playwright-mcp/` (gitignored).
- Headless-Playwright rendert ohne GPU: Laden und Animationen sind dort stark verlangsamt.
