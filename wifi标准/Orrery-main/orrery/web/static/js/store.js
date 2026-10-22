import { reactive } from 'vue'

// The whole front end is one idea: state = events.reduce(applyEvent, {}).
// Live traffic and replayed history go through the same function, so catching
// up on history needs no second code path and cannot drift from the live one.

// The node table in the backend's own order (pipeline/table.py), filled once at
// boot from /api/meta/vocabulary. A stale second copy would drift silently: the
// missing step vanishes from the strip, its events show up as a phantom
// scenario, and unitDir() builds a path its sessions cannot be opened from.
export const NODES = reactive([])

/** Adopt the backend's node table. Mutates in place, so every module that
 *  imported NODES sees it and Vue re-renders. */
export function setNodes (names) {
  NODES.splice(0, NODES.length, ...names)
}

// The identities the build_root and build_world apply sessions run under
// (nodes/root/node.py::ROOT_IDENT). They ride in the envelope's `scenario`
// field because that field carries a session's identity; neither is a scenario,
// so everything that lists scenarios filters them out.
export const ROOT_IDENT = 'root'
export const WORLD_IDENT = 'world'

// Every event type this page knows what to do with. Compared against the
// backend's own KNOWN list at boot — the runtime stand-in for a compiler
// checking that a switch covers its union.
export const HANDLED = new Set([
  'run_started', 'node_started', 'node_progress', 'node_finished',
  'node_scored',
  'invalidated', 'interrupted', 'run_finished', 'run_failed',
  'check_ran',
  'scenario_started', 'scenario_finished', 'solve_finished',
  'aggregated', 'cross_checked',
  'prompt_filed', 'round_started', 'tool_called', 'tool_returned',
  'finding_recorded', 'review_closed',
  'attack_status', 'attacks_summarized',
  'session_usage',
  'check_report', 'framework_action', 'gap_reported', 'gap_verdict',
  'awaiting_approval', 'awaiting_confirm', 'expert_asked', 'expert_replied',
  'model_delta',
])

// The events that mean a session is doing something, as opposed to the run
// moving between steps.
const SESSION_EVENTS = new Set([
  'prompt_filed', 'round_started', 'model_delta', 'tool_called',
  'tool_returned', 'framework_action', 'check_report', 'solve_finished',
])


export const state = reactive({
  runs: [],
  current: null,
  status: 'unknown',
  nodes: {},
  // What each step said about itself, in order: the node-level lines that are
  // not a session's. Kept here rather than read back out of `feed`, which the
  // view draws only the tail of — a long run puts the first step's lines out of
  // reach, and they are what a step with no session has to show.
  nodeLines: {},            // node -> [{t, text, artifacts}]
  scenarios: {},            // label -> {status, assignment, verdicts, units}
  results: [],              // [{id, verdict, description?}] — the answers, from aggregate
  crossCheck: null,         // per-cell comparison, for locating which column differs
  // The readings people have filed on this run's cells, newest first, and
  // whether the run is still open for review. Both come off the ledger and the
  // review state file: a reading is somebody's judgement added after the run,
  // never an artifact of it.
  review: { state: 'open', note: '' },
  findings: [],             // [{goal, scenario, reading, responsible_step, why, seq}]
  // Where each false cell's attack reproduction stands, keyed by reproKey:
  // {goal, label, status, reason, manual, seq}. Only the state; which cells were chosen,
  // the scripts and the explanations are read from the step's files
  // (/api/runs/{name}/attacks) when the page needs them. Named apart from the
  // corpus's documented attacks, which main.js calls attack*.
  reproductions: {},
  // Bumped whenever a summary over the reproduced cells is rewritten, so the
  // page knows to read it again.
  reproSummaries: 0,
  // Why the run stopped, when it stopped badly. The reason rides on run_failed;
  // without it the page has a red chip and no sentence.
  failure: null,            // {kind, reason, node, where}
  failedNode: null,         // the step whose node_finished said failed
  // What each step's product scored against the corpus, keyed by step:
  // {slug, num, den, extra}. Numbers only; the entries a comparison missed stay
  // in the run's eval files. A step with no entry was never scored — it produces
  // nothing the corpus answers, it was handed its artifact, or there is no
  // corpus.
  scores: {},
  // Principals' candidate → corpus alpha-renaming. Kept beside, rather than
  // inside, the score so a failed aligner never turns into "undefined/undefined".
  alignments: {},
  // The range this run was given: {start, end} over the chain's stops, derived
  // by the engine off run.json (api/corpus_inputs.stops_of).
  range: null,
  reference: [],            // the corpus's own files, for the reference side
  feed: [],
  // unit -> the fragment buffer, never folded. Its own field: `live` below is
  // the stage index off /tree, and one name for both had every tree refresh
  // wipe the expert's half-written reply and every re-entry wipe the index.
  drafts: {},
  usage: { in: 0, out: 0, cached: 0, by: {} },   // the run's bill, by node
  // Where the newest session event came from: a fact about the run, not a
  // selection, which the page may choose to follow.
  lastAt: null,             // {ident, unit}
  awaiting: null,           // the node a manual-mode run is parked at
  lastSeq: -1,
  runStarts: 0,             // how many times this run has been started, off the ledger
  unknownTypes: [],
  connected: false,
  files: [],                // the run's real file tree, for resolving evidence
  // The run's index: every execution, and which of them are current. Fetched
  // beside the file list, because a path is only half an answer without it: a
  // step that was re-worked has two directories and only one of them is what the
  // run means now (services/store/stages).
  stages: [],               // [{dir, ident, parent, kind, n, cause, by, supersedes, ts}]
  problems: [],             // where the index and the directory tree disagree
  live: {},                 // parent dir -> {ident: dir}
  // Steps handed their artifact instead of producing it, so re-entering one
  // would write the same bytes back. Decided by the engine and read off the
  // tree, never worked out here from the run's inputs.
  pinned: [],               // [node name]
  // Reference data behind the tooltips, not run state, so it is fetched rather
  // than folded:
  //   vocab  {assumptions|goals: {kind: {subtype: one sentence}}}, /api/meta
  //   decl   what this run was asked — the claims step's own three files, which
  //          carry a goal's values and parties and a dimension's declared
  //          domain, none of which any event repeats.
  vocab: { assumptions: {}, goals: {}, world_axes: [] },
  decl: { goals: {}, dims: {} },
  // Which halves of `decl` have been read back off the tree. Kept in the state
  // because `reenter` is what invalidates them and it lives here too.
  declLoaded: { goals: false, dims: false },
  // The launcher's own two reads, both about the machine rather than about any
  // run: the effective config (credentials already taken out server side) and
  // whatever protocols a corpus root turns out to hold.
  cfg: null,                // {config, complete, secret, readonly, why?}
  protocols: [],
  chat: [],                 // {who: 'me'|'it', text}
  expertRound: 0,
  asking: false,            // a turn is in flight
  pending: null,            // the fix plan waiting on a decision
})

/** Where a corpus path splits into the protocol and the sub-protocol. The corpus
 *  marks this itself: a standard that is a family of mechanisms puts them under
 *  a literal `subprotocols/` directory, so the split needs no rule about names. */
const SUBS = '/subprotocols/'

/** Compare two names with their digit runs read as numbers, so a standard's
 *  mechanisms sort `mechanism-2` before `mechanism-13`. */
const NAT = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

/** Split a corpus path into {head, leaf} at `subprotocols/`. Returns null for a
 *  path with no sub-protocol, the caller's signal to list it as itself. */
export function splitSub (dir) {
  const i = (dir || '').indexOf(SUBS)
  return i < 0 ? null : { head: dir.slice(0, i), leaf: dir.slice(i + SUBS.length) }
}

