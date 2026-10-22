import { state, applyEvent } from './store.js'

// The only place the network is touched: the run event stream plus every REST
// call the console makes. EventSource reconnects and resumes on its own, so the
// page just folds what arrives, batched per frame so a burst is one render.

let source = null
let pending = []
let scheduled = false
let timer = null

function flush () {
  scheduled = false
  clearTimeout(timer)
  timer = null
  const batch = pending
  pending = []
  batch.forEach(applyEvent)
}

function push (ev) {
  pending.push(ev)
  if (scheduled) return
  scheduled = true
  // A frame and a timer, whichever comes first: a hidden tab is never given a
  // frame, so requestAnimationFrame alone would let the queue grow for the
  // whole run while the page still reports the stream as connected.
  requestAnimationFrame(flush)
  timer = setTimeout(flush, 250)
}

export function open (name) {
  close()
  source = new EventSource(`/api/runs/${encodeURIComponent(name)}/stream`)
  source.onopen = () => { state.connected = true }
  source.onerror = () => { state.connected = false }
  // One listener for every event. The server leaves frames unnamed and puts the
  // type in the payload; applyEvent switches on it.
  source.onmessage = (m) => push(JSON.parse(m.data))
}

export function close () {
  if (source) { source.close(); source = null }
  state.connected = false
  pending = []
}

/** A failed request, turned into a message a person can act on. The body is
 *  read as text once and only then tried as JSON: a 500 from FastAPI is plain
 *  text, and parsing it inside the error path throws again and puts the
 *  parser's complaint on screen instead of the fault. The status is always in
 *  the message.
 */
async function failure (r) {
  const body = await r.text().catch(() => '')
  let detail = ''
  try { detail = JSON.parse(body).detail || '' } catch { detail = body.slice(0, 300) }
  return new Error(detail ? `${detail} (HTTP ${r.status})`
                          : `the server answered ${r.status} with nothing to say`)
}

/** A reply that must be JSON: hand back the parsed body, or reject with the
 *  message `failure` builds.
 */
async function ok (r) {
  if (!r.ok) throw await failure(r)
  return r.json()
}