/** Group anything that carries a corpus path into openable protocols: a standard
 *  opens into its mechanisms, and four fifths of the corpus being ISO mechanisms
 *  is what makes the flat list unreadable. A group with one child is flattened
 *  back to a leaf, which is why this returns rows rather than a map — whether an
 *  entry is a group is decided here, from how many children it has. `key(item)`
 *  gives the corpus path, `order(rows)` sorts the result; an item with no corpus
 *  path lists as a leaf. */
export function corpusRows (items, key, order) {
  const heads = new Map()
  const rows = []
  for (const it of items) {
    const s = splitSub(key(it) || '')
    if (!s) { rows.push({ group: false, item: it }); continue }
    // A standard takes the position of its first mechanism, so the reading order
    // the backend already applied carries through.
    if (!heads.has(s.head)) {
      const row = { group: true, head: s.head, children: [] }
      heads.set(s.head, row)
      rows.push(row)
    }
    heads.get(s.head).children.push({ item: it, leaf: s.leaf })
  }
  // Inside a standard, by mechanism name: the caller's order is about the
  // standards and says nothing about mechanism 2 versus mechanism 13.
  for (const row of heads.values()) row.children.sort((a, b) => NAT.compare(a.leaf, b.leaf))
  // Demoted in place, so flattening a group of one does not move it either.
  const out = rows.map(r => (r.group && r.children.length === 1)
    ? { group: false, item: r.children[0].item }
    : r)
  return order ? order(out) : out
}

/** The run list grouped by protocol, the shape the run tree on disk already has
 *  (`<work_root>/<protocol>/<run>`). Group order follows the newest run in each,
 *  so a protocol somebody just ran is at the top; within a group the backend's
 *  order (newest first) is kept. */
export function runGroups () {
  const by = new Map()
  for (const r of state.runs) {
    if (!by.has(r.protocol)) by.set(r.protocol, [])
    by.get(r.protocol).push(r)
  }
  const groups = [...by.entries()].map(([protocol, runs]) => ({
    protocol,
    runs,
    // Where this protocol sits in the corpus, for the standard it may belong to.
    // Taken off any of its runs: they are runs of one protocol and were all
    // scored against the same corpus entry.
    dir: runs.find(r => r.dir)?.dir || '',
    // Its place in the corpus's reading order, computed by the backend off the
    // one list in api/reading_order.py.
    rank: runs.find(r => r.dir)?.rank ?? Number.MAX_SAFE_INTEGER,
    latest: runs.reduce((a, b) => (a.started >= b.started ? a : b)),
    // A group opens by itself when something in it is still moving: that is the
    // run a reader wants without asking.
    running: runs.some(r => r.status === 'running'),
    // How many nobody has read. Kept at the group so a collapsed protocol still
    // says there is something in it to look at.
    unread: runs.filter(r => r.review === 'open' && r.status !== 'running').length,
  }))
  groups.sort((a, b) => (a.latest.started < b.latest.started ? 1 : -1))
  return groups
}

/** The run list as the two levels above a run: standards that open into their
 *  mechanisms, and protocols that are simply themselves. In the corpus's reading
 *  order, the same one the launch panel uses — textbook protocols first, then
 *  the standards, ISO last — so the page has the same shape every time it opens.
 *  Within a standard the mechanisms keep their own order. */
export function runCorpusRows () {
  const at = (row) => row.group
    ? [row.children[0].item.rank, row.head]
    : [row.item.rank, row.item.dir || row.item.protocol]
  return corpusRows(runGroups(), g => g.dir, rows => rows.sort((a, b) => {
    const [ra, da] = at(a), [rb, db] = at(b)
    return ra !== rb ? ra - rb : String(da).localeCompare(String(db))
  }))
}

/** The pipeline as the graph it actually is, laid out on a grid. The node table
 *  is a list but the real shape is a DAG: the two vocabulary readers run side by
 *  side and extract_claims joins them back. Columns come from the longest path
 *  to each node; nodes sharing a column ran in parallel and stack inside it.
 *  Parents come from the backend's `depends_on` (/api/meta/vocabulary), and a
 *  node that declares none falls back to the one before it in the table. */
export function pipelineLayout () {
  const dep = (state.vocab && state.vocab.depends_on) || {}
  const at = {}
  NODES.forEach((n, i) => { at[n] = i })
  const parentsOf = (n) => {
    const d = dep[n]
    if (d && d.length) return d.filter(p => p in at)
    const i = at[n]
    return i > 0 ? [NODES[i - 1]] : []
  }
  const col = {}
  for (const n of NODES) {
    const ps = parentsOf(n)
    // NODES is in table order and a dependency always points backwards in it,
    // so every parent already has a column by the time its child is read.
    col[n] = ps.length ? Math.max(...ps.map(p => (col[p] === undefined ? -1 : col[p]) + 1)) : 0
  }
  const byCol = []
  for (const n of NODES) {
    if (!byCol[col[n]]) byCol[col[n]] = []
    byCol[col[n]].push(n)
  }
  // Two rows even when nothing forks, so a solo column and a forked one share a
  // centre line instead of the fork pushing the whole strip down.
  const rows = Math.max(2, ...byCol.map(c => c.length))
  const cells = []
  byCol.forEach((names, c) => {
    if (names.length === 1) {
      cells.push({ node: names[0], col: c + 1, row: 1, span: rows, forked: false })
    } else {
      const span = Math.max(1, Math.floor(rows / names.length))
      names.forEach((n, k) => cells.push(
        { node: n, col: c + 1, row: k * span + 1, span, forked: true }))
    }
  })
  return { cells, rows, cols: byCol.length, parentsOf }
}

/** A step's directory: the one holding its current work, resolved through the
 *  run's index rather than matched against a name. A run that went back holds
 *  more than one directory per step (`03_extract_principals` beside
 *  `09_extract_principals`), and the index is what the engine itself resolves
 *  with, so page and run cannot disagree about which attempt is the answer. */
export function stepDir (node) {
  return (state.live[''] || {})[node] || null
}

/** Every execution of one identity under a parent, oldest first: the step's own
 *  history. */
export function stagesOf (parent, ident) {
  return state.stages.filter(s => s.parent === parent && s.ident === ident)
                     .sort((a, b) => a.n - b.n)
}

/** What actually happened under one parent, in the order it happened, each
 *  execution marked with whether it is still the answer. The run's own shape
 *  rather than the pipeline's. One call serves every level, because the index
 *  has the same shape at every level: the node chain, a scenario's apply chain,
 *  its goal families. */
export function timeline (parent = '') {
  const live = new Set(Object.values(state.live[parent] || {}))
  return state.stages.filter(s => s.parent === parent)
                     .map(s => ({ ...s, live: live.has(s.dir) }))
}

/** Whether a parent's executions are an ordered chain or a concurrent fan-out,
 *  read off its children, which agree by construction. */
export function timelineKind (parent = '') {
  const first = state.stages.find(s => s.parent === parent)
  return first ? first.kind : 'seq'
}

/** How many times anything inside this directory's tree was re-worked — what the
 *  level above has to show. A fix aimed at one apply point appends deep in the
 *  tree and leaves the step above holding the directory it already had, so
 *  without this the step's own row would read as untouched. */
export function reworksUnder (dir) {
  return state.stages.filter(
    s => s.dir !== dir && s.cause !== 'initial'
      && (s.parent === dir || s.parent.startsWith(dir + '/'))).length
}

/** The files one execution left, top level only: its products and its session,
 *  not the rounds below them or a deeper stage's tree. */
export function stageFiles (dir) {
  return state.files
    .filter(p => p.startsWith(`${dir}/`))
    .map(p => p.slice(dir.length + 1))
    .filter(f => !f.includes('/'))
    .sort()
}

/** Which directory holds one goal family's current work inside a scenario.
 *  Families run concurrently, so they are generation-numbered like scenarios
 *  and their identity is the family name alone. */
export function famDir (label, family) {
  const home = scenarioDir(label)
  return home ? (state.live[`${home}/inject`] || {})[family] || null : null
}

/** Which directory holds a scenario's current work. Scenarios run concurrently
 *  and are numbered by generation rather than execution order, so their identity
 *  is the label alone. */
export function scenarioDir (label) {
  const home = stepDir('scenarios')
  return home ? (state.live[home] || {})[label] || null : null
}

/** A unit's file, by exact path. The unit is the address: `unit_name` reports a
 *  session's directory relative to the step it lands under
 *  (`apply/03_leaked_from_start`, `inject/Secrecy`), so this is a join and not a
 *  search — superseding seals in place, so a stale `03_model.pv` sits beside the
 *  live `model.pv` and a suffix match would offer either. Returns null when the
 *  file is not in the tree, which keeps the link from appearing at all. */
export function evidence (ident, unitKey, filename) {
  const dir = unitDir(ident, unitKey)
  return dir && state.files.includes(`${dir}/${filename}`) ? `${dir}/${filename}` : null
}

/** Which scenario column a cross_check row is about. A cell names its world by
 *  assignment rather than by label — the corpus has no idea what this run called
 *  its scenarios — so the column is found by matching every (assumption,
 *  subtype) the cell names against what each scenario actually assigned. One
 *  definition, shared by the matrix and by cellDetail. */
export function columnOf (cell) {
  const named = cell.scenario || []
  if (!named.length) return null
  return Object.keys(state.scenarios).find(l => {
    const assign = {}
    for (const r of state.scenarios[l].assignment || []) assign[r.id] = r.subtype
    return named.every(x => assign[x.id] === x.subtype)
  }) || null
}

/** A goal's family as the layout names it: `Authentication.injective_agreement`
 *  for a goal with a subtype, `Secrecy.basic` for one without. The `basic`
 *  default is the injector registry's — the directory the inject step writes. */
export function familyOf (goalId) {
  const g = state.decl.goals[goalId]
  if (!g || !g.type) return null
  return { type: g.type, subtype: g.subtype || 'basic' }
}

/** Everything known about one (goal, scenario): the verdict, what the corpus
 *  expected, the reading somebody filed on it, and the files behind those. A
 *  join, not a calculation — the verdict comes from the scenario, the expected
 *  answer from cross_check, the reading off the ledger. Paths are filtered
 *  against the run's own file list, so a cell that never reached a solver offers
 *  what exists and nothing more. */
export function cellDetail (goalId, label) {
  const sc = state.scenarios[label]
  if (!sc) return null
  const fam = familyOf(goalId)
  const truth = (state.crossCheck || []).find(
    c => c.id === goalId && columnOf(c) === label)

  const finding = findingFor(goalId, label)

  const home = scenarioDir(label)
  const famD = fam ? famDir(label, fam.type) : null
  // The batch's directory is the cell's: one batch is one session and one .pv,
  // so there is no level below the family.
  const injectDir = home && famD ? `${home}/inject/${famD}` : null
  // The long-display trace behind a false cell: the reproduction step's own,
  // or one made afterwards for a question somebody asked (_attacks/, outside
  // the run's own tree).
  const attackStep = stepDir('reproduce_attacks')
  const attackDirs = [attackStep && `${attackStep}/${label}/${goalId}`,
                      `_attacks/${label}/${goalId}`].filter(Boolean)
  const at = (dir, f) => dir && state.files.includes(`${dir}/${f}`)
    ? `${dir}/${f}` : null
  // The verdict's evidence is the last solve actually spent on this goal:
  // precise, then trace, then the shared no-trace pass. A false verdict carries
  // its concrete attack trace only in one of the goal-only retries, so
  // 01_proverif.txt would show the provisional answer the final one replaced.
  const solverFile = suffix =>
    at(injectDir, `03_proverif_precise_${goalId}.${suffix}`)
    || at(injectDir, `02_proverif_trace_${goalId}.${suffix}`)
    || at(injectDir, `01_proverif.${suffix}`)
  const round = (dir, suffix) => {
    if (!dir) return null
    const hits = state.files.filter(
      f => f.startsWith(`${dir}/rounds/`) && f.endsWith(suffix))
    return hits.length ? hits[hits.length - 1] : null
  }

  return {
    goal: goalId,
    label,
    family: fam,
    verdict: sc.verdicts[goalId],
    expected: truth ? truth.expected : null,
    match: truth ? truth.match : null,
    finding: finding || null,
    // Ordered as a reader needs them: what the solver said, what it was asked,
    // what produced the asking. The trace is first, being the evidence a
    // disagreement is about.
    evidence: [
      ['trace', solverFile('txt')],
      ['sent', solverFile('pv')],
      ['model', at(injectDir, 'model.pv')],
      // The round files carry a slot number that depends on how many prompts
      // came before them, so they are found by suffix. Last match wins: the
      // interesting round is the one that settled it.
      ['edits', round(injectDir, '_edits.json')],
      ['checks', round(injectDir, '_checks.md')],
      ['typecheck', round(injectDir, '_typecheck.txt')],
      ['injectPrompt', round(injectDir, '_prompt.md')],
      ['scenarioPv', scenarioDir(label) &&
        state.files.includes(`${scenarioDir(label)}/apply/scenario.pv`)
        ? `${scenarioDir(label)}/apply/scenario.pv` : null],
      ['longTrace', attackDirs.map(d => at(d, 'trace.txt')).find(Boolean)],
    ].filter(([, v]) => v),
  }
}

/** How this cell's model was built, one step at a time: flow.pv --build_world->
 *  world.pv --build_root-> root.pv --apply-> scenario.pv --inject-> model.pv.
 *  Every neighbouring pair is the same file one step apart, so what a step did
 *  is the difference between them. The last is inject's own product rather than
 *  the solver's 01_proverif.pv copy of it. Steps whose files are missing drop
 *  out, so a run that stopped early offers the stages it reached. */
export function lineage (goalId, label) {
  // The ledger first, the declarations second. They are the same fact, but not
  // equally available: the ledger is replayed and survives a reconnect, while
  // the declarations are an HTTP read of the claims step's files that a run
  // stopped before claims cannot make at all (main.js::loadDeclarations). The
  // fallback still earns its place: a cell whose model was built but never
  // solved has no solve event to be addressed by.
  const fam = familyOf(goalId)
  const home = scenarioDir(label)
  const cellDir = injectCellDir(label, goalId)
    || (fam && home && famDir(label, fam.type)
        ? `${home}/inject/${famDir(label, fam.type)}` : null)
  const has = (f) => f && state.files.includes(f) ? f : null
  const at = (node, file) => has(stepDir(node) && `${stepDir(node)}/${file}`)

  const flow = at('extract_flow', 'flow.pv')
  const world = at('build_world', 'apply/world.pv')
  const root = at('build_root', 'apply/root.pv')
  const scen = has(home && `${home}/apply/scenario.pv`)
  const model = has(cellDir && `${cellDir}/model.pv`)
             || has(cellDir && `${cellDir}/01_proverif.pv`)

  const stages = [
    { step: 'build_world', before: flow, after: world },
    { step: 'build_root', before: world, after: root },
    { step: 'apply', before: root, after: scen },
    { step: 'inject', before: scen, after: model },
  ].filter(st => st.before && st.after && st.before !== st.after)
  return { stages, flow, world, root, scen, model }
}

/** The readings filed on this run, newest first, one per cell. A cell may
 *  collect several over time and they all stay on the ledger; only the newest is
 *  shown. */