export const api = {
  runs: () => fetch('/api/runs').then(ok),
  eventTypes: () => fetch('/api/meta/event-types').then(ok),
  vocabulary: () => fetch('/api/meta/vocabulary').then(ok),
  config: () => fetch('/api/config').then(ok),
  // Which mode the console is in. Playback is the default; asked at boot and
  // after every toggle, since the work root and the launch tree move with it.
  playbackMode: () => fetch('/api/playback').then(ok),
  setPlaybackMode: (on) => fetch('/api/playback', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ on }),
  }).then(ok),
  // Persists: the server writes config.yaml and answers with the whole config,
  // so a change that drags others with it lands in one round trip.
  saveConfig: (path, value) => fetch('/api/config', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ path, value }),
  }).then(async r => r.ok ? r.json() : Promise.reject(await failure(r))),
  protocols: (root) =>
    fetch(`/api/protocols?root=${encodeURIComponent(root)}`)
      .then(async r => r.ok ? r.json() : Promise.reject(await failure(r))),
  // Walks the tree the server sees, one directory at a time: a native file
  // dialog yields no path the server could open. No path means the reader's
  // home.
  browse: (path) =>
    fetch('/api/browse' + (path ? `?path=${encodeURIComponent(path)}` : ''))
      .then(async r => r.ok ? r.json() : Promise.reject(await failure(r))),
  // What one pick actually is: which directory, which document, and which
  // supply switches it can answer. The launch form is filled from this.
  target: (path) =>
    fetch(`/api/target?path=${encodeURIComponent(path)}`)
      .then(async r => r.ok ? r.json() : Promise.reject(await failure(r))),
  startRun: (body) => fetch('/api/runs', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async r => r.ok ? r.json() : Promise.reject(await failure(r))),
  // Always the same shape, 404 included: a run's directory does not exist until
  // its first write, and the page navigates there the moment the start call
  // returns. An `undefined` would reach state.files, which every path lookup on
  // the page reads.
  tree: (name) => fetch(`/api/runs/${name}/tree`)
    .then(r => r.ok ? r.json() : { files: [] })
    .catch(() => ({ files: [] })),
  // The corpus scores and the review state filed on a run that already
  // finished. Live runs get the same numbers on the stream.
  // Both tolerate a 404 the way `tree` does: the page navigates to a run the
  // moment the start call returns, before its directory exists.
  evaluation: (name) => fetch(`/api/runs/${name}/eval`)
    .then(r => r.status === 404 ? { products: {} } : ok(r)),
  review: (name) => fetch(`/api/runs/${name}/review`)
    .then(r => r.status === 404 ? { review: null, findings: [] } : ok(r)),
  // The attack reproductions: which false cells were chosen, what came of
  // each, and the summary. Same 404 tolerance as the two above.
  attacks: (name) => fetch(`/api/runs/${name}/attacks`)
    .then(r => r.status === 404 ? { step: null, cells: [], summary: null } : ok(r)),
  // Asking answers at once — the work and its results come on the stream —
  // so a bounded wait is enough; stopping waits for the cell in hand to
  // unwind, which the server bounds a little under this.
  askAttacks: (name, cells) => fetch(`/api/runs/${name}/attacks`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ cells }), signal: AbortSignal.timeout(20000),
  }).then(ok),
  stopAttacks: (name) => fetch(`/api/runs/${name}/attacks/stop`, {
    method: 'POST', signal: AbortSignal.timeout(45000),
  }).then(ok),
  resummarize: (name) => fetch(`/api/runs/${name}/attacks/summary`, {
    method: 'POST', signal: AbortSignal.timeout(20000),
  }).then(ok),
  setReview: (name, state, note = '') => fetch(`/api/runs/${name}/review`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ state, note }),
  }).then(ok),
  // The corpus this run was scored against. Read-only and one directory over:
  // the reference model and the recorded attacks live there, not in the run.
  referenceTree: (name) =>
    fetch(`/api/runs/${name}/reference/tree`)
      .then(r => r.ok ? r.json() : { root: null, files: [] }),
  referenceFile: (name, path) =>
    fetch(`/api/runs/${name}/reference/file?path=${encodeURIComponent(path)}`)
      .then(r => r.ok ? r.json() : { path, text: `(cannot read ${path})` }),
  file: (name, path) =>
    fetch(`/api/runs/${name}/file?path=${encodeURIComponent(path)}`)
      .then(r => r.ok ? r.json() : { path, text: `(cannot read ${path})` }),
  // The one call that destroys something. The page asks twice before it is
  // sent, and the server refuses a run in flight.
  remove: (name) => fetch(`/api/runs/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  }).then(async r => r.ok ? r.json() : Promise.reject(await failure(r))),
  // Re-enters a stopped run at one of its own steps: `scenarios`,
  // `scenarios/baseline`, `scenarios/baseline/inject/Secrecy`, or a bare node
  // name; the server strips the numbers the directories carry. Re-entering a
  // live run stops it first and the server waits for it to unwind, so the
  // client timeout is bounded and a little longer than that wait.
  rerun: (name, fromStep) => fetch(`/api/runs/${name}/rerun`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ from_step: fromStep }),
    signal: AbortSignal.timeout(45000),
  }).then(async r => r.ok ? r.json() : Promise.reject(await failure(r))),
  // Commands too answer with JSON or reject: a refusal (409, 500) has to
  // reach the page rather than dissolve into a resolved response nobody reads.
  interrupt: (name) => fetch(`/api/runs/${name}/interrupt`, { method: 'POST' }).then(ok),
  approve: (name) => fetch(`/api/runs/${name}/approve`, { method: 'POST' }).then(ok),
  ask: (name, text, cell = null) => fetch(`/api/runs/${name}/chat`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(cell ? { text, cell } : { text }),
  }).then(async r => r.ok ? r.json() : Promise.reject(await failure(r))),
  stopAsk: (name) => fetch(`/api/runs/${name}/chat/stop`, { method: 'POST' }),
  plan: (name) => fetch(`/api/runs/${name}/pending`).then(ok),
  decide: (name, execute) => fetch(`/api/runs/${name}/pending`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ execute }),
  }),
}