export function reviewFindings () {
  const seen = new Set()
  return (state.findings || []).filter(f => {
    const k = `${f.goal}\u0000${f.scenario}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

/** The key a cell's reproduction is filed under, in the ledger's fold and in
 *  the index the page reads. */
export const reproKey = (label, goal) => `${label}|${goal}`

/** How the results table draws one false cell's reproduction, or null when
 *  there is nothing to draw: `look` is done | queued | running | failed |
 *  pending | skipped, with `manual`, `stale` and the `reason` beside it.
 *
 *  Two sources. `row` is the cell's entry in the index the page read off the
 *  step's files — what was decided for it and what came of it. The ledger's
 *  fold is newer: a cell starts and finishes between two readings. A cell the
 *  ledger calls in flight is only believed while something can still be
 *  working on it — the step itself, or the queue the index reports — since a
 *  run killed mid-cell never says it stopped. */
export function reproOf (goal, label, row, queue = []) {
  const key = reproKey(label, goal)
  const ev = state.reproductions[key]
  const flying = ev && (ev.status === 'queued' || ev.status === 'running')
    && (ev.manual ? queue.includes(key)
                  : state.nodes.reproduce_attacks === 'running')
  if (flying) return { look: ev.status, manual: ev.manual, stale: false, reason: '' }
  if (row && row.status) {
    if (row.stale) return { look: 'pending', manual: row.manual, stale: true, reason: '' }
    return { look: row.status === 'ok' ? 'done' : 'failed', manual: row.manual,
             stale: false, reason: row.reason || '' }
  }
  if (ev && ev.status !== 'queued' && ev.status !== 'running') {
    const look = { ok: 'done', failed: 'failed' }[ev.status] || 'pending'
    return { look, manual: ev.manual, stale: false, reason: ev.reason }
  }
  if (!row) return null
  // Chosen by the step and not started yet: waiting its turn, not waiting for
  // a person.
  if (row.decision === 'auto') {
    return state.nodes.reproduce_attacks === 'running'
      ? { look: 'queued', manual: false, stale: false, reason: '' } : null
  }
  return { look: row.decision === 'pending' ? 'pending' : 'skipped',
           manual: false, stale: false, reason: row.reason || '' }
}

/** The reading filed on one cell, if any. */
export function findingFor (goalId, label) {
  return reviewFindings().find(f => f.goal === goalId && f.scenario === label)
    || null
}

/** The directory one session wrote into, addressed by identity and unit key.
 *  Null when the identity has no directory in this run yet. */
export function unitDir (ident, unitKey) {
  // A pipeline step's one session writes straight into the step's own
  // directory, and its events carry the node's name as their unit. A step that
  // runs several (reproduce_attacks: one per cell, then a summary) names each
  // by its directory under the step, like any other unit — or, for a session
  // somebody asked for after the run, under the run itself: those live in
  // directories with a leading underscore (_attacks/), outside the step tree.
  if (NODES.includes(ident)) {
    if (unitKey && unitKey.startsWith('_')) return unitKey
    const dir = stepDir(ident)
    return dir && unitKey && unitKey !== ident ? `${dir}/${unitKey}` : dir
  }
  const home = ident === ROOT_IDENT
    ? stepDir('build_root')
    : ident === WORLD_IDENT
      ? stepDir('build_world')
      : scenarioDir(ident)
  return home ? `${home}/${unitKey}` : null
}

/** Which step owns a bucket in `state.scenarios`. Buckets are keyed by the
 *  envelope's identity, and three kinds land there: the two shared-base models
 *  under their own names, a scenario label under the scenario stage, and a
 *  session-running step under its node name. */
export function ownerOf (ident) {
  if (ident === WORLD_IDENT) return 'build_world'
  if (ident === ROOT_IDENT) return 'build_root'
  return NODES.includes(ident) ? ident : 'scenarios'
}

/** Drop what a re-entry supersedes, so the second attempt folds onto a clean
 *  slate instead of on top of the first one's answers. The engine seals the
 *  artifacts of `from` and everything after it; this is the same cut applied to
 *  the view. The feed, the bill and the filed readings survive it: both attempts
 *  really happened, and a reading is somebody's judgement rather than an
 *  artifact of the run. */
function reenter (from) {
  // A re-entry point missing from the backend's own table — or a table that
  // has not arrived yet, when a reload's stream outruns /api/meta/vocabulary —
  // means this side cannot say where the cut falls. Dropping everything is
  // the safe reading: it drops more than it must, never less. `NODES.indexOf`
  // alone cannot express that: with an empty table every lookup is -1, and
  // "-1 >= 0" would keep everything instead.
  const start = NODES.indexOf(from)
  const all = start < 0
  if (all) {
    console.error(`re-entry at unknown node ${from}; clearing the whole view`)
  }
  const drop = (node) => all || NODES.indexOf(node) >= start
  for (const node of Object.keys(state.nodes)) {
    if (drop(node)) delete state.nodes[node]
  }
  for (const node of Object.keys(state.nodeLines)) {
    if (drop(node)) delete state.nodeLines[node]
  }
  // The corpus scores and alignments of the steps being redone: left, the
  // strip would wear the last attempt's badge beside the new attempt's dot.
  for (const node of Object.keys(state.scores)) {
    if (drop(node)) { delete state.scores[node]; delete state.alignments[node] }
  }
  for (const ident of Object.keys(state.scenarios)) {
    if (drop(ownerOf(ident))) delete state.scenarios[ident]
  }
  if (drop('aggregate')) state.results = []
  if (drop('cross_check')) state.crossCheck = null
  // The step's own reproductions go with it. The ones a person asked for
  // after the run stay: whether their basis still holds is the index's call
  // (api/attacks.py), not something the cut can tell.
  if (drop('reproduce_attacks')) {
    for (const [k, r] of Object.entries(state.reproductions)) {
      if (!r.manual) delete state.reproductions[k]
    }
  }
  // The two vocabularies, each cleared only when the step that writes it is
  // being re-run: a re-entry at the goals step leaves the assumption space
  // standing, because nothing is going to rewrite it. They are read back off the
  // tree by loadDeclarations, so clearing is all this side has to do.
  if (drop('extract_properties')) {
    state.decl.goals = {}
    state.declLoaded.goals = false
  }
  if (drop('extract_assumptions')) {
    state.decl.dims = {}
    state.declLoaded.dims = false
  }
  state.failure = null
  state.failedNode = null
  state.awaiting = null
  // The fragment buffers, not the stage index: the index comes off /tree and
  // a re-entry makes it older, never wrong, until the next refresh replaces it.
  state.drafts = {}
  state.lastAt = null
}

/** Point the page at another run and clear everything the last one left. */
export function resetRun (name) {
  Object.assign(state, {
    // `files` among them: it is this run's tree, and until the new one is
    // fetched every path on the page would resolve against the last run's.
    current: name, status: 'unknown', files: [], stages: [], live: {},
    problems: [], pinned: [],
    nodes: {}, nodeLines: {}, scores: {}, alignments: {}, range: null,
    // `decl` for the same reason as `files`: it is this run's question, and a
    // goal id the two runs share would carry the wrong declaration until the new
    // ones arrive.
    decl: { goals: {}, dims: {} },
    declLoaded: { goals: false, dims: false },
    scenarios: {},
    results: [], crossCheck: null, reference: [],
    failure: null, failedNode: null,
    review: { state: 'open', note: '' }, findings: [],
    reproductions: {}, reproSummaries: 0,
    feed: [], drafts: {}, lastSeq: -1, runStarts: 0,
    usage: { in: 0, out: 0, cached: 0, by: {} }, awaiting: null, lastAt: null,
    chat: [], asking: false, pending: null, expertRound: 0,
  })
}

/** The run's scenarios, by the only thing that makes one: a scenario_started.
 *  The buckets are keyed by envelope identity and the shared-base models land
 *  there too, so asking who was announced is what keeps them out of every list a
 *  reader sees. It also depends on no name list, where "not a known node name"
 *  would depend on the node table being current. */
export const scenarioLabels = () =>
  Object.keys(state.scenarios).filter(l => state.scenarios[l].declared).sort()

/** The pipeline steps that ran sessions, in table order, each with whatever it
 *  fanned out over. One list, because every row here is a row of the node table;
 *  what differs is the shape of the fan-out — extract_flow runs one session,
 *  build_world and build_root one per fixed assumption, the scenario stage a
 *  whole assignment per scenario that fans out again inside each. */
export function stepRows () {
  const rows = []
  // A step that was gone back to has more than one execution, and the panel is
  // where that shows: the strip above it is the pipeline's shape, this is what
  // the run actually did.
  const runsOf = (node) => stagesOf('', node)
  for (const node of NODES) {
    // A shared-base step is listed because it ran, not because it had apply
    // points: with nothing to apply it opens no session and no bucket is created
    // under its identity, yet it still wrote the model every scenario
    // downstream is built from. An empty step is a fact worth showing; a missing
    // one reads as a step that never ran.
    if (node === 'build_world') {
      if (state.scenarios[WORLD_IDENT] || state.nodes[node]) {
        rows.push({ node, kind: 'root', ident: WORLD_IDENT })
      }
    } else if (node === 'build_root') {
      if (state.scenarios[ROOT_IDENT] || state.nodes[node]) {
        rows.push({ node, kind: 'root', ident: ROOT_IDENT })
      }
    } else if (node === 'scenarios') {
      const labels = scenarioLabels()
      if (labels.length) rows.push({ node, kind: 'scenarios', labels })
    } else if (state.scenarios[node]) {
      rows.push({ node, kind: 'session', ident: node })
    } else if (state.nodes[node]) {
      // A step that ran without opening a session — the claims step reads the
      // corpus, load_document and tag_sections take the document as it is. It
      // has no timeline, so its row is its products; where it writes no
      // directory at all the row still says the step ran.
      rows.push({ node, kind: 'quiet', ident: node, files: stepArtifacts(node) })
    }
  }
  return rows.map(r => ({ ...r, runs: runsOf(r.node) }))
}

/** A step's products, read off the run's own tree rather than a list kept here,
 *  so a step that starts writing something new shows it with no change on this
 *  side. Top level, plus the apply band's own result: what sits in a point
 *  (`apply/01_exposure_A/…`) or a cell (`inject/…`) belongs to that session, but
 *  `apply/world.pv` is the chain's product. Product versus record follows the
 *  backend's own rule (services/transcript/prompt.py::is_session_file). */
export function stepArtifacts (node) {
  const dir = stepDir(node)
  if (!dir) return []
  const shallow = (f) => !f.includes('/')
        || (f.startsWith('apply/') && shallow(f.slice('apply/'.length)))
  return state.files
    .filter(p => p.startsWith(`${dir}/`))
    .map(p => p.slice(dir.length + 1))
    .filter(f => shallow(f) && !isRecord(f))
    .sort()
}

/** The backend's own rule, in the backend's own order. */
const isRecord = (name) =>
  name.endsWith('transcript.jsonl') || name === 'facts.jsonl'
  || name.endsWith('prompt.md') || name.includes('.prompt.')

/** One identity's bucket, created on first sight. */
function scenario (label) {
  if (!state.scenarios[label]) {
    state.scenarios[label] = { status: 'running', assignment: [], verdicts: {},
                               units: {}, declared: false }
  }
  return state.scenarios[label]
}

/** Whose timeline an agent event belongs to: a scenario when it has one, and
 *  otherwise the node itself. The extraction steps run a session each and the
 *  envelope leaves `scenario` empty for them, so testing that field alone would
 *  drop the two largest prompts a run sends. */
const identOf = (ev) => ev.scenario || ev.node

/** Which of a scenario's concurrent sessions an event came from.
 *  `unit` is the envelope field; a ledger without it carries the composite in
 *  `node` ("inject:<scenario>:<cell>"), so the scenario is stripped back out
 *  of it here. */
function unitOf (ev) {
  if (ev.unit) return ev.unit
  const node = ev.node || ''
  return ev.scenario ? node.replace(`:${ev.scenario}`, '') : node
}

function unit (label, key) {
  const sc = scenario(label)
  if (!sc.units[key]) {
    // `items` is the session as it happened, in order: the prompt that opened
    // each round, the reply, the tool calls, what the framework did, the solver.
    // `rounds` is the same events bucketed by round, which is what a summary
    // needs; the timeline is what a reader watches.
    sc.units[key] = { key, rounds: [], items: [], usage: null, solves: [] }
  }
  return sc.units[key]
}

const push = (label, key, item) => unit(label, key).items.push(item)

const newReply = (label, key) => {
  const r = { kind: 'reply', no: null, live: { thinking: '', text: '' },
              streaming: true }
  push(label, key, r)
  return r
}

/** The reply still being written in this unit, if any. */
function openReply (label, key) {
  const items = unit(label, key).items
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].kind === 'reply') return items[i].streaming ? items[i] : null
  }
  return null
}

function round (u, no) {
  let r = u.rounds.find(x => x.no === no)
  if (!r) { r = { no, tools: [], framework: [], checks: null }; u.rounds.push(r) }
  return r
}

/** One step's line, appended. */
function noteNode (node, line) {
  if (!state.nodeLines[node]) state.nodeLines[node] = []
  state.nodeLines[node].push(line)
}

/** One event folded into the state. Pure apart from the mutation, and idempotent
 *  on seq, so reconnects, double subscriptions and a resending server all land
 *  here safely. */
export function applyEvent (ev) {
  const durable = ev.t !== 'model_delta'
  if (durable) {
    if (ev.seq <= state.lastSeq) return
    state.lastSeq = ev.seq
    // Every line is kept, and no cap here: what a long run costs is drawing
    // thousands of rows, not holding thousands of small objects. The window that
    // keeps the page quick is in the view (main.js::FEED_WINDOW), where it can
    // name what it is not showing.
    state.feed.push(ev)
    if (!HANDLED.has(ev.t) && !state.unknownTypes.includes(ev.t)) {
      state.unknownTypes.push(ev.t)          // shown as a banner, never swallowed
    }
  }
  const d = ev.data || {}
  const key = unitOf(ev)

  switch (ev.t) {
    case 'run_started':
      // A re-entry writes into the run's own ledger, so this is the second
      // run_started on one stream and the page's only notice that everything
      // from `from_node` down was superseded. Folded here, so a reload replaying
      // from seq 0 arrives at the same page as the tab that watched it happen.
      if (d.from_node) reenter(d.from_node)
      // Counted, because "a run started" is not the same fact as "the status
      // changed": a re-entry into pure-code steps can arrive in one batch with
      // the status ending where it began, so anything waiting on the engine to
      // pick up a request watches this rather than the status.
      state.runStarts += 1
      state.status = 'running'
      break
    case 'run_finished': state.status = 'ok'; break
    case 'interrupted': state.status = 'interrupted'; break
    case 'run_failed':
      // a check saying no is a result, not a breakage — the two read apart
      state.status = d.kind === 'check' ? 'check_failed' : 'failed'
      // node_finished says a step failed but not why; run_failed says why, and
      // for a step that fans out which branch of it. Neither is an answer alone,
      // so they are joined here. `where` is the branch's identity path
      // (scenarios/baseline/inject/Secrecy), empty when the failure was on the
      // run's serial spine.
      state.failure = { kind: d.kind || 'crash', reason: d.reason || '',
                        node: state.failedNode || null, where: d.where || '' }
      break

    case 'node_started':
      state.nodes[ev.node] = 'running'
      state.awaiting = null          // released, or never gated
      break
    case 'node_progress':
      noteNode(ev.node, { t: 'progress', text: d.text || '' })
      break
    case 'node_finished':
      state.nodes[ev.node] = d.status || 'ok'
      noteNode(ev.node, { t: 'finished', text: d.status || 'ok',
                          artifacts: d.artifacts || [] })
      // Remembered for run_failed, which arrives next carrying the reason but
      // not the place. Both ways a run stops badly are recorded: a node that
      // broke says `failed`, one whose check said no says `check_failed`. Where
      // it stopped is what a re-entry point is decided from.
      if (d.status === 'failed' || d.status === 'check_failed') state.failedNode = ev.node
      break
    case 'node_scored':
      state.scores[ev.node] = { slug: d.slug, num: d.num, den: d.den,
                                extra: d.extra }
      if (d.alignment_status === 'ok') {
        state.alignments[ev.node] = { status: 'ok', mappings: d.alignment }
      }
      // On the step's own record too, right after the checks verdict: "all
      // passed" says the product is well formed, this says how much of it the
      // corpus agrees with. Two different questions, wanted in one column.
      if (identOf(ev)) {
        push(identOf(ev), key, { kind: 'scored', slug: d.slug, num: d.num,
                                 den: d.den, extra: d.extra })
      }
      break
    case 'invalidated': state.nodes[ev.node] = 'pending'; break

    case 'scenario_started': {
      const sc = scenario(ev.scenario)
      sc.assignment = d.assignment || []
      // The one event that says a scenario exists. Everything else landing in
      // the scenario envelope — a step's own sessions among them — was never
      // announced, and a column drawn for it is a column of nothing.
      sc.declared = true
      break
    }
    case 'scenario_finished': {
      const sc = scenario(ev.scenario)
      sc.status = d.status || 'ok'
      sc.verdicts = d.verdicts || {}
      break
    }
    case 'solve_finished':
      unit(ev.scenario, key).solves.push({ cell: d.cell, kind: d.kind,
        seconds: d.seconds, verdicts: d.verdicts, retried: d.retried })
      push(ev.scenario, key, { kind: 'solve', cell: d.cell, ok: d.kind,
        seconds: d.seconds, verdicts: d.verdicts, retried: d.retried })
      break

    // A prompt is the one part of a session a reader cannot locate for itself:
    // the file's slot is claimed as it is written. The text stays in the file
    // and is fetched when the line is opened.
    case 'prompt_filed':
      if (identOf(ev)) {
        push(identOf(ev), key, { kind: 'prompt', no: d.round_no,
                                 path: d.path, chars: d.chars, how: d.how })
      }
      break

    // A reading filed by the expert mid-conversation. Folded like any other
    // event, so the cell it is about wears it immediately rather than after a
    // reload — the person who asked is still looking at that cell.
    case 'finding_recorded':
      state.findings.unshift({ ...d, seq: ev.seq, at: ev.ts })
      break
    case 'review_closed':
      state.review = { state: d.state, note: d.note || '' }
      break

    // One cell's reproduction, newest word wins. A new pass of the step starts
    // every cell again, and a request after the run re-queues the ones asked for.
    case 'attack_status':
      state.reproductions[reproKey(d.label, d.goal)] = {
        goal: d.goal, label: d.label, status: d.status,
        reason: d.reason || '', manual: Boolean(d.manual), seq: ev.seq }
      break
    case 'attacks_summarized':
      state.reproSummaries += 1
      break

    case 'round_started':
      if (ev.scenario || ev.node !== 'expert') {
        round(unit(identOf(ev), key), d.round_no)
        const r = openReply(identOf(ev), key) || newReply(identOf(ev), key)
        r.no = d.round_no
        r.streaming = false
        // This round's own bill, not the session's, which is shown once on the
        // unit. Only when the event actually carries it: an older ledger has no
        // such fields, and defaulting to zero would print "0 in · 0 out" beside
        // every round of it, claiming the round was free.
        if (d.input_tokens != null || d.output_tokens != null) {
          r.usage = { in: d.input_tokens || 0, out: d.output_tokens || 0,
                      cached: d.cached_tokens || 0 }
        }
      } else if (ev.node === 'expert') {
        state.expertRound = d.round_no
        // A round lands after the model has already answered, so the thinking
        // that built it is over: dropped, or nine rounds of it pile up in one
        // bubble. The text is kept — on the last round it is the answer being
        // written, and clearing it would blink.
        if (state.drafts.expert) state.drafts.expert.thinking = ''
      }
      break
    case 'tool_called':
      if (identOf(ev)) {
        const u = unit(identOf(ev), key)
        const r = u.rounds[u.rounds.length - 1] || round(u, 1)
        r.tools.push({ tool: d.tool, args: d.args_digest })
        push(identOf(ev), key, { kind: 'tool', tool: d.tool, args: d.args_digest })
      }
      break
    case 'tool_returned':
      if (identOf(ev)) {
        const u = unit(identOf(ev), key)
        const r = u.rounds[u.rounds.length - 1]
        const t = r && [...r.tools].reverse().find(x => x.tool === d.tool)
        if (t) { t.ok = d.ok; t.result = d.result_digest }
        const it = [...u.items].reverse().find(x => x.kind === 'tool' && x.tool === d.tool)
        if (it) { it.ok = d.ok; it.result = d.result_digest }
      }
      break
    case 'framework_action':
      if (identOf(ev)) {
        const u = unit(identOf(ev), key)
        const r = u.rounds[u.rounds.length - 1] || round(u, 1)
        r.framework.push(d.text)
        push(identOf(ev), key, { kind: 'framework', text: d.text })
      }
      break
    // One named check. `running` opens the line and the outcome closes it in
    // place, the same pair tool_called/tool_returned already uses.
    case 'check_ran':
      if (identOf(ev)) {
        const u = unit(identOf(ev), key)
        const open = [...u.items].reverse()
          .find(x => x.kind === 'check' && x.check === d.check && x.running)
        if (d.state === 'running') {
          if (!open) {
            push(identOf(ev), key, { kind: 'check', check: d.check,
                                     running: true, findings: [], note: '' })
          }
        } else {
          const it = open || (push(identOf(ev), key,
            { kind: 'check', check: d.check, findings: [], note: '' })
            , u.items[u.items.length - 1])
          it.running = false
          it.passed = d.state === 'passed'
          it.seconds = d.seconds
          it.findings = d.findings || []
          it.note = d.note || ''
        }
      }
      break
    case 'check_report':
      if (identOf(ev)) {
        const u = unit(identOf(ev), key)
        const r = u.rounds[u.rounds.length - 1] || round(u, 1)
        r.checks = { passed: d.passed, findings: d.findings || [] }
        // The verdict's findings are the union of the failing checks', so where
        // each check has already reported its own, repeating them buries the one
        // new thing: how many, out of how many checks. A ledger with no
        // per-check lines keeps them, being there the only account of why.
        const detail = [...u.items].reverse()
        const prev = detail.findIndex(x => x.kind === 'checks')
        const named = (prev < 0 ? detail : detail.slice(0, prev))
          .some(x => x.kind === 'check')
        push(identOf(ev), key,
             { kind: 'checks', passed: d.passed, count: (d.findings || []).length,
               findings: named ? [] : (d.findings || []) })
      }
      break
    case 'session_usage': {
      // Every session, not only a scenario's: the extraction steps have no
      // scenario, and dropping their cost would leave the page unable to say
      // what a run had spent.
      const u = { in: d.input_tokens || 0, out: d.output_tokens || 0,
                  cached: d.cached_tokens || 0 }
      const bill = state.usage
      bill.in += u.in; bill.out += u.out; bill.cached += u.cached
      // Billed to the identity that ran the session, not to the ledger's node
      // field: apply sessions all say `apply` there, whether the root model's or
      // a scenario's, so a per-node tally cannot tell the two steps apart.
      const at = identOf(ev)
      const per = bill.by[at] || (bill.by[at] = { in: 0, out: 0, cached: 0 })
      per.in += u.in; per.out += u.out; per.cached += u.cached
      if (identOf(ev)) unit(identOf(ev), key).usage = u
      break
    }

    // The manual gate. The engine stops here and waits to be released, so this
    // has to reach a button: a run parked at a boundary with nothing on screen
    // but a log line waits forever.
    case 'awaiting_approval': state.awaiting = ev.node; break

    case 'aggregated': state.results = d.results || []; break
    case 'cross_checked':
      state.crossCheck = d.cells || []
      break

    case 'expert_replied':
      state.chat.push({ who: 'it', text: d.text })
      state.asking = false
      // The turn that proposed a plan is over with this reply, decided or
      // stopped (the host answers the plan on every way out), so nothing is
      // waiting any more. Folded here so a reload that replays an old
      // awaiting_confirm does not bring the card back for a plan long gone.
      state.pending = null
      delete state.drafts.expert
      break
    case 'expert_asked':
      state.chat.push({ who: 'me', text: d.text })
      break
    case 'awaiting_confirm':
      state.pending = { digest: d.plan_digest, cost: d.cost_digest }
      break

    case 'model_delta': {
      // The second, temporary input: fragments are not on the ledger and take
      // no seq, so they exist only while something is speaking. Thinking and the
      // answer are kept apart — one buffer makes the reply start mid-thought.
      const slot = d.kind === 'thinking' ? 'thinking' : 'text'
      if (ev.node === 'expert' && !ev.scenario) {
        // The expert is not a step of the pipeline and has no unit: its
        // fragments belong to the chat panel, which reads `live.expert`. Keyed
        // like a unit they land in a lane nobody draws, and a question that
        // takes minutes shows nothing but "thinking… round N".
        const buf = state.drafts.expert || (state.drafts.expert = { thinking: '', text: '' })
        buf[slot] += (d.text || '')
        break
      }
      const at = `${identOf(ev)}/${key}`
      const buf = state.drafts[at] || (state.drafts[at] = { thinking: '', text: '' })
      buf[slot] += (d.text || '')
      if (identOf(ev)) {
        // The first fragment is what opens the reply. round_started lands after
        // the call returns, which is too late to watch anything.
        const r = openReply(identOf(ev), key) || newReply(identOf(ev), key)
        r.live[slot] += (d.text || '')
      }
      break
    }
  }

  // Whatever spoke last, so a reader who has not chosen for themselves can be
  // shown something happening rather than an empty panel. Who acts on it is the
  // page's business.
  if (SESSION_EVENTS.has(ev.t) && identOf(ev)) {
    state.lastAt = { ident: identOf(ev), unit: key }
  }

  // Anything the framework says means the model has already returned, so a reply
  // still marked as being written is over. round_started normally does this;
  // these are the paths that reach the framework without one.
  if (identOf(ev) && ['tool_called', 'framework_action', 'check_report'].includes(ev.t)) {
    const r = openReply(identOf(ev), key)
    if (r) r.streaming = false
  }

  // a finished round supersedes whatever fragments built it
  if (ev.t === 'check_report' && identOf(ev)) delete state.drafts[`${identOf(ev)}/${key}`]
}

// A scenario walks four stages on disk, and the lane draws them as four segments
// rather than one bar, so "how far" and "which stage" read at once. The names
// are the directories the stage writes; the fixed layer is the build_root step
// and runs before any scenario starts.
export const PHASES = ['apply', 'scenario.pv', 'inject', 'solve']

// One apply point is one unit: `apply/03_leaked_from_start`. The depth guard
// keeps anything nested below a point from being counted as a second one.
const A_POINT = /^apply\/[^/]+$/
// A family is `inject/Secrecy`; a chunk the per-call cap split off is a family
// directory of its own (`inject/Authentication_c2`). Both
// belong to the one family, so the depth is trimmed before counting.
const IN_INJECT = /^inject\/[^/]+/
const family = (k) => k.split('/').slice(0, 2).join('/')

/** Which directory one goal's model was built in, addressed the way the ledger
 *  addresses it. A cell's directory is `<scenario>/inject/<Type>/<subtype>` and
 *  the ledger names all three: the envelope's unit is the inject family that ran
 *  the call (`inject/Secrecy`), SolveFinished's `cell` is the subtype inside it,
 *  and its `verdicts` say which goals that cell answered for, so the address is
 *  a lookup in what is already folded. */
function injectCellDir (label, goalId) {
  const sc = state.scenarios[label]
  const home = scenarioDir(label)
  if (!sc || !home) return null
  for (const key of Object.keys(sc.units)) {
    if (!IN_INJECT.test(key)) continue
    for (const s of sc.units[key].solves) {
      if (s.cell && s.verdicts && goalId in s.verdicts) {
        // The unit key is the session's path relative to its scenario, so it
        // already carries the family's own numbered directory and nothing here
        // has to rebuild it. The batch directory is the answer's directory —
        // one session, one .pv — so nothing is appended to it.
        return `${home}/${family(key)}`
      }
    }
  }
  return null
}

/** Where a scenario has got to: how many phases are behind it, and the counts
 *  behind the status line. Derived from what the ledger already says, there
 *  being no progress event. Returns a shape, never a sentence — the words belong
 *  to whichever language the page is in. */
export function lanePhase (label) {
  const sc = state.scenarios[label]
  if (!sc) return { at: 0, kind: 'waiting' }
  const keys = Object.keys(sc.units)
  const applies = keys.filter(k => A_POINT.test(k))
  const injects = [...new Set(keys.filter(k => IN_INJECT.test(k)).map(family))]
  const solved = Object.keys(sc.verdicts).length

  // Finished: how many of the goals this scenario was asked about hold in it.
  // The transpose of the results table's `holds in k/m`, which counts scenarios
  // for one goal.
  if (solved) {
    const hold = Object.values(sc.verdicts).filter(v => v === 'true').length
    return { at: 4, kind: 'verdicts', a: hold, b: solved }
  }
  if (injects.length) {
    // scenario.pv is behind it by then: a family is injected into that file.
    const done = injects.filter(k => sc.units[k] && sc.units[k].solves.length).length
    return { at: 2, kind: 'inject', a: done, b: injects.length }
  }
  if (applies.length) {
    const done = applies.filter(k => {
      const r = sc.units[k].rounds
      return r.length && r[r.length - 1].checks && r[r.length - 1].checks.passed
    }).length
    return { at: 0, kind: 'apply', a: done, b: applies.length }
  }
  return { at: -1, kind: 'queued' }
}

/** How one scenario's cells came out against the corpus's own answers. Null when
 *  there is nothing to compare with — no ground truth, or cross_check not
 *  reached — and the caller falls back to the scenario's own verdict. The cells
 *  name their scenario by the assumptions it assigned, so the column is found
 *  the same way the matrix finds it (columnOf). */
export function laneAgreement (label) {
  const cells = (state.crossCheck || []).filter(c => columnOf(c) === label)
  if (!cells.length) return null
  return { of: cells.length, matched: cells.filter(c => c.match).length }
}

/** The goals one inject unit answered, and how many of them the corpus agrees
 *  with. One session injects a whole goal family and hands ProVerif every goal
 *  in it at once, so the goals are listed under the row that produced them
 *  rather than promoted to rows of their own. Read off the unit's own solve
 *  events, so it still works on a run whose declarations never loaded. Null for
 *  a unit that solved nothing. */
export function unitGoals (label, key) {
  const sc = state.scenarios[label]
  const u = sc && sc.units[key]
  if (!u || !u.solves.length) return null
  const truth = {}
  for (const c of state.crossCheck || []) {
    if (columnOf(c) === label) truth[c.id] = c
  }
  // A retried solve reports the same goals again; the last word is the answer.
  const seen = new Map()
  for (const s of u.solves) {
    for (const id of Object.keys(s.verdicts || {})) {
      seen.set(id, { id, verdict: s.verdicts[id], cell: truth[id] || null })
    }
  }
  if (!seen.size) return null
  const goals = [...seen.values()].sort((a, b) => (a.id < b.id ? -1 : 1))
  // Only the goals the corpus has an opinion about are counted, the same rule
  // the lane above uses: otherwise a run with no ground truth reads as 0/4
  // rather than as not compared.
  const compared = goals.filter(g => g.cell)
  return { goals,
           of: compared.length,
           matched: compared.filter(g => g.cell.match).length }
}

/** The run's scenarios as columns, ordered by how much each one declares: the
 *  one that assumes least sits leftmost and every column to its right piles more
 *  on. There is no order in the source, the scenarios being independent and run
 *  concurrently. */
export function scenarioColumns () {
  return scenarioLabels()
    .map(label => {
      const sc = state.scenarios[label]
      const rows = sc.assignment || []
      return {
        label,
        sc,
        declares: rows.filter(r => r.from === 'condition').length,
        // A finished scenario's verdicts hold exactly the goals the claims named
        // it against, so absence there means "never asked". While it is still
        // running, absence means "not yet", which is a different thing.
        settled: sc.status !== 'running',
      }
    })
    .sort((a, b) => a.declares - b.declares || a.label.localeCompare(b.label))
}

/** A dimension's target, in as few words as it can be said. */
export const targetOf = (t) => !t ? ''
  : Object.entries(t)
      .map(([k, v]) => k === 'phase' ? `phase ${v}`
                     : Array.isArray(v) ? v.join('→') : String(v))
      .join(' · ')

/** The assumption side of the table: what every scenario carries, and what
 *  differs between them. Grouped by axis — the KB's assumption axis, what
 *  realizers are registered against — because one protocol can hang several
 *  dimensions off the same axis, told apart only by their target (Otway-Rees has
 *  exposure_A and exposure_B, both on `exposure`). */
export function dimensions () {
  const cols = scenarioColumns()
  const byId = {}
  for (const w of cols) {
    for (const r of w.sc.assignment || []) {
      const d = byId[r.id] || (byId[r.id] = { id: r.id, axis: r.axis, target: r.target, by: {} })
      d.by[w.label] = r
    }
  }
  const all = Object.values(byId)
  const isFixed = (d) => cols.length > 0 &&
    cols.every(w => d.by[w.label] && d.by[w.label].from === 'fixed')

  // The assumptions every scenario carries, split the way the pipeline builds
  // them: build_world lays down the terrain (population, honesty, role binding,
  // session multiplicity), build_root applies the rest onto it. Which axes are
  // which comes from the backend's vocabulary, so an axis moving tiers needs no
  // change on this side.
  const worldAxes = new Set(state.vocab.world_axes || [])
  const carried = all.filter(isFixed).sort((a, b) => a.id.localeCompare(b.id))
  const world = carried.filter(d => worldAxes.has(d.axis))
  const root = carried.filter(d => !worldAxes.has(d.axis))

  const groups = {}
  for (const d of all.filter(d => !isFixed(d)).sort((a, b) => a.id.localeCompare(b.id))) {
    (groups[d.axis] = groups[d.axis] || []).push(d)
  }
  return {
    world,
    root,
    groups: Object.keys(groups).sort().map(axis => ({
      axis,
      rows: groups[axis],
      // The values this run actually used on the axis, not the declared domain:
      // the ledger carries the value each scenario took, so this is a summary of
      // what is visible in the cells below it.
      seen: [...new Set(groups[axis].flatMap(d =>
        cols.map(w => d.by[w.label] && d.by[w.label].subtype).filter(Boolean)))],
    })),
  }
}

/** The goal side. A join, not a calculation: every verdict comes from the
 *  backend, the cells from each scenario's own verdicts and the truth column
 *  from cross_check, and the conjunction rule lives in `nodes/aggregate`. Rows
 *  come back in blocks — runs of goals the claims asked in the same set of
 *  scenarios — so a block's whole unused region is drawn once instead of once
 *  per row. The one thing worked out here is which column a disagreement belongs
 *  to, since a cross-check cell names its scenario as an assignment. */
export function matrix () {
  const cols = scenarioColumns()
  const labels = cols.map(c => c.label)


  // The comparison against ground truth, cell by cell — the level the table is
  // drawn at. Read one level up, off the aggregated answer, two conjunctions
  // agree whenever their disagreements cancel, and a row shows green while one
  // of its scenarios is wrong.
  const truthAt = {}
  for (const c of state.crossCheck || []) {
    const l = columnOf(c)
    if (l) (truthAt[c.id] = truthAt[c.id] || {})[l] = c
  }

  // Rows are the answers the run gave. Before aggregate runs there are none, so
  // the scenarios' own goals stand in: a matrix mid-run is still worth showing,
  // it simply has no answer column yet.
  const ids = state.results.length
    ? state.results.map(r => r.id)
    : [...new Set(labels.flatMap(l => Object.keys(state.scenarios[l].verdicts)))].sort()
  const answer = Object.fromEntries(state.results.map(r => [r.id, r]))

  const rows = ids.map(id => {
    const cells = cols.map(w => {
      const c = (truthAt[id] || {})[w.label]
      const v = w.sc.verdicts[id]
      // The truth this scenario expected travels with the cell, so a wrong
      // answer says what the right one was where the wrong one is.
      const seen = c ? { match: c.match, expected: c.expected } : null
      if (v) return { kind: 'verdict', v, ...seen }
      // Only a settled scenario can say "never asked"; until then it is simply
      // not in yet.
      return { kind: w.settled ? 'unasked' : 'pending', ...seen }
    })
    const asked = cells.map(c => c.kind !== 'unasked')
    const compared = cells.filter(c => c.match !== undefined && c.match !== null)
    return {
      id,
      cells,
      asked,
      // Counted over correctness, not over verdicts: being right in one scenario
      // and right in another add up, while "held in 1 of 2 scenarios" adds
      // across mutually exclusive alternatives.
      matched: compared.filter(c => c.match).length,
      compared: compared.length,
      why: answer[id] ? answer[id].description || '' : '',
    }
  })

  // Blocks: goals sharing a coverage pattern, widest coverage first, then by the
  // leftmost scenario each uses. Sorting is the whole mechanism — once rows with
  // the same pattern are adjacent, each block's unused region is one contiguous
  // rectangle and needs no heading to be legible.
  const key = (r) => r.asked.map(a => a ? '1' : '0').join('')
  const rank = (r) => [-r.of, ...r.asked.flatMap((a, i) => a ? [i] : [])]
  const seen = new Map()
  for (const r of rows) {
    const k = key(r)
    if (!seen.has(k)) seen.set(k, { uses: r.asked, rows: [], rank: rank(r) })
    seen.get(k).rows.push(r)
  }
  const cmp = (a, b) => {
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const d = (a[i] ?? Infinity) - (b[i] ?? Infinity)
      if (d) return d
    }
    return 0
  }

  return {
    labels,
    scenarios: cols,
    // Ground truth is compared cell by cell, so its presence is a fact about the
    // cells: a corpus with no results/ directory simply has no column.
    hasTruth: Boolean((state.crossCheck || []).length),
    rows,
    blocks: [...seen.values()].sort((a, b) => cmp(a.rank, b.rank)),
  }
}
