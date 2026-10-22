import { createApp, computed, ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import {
  timeline, timelineKind, reworksUnder, stageFiles,
  state, resetRun, matrix, dimensions, targetOf, evidence, cellDetail,
  reviewFindings, findingFor, lineage,
  stepDir, scenarioDir, lanePhase, scenarioLabels, stepRows,
  laneAgreement, ownerOf, unitGoals,
  stepArtifacts,
  NODES, PHASES, ROOT_IDENT, WORLD_IDENT, HANDLED, setNodes,
  pipelineLayout, runGroups, runCorpusRows, corpusRows,
  reproKey, reproOf,
} from './store.js'
import { open, close, api } from './stream.js'
import { line, marked, where, clock, day, tokens } from './format.js'
import { t, lang, setLang } from './i18n.js'
import { introduced, removed, quoted, hasQuote, lineDiff } from './diff.js'
import { highlight } from './pv.js'
import { AttackPlayer, quoteParts } from './replay.js'

const VERDICT = { true: '✓', false: '✗', unknown: '?' }

/** #/            → the run list
 *  #/run/NSPK01  → that run */
const route = ref(location.hash.slice(2).split('/'))
addEventListener('hashchange', () => { route.value = location.hash.slice(2).split('/') })

/** What ran under one parent, in the order it ran. One component for every
 *  level of the tree, drawn only when something there ran more than once.
 *
 *  A chain (the node table, a scenario's apply points) is drawn as the sequence
 *  it is, with superseded executions struck through off `stages.live`. A
 *  fan-out (a stage's scenarios, a scenario's goal families) has no order, so
 *  it reports generations instead. */
const StageTimeline = {
  props: { parent: { type: String, default: '' }, band: { type: String, default: '' } },
  setup (props) {
    const open = ref(null)
    const rows = computed(() => timeline(props.parent))
    const kind = computed(() => timelineKind(props.parent))
    // Worth drawing only when something here ran twice.
    const worth = computed(() => {
      const seen = {}
      for (const r of rows.value) seen[r.ident] = (seen[r.ident] || 0) + 1
      return Object.values(seen).some((n) => n > 1)
    })
    const gens = computed(() => {
      const by = {}
      for (const r of rows.value) (by[r.ident] = by[r.ident] || []).push(r)
      return Object.entries(by).map(([ident, all]) => ({ ident, all }))
    })
    // How many times it went back: an execution that replaced an earlier one,
    // which is what the ↩ beside it marks.
    const backs = computed(() => rows.value.filter(r => r.supersedes).length)
    const toggle = (dir) => { open.value = open.value === dir ? null : dir }
    /** One cell's hover text. Composed here rather than in the dictionary,
     *  which has no way for one phrase to call another. */
    const tip = (r) => [r.dir, t.value.causeOf(r.cause, r.by),
                        r.supersedes ? t.value.replaces(r.supersedes) : '',
                        '', t.value.openStage].filter(x => x !== undefined).join('\n')
    return { rows, kind, worth, gens, backs, open, toggle, tip, t,
             files: stageFiles, show: (p) => showFile(p),
             pin: (p) => pinFile(p), pinned: (p) => isPinned(p) }
  },
  template: `
  <div v-if="worth" class="tline">
    <div class="thead">
      <span v-if="band" class="mono dim">{{ band }}</span>
      <span class="why">{{ t.wentBack(backs) }}</span>
      <span class="dim sm">{{ kind === 'seq' ? t.tlSeqHint : t.tlGenHint }}</span>
    </div>

    <div v-if="kind === 'seq'" class="trow">
      <template v-for="r in rows" :key="r.dir">
        <span v-if="r.supersedes" class="wentback" :title="t.causeOf(r.cause, r.by)">↩</span>
        <a href="#" class="tcell" :class="{stale: !r.live, on: open === r.dir}"
           :title="tip(r)"
           @click.prevent="toggle(r.dir)">{{ r.dir.split('/').pop() }}</a>
      </template>
    </div>

    <div v-else class="trow">
      <span v-for="g in gens" :key="g.ident" class="tgen">
        <a href="#" class="tcell" :class="{on: open === g.all[g.all.length - 1].dir}"
           :title="tip(g.all[g.all.length - 1])"
           @click.prevent="toggle(g.all[g.all.length - 1].dir)">{{ g.ident }}</a>
        <span class="dim sm">{{ t.generation(g.all.length - 1) }}</span>
      </span>
    </div>

    <!-- What that execution left: the only way into a superseded attempt's
         files, which are still on disk. -->
    <ul v-if="open" class="nodelog tfiles">
      <li v-for="f in files(open)" :key="f" class="product">
        <span class="glyph">·</span>
        <a href="#" class="mono" @click.prevent="show(open + '/' + f)">{{ f }} ↗</a>
        <a href="#" class="pin" :class="{on: pinned(open + '/' + f)}"
           :title="pinned(open + '/' + f) ? t.unpinTip : t.pinTip"
           @click.stop.prevent="pin(open + '/' + f)">{{ pinned(open + '/' + f) ? '✓' : '+' }}</a>
      </li>
      <li v-if="!files(open).length"><span class="glyph">·</span>
        <span class="muted">{{ t.noProducts }}</span></li>
    </ul>
  </div>`,
}

/** A coach mark: one bubble pointed at something already on the page.
 *
 *  Anchored by selector and drawn over the page from measured coordinates —
 *  the things it points at sit inside scrolling boxes that would clip a nested
 *  bubble. Nothing is drawn while the anchor is absent or off-screen, and it
 *  starts the moment one appears. Re-measured every frame, since the anchors
 *  move for reasons no event names; state changes only when the numbers do. */
const COACH_GAP = 14        // between the ring round the anchor and the bubble

/** Where the marks already on screen sit, so a later one can step out of an
 *  earlier one's way. Keyed by mount order and consulted upwards only: a mark
 *  yields to the ones placed before it and never the other way round, which is
 *  what keeps the answer the same every frame. */
const COACH_TAKEN = new Map()
let coachSeq = 0

const CoachMark = {
  props: {
    at: { type: String, required: true },       // what it points at
    head: { type: String, default: '' },
    text: { type: String, default: '' },
    side: { type: String, default: 'right' },   // right, or below
    align: { type: String, default: 'start' },  // which end of the box it lines up with
    // Whether the rest of the page goes dark behind it. On for a mark asking
    // for a click on one particular control, off for one annotating something
    // already on screen: two scrims at once would each darken what the other
    // is pointing at.
    spotlight: { type: Boolean, default: false },
  },
  emits: ['close'],
  setup (props, { emit }) {
    const bubble = ref(null)
    const pos = ref(null)     // null while there is nothing to point at
    const seq = coachSeq++
    let raf = 0
    const measure = () => {
      raf = requestAnimationFrame(measure)
      const el = document.querySelector(props.at)
      const b = el && el.getBoundingClientRect()
      // Off-screen counts as absent: a mark parked against the top edge while
      // its anchor is two screens down is pointing at nothing.
      if (!b || !b.width || b.bottom < 0 || b.top > innerHeight) {
        if (pos.value) pos.value = null
        COACH_TAKEN.delete(seq)
        return
      }
      // The bubble's own size, so the fallback never has to agree with a width
      // in the stylesheet. Measured hidden on the first frame.
      const w = bubble.value ? bubble.value.offsetWidth : 320
      const h = bubble.value ? bubble.value.offsetHeight : 120
      // Centred in a box taller than itself, top-aligned in one that is not.
      let top = props.side === 'below' ? b.bottom + COACH_GAP
        : b.height >= h ? b.top + (b.height - h) / 2 : b.top
      let left = props.side === 'below'
        ? (props.align === 'end' ? b.right - w : b.left)
        : b.right + COACH_GAP
      // Flipped to the other side rather than run off the edge, and never past
      // the top or the bottom of the window.
      let flipped = false
      if (left + w > innerWidth - 8) {
        left = Math.max(8, b.left - COACH_GAP - w)
        flipped = true
      }
      left = Math.max(8, left)
      top = Math.max(8, Math.min(top, innerHeight - h - 8))
      // Pushed under whatever was placed before it where the two would overlap;
      // down rather than sideways, since these hang off panels stacked
      // down the page.
      for (const [id, m] of COACH_TAKEN)
        if (id < seq && left < m.left + m.w && left + w > m.left
            && top < m.top + m.h && top + h > m.top)
          top = m.top + m.h + 8
      COACH_TAKEN.set(seq, { top, left, w, h })
      // Which edge of the bubble faces the anchor, and how far along that edge
      // the anchor's middle falls: the nib is drawn there, so the bubble points
      // at the one thing it is about rather than merely sitting near it. Kept
      // off the corners, which are rounded and would cut it in half.
      const dir = props.side === 'below' ? 'up' : flipped ? 'right' : 'left'
      const along = dir === 'up'
        ? b.left + b.width / 2 - left : b.top + b.height / 2 - top
      const caret = Math.round(
        Math.max(16, Math.min(along, (dir === 'up' ? w : h) - 16)))
      // "click here" belongs at here, not in the prose. Above the anchor where
      // there is room for it, under it where there is not. The 110 is a bound
      // on the chip: two short words in either language, and nothing else.
      const ct = b.top > 34 ? b.top - 27 : b.bottom + 9
      const cl = Math.max(8, Math.min(b.left, innerWidth - 110))
      const o = pos.value
      if (!o || o.rt !== b.top || o.rl !== b.left || o.rw !== b.width
          || o.rh !== b.height || o.top !== top || o.left !== left
          || o.caret !== caret)
        pos.value = { rt: b.top, rl: b.left, rw: b.width, rh: b.height,
                      top, left, dir, caret, ct, cl }
    }
    // One box round the anchor, worn by both the ring and the pulse over it.
    const ringStyle = computed(() => pos.value && {
      top: (pos.value.rt - 5) + 'px', left: (pos.value.rl - 5) + 'px',
      width: (pos.value.rw + 10) + 'px', height: (pos.value.rh + 10) + 'px',
    })
    const nibStyle = computed(() => pos.value && (pos.value.dir === 'up'
      ? { left: pos.value.caret + 'px' } : { top: pos.value.caret + 'px' }))
    // A darkened page that outstays its welcome is worse than none, so a mark
    // holding the page down goes when the reader clicks anywhere else. Only
    // that mark: one that darkens nothing costs nothing to leave standing, and
    // the two on the run page are two separate answers — waving one away is no
    // answer at all about the other. The mark swallows no clicks, so this
    // listener is the only thing that notices.
    const away = (e) => {
      const el = document.querySelector(props.at)
      if (bubble.value?.contains(e.target) || el?.contains(e.target)) return
      emit('close')
    }
    onMounted(() => {
      measure()
      if (props.spotlight) addEventListener('pointerdown', away, true)
    })
    onUnmounted(() => {
      cancelAnimationFrame(raf)
      if (props.spotlight) removeEventListener('pointerdown', away, true)
      COACH_TAKEN.delete(seq)
    })
    return { pos, bubble, t, ringStyle, nibStyle, close: () => emit('close') }
  },
  template: `
  <div class="coach" :class="{on: !!pos}">
    <template v-if="pos">
      <span class="ring" :class="{lit: spotlight}" :style="ringStyle"></span>
      <!-- Drawn over the ring rather than on it: the ring carries the scrim,
           and that must not breathe with the pulse. -->
      <span class="glow" :style="ringStyle"></span>
      <span v-if="spotlight" class="cue"
            :style="{top: pos.ct + 'px', left: pos.cl + 'px'}">{{ t.tourHere }}</span>
    </template>
    <!-- Always rendered, hidden until placed: it has to be on the page to be
         measured. -->
    <div class="bub" ref="bubble" :class="pos ? 'to-' + pos.dir : null" @click="close"
         :style="pos ? {top: pos.top + 'px', left: pos.left + 'px'} : null">
      <span v-if="pos" class="nib" :style="nibStyle"></span>
      <strong>{{ head }}</strong>
      <p>{{ text }}</p>
      <span class="hint">{{ t.tourDismiss }}</span>
    </div>
  </div>`,
}

// The three things the timeline needs from the page it sits in, bound once the
// app is set up: a component defined at module scope cannot reach the run
// panel's own closures.
let showFile = () => {}
let pinFile = () => {}
let isPinned = () => false

const App = {
  setup () {
    /** The three levels of one address. `openNode` is the selected pipeline
     *  cell, `openScenario` the identity showing under it (a scenario label,
     *  or the ident a shared-base step files its sessions under), `openUnit`
     *  the session. Together they spell the step path a retry is aimed by. */
    const openNode = ref(null)
    const openScenario = ref(null)
    const openUnit = ref(null)
    const filter = ref(null)
    const viewing = ref(null)          // {path, text} in the file dialog
    const feedEl = ref(null)
    /** How much of the feed is drawn before a reader asks for the rest. A cap
     *  on rows in the DOM, not on what is kept: nothing is dropped from
     *  state.feed.
     *
     *  Declared here rather than beside the computed that reads it: the
     *  run-change watcher is immediate, so a `const` further down the setup
     *  would still be in its temporal dead zone. */
    const FEED_WINDOW = 300
    const showAllFeed = ref(false)
    // Follow the tail unless the reader has scrolled up to look at something;
    // scrolling back down re-attaches.
    const stick = ref(true)
    const onFeedScroll = () => {
      const el = feedEl.value
      if (el) stick.value = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    }

    // ── how wide one scenario column is ──────────────────────────────────
    // The matrix always fills its panel: the fixed columns take what their
    // contents need and the scenarios share the rest, down to a floor past
    // which they stop shrinking and the box scrolls instead.
    //
    // The floor is set by the header, not the cell: a column name must be
    // readable in full, so eleven monospace characters at --t-sm (7.5px each)
    // plus the cell's padding. Names wrap at their underscores rather than
    // being cut — two truncated scenario names can read as the same thing.
    const MIN_COL = 11 * 7.5 + 24
    const matrixEl = ref(null)
    const colw = ref(MIN_COL)
    // Where the match column pins: the property column's real width, set by
    // the longest goal id and so not knowable here.
    const idw = ref(0)

    /** A label split for wrapping: each piece keeps its trailing underscore and
     *  the template puts a break opportunity after it, so a narrow column wraps
     *  at the name's own joints rather than mid-word. */
    const nameParts = (l) => {
      const seg = String(l).split('_')
      return seg.map((s, i) => (i < seg.length - 1 ? s + '_' : s))
    }

    function fitColumns () {
      const wrap = matrixEl.value
      const table = wrap && wrap.querySelector('table.matrix')
      const n = matrix().labels.length
      if (!table || !table.tHead || !n) return
      // The fixed side is measured, not assumed: the property column sizes to
      // the longest goal id. None of these widths depend on colw, so this
      // settles in one pass.
      const cells = [...table.tHead.rows[0].cells]
      const fixed = cells.filter(c => !c.classList.contains('sc'))
                         .reduce((a, c) => a + c.offsetWidth, 0)
      colw.value = Math.max(MIN_COL, Math.floor((wrap.clientWidth - fixed) / n))
      idw.value = cells[0].offsetWidth
    }

    // ── tooltips ─────────────────────────────────────────────────────────
    // Two sources, answering two questions. The vocabulary says what a subtype
    // means, written where the realizer or the injector lives; the run's own
    // claim files say what this question was. Neither is state, so neither is
    // folded from the ledger.

    /** A dimension's value: what this subtype does to the model. */
    const dimTip = (d, cell) => {
      if (!cell) return ''
      const said = (state.vocab.assumptions[d.axis] || {})[cell.subtype]
      const from = cell.from === 'condition' ? t.value.fromCondition
                 : cell.from === 'fixed' ? t.value.fromFixed : t.value.defaultTip
      return [`${cell.subtype} — ${from}`, said].filter(Boolean).join('\n\n')
    }

    /** A dimension itself: which target it is about, and its declared domain,
     *  of which the ledger only ever shows one value. */
    const dimNameTip = (d) => {
      const decl = state.decl.dims[d.id]
      const domain = decl && (decl.subtypes || (decl.subtype ? [decl.subtype] : []))
      // The axis is the heading right above this row, so it is left out here.
      return [d.target ? `${t.value.tipTarget}: ${targetOf(d.target)}` : '',
              domain && domain.length ? `${t.value.tipDomain}: ${domain.join(' | ')}` : '',
             ].filter(Boolean).join('\n')
    }

    /** An axis, explained by the values it can take. The vocabulary is written
     *  per subtype and there is no axis-level sentence anywhere. */
    const axisTip = (axis) => {
      const said = state.vocab.assumptions[axis] || {}
      const lines = Object.keys(said).sort().map(sub => `${sub} — ${said[sub]}`)
      return [axis, ...lines].join('\n\n')
    }

    /** A goal: its kind, what that kind means, and what it is about. */
    const goalTip = (id) => {
      const g = state.decl.goals[id]
      if (!g) return id
      const kind = g.subtype ? `${g.type} / ${g.subtype}` : g.type
      const said = (state.vocab.goals[g.type] || {})[g.subtype || 'basic']
      const who = g.parties && Object.entries(g.parties)
        .map(([k, v]) => `${k} ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ')
      return [kind, said,
              g.values && g.values.length ? `${t.value.tipValues}: ${g.values.join(', ')}` : '',
              who ? `${t.value.tipParties}: ${who}` : '',
             ].filter(Boolean).join('\n')
    }

    /** The kind badge beside a goal id — the one thing the id itself omits. */
    const goalKind = (id) => {
      const g = state.decl.goals[id]
      return g ? (g.subtype || g.type) : ''
    }

    /** How much of the run agrees with the ground truth, cell by cell, counted
     *  off the comparison cross_check published. The page never decides what
     *  agrees. */
    const agreeCount = computed(() => {
      const cells = state.crossCheck || []
      const hit = cells.filter(c => c.match).length
      return { hit, of: cells.length, all: hit === cells.length }
    })

    // Re-fit on anything that moves the arithmetic: the panel resizing, a
    // scenario arriving, or a language change (the fixed headers are words).
    onMounted(() => {
      new ResizeObserver(fitColumns).observe(document.body)
      fitColumns()
    })
    watch([() => matrix().labels.length, () => matrix().rows.length, lang],
          () => nextTick(fitColumns))

    // Keep the newest line in view while the reader is at the foot of the feed.
    watch(() => state.feed.length, () => {
      if (!stick.value) return
      nextTick(() => {
        const el = feedEl.value
        if (el) el.scrollTop = el.scrollHeight
      })
    })

    const runName = computed(() =>
      route.value[0] === 'run' ? route.value[1] : null)

    // ── the launcher ─────────────────────────────────────────────────────
    // Everything a run needs except the protocol's identity comes out of the
    // corpus layout (resolve_lib_inputs, server side), so this is a picker with
    // three fields after it. The name cannot be resolved — some corpus entries
    // declare no protocol_id — so a blank one is asked for rather than guessed;
    // the run directory is named after it.
    // The corpus root lives in the config (paths.lib_root) rather than in the
    // browser, and is seeded from it once the config arrives.
    const libRoot = ref('')
    // Which mode the console is in, straight off the server: the launch route,
    // the protocol scan and the stream all read it, and a mode held in the
    // browser would be a second answer. Not in `store.js` — the fold must not
    // learn whether it is folding a playback or a run.
    const playbackMode = ref({ on: true, root: '', root_exists: false, runs: [] })
    const playbackOn = computed(() => !!playbackMode.value.on)

    /*  Whether the config panel stands open. Live it is what a fresh clone has
     *  to fill in before anything runs, so it opens; playing back it is
     *  read-only, so it folds and the launch panel above takes the height. A
     *  mode switch resets it; the reader's own answer holds until then. */
    const cfgOpen = ref(true)
    watch(playbackOn, (on) => { cfgOpen.value = !on }, { immediate: true })
    const picked = ref(null)          // the chosen protocol row
    const form = ref({ name: '', version: '', subprotocol: '', runName: '' })
    const scanErr = ref('')
    const starting = ref(false)
    const protoFilter = ref('')

    const shownProtocols = computed(() => {
      const q = protoFilter.value.trim().toLowerCase()
      return state.protocols.filter(p => !q ||
        p.dir.toLowerCase().includes(q) || (p.name || '').toLowerCase().includes(q))
    })

    /* ── the launch list, as standards that open ───────────────────────────
     *  Four fifths of the corpus is ISO mechanisms, so `corpusRows` folds those
     *  into openable standards and leaves everything else flat.
     *
     *  Alphabetical, unlike the run list: this one answers "what can I run",
     *  and the corpus's own order is how a person looks something up in it. */
    const openProtoGroups = ref(new Set())
    const toggleProtoGroup = (head) => {
      const s = new Set(openProtoGroups.value)
      s.has(head) ? s.delete(head) : s.add(head)
      openProtoGroups.value = s
    }
    /*  Open when the reader opened it, or when a filter is running: every ISO
     *  hit lives inside a collapsed standard, so without the second half a
     *  filter would leave every match invisible. */
    const protoGroupOpen = (head) =>
      openProtoGroups.value.has(head) || Boolean(protoFilter.value.trim())

    /*  Kept in the order api/reading_order.py gave, not re-sorted: sorting by
     *  path puts ISO between Denning-Sacco and NSPK and splits the two textbook
     *  protocols a reader should meet first. */
    const protoRows = computed(() => corpusRows(shownProtocols.value, p => p.dir))

    /** The rows the panel draws: every group, and the children of the open
     *  ones. Flattened here rather than nested in the template — the list is
     *  one scrolling column and a row's depth is a class on it. */
    const protoVisible = computed(() => {
      const out = []
      for (const r of protoRows.value) {
        if (!r.group) { out.push({ kind: 'leaf', p: r.item, sub: false }); continue }
        out.push({ kind: 'head', head: r.head, n: r.children.length })
        if (protoGroupOpen(r.head))
          for (const c of r.children)
            out.push({ kind: 'leaf', p: c.item, sub: true, leafName: c.leaf })
      }
      return out
    })

    /* ── the first visit ────────────────────────────────────────────────
     *  Four marks over two pages: which protocol, the button that starts it,
     *  and the two panels the run itself is read through. `?tour` in the URL
     *  asks for the whole thing back at any time.
     *
     *  The seen flag is written on reaching the run page, not on starting the
     *  tour, so a stray load of the list does not spend it. A mark timing out
     *  hides that mark alone and leaves the tour running, since the stages are
     *  advanced by what the reader clicks. The stages are a string so the
     *  places that advance it say which mark they advance from. */
    const TOUR_KEY = 'aifv.tour'
    // Private mode throws on both. Unreadable storage reads as "seen", so a
    // browser that cannot remember the tour is not shown it on every load.
    const tourSeen = () => {
      try { return !!localStorage.getItem(TOUR_KEY) } catch { return true }
    }
    const markTourSeen = () => {
      try { localStorage.setItem(TOUR_KEY, '1') } catch { /* private mode */ }
    }
    // What each stage puts on screen, so a timeout can retire exactly those.
    const TOUR_MARKS = { pick: ['proto'], start: ['start'], run: ['pipe', 'inside'] }
    // How long a mark stands untouched. The two here wait for a click; the
    // pair on the run page annotate something already moving, so they go
    // sooner.
    const TOUR_HOLD = { pick: 45000, start: 45000, run: 22000 }
    const tour = ref('')            // '' | 'pick' | 'start' | 'run'
    // Which marks are off screen — clicked away, or timed out. The run page
    // shows two about different things, so dismissing one keeps the other.
    const tourShut = ref([])
    let tourTimer = 0
    const tourTo = (stage) => {
      clearTimeout(tourTimer)
      tour.value = stage
      tourShut.value = []
      if (stage === 'run') markTourSeen()
      if (stage) tourTimer = setTimeout(() => {
        if (tour.value === stage) tourShut.value = TOUR_MARKS[stage]
      }, TOUR_HOLD[stage])
    }
    // Over for good, and said so on disk: waving a mark away answers for the
    // whole tour, not just that bubble.
    const endTour = () => { clearTimeout(tourTimer); markTourSeen(); tour.value = '' }
    const shutMark = (m) => { tourShut.value = tourShut.value.concat(m) }
    // Not `marked`: that name is already the feed's line highlighter, and an
    // object literal with the key twice keeps the second.
    const showMark = (m, stage) => tour.value === stage && !tourShut.value.includes(m)

    /** The row the first mark points at: NSPK where the tree has it, the
     *  protocol the tour names, and otherwise whatever the tree leads with. */
    const tourProto = computed(() => {
      const leaves = protoVisible.value.filter(r => r.kind === 'leaf')
      const one = leaves.find(r => (r.p.name || '') === 'NSPK') || leaves[0]
      return one ? one.p.abs : ''
    })

    /* ── two ways in ───────────────────────────────────────────────────────
     *  A corpus and a document of your own are two questions, so they are two
     *  controls. The corpus box is a recursive sweep whose endpoint calls
     *  itself a suggestion, not a resolution; a reader who has the document
     *  already has the answer, so: browse, point, run. The one thing that
     *  cannot be derived — which document is the subject when a folder holds
     *  several — is asked. A recording is not a document, so the switch is
     *  live-only and playing back forces the mode back. */
    const sourceMode = ref('corpus')          // 'corpus' | 'document'
    watch(playbackOn, (on) => { if (on) sourceMode.value = 'corpus' })
    const browsing = ref(null)      // the directory listing on screen
    const browsePath = ref('')      // the box above it; typing a path still works
    const browseErr = ref('')
    const target = ref(null)        // what the reader pointed at, resolved
    // Which document is the subject, and which neighbours ride with it. Only
    // ever set by the reader: `target.main` answers whenever it can, and these
    // fill the gap when it cannot.
    const mainDoc = ref('')
    const refDocs = ref([])

    async function openDir (path) {
      browseErr.value = ''
      try {
        browsing.value = await api.browse(path)
        // Echo what was opened rather than what was typed: the server expands
        // ~ and resolves symlinks.
        browsePath.value = browsing.value.path
      } catch (e) { browseErr.value = String(e.message || e) }
    }

    /** Open the browser the first time this mode is chosen, at home rather than
     *  at the process's working directory. */
    function toDocumentMode () {
      sourceMode.value = 'document'
      if (!browsing.value) openDir(browsePath.value || '')
    }

    /** The sub-protocols of whatever is chosen, whichever way it was chosen.
     *  One form over two sources: without it the form reads `picked` and throws
     *  when it was filled from a document. */
    const chosenSubs = computed(() => sourceMode.value === 'document'
      ? (target.value ? target.value.subprotocols : [])
      : (picked.value ? picked.value.subprotocols : []))

    /** Point at one thing — a directory or a document — and fill the form from
     *  what it turns out to be. */
    async function pickTarget (path) {
      browseErr.value = ''
      try {
        const t = await api.target(path)
        target.value = t
        mainDoc.value = t.main || ''
        refDocs.value = t.refs.slice()
        form.value = { name: t.name || '', version: '',
                       subprotocol: t.subprotocols[0] || '', runName: '' }
        // A switch the target cannot answer is turned off here, visibly: the
        // engine refuses that combination outright, so the run would never
        // start.
        for (const r of LIB_ROWS)
          if (!supplies(r.knob) && knobAt(r.knob) === true) await setLib(r.knob, false)
      } catch (e) { target.value = null; browseErr.value = String(e.message || e) }
    }

    /** Whether the thing now pointed at can answer one switch. True with
     *  nothing pointed at, so the corpus list is not greyed by a question
     *  nobody asked. */
    const supplies = (knob) => {
      const k = knob.replace('inputs.', '')
      if (sourceMode.value === 'document')
        return !target.value || (target.value.supplies || {})[k] !== false
      const p = picked.value
      if (!p || !p.supplies) return true
      const row = p.supplies[form.value.subprotocol || ''] || p.supplies[''] ||
                  Object.values(p.supplies)[0]
      return !row || row[k] !== false
    }

    /** The documents this folder offers, when it offered more than one and the
     *  reader has to say which is the subject. Empty otherwise. */
    const docChoice = computed(() =>
      target.value && target.value.layout === 'documents'
        && target.value.docs.length > 1 ? target.value.docs : [])
    /*  The name follows the chosen document until the reader types one: a
     *  folder can only suggest its own name, and once the subject is known the
     *  document's is the better guess. Equality with the last suggestion is
     *  what says nobody has edited it. */
    watch(mainDoc, (path) => {
      if (!path || !target.value) return
      const stem = (path.split('/').pop() || '').replace(/\.[^.]+$/, '')
      if (!form.value.name || form.value.name === target.value.name)
        form.value.name = stem
      target.value = { ...target.value, name: stem }
    })

    const toggleRef = (path) => {
      refDocs.value = refDocs.value.includes(path)
        ? refDocs.value.filter(x => x !== path)
        : refDocs.value.concat(path)
    }
    // Ready when there is a subject. A corpus-shaped folder has none to name,
    // since its own layout answers, so pointing at one is enough.
    const targetReady = computed(() => !!target.value
      && (target.value.layout === 'corpus' || !!mainDoc.value))

    /** The tree the launch panel points at: the recorded runs when playing
     *  back, the protocol corpus when live. The server has resolved both, so
     *  this only asks which. */
    function rootForMode () {
      return playbackOn.value ? (playbackMode.value.root || '')
                            : (knobAt('paths.lib_root') || '')
    }

    /** Flip between playing back the record and running the pipeline for real.
     *  Everything downstream re-reads: the work root moves, so the run list and
     *  the launch tree are both different. */
    async function setMode (on) {
      if (playbackOn.value === on) return
      scanErr.value = ''
      picked.value = null
      state.protocols = []
      try {
        playbackMode.value = await api.setPlaybackMode(on)
        state.cfg = await api.config()
        state.runs = await api.runs()
      } catch (e) {
        // The panel was emptied above for the mode about to arrive; a refusal
        // has to be said, or it reads as a mode with nothing in it.
        scanErr.value = String(e.message || e)
        return
      }
      libRoot.value = rootForMode()
      scan()
    }

    async function scan () {
      scanErr.value = ''
      try {
        const r = await api.protocols(libRoot.value)
        state.protocols = r.protocols
        // The server resolved it (relative paths are project-relative), so show
        // what was read rather than what was typed.
        libRoot.value = r.root
        // Remembered only once it is known to work, so a failed scan does not
        // become the next start's tree. One box, two knobs: playing back it is
        // where the recordings are, live it is where the corpus is, and each
        // mode writes its own.
        const rootKnob = playbackOn.value ? 'paths.playback_root' : 'paths.lib_root'
        if (r.root !== knobAt(rootKnob)) {
          const k = knobs.value.find(x => x.path === rootKnob)
          if (k) await saveKnob(k, r.root)
        }
      } catch (e) { scanErr.value = String(e.message || e); state.protocols = [] }
    }

    function pick (p) {
      picked.value = p
      form.value = { name: p.name || '', version: p.version || '',
                     subprotocol: p.subprotocols[0] || '', runName: '' }
      // The tour's first mark asked for this click, and the button it points
      // at next does not exist until it happens.
      if (tour.value === 'pick') tourTo('start')
    }

    async function startRun () {
      const doc = sourceMode.value === 'document'
      if (doc ? !targetReady.value : !picked.value) return
      if (!form.value.name.trim() || starting.value) return
      starting.value = true
      scanErr.value = ''
      try {
        const { name } = await api.startRun({
          protocol_name: form.value.name.trim(),
          protocol_dir: doc ? target.value.root : picked.value.abs,
          version: form.value.version.trim(),
          subprotocol: form.value.subprotocol,
          run_name: form.value.runName.trim(),
          // Named only where they were chosen. A corpus entry sends nothing and
          // load_document discovers its own documents, the same "given, use it;
          // absent, do the work" the supplied artifacts follow.
          ...(doc && target.value.layout === 'documents'
              ? { main_doc: mainDoc.value, ref_docs: refDocs.value } : {}),
        })
        state.runs = await api.runs()
        // The playback session exists only once the server has built it, so the
        // badge's speed is read back rather than guessed.
        if (playbackOn.value) playbackMode.value = await api.playbackMode()
        // The last two marks are on the page this is about to open.
        if (tour.value === 'start') tourTo('run')
        location.hash = `#/run/${name}`   // straight to watching it
      } catch (e) { scanErr.value = String(e.message || e) }
      starting.value = false
    }

    // ── the config panel ─────────────────────────────────────────────────
    // Every edit is saved to config.yaml the moment it is made, so a setting
    // outlives the run it was made for. The server owns the file; this only
    // reports what it says.
    const knobs = computed(() => (state.cfg && state.cfg.knobs) || [])
    const cfgErr = ref('')
    const saving = ref('')

    /** A knob's value as the file has it. */
    const knobAt = (path) => {
      const k = knobs.value.find(x => x.path === path)
      return k ? k.value : ''
    }

    /** Which backend's slot is live — the only one of the four the panel
     *  shows. */
    const backend = computed(() => knobAt('llm.backend'))
    const ready = computed(() => (state.cfg && state.cfg.ready) || [])

    /** The rows to draw: everything that is not a profile slot, plus the live
     *  slot's own, folded in where llm.backend sits. */
    const rows = computed(() => {
      const out = []
      for (const k of knobs.value) {
        if (k.profile && k.profile !== backend.value) continue
        out.push(k)
      }
      return out
    })

    /** A knob's list, which for some knobs is another knob's answer. Looked up
     *  through the relation the backend declared. */
    const choicesFor = (k) => {
      if (!k.depends_on) return k.choices
      return ((state.cfg.backends || {})[knobAt(k.depends_on)] || {}).models || []
    }

    /** A suggested list with the current value folded in. BACKENDS lists what
     *  this repo has talked to, not what a gateway accepts, so a value set by
     *  hand has to survive being shown in a dropdown. */
    const withCurrent = (k) => {
      const list = choicesFor(k)
      return k.value && !list.includes(k.value) ? [k.value, ...list] : list
    }

    /** The label a row shows: a profile slot is drawn under its leaf name, so
     *  `profiles.remote-claude.` is not repeated on every line of the block. */
    const knobLabel = (k) => k.profile
      ? k.path.split('.').pop()
      : k.path.split('.').slice(1).join('.')

    /** Save one value. The reply is the whole config again, so anything the
     *  change dragged with it — a new backend's url and model — lands in the
     *  same update. */
    async function saveKnob (k, raw) {
      const same = String(raw) === String(k.value ?? '')
      if (same || (k.secret && raw === '(set)')) return
      let value = raw
      if (raw === '') value = null
      else if (k.type === 'number') value = Number(raw)
      else if (k.type === 'boolean') value = raw === 'true'
      cfgErr.value = ''
      saving.value = k.path
      try {
        state.cfg = await api.saveConfig(k.path, value)
        // The run list is a different directory's now.
        if (k.path === 'paths.work_root') state.runs = await api.runs()
        // The recordings moved. Playing back, that tree is also what the run
        // routes read, so the list and the mode's own answer both follow —
        // without this the panel offers protocols whose run pages 404.
        if (k.path === 'paths.playback_root') {
          playbackMode.value = await api.playbackMode()
          state.runs = await api.runs()
        }
        // The corpus root moved.
        if (k.path === 'paths.lib_root') await scan()
      } catch (e) { cfgErr.value = String(e.message || e) }
      saving.value = ''
    }

    /** The two switches beside the start button: take this band from the
     *  corpus, or let the run extract it. Ordinary config knobs, not launch
     *  options — the launch request carries no settings, so a run started from
     *  the command line with that config resolves the same files. */
    async function toggleInput (path, on) {
      const k = knobs.value.find(x => x.path === path)
      if (k) await saveKnob(k, on ? 'true' : 'false')
    }

    /** One of the two supply bands, straight to config. The value is a stage
     *  name, so the chain rule ("this file and everything before it") stays in
     *  the engine. */
    async function setInput (path, value) {
      const k = knobs.value.find(x => x.path === path)
      if (k) await saveKnob(k, value)
    }

    /** One row per artifact: take the corpus's copy, or extract it.
     *
     *  Independent choices with one real dependency — a mother model needs the
     *  principals.json it was written on, because flow_fixed_parts compares its
     *  role signatures against the template rendered from that file. The
     *  question is not coupled to the model: corpus claims with an extracted
     *  flow model measures the flow extraction on a fixed question. */
    const LIB_ROWS = [
      { knob: 'inputs.lib_principals', label: () => t.value.libPrincipals,
        makes: 'extract_principals' },
      { knob: 'inputs.lib_flow', label: () => t.value.libFlow,
        makes: 'extract_flow', needs: 'inputs.lib_principals' },
      { knob: 'inputs.lib_claims', label: () => t.value.libClaims,
        makes: 'extract_assumptions … extract_claims' },
    ]

    /** Where a run may be told to stop, and what the last step is called.
     *  `scenarios` runs to the end of the table, so its last step is whatever
     *  the backend's table ends with. */
    const END_POINTS = computed(() => [
      { id: 'principals', after: 'extract_principals' },
      { id: 'flow', after: 'extract_flow' },
      { id: 'claims', after: 'extract_claims' },
      { id: 'scenarios', after: NODES[NODES.length - 1] || 'scenarios' },
    ])

    const libRows = computed(() => LIB_ROWS.map(r => ({
      ...r, label: r.label(), on: knobAt(r.knob) === true,
      // Whether "supplied" is a choice here at all: a directory with no
      // flow/principals.json cannot answer it, and offering the button anyway
      // buys a FileNotFoundError where a run should have been.
      can: supplies(r.knob),
    })))

    /** Set one row, keeping the dependency true in both directions: a model
     *  turns on its principals, and turning the principals off turns off the
     *  model. The engine refuses the broken pair too
     *  (api/corpus_inputs.check_inputs); this keeps the panel from asking. */
    async function setLib (knob, on) {
      await setInput(knob, on ? 'true' : 'false')
      for (const r of LIB_ROWS) {
        if (on && r.knob === knob && r.needs) await setInput(r.needs, 'true')
        if (!on && r.needs === knob) await setInput(r.knob, 'false')
      }
    }

    /** What a finished run was handed, and where it stopped — off its own
     *  record, mapped by the engine (api/corpus_inputs.supplied_of). */
    const ranLib = computed(() => state.range || null)

    /** The steps this run will actually do, in table order: every row set to
     *  extract, cut off at the end point. */
    const willRun = computed(() => {
      const end = knobAt('inputs.end_point') || 'scenarios'
      const ends = END_POINTS.value
      const upto = ends.findIndex(e => e.id === end)
      const steps = libRows.value.filter(r => !r.on).map(r => r.makes)
      if (upto >= 0 && upto < ends.length - 1) {
        steps.length = Math.min(steps.length, upto + 1)
      } else {
        steps.push(`build_world … ${ends[ends.length - 1].after}`)
      }
      return steps.join(' · ') || t.value.willRunNothing
    })


    /** A request the page needed that the server did not answer: said in a
     *  banner rather than left in the console, and cleared by the next poll
     *  that succeeds. */
    const serverErr = ref('')
    const failed = (what) => (e) => {
      serverErr.value = `${what}: ${String(e.message || e)}`
    }

    // The step table travels with the vocabulary, and everything that folds a
    // re-entry needs it (store.js::reenter): a reload's stream must not outrun
    // it, so the stream on a run opens only once this has landed. The page
    // holds no table of its own, so a node added to the pipeline appears here
    // with no front-end change.
    const booted = api.vocabulary().then(v => {
      state.vocab = v
      setNodes(Object.keys(v.steps || {}))
    })
    booted.catch(failed('the vocabulary did not load'))

    onMounted(async () => {
      try {
        await booted
        state.runs = await api.runs()
        // The page's own exhaustiveness check: the backend names every event
        // type it can send, and anything with no case here is said out loud.
        const known = await api.eventTypes()
        state.unknownTypes = known.filter(t => !HANDLED.has(t))
        state.cfg = await api.config()
        playbackMode.value = await api.playbackMode()
      } catch (e) {
        failed('the console did not start')(e)
        return
      }
      libRoot.value = rootForMode()
      scan()
      // Only ever from the list: the tour's first mark points at a row that
      // exists on this page alone.
      if (!runName.value && (!tourSeen() || location.search.includes('tour')))
        tourTo('pick')
    })

    // The run list is a snapshot of a directory tree, and a run in flight keeps
    // changing it. Polled only while the list is the page a reader is on.
    setInterval(async () => {
      if (runName.value) return
      try {
        state.runs = await api.runs()
        serverErr.value = ''
      } catch (e) {
        failed('the run list did not refresh')(e)
      }
    }, 4000)

    /** What this run was asked, read out of the step that wrote it: a goal's
     *  values and parties, a dimension's declared domain. Reference data, not
     *  state — no event repeats it.
     *
     *  Each vocabulary is tried at its own extraction step, then extract_claims,
     *  then `claims`, and accumulated into `state.decl`, so whichever half is
     *  ready shows now. Retried on every tree refresh — with no declarations a
     *  cell's inject stage cannot be addressed (store.js::familyOf). */
    async function loadDeclarations (name) {
      const read = async (nodes, file) => {
        for (const n of nodes) {
          const dir = stepDir(n)
          if (!dir) continue               // that step has not written yet
          const r = await api.file(name, `${dir}/${file}`)
          try { return JSON.parse(r.text) } catch { /* mid-write; try the next */ }
        }
        return null
      }
      if (!state.declLoaded.goals) {
        const props = await read(['extract_properties', 'extract_claims', 'claims'], 'properties.json')
        if (state.current !== name) return      // the page moved on meanwhile
        if (props) {
          for (const p of props.properties || []) state.decl.goals[p.id] = p
          state.declLoaded.goals = true
        }
      }
      if (!state.declLoaded.dims) {
        const asmp = await read(['extract_assumptions', 'extract_claims', 'claims'], 'assumptions.json')
        if (state.current !== name) return
        if (asmp) {
          for (const k of ['fixed', 'variable']) {
            for (const a of asmp[k] || []) state.decl.dims[a.id] = { ...a, section: k }
          }
          state.declLoaded.dims = true
        }
      }
    }

    /** The run's file list, and whatever reading it makes newly possible. One
     *  function for both callers, because the declarations are read off the
     *  tree: `stepDir` finds the claims directory in it, so a fresh tree is the
     *  only moment worth trying again. */
    async function refreshTree (name) {
      const t = await api.tree(name)
      // A reply that arrives after the page has moved to another run would
      // resolve every path on it against this one's tree. Same guard on every
      // reader below.
      if (state.current !== name) return
      state.files = t.files || []
      // The index comes with the files, and neither answers alone: a step the
      // run went back to has two directories, and which one to read is not
      // something the names state.
      state.stages = t.stages || []
      state.live = t.live || {}
      state.problems = t.problems || []
      // Which steps were handed their artifact instead of producing it. The
      // engine decides (nodes/base.py::pinned_nodes); the page only draws it.
      state.pinned = t.pinned || []
      // What this run was asked to do, over the same stops the New run panel
      // offers: handed in up to `start`, stopped at `end`.
      state.range = t.range || null
      await loadDeclarations(name)
    }

    /** The readings filed on this run, and whether it is still open. Read once
     *  when the run opens; after that they arrive on the stream, so one filed
     *  while you are looking at a cell appears without a reload. */
    async function loadReview (name) {
      const r = await api.review(name)
      if (state.current !== name) return
      state.review = r.review || { state: 'open', note: '' }
      state.findings = r.findings || []
    }

    /** The corpus scores for a run that already finished — the catch-up read,
     *  since a live run puts the same numbers on the stream as each step ends.
     *  A run with no corpus answers empty and the strip carries no badges. */
    async function loadScores (name) {
      const r = await api.evaluation(name)
      if (state.current !== name) return
      const out = {}
      const alignments = {}
      for (const [node, v] of Object.entries(r.products || {})) {
        if (v && !v.supplied && Number.isFinite(v.num)) out[node] = v
        if (v && v.alignment) {
          alignments[node] = {
            status: v.alignment.status,
            error: v.alignment.error || '',
            mappings: [
              ...(v.alignment.mappings || []),
              ...(v.alignment.principal_mappings || []),
              ...(v.alignment.symbol_mappings || [])
            ].map(x => ({ candidate: x.candidate, gold: x.gold }))
          }
        }
      }
      state.scores = out
      state.alignments = alignments
    }

    // ── attack reproductions ─────────────────────────────────────────────
    // What the reproduce_attacks step chose and made, read off its files
    // (api/attacks.py): which false cells were replayed, which wait for a
    // person, which were left out and why. A reading, not state, so it is read
    // again whenever the ledger says something changed there; the script and
    // the explanation behind a cell are read only while its player is open.
    // Declared above the run watcher, which is immediate and resets them.
    const EMPTY_REPRO = { step: null, cells: [], summary: null }
    const reproIndex = ref(EMPTY_REPRO)
    const reproErr = ref('')
    const reproOpen = ref(null)       // the key of the cell whose player is open
    const reproFiles = ref(null)      // {key, script, explanation, error} behind it
    let reproOpenedFor = ''           // the run whose first attack was opened for it
    let reproSoon = 0
    // Asking for cells. The choice is the page's own until it is sent — never
    // folded, never on the ledger — and nothing changes on screen when a
    // request is sent: the cells turn queued when the stream says so.
    const reproSelecting = ref(false)
    const reproPicked = ref(new Set())
    const reproSending = ref(false)
    const reproNote = ref('')
    let summaryPoll = 0

    const reproRows = computed(() => Object.fromEntries(
      reproIndex.value.cells.map(c => [reproKey(c.label, c.goal), c])))
    const reproQueue = computed(() => reproIndex.value.queue || [])
    /** How one false cell's reproduction is drawn, or null (store.reproOf). */
    const reproLook = (goal, label) =>
      reproOf(goal, label, reproRows.value[reproKey(label, goal)], reproQueue.value)

    /** Every false cell the index or the ledger knows of, with its look, in
     *  the results table's order. A cell the step chose and never finished —
     *  the step stopped under it — is said to be unfinished rather than drawn
     *  as though nothing had been decided. */
    const reproCells = computed(() => {
      const m = matrix()
      const rowAt = Object.fromEntries(m.rows.map((r, i) => [r.id, i]))
      const colAt = Object.fromEntries(m.labels.map((l, i) => [l, i]))
      const all = new Map(reproIndex.value.cells.map(c => [reproKey(c.label, c.goal), c]))
      for (const [k, r] of Object.entries(state.reproductions)) {
        if (!all.has(k)) all.set(k, { goal: r.goal, label: r.label, decision: 'auto',
                                      manual: r.manual })
      }
      const out = []
      for (const [key, c] of all) {
        const rp = reproOf(c.goal, c.label, reproRows.value[key], reproQueue.value)
          || (c.decision === 'auto'
            ? { look: 'unfinished', manual: false, stale: false, reason: '' } : null)
        if (!rp) continue
        out.push({ ...c, ...rp, key,
                   at: [rowAt[c.goal] ?? Infinity, colAt[c.label] ?? Infinity] })
      }
      return out.sort((a, b) => a.at[0] - b.at[0] || a.at[1] - b.at[1])
    })
    const reproBy = computed(() => {
      const by = { done: [], flying: [], failed: [], pending: [], skipped: [] }
      for (const c of reproCells.value) {
        by[c.look === 'queued' || c.look === 'running' ? 'flying'
           : c.look === 'unfinished' ? 'failed' : c.look].push(c)
      }
      return by
    })
    const reproCounts = computed(() => {
      const b = reproBy.value
      return { all: reproCells.value.length, done: b.done.length,
               flying: b.flying.length, failed: b.failed.length,
               pending: b.pending.length, skipped: b.skipped.length }
    })
    const reproPanel = computed(() =>
      reproIndex.value.step !== null || reproCells.value.length > 0)
    /** Cells reproduced on request after the summary was written, which it
     *  therefore does not speak for. */
    const reproOutside = computed(() => {
      const covered = new Set((reproIndex.value.summary || {}).covered || [])
      return reproBy.value.done.filter(c => c.manual && !covered.has(c.label + '/' + c.goal))
    })
    /** A summary names a cell as scenario/goal. */
    const summaryKey = (n) => {
      const i = n.indexOf('/')
      return reproKey(n.slice(0, i), n.slice(i + 1))
    }
    const summaryCell = (n) => {
      const i = n.indexOf('/')
      return n.slice(i + 1) + ' @ ' + (colOf(n.slice(0, i)) || n.slice(0, i))
    }

    async function loadRepro (name) {
      try {
        const r = await api.attacks(name)
        if (state.current !== name) return
        reproIndex.value = r
        reproErr.value = ''
      } catch (e) {
        if (state.current === name) reproErr.value = String(e.message || e)
        return
      }
      // The first attack opens by itself, once per visit: the panel is for
      // watching, and a column of closed rows asks for a click first. Once
      // only, so a reader who closed it is not overruled by the next reading.
      if (reproOpenedFor !== name && !reproOpen.value) {
        const first = reproBy.value.done[0]
        if (first) { reproOpenedFor = name; openRepro(first.key) }
      }
    }
    /** Read the index again soon: a cell finishing lands several events at
     *  once, and one reading answers them all. */
    const reloadRepro = () => {
      clearTimeout(reproSoon)
      reproSoon = setTimeout(() => {
        if (state.current) loadRepro(state.current)
      }, 700)
    }
    // What says the step's files moved: a cell's status, a new summary, and
    // the step's own lines — a session ending is an explanation written.
    const REPRO_WROTE = new Set(['attack_status', 'attacks_summarized'])
    const STEP_WROTE = new Set(['node_started', 'node_progress', 'node_finished',
                                'session_usage'])
    watch(() => state.lastSeq, (seq, prev) => {
      const from = prev === undefined || seq < prev ? -1 : prev
      for (let i = state.feed.length - 1; i >= 0 && state.feed[i].seq > from; i--) {
        const e = state.feed[i]
        if (REPRO_WROTE.has(e.t)
            || (e.node === 'reproduce_attacks' && STEP_WROTE.has(e.t))) {
          reloadRepro()
          return
        }
      }
    })

    /** A JSON file of this run, or a thrown reason: the file route answers a
     *  missing file with a sentence rather than a status. */
    async function readJson (path) {
      const r = await api.file(state.current, path)
      try { return JSON.parse(r.text) } catch { throw new Error(r.text) }
    }
    /** Read whatever the open player still lacks. */
    async function readRepro (key) {
      const c = reproRows.value[key]
      const f = reproFiles.value
      if (!c || !f || f.key !== key) return
      try {
        if (!f.script && c.script) f.script = await readJson(c.script)
        if (!f.explanation && c.explanation) f.explanation = await readJson(c.explanation)
      } catch (e) { f.error = String(e.message || e) }
    }
    /** Open one cell's player, or close it; `jump` brings it into view and
     *  never closes it. */
    function openRepro (key, jump = false) {
      if (reproOpen.value === key && !jump) {
        reproOpen.value = reproFiles.value = null
        return
      }
      if (reproOpen.value !== key) {
        reproOpen.value = key
        reproFiles.value = { key, script: null, explanation: null, error: '' }
        readRepro(key)
      }
      if (jump) nextTick(() => {
        const el = document.querySelector('.rp-item.open')
        const col = el && el.closest('.main-col')
        if (col) col.scrollTop += el.getBoundingClientRect().top
                                 - col.getBoundingClientRect().top - 12
      })
    }
    // An explanation written while its player is open is read at once.
    watch(() => reproOpen.value && (reproRows.value[reproOpen.value] || {}).explanation,
          (path) => { if (path) readRepro(reproOpen.value) })

    /** Something is being worked on: a cell queued or in hand, or a summary
     *  being written. */
    const reproBusy = computed(() => reproBy.value.flying.length > 0
      || reproQueue.value.length > 0 || Boolean(reproIndex.value.summarizing))
    const reproToolbar = computed(() => Boolean(reproIndex.value.step
      && reproIndex.value.step.enabled
      && (reproBy.value.pending.length || reproBusy.value)))

    function toggleSelecting () {
      reproSelecting.value = !reproSelecting.value
      if (!reproSelecting.value) reproPicked.value = new Set()
      reproNote.value = ''
    }
    function pickCell (key) {
      const s = new Set(reproPicked.value)
      s.has(key) ? s.delete(key) : s.add(key)
      reproPicked.value = s
      reproNote.value = ''
    }
    function pickAllWaiting () {
      reproSelecting.value = true
      reproPicked.value = new Set(reproBy.value.pending.map(c => c.key))
      reproNote.value = ''
    }
    // A picked cell that stopped waiting (queued by another tab, say) is no
    // longer the reader's to ask for.
    watch(() => reproBy.value.pending.map(c => c.key).join(','), () => {
      const waiting = new Set(reproBy.value.pending.map(c => c.key))
      const kept = [...reproPicked.value].filter(k => waiting.has(k))
      if (kept.length !== reproPicked.value.size) reproPicked.value = new Set(kept)
    })

    /** Send cells to the run's queue. The answer names what was taken; the
     *  cells themselves turn queued when the stream says so. */
    async function askFor (keys) {
      if (reproSending.value) return
      const byKey = Object.fromEntries(reproCells.value.map(c => [c.key, c]))
      const cells = keys.map(k => byKey[k]).filter(Boolean)
        .map(c => ({ scenario: c.label, goal: c.goal }))
      if (!cells.length) { reproNote.value = t.value.rpPickFirst; return }
      reproSending.value = true
      reproNote.value = ''
      try {
        const r = await api.askAttacks(state.current, cells)
        reproNote.value = t.value.rpAsked(r.queued.length, r.refused)
        reproPicked.value = new Set()
      } catch (e) {
        reproNote.value = t.value.rpAskFailed(e.name === 'TimeoutError'
          ? t.value.rpNoAnswer : String(e.message || e))
      }
      reproSending.value = false
      reloadRepro()
    }
    const askSelected = () => askFor([...reproPicked.value])
    const askOne = (goal, label) => askFor([reproKey(label, goal)])

    async function stopRepro () {
      try {
        const r = await api.stopAttacks(state.current)
        reproNote.value = t.value.rpStopped(r.stopped)
      } catch (e) {
        reproNote.value = t.value.rpAskFailed(String(e.message || e))
      }
      reloadRepro()
    }

    async function resummarize () {
      reproNote.value = ''
      try {
        await api.resummarize(state.current)
      } catch (e) {
        reproNote.value = t.value.rpAskFailed(String(e.message || e))
      }
      reloadRepro()
    }
    // A summary being written says nothing on the stream until it is done, and
    // nothing at all when it fails, so the index is asked again while it runs.
    watch(() => Boolean(reproIndex.value.summarizing), (on) => {
      clearInterval(summaryPoll)
      if (on) summaryPoll = setInterval(() => {
        if (state.current) loadRepro(state.current)
      }, 3000)
    })

    /** What stands where an explanation should be. A cell's explanation is
     *  still coming while whatever reproduced it is at work: the step for its
     *  own cells, the queue for the ones asked for. */
    const reproNoExplain = (c) => c.explain_error ? t.value.rpExplainFailed(c.explain_error)
      : (c.manual ? reproQueue.value.includes(c.key)
                  : state.nodes.reproduce_attacks === 'running') ? t.value.rpExplaining
      : t.value.rpNoExplanation

    // ── the false cells in the table ────────────────────────────────────
    const REPRO_GLYPH = { done: '\u25B6\uFE0E', queued: '\u25F7', running: '\u27F3',
                          failed: '!', unfinished: '!' }
    const cellRepro = (goal, label, cell) =>
      cell.kind === 'verdict' && cell.v === 'false' ? reproLook(goal, label) : null
    /** The classes a false cell wears for its reproduction. Waiting and left
     *  out look like any other false: the table's ground already says what
     *  the comparison said. */
    const reproCellClass = (goal, label, cell) => {
      const rp = cellRepro(goal, label, cell)
      if (!rp) return null
      const waiting = rp.look === 'pending'
      return [waiting || rp.look === 'skipped' ? '' : 'rp-' + rp.look, {
        'rp-manual': rp.manual && rp.look === 'done',
        'rp-sel': reproPicked.value.has(reproKey(label, goal)),
        'rp-pickable': reproSelecting.value && waiting,
      }]
    }
    const reproCellMark = (goal, label, cell) => {
      const rp = cellRepro(goal, label, cell)
      if (!rp) return ''
      if (reproPicked.value.has(reproKey(label, goal))) return '\u2611'
      return REPRO_GLYPH[rp.look] || ''
    }
    const reproCellTip = (goal, label, cell) => {
      const rp = cellRepro(goal, label, cell)
      if (!rp) return ''
      const row = reproRows.value[reproKey(label, goal)] || {}
      return t.value.rpCellTip({ ...rp, expected: row.expected || '' })
    }
    const opensAttack = (goal, label, cell) => {
      const rp = cellRepro(goal, label, cell)
      return Boolean(rp && (rp.look === 'done'
                            || (reproSelecting.value && rp.look === 'pending')))
    }
    /** A reproduced cell opens its attack; while selecting, a waiting cell
     *  is picked or put back; every other cell opens its inspector. */
    function cellClick (goal, label, cell) {
      if (cell.kind !== 'verdict') return pickScenario(label)
      const rp = cellRepro(goal, label, cell)
      if (reproSelecting.value && rp && rp.look === 'pending') {
        return pickCell(reproKey(label, goal))
      }
      if (rp && rp.look === 'done') return openRepro(reproKey(label, goal), true)
      openInspector(goal, label)
    }

    /** The playback playing this run, if one is. Carries the speed, which is the
     *  one thing on screen that is true of the playback and not of the run. */
    const playbackHere = computed(() => (playbackMode.value.runs || [])
      .find(r => r.name === runName.value) || null)

    // Declared above the run watcher that resets it: that watcher is
    // `immediate`, so a `const` further down would still be in its temporal
    // dead zone when it ran.
    const follow = ref(true)

    /** The results panel, so the end of a run can put the answer on screen —
     *  what the reader came for sits a panel below the last step's session.
     *  Only while the page was still following on its own: a reader who picked
     *  a step or a unit has said where they want to be. */
    const resultsEl = ref(null)
    watch(() => state.status, (now, was) => {
      if (was !== 'running' || now === 'running' || !follow.value) return
      // On a timer rather than on nextTick: the events that end a run land in
      // the same batch as the status, and the table is still growing when the
      // tick fires.
      //
      // Scrolled by hand rather than through `scrollIntoView`, and without
      // `behavior: 'smooth'` — neither does anything here. The offset comes
      // from the two rectangles, so it does not depend on which element is the
      // offset parent.
      setTimeout(() => {
        const el = resultsEl.value
        const col = el && el.closest('.main-col')
        if (col) col.scrollTop += el.getBoundingClientRect().top
                                 - col.getBoundingClientRect().top
      }, 400)
    })
    let movedAt = 0

    watch(runName, (name) => {
      close()
      // The run page's two marks belong to the run page, so leaving it ends
      // them. This watcher also fires on the way in, which is the one moment
      // the pair must survive.
      if (!name && tour.value === 'run') endTour()
      if (!name) return
      resetRun(name)
      // Following starts on again for a new run. Any choice the reader makes
      // switches it off, but that choice was about the run they were reading,
      // not about every run they open afterwards.
      follow.value = true
      movedAt = 0
      openNode.value = openScenario.value = openUnit.value = null
      showAllFeed.value = false
      // The stream waits for the step table (see `booted`): its first frames
      // can carry a re-entry, which is folded against that table.
      booted.then(() => { if (runName.value === name) open(name) })
      refreshTree(name).catch(failed('the run tree did not load'))
      loadReview(name).catch(failed('the readings did not load'))
      loadScores(name).catch(failed('the scores did not load'))
      // What the corpus holds for this protocol. Absent for a run with no
      // ground truth, which is not an error: the reference side is not offered.
      api.referenceTree(name).then(r => {
        if (state.current === name) state.reference = r.files || []
      })
      reproIndex.value = EMPTY_REPRO
      reproOpen.value = reproFiles.value = null
      reproErr.value = ''
      reproOpenedFor = ''
      reproSelecting.value = false
      reproPicked.value = new Set()
      reproNote.value = ''
      loadRepro(name)
    }, { immediate: true })

    // The file list is a snapshot and a running run keeps writing. The evidence
    // links resolve through it, so it is re-read whenever an event says
    // something was written. Prompts carry their path on the event itself.
    const WROTE = ['solve_finished', 'check_report', 'node_finished',
                   'scenario_finished']
    let treeSoon = null          // the pending refresh, null when none is
    let treeWanted = 0           // when the pending one was first asked for
    watch(() => state.lastSeq, (seq, prev) => {
      // Everything that arrived since the last look, not just the newest: the
      // stream folds in batches, so a step finishing and the run failing arrive
      // in the same tick and testing the last event alone misses one of them.
      const from = prev === undefined || seq < prev ? -1 : prev   // < : a different run
      if (!state.feed.some(e => e.seq > from && WROTE.includes(e.t))) return
      // Debounced, because a stage finishing emits several at once, but with a
      // ceiling on the wait: a busy run pushes one out every second or two, and
      // a plain debounce is starved by exactly that.
      const now = performance.now()
      if (!treeSoon) treeWanted = now
      clearTimeout(treeSoon)
      const wait = Math.min(1500, Math.max(0, treeWanted + 6000 - now))
      treeSoon = setTimeout(() => {
        treeSoon = null
        if (state.current) refreshTree(state.current)
      }, wait)
    })

    // ── the cell inspector ───────────────────────────────────────────────
    // A verdict is the run's product and a disagreement is the interesting
    // case, so a cell has to answer "why". The trace, the model, the prompt and
    // the reading filed on it live in four directories; this assembles them
    // where the reader is already looking.
    const openCell = ref(null)          // {goal, label}
    const cellSide = ref(null)          // {path, text, side} in the compare pane

    /** The column a scenario is drawn as. The table identifies a scenario by
     *  position (S1, S2) because its real name is an address, so anything
     *  naming a scenario elsewhere has to say the position too. */
    const colOf = (label) => {
      const i = matrix().scenarios.findIndex(w => w.label === label)
      return i < 0 ? '' : `S${i + 1}`
    }

    const inspect = computed(() =>
      openCell.value ? cellDetail(openCell.value.goal, openCell.value.label) : null)

    /** Where the open cell's reproduction stands, for the inspector's line. */
    const inspectRepro = computed(() => {
      const d = inspect.value
      if (!d || d.verdict !== 'false') return null
      const rp = reproLook(d.goal, d.label)
      if (!rp) return null
      const row = reproRows.value[reproKey(d.label, d.goal)] || {}
      return { ...rp, expected: row.expected || '', steps: row.steps || 0,
               limit: (reproIndex.value.step || {}).limit ?? null,
               key: reproKey(d.label, d.goal) }
    })

    function openInspector (goal, label) {
      openCell.value = { goal, label }
      cellSide.value = stage.value = null
      texts.value = {}
      // Open on the step the diagnosis blames, or on inject, where a goal's own
      // machinery is written and so where most of them land.
      loadLineage(goal, label).then(() => {
        const list = stages.value
        const first = list.find(st => st.blamed) || list[list.length - 1]
        if (first) openStage(first)
      })
      nextTick(() => {
        const el = document.querySelector('.inspector')
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      })
    }
    function closeInspector () {
      openCell.value = cellSide.value = stage.value = null
      texts.value = {}
    }

    /** The corpus's own model of this protocol — `main.pv`, and its variants.
     *  Picked by name rather than by sort order: a corpus that also ships
     *  `main-compromise-A.pv` sorts that one ahead. The variants stay
     *  pickable. */
    const refChoices = computed(() =>
      state.reference.filter(f => f.endsWith('.pv')).sort())
    const referencePv = computed(() =>
      refChoices.value.find(f => baseName(f) === 'main.pv')
      || refChoices.value.find(f => f.includes('proverif'))
      || refChoices.value[0] || null)

    // Which corpus file the right pane shows. Null means "whatever main.pv is".
    const refPick = ref(null)
    const refShown = computed(() => refPick.value || referencePv.value)
    // Keyed by run as well as by path: the corpus is per protocol, so a cache
    // keyed by file alone serves the previous run's model after a switch.
    const refTexts = ref({})
    const refKey = (f) => `${state.current}::${f}`
    async function loadRef (path) {
      if (!path || !state.current) return
      const k = refKey(path)
      if (refTexts.value[k] != null) return
      const r = await api.referenceFile(state.current, path)
      refTexts.value = { ...refTexts.value, [k]: r.text }
    }
    watch([refShown, () => state.current], ([f]) => loadRef(f), { immediate: true })
    // A pick belongs to the corpus it was made in; the next run's list drops it.
    watch(refChoices, (list) => {
      if (refPick.value && !list.includes(refPick.value)) refPick.value = null
    })
    const referenceAttacks = computed(() =>
      state.reference.filter(f => f.startsWith('attacks/')))

    /* Which documented attack, if any, a cell's false is about.
     *
     *  `attacks/attacks.json` names, per (property, scenario), the attack the
     *  literature records for that cell. Not a statement about the
     *  counter-example this run found, which is why the badge reads "under
     *  correct modelling". Keyed by the scenario's name, so it matches only for
     *  runs given the corpus's claims; a run that named its own scenarios marks
     *  no cell. */
    const attackIndex = ref({})
    // A separator no goal id or label carries, written as an escape: a raw
    // NUL in the source is what an editor strips first (store.js writes it
    // the same way).
    const attackKey = (goal, label) => `${goal}\u0000${label}`
    watch([() => state.current, () => state.reference], async ([name, files]) => {
      attackIndex.value = {}
      if (!name || !(files || []).includes('attacks/attacks.json')) return
      const r = await api.referenceFile(name, 'attacks/attacks.json')
      // A corpus file the reader can edit: a malformed one leaves the console
      // whole and unmarked rather than taking the page down.
      let doc = null
      try { doc = JSON.parse(r.text) } catch (e) {
        console.warn('attacks.json is not valid JSON', e); return
      }
      const idx = {}
      for (const a of doc.attacks || [])
        for (const c of a.refutes || []) idx[attackKey(c.property, c.scenario)] = a
      // Only once the whole file parsed, and only if the run has not moved on
      // while the fetch was in flight.
      if (state.current === name) attackIndex.value = idx
    }, { immediate: true })

    const attackOn = (goal, label) => attackIndex.value[attackKey(goal, label)] || null

    // ── the two model panes ──────────────────────────────────────────────
    // Two independent scrolls of the whole file, never an aligned diff: a
    // standards-sized protocol drifts far enough that a row-by-row view falls
    // apart. What each construction step did is carried as marks on the text,
    // which survives however far the file has moved on.
    const stage = ref(null)             // {step, before, after}
    const paneEls = ref({})

    /** Every model on this cell's lineage, read once when the cell opens: the
     *  marks are computed across the whole chain rather than per tab, and four
     *  small reads up front make every tab switch instant. */
    const texts = ref({})

    async function loadLineage (goal, label) {
      texts.value = {}
      const ln = lineage(goal, label)
      const want = [...new Set([ln.flow, ln.world, ln.root, ln.scen, ln.model]
        .filter(Boolean))]
      const got = await Promise.all(want.map(f => api.file(state.current, f)))
      const map = {}
      want.forEach((f, i) => { map[f] = got[i].text })
      texts.value = map
    }

    /** What this scenario's apply rewrote against the model it was applied to.
     *  Carried into every later pane as secondary marks, so the lines that make
     *  this scenario itself stay findable in inject's output. */
    const applied = computed(() => {
      const d = inspect.value
      if (!d) return { added: new Set(), gone: new Set() }
      const ln = lineage(d.goal, d.label)
      const a = texts.value[ln.root], b = texts.value[ln.scen]
      if (!a || !b) return { added: new Set(), gone: new Set() }
      return { added: introduced(a, b), gone: removed(a, b) }
    })

    const marks = computed(() => quoted(inspect.value && inspect.value.finding))

    /** The left pane: this step's own product, with the change that made it.
     *
     *  One column, not two: the step's before and after are the same file one
     *  step apart, so they align and a `+`/`-` column says what the step did.
     *  Two layers of mark — `+`/`-` is this step, and lines carried in from
     *  apply keep a quieter shade. */
    const diffLines = computed(() => {
      const st = stage.value
      if (!st) return null
      const a = texts.value[st.before], b = texts.value[st.after]
      if (a == null || b == null) return null
      const ap = applied.value, q = marks.value
      return lineDiff(a, b).map((l, i) => {
        const k = l.text.trim()
        const carried = l.kind === 'ctx' && k !== '' && ap.added.has(k)
        return {
          key: i,
          n: l.n,
          html: highlight(l.text),
          sign: l.kind === 'add' ? '+' : l.kind === 'del' ? '-' : '',
          tone: l.kind === 'add' ? 'add' : l.kind === 'del' ? 'del'
              : carried ? 'ap-add' : '',
          quoted: hasQuote(l.text, q),
        }
      })
    })

    /** The right pane: the corpus's model, whole and unmarked apart from what a
     *  filed reading quotes. Nothing is diffed against it — it is written to
     *  another convention and cut at another granularity. */
    const refLines = computed(() => {
      const text = refShown.value && refTexts.value[refKey(refShown.value)]
      if (text == null) return null
      const q = marks.value
      return text.split('\n').map((raw, i) => ({
        key: i, n: i + 1, html: highlight(raw), sign: '', tone: '',
        quoted: hasQuote(raw, q),
      }))
    })

    function openStage (st) {
      stage.value = st
      cellSide.value = null
      // Land on the part of the file the tab is about, scrolled to rather than
      // filtered to. Measured by rectangle rather than offsetTop: the lines
      // have no positioned ancestor, so offsetTop is relative to the page and
      // lands nowhere near the pane's own scroll.
      nextTick(() => {
        // Only the left pane: the right one is the corpus's model, which this
        // step did not touch.
        const box = paneEls.value.left
        if (!box) return
        // The step's own change first, then anything else marked, so a step
        // that changed nothing still lands somewhere meaningful.
        const first = box.querySelector('.ln.add, .ln.del')
                   || box.querySelector('.ln.ap-add, .ln.ap-del')
        if (!first) { box.scrollTop = 0; return }
        box.scrollTop += first.getBoundingClientRect().top
          - box.getBoundingClientRect().top - box.clientHeight / 3
      })
    }

    /** The steps this cell's model passed through, with the one the finding
     *  blames marked — a diagnosis naming `responsible_step` is otherwise left
     *  for the reader to join up. */
    const stages = computed(() => {
      const d = inspect.value
      if (!d) return []
      const blamed = d.finding && d.finding.responsible_step
      return lineage(d.goal, d.label).stages.map(st => ({
        ...st, blamed: st.step === blamed }))
    })

    async function showEvidence (path) {
      cellSide.value = { path, text: '…', side: 'ours' }
      const r = await api.file(state.current, path)
      cellSide.value = { path, text: r.text, side: 'ours' }
    }
    async function showReference (path) {
      cellSide.value = { path, text: '…', side: 'corpus' }
      const r = await api.referenceFile(state.current, path)
      cellSide.value = { path, text: r.text, side: 'corpus' }
    }

    /** Hand this cell to the expert, with the files on screen attached.
     *
     *  The attachment is per message and visible as chips, never a consequence
     *  of this panel happening to be open. Two questions, not one: a cell
     *  called false has a counter-example to read and one called true has none,
     *  and asked as the same question a model invents the trace. */
    function askAboutCell () {
      const d = inspect.value
      if (!d) return
      const overclaim = d.verdict === 'false'
      // `expected` is null on a run with no corpus; the sentence naming it
      // is then left out rather than reading "the corpus expects null".
      draft.value = overclaim
        ? t.value.askWhyFalse(d.goal, colOf(d.label), d.expected ?? null)
        : t.value.askWhyTrue(d.goal, colOf(d.label), d.expected ?? null)
      attach.value = {
        goal: d.goal, scenario: d.label,
        stage: (stage.value && stage.value.step) || 'inject',
        paths: [...new Set([
          // The counter-example and the model it came out of, always: they are
          // what "is this a real attack" is answered from, whichever stage the
          // reader happens to have open.
          ...d.evidence.filter(([k]) => k === 'trace' || k === 'model')
            .map(([, p]) => p),
          stage.value && stage.value.before, stage.value && stage.value.after,
        ].filter(Boolean))],
      }
      nextTick(() => {
        const box = document.querySelector('.composer textarea')
        if (box) box.focus()
      })
    }

    /** What is riding with the next message, or null. Cleared when it is sent,
     *  since by then the files are in the conversation.
     *
     *  A cell fills it whole (askAboutCell) and names the goal and scenario;
     *  a reader reading a step fills it a file at a time, and then the files
     *  are the whole of what it says. */
    const attach = ref(null)
    const dropAttached = (path) => {
      if (!attach.value) return
      attach.value.paths = attach.value.paths.filter(p => p !== path)
      if (!attach.value.paths.length) attach.value = null
    }

    /** How many files one question may carry — the backend's number rather
     *  than a copy, since it refuses anything over the ceiling. */
    const attachCap = computed(() => state.vocab.max_attached || 0)
    const attachedPaths = computed(() => (attach.value && attach.value.paths) || [])
    const isAttached = (path) => !!path && attachedPaths.value.includes(path)
    const attachFull = computed(() => attachedPaths.value.length >= attachCap.value)

    /** Put one of this run's files on the next question, or take it off again.
     *  Not about what the expert can reach — it has tools for that — but about
     *  what the reader has already decided is relevant. Toggling, so a
     *  mis-click is corrected by clicking the same thing again. */
    function toggleAttached (path) {
      if (!path) return
      if (isAttached(path)) return dropAttached(path)
      if (attachFull.value) return
      if (!attach.value) attach.value = { goal: '', scenario: '', stage: '', paths: [] }
      attach.value.paths = [...attach.value.paths, path]
    }

    // ── deleting a run ───────────────────────────────────────────────────
    // Two clicks in the row rather than a dialog: the run's own name has to
    // stay on screen while the question is asked.
    const armed = ref('')          // the run whose delete is asking
    const deleting = ref('')
    const deleteErr = ref('')

    function arm (name) {
      armed.value = armed.value === name ? '' : name
      deleteErr.value = ''
    }

    async function removeRun (name) {
      if (deleting.value) return
      deleting.value = name
      deleteErr.value = ''
      try {
        await api.remove(name)
        state.runs = await api.runs()
      } catch (e) { deleteErr.value = `${name}: ${e.message || e}` }
      deleting.value = ''
      armed.value = ''
    }

    /** Mark this run reviewed, or open it again. Not the run's status: what the
     *  pipeline concluded and what a person concluded are two facts. */
    async function setReview (next) {
      try {
        state.review = await api.setReview(state.current, next)
      } catch (e) {
        failed('the review state was not saved')(e)
      }
    }

    // ── re-entering ──────────────────────────────────────────────────────
    // Offered whatever state the run is in — finished, interrupted, broken, or
    // still working. Re-entering a live run stops it first
    // (web/server.py::rerun); the run unwinds rather than being killed and
    // everything already on disk stays, so a mistaken click costs the tokens of
    // the step in flight.

    /** How far this run got, as a position in the node table. A step past it
     *  has no upstream and the engine refuses that re-entry by name. A failure
     *  at a step not in this build's table is read as "the end", so the run
     *  still has a way forward. */
    const reachedAt = computed(() => {
      if (state.failure && NODES.indexOf(state.failure.node) < 0) {
        return NODES.length - 1
      }
      let last = -1
      NODES.forEach((n, i) => { if (state.nodes[n]) last = i })
      return last
    })

    /** Steps the run can be re-entered at: the furthest it reached and anything
     *  before it, minus the ones holding an artifact this run was handed rather
     *  than produced — re-entering one of those writes the same file back and
     *  pays for everything after it again. The server refuses those too. */
    const pinnedStep = (n) => state.pinned.includes(n)
    const retryable = (n) =>
      canRetry.value && !pinnedStep(n)
      && (NODES.indexOf(n) <= reachedAt.value || nextStep(n))

    /** The one step past the furthest reached, once everything it waits on has
     *  finished: a run recorded before that step existed (the attack step on
     *  an older run) can still be carried on to it. A dependency that ended
     *  check_failed counts only for a step that runs after one. */
    const nextStep = (n) => {
      if (state.status === 'running' || NODES.indexOf(n) !== reachedAt.value + 1) return false
      const v = state.vocab || {}
      const after = (v.after_check_failure || []).includes(n)
      const deps = (v.depends_on || {})[n] || []
      const parents = deps.length ? deps : [NODES[reachedAt.value]]
      return parents.every(p => state.nodes[p] === 'ok'
                                || (after && state.nodes[p] === 'check_failed'))
    }

    /** What pressing it will do, said before it is pressed. The second sentence
     *  only when there is something to stop. */
    // t is a computed: unwrapped in the template, a ref in here.
    const retryTitle = (addr) => t.value.retryTip(addr)
      + (state.status === 'running' ? '\n\n' + t.value.retryStops : '')

    /** The same gate one level down. A step inside a node that ran has a
     *  complete upstream by construction, so all that is left is not asking
     *  twice while a request is already on its way. */
    const canRetry = computed(() => !retrying.value)

    /** A step's address, for every level the page draws. This is what goes on
     *  the wire; the directory numbers stay on, because which step a path names
     *  is the resolver's business. */
    const stepAddr = (ident, unitKey) =>
      ident === ROOT_IDENT ? (unitKey ? `build_root/${unitKey}` : 'build_root')
      : ident === WORLD_IDENT ? (unitKey ? `build_world/${unitKey}` : 'build_world')
      // A plain step runs one session and is its own unit, so it has no address
      // below itself; the cell in the strip is the whole of it.
      : NODES.includes(ident) ? ident
      : (unitKey ? `scenarios/${ident}/${unitKey}` : `scenarios/${ident}`)

    /** Whether the Expert column is open. Folded by default: the run's own
     *  panels want the width, and asking is the rarer errand. Kept per
     *  reader in the browser, which may refuse to store it. */
    const expertOpen = ref(false)
    try { expertOpen.value = localStorage.getItem('orrery.expert') === 'open' } catch {}
    function setExpertOpen (on) {
      expertOpen.value = on
      try { localStorage.setItem('orrery.expert', on ? 'open' : 'folded') } catch {}
    }

    const retrying = ref('')
    const retryErr = ref('')
    let retrySeq = 0             // which request the fallback timer belongs to

    async function retryStep (path) {
      if (retrying.value) return
      const mine = ++retrySeq
      retrying.value = path
      retryErr.value = ''
      try {
        // Nothing is done to the view here: the engine's run_started carries
        // the re-entry point and the page folds the supersession off that
        // (store.js::reenter), so a second tab arrives at the same page.
        await api.rerun(state.current, path)
      } catch (e) {
        retryErr.value = e.name === 'TimeoutError'
          ? t.value.retryNoAnswer : String(e.message || e)
        retrying.value = ''
      }
      // Whatever happens, the controls come back: one pending request hides
      // every retry on the page, so a request that never resolves would take
      // the whole offer with it.
      setTimeout(() => {
        // Only this request's timer: the first request's, firing after a
        // second request for the same address had begun, would clear that one
        // and blame the server for an answer still on its way.
        if (retrySeq === mine && retrying.value === path) {
          retrying.value = ''
          if (!retryErr.value) retryErr.value = t.value.retryNoAnswer
        }
      }, 50000)
    }

    // The request stops pending when the ledger says a run started, not when
    // the status changes: a re-entry into the pure-code steps runs to
    // completion inside one batch of frames and the status never moves.
    watch(() => state.runStarts, () => { retrying.value = '' })

    /** Which of the three readings a finding carries, as a class. They are not
     *  the same kind of failure: a modelling gap is ours to fix, a genuine
     *  attack may mean the corpus is wrong, and undecided is neither. */
    const readingOf = (goal, label) => {
      const f = (cellDetail(goal, label) || {}).finding
      return f ? f.reading : null
    }

    /** Panels a dead run will never fill. "No verdicts yet" is a promise that
     *  will not be kept on a run that stopped at step four. Folded, not
     *  removed — the structure stays one click away. */
    const diedEarly = computed(() =>
      state.status === 'failed' && !matrix().rows.length)

    // The timeline is a component, so it cannot see these; bound here rather
    // than passed as props at each of its three placements.
    showFile = show
    pinFile = toggleAttached
    isPinned = isAttached

    const draft = ref('')

    /** The expert's answer while it is still arriving, or null. Null rather
     *  than the empty buffer, so the panel falls back to "thinking… round N"
     *  instead of drawing an empty bubble. */
    const liveExpert = computed(() => {
      const b = state.drafts.expert
      return b && (b.thinking || b.text) ? b : null
    })

    async function ask () {
      const text = draft.value.trim()
      if (!text || state.asking) return
      // The message is not echoed here: the server files it as ExpertAsked
      // before answering, so it arrives on the stream and a second tab watching
      // this run sees the question too.
      state.asking = true
      draft.value = ''
      // Sent with the message, then dropped: the files are in the conversation
      // now, so a follow-up needs no second copy.
      const cell = attach.value
      attach.value = null
      try {
        await api.ask(state.current, text, cell)
      } catch (e) {
        // Nothing was filed, so nothing will arrive: say so and give the words
        // back rather than locking the composer.
        state.asking = false
        draft.value = text
        state.chat.push({ who: 'it', text: t.value.askFailed(String(e.message || e)) })
      }
    }

    // Stopping is the only thing that ends a turn the model will not end
    // itself: the expert's rounds and readings are unbounded on purpose.
    async function stopAsk () { await api.stopAsk(state.current) }

    async function decide (execute) {
      await api.decide(state.current, execute)
      state.pending = null
    }

    watch(() => state.pending, async (p) => {
      if (!p || p.plan) return
      let plan = null
      try {
        plan = (await api.plan(state.current)).plan
      } catch (e) {
        failed('the plan did not load')(e)
        return
      }
      // No plan waiting on the server: the event that put the card up was
      // replayed for a plan long since decided, so the card comes down.
      if (plan) p.plan = plan
      else state.pending = null
    })

    const feedRows = computed(() => filter.value
      ? state.feed.filter(e => e.scenario === filter.value)
      : state.feed)
    /** Lines this run filed that the window is not showing. */
    const feedHidden = computed(() =>
      showAllFeed.value ? 0 : Math.max(0, feedRows.value.length - FEED_WINDOW))
    const feed = computed(() =>
      // Oldest first, newest at the foot, the direction everything else on the
      // page grows in.
      showAllFeed.value ? feedRows.value : feedRows.value.slice(-FEED_WINDOW))

    function showEarlierFeed () {
      const el = feedEl.value
      const from = el ? el.scrollHeight - el.scrollTop : 0
      showAllFeed.value = true
      // Hold the reader where they were reading: the lines arrive above them,
      // so keeping scrollTop would move the page under their eyes.
      nextTick(() => {
        if (el) el.scrollTop = el.scrollHeight - from
      })
    }

    const scenarioNames = computed(() => scenarioLabels())
    const steps = computed(() => stepRows())
    /** What the open pipeline cell holds, or null when that step never ran.
     *  The strip lists the whole table; this lists only what happened. */
    const openRow = computed(() =>
      steps.value.find(r => r.node === openNode.value) || null)

    /** The word the strip draws a step with, declared by the node itself and
     *  carried on /api/meta/vocabulary. Falls back to the full name only for
     *  the moment before that request lands — a step with no short name is a
     *  missing declaration, and tests/unit/nodes/test_short_names.py refuses
     *  one. */
    const stepLabel = (n) => (state.vocab.step_short || {})[n] || n

    /** How many ways a step fanned out, asked of the scenario buckets through
     *  ownerOf() rather than hard-coded to the one step that does it. Zero or
     *  one means it did not fan, and the strip draws it plainly. */
    const fanOut = (n) => scenarioLabels().filter(l => ownerOf(l) === n).length

    /* The run list, grouped by protocol. Collapsed unless something in the
       group is running. */
    const groups = computed(() => runGroups())

    /* ── the run list, as standards that open ──────────────────────────────
     *  The same fold as the launch panel, over the runs instead of the corpus,
     *  but newest-first: this list answers "how did what I just ran turn out".
     *
     *  Open by default while something inside is still moving. A map and not a
     *  Set, so a standard can be closed on purpose — with a Set the running
     *  clause is an unconditional or, and a standard clicked shut springs open
     *  again on the same frame. Same shape as `openGroups` one level down. */
    const openStandards = ref({})
    const standardOpen = (r) => openStandards.value[r.head] !== undefined
      ? openStandards.value[r.head] : r.children.some(c => c.item.running)
    const toggleStandard = (r) => {
      openStandards.value = { ...openStandards.value, [r.head]: !standardOpen(r) }
    }
    const runRows = computed(() => runCorpusRows())
    const standardRuns = (r) => r.children.reduce((n, c) => n + c.item.runs.length, 0)
    const standardUnread = (r) => r.children.reduce((n, c) => n + c.item.unread, 0)
    const standardLatest = (r) => r.children.reduce(
      (a, c) => (a > c.item.latest.started ? a : c.item.latest.started), '')
    const openGroups = ref({})
    const groupOpen = (g) => openGroups.value[g.protocol] !== undefined
      ? openGroups.value[g.protocol] : g.running
    const toggleGroup = (g) => { openGroups.value[g.protocol] = !groupOpen(g) }

    const pipe = computed(() => pipelineLayout())

    /* A step's hover text: what it is, what it waits on, and why the run
       stopped if it stopped here. The waits-on line is the only place the graph
       says itself in words; a grid position cannot state which of two stacked
       cells feeds which. */
    const stepTitle = (n) => {
      const task = state.vocab.steps && state.vocab.steps[n]
      const on = pipe.value.parentsOf(n)
      return n + (task ? ' \u2014 ' + task : '')
        + (on.length ? '\n' + t.value.waitsOn(on.join(', ')) : '')
        // Said on the step itself: a greyed-out box with no retry link
        // otherwise reads as broken rather than as pinned.
        + (pinnedStep(n) ? '\n\n' + t.value.pinnedTip : '')
        + (state.failure && state.failure.node === n
           ? '\n\n' + state.failure.reason : '')
    }
    const units = computed(() => {
      const sc = state.scenarios[openScenario.value]
      return sc ? Object.keys(sc.units).sort() : []
    })
    const unitData = computed(() => {
      const sc = state.scenarios[openScenario.value]
      return sc && openUnit.value ? sc.units[openUnit.value] : null
    })

    /** Has the open step anything to put in the second column? The scenario
     *  stage has, through whichever scenario is chosen, and so has a step that
     *  ran one session; a step that opened none has not. */
    const hasSessions = computed(() => !!openRow.value
      && (openRow.value.kind === 'scenarios' || units.value.length > 0))

    // The step this panel is about, whichever identity it was opened under: the
    // two shared-base steps run their sessions under `root` / `world`, and the
    // ledger files their own lines under the node name. A step that opened no
    // session answers with the lines it filed and the files it left, in place
    // of a timeline.
    const openStep = computed(() =>
      openScenario.value === ROOT_IDENT ? 'build_root'
      : openScenario.value === WORLD_IDENT ? 'build_world'
      : NODES.includes(openScenario.value) ? openScenario.value : null)
    const stepLog = computed(() =>
      openStep.value ? (state.nodeLines[openStep.value] || []) : [])
    const stepFiles = computed(() =>
      openStep.value ? stepArtifacts(openStep.value) : [])

    /** The open scenario's own directory, or "" when what is open is a step
     *  rather than a scenario. What the two nested timelines hang off. */
    const openScenarioDir = computed(() =>
      openScenario.value && !openStep.value
        ? (scenarioDir(openScenario.value) || '') : '')

    /** What a lane says once it is over: how it did against the corpus, not how
     *  many goals held — the matrix one panel up already answers that per goal
     *  and per scenario. With no ground truth, how many of this scenario's
     *  goals hold is the only answer there is. */
    const laneAgree = (l) => laneAgreement(l)

    /* What one inject row answered. The lane above it counts goals and the rows
       under it are families, so without this the two numbers never meet. */
    const uGoals = (l, u) => unitGoals(l, u)
    /* Verdicts travel as the three-valued strings the pipeline uses
       ("true" / "false" / "unknown"), never as booleans. */
    const goalMark = (g) => ({ true: '\u2713', false: '\u2717' })[g.verdict] || '?'


    /** The colour on that number, and the whole of what the lane reports: whole
     *  is green, short of whole is red. Nothing while the lane is still
     *  working — `apply 2/5` is a position, not a result. */
    const laneStatClass = (l) => {
      const a = laneAgree(l)
      if (a) return a.matched === a.of ? 'ok' : 'bad'
      const p = lanePhase(l)
      if (p.kind !== 'verdicts') return ''
      return p.a === p.b ? 'ok' : 'bad'
    }

    /** The lane's status line in the current language. The store returns the
     *  shape (which stage, how many of how many); the words are never baked
     *  into state. */
    function laneText (l) {
      const a = laneAgree(l)
      if (a) return t.value.laneMatched(a.matched, a.of)
      const p = lanePhase(l)
      if (p.kind === 'verdicts') return t.value.laneVerdicts(p.a, p.b)
      if (p.kind === 'inject') return t.value.laneInject(p.a, p.b)
      if (p.kind === 'apply') return t.value.laneApply(p.a, p.b)
      if (p.kind === 'queued') return t.value.laneQueued
      return t.value.laneWaiting
    }

    // ── following the run ────────────────────────────────────────────────
    // With nothing chosen, the detail panel shows whatever is speaking, so a
    // reader who has just opened a live run sees it working. Choosing anything
    // stops the following.
    // How long a unit keeps the panel once it has it: sessions run several at a
    // time, and switching to every newest event would strobe between them.
    const HOLD_MS = 4000

    watch(() => state.lastAt, (at) => {
      if (!follow.value || !at || state.status !== 'running') return
      if (openScenario.value === at.ident && openUnit.value === at.unit) return
      const now = Date.now()
      if (openScenario.value && now - movedAt < HOLD_MS) return
      movedAt = now
      // The cell as well as its inside: they are three pieces of one address,
      // so the strip and the panel under it must point at the same step.
      openNode.value = ownerOf(at.ident)
      openScenario.value = at.ident
      openUnit.value = at.unit
    })

    /** Open one identity and its first session, without toggling. The two
     *  callers below differ only in what they do when it is already open. */
    function openIdent (ident) {
      openScenario.value = ident
      // A step that ran with nothing to apply has no bucket at all — its row is
      // listed off the node table, not off state.scenarios — so opening it must
      // show an empty unit list rather than throw.
      const sc = state.scenarios[ident]
      openUnit.value = (sc ? Object.keys(sc.units).sort()[0] : null) || null
    }

    /** A pipeline cell. What opens under it is the step's own inside: the
     *  scenario stage lists its scenarios, the shared-base steps their apply
     *  points, and a one-session step opens straight into it. */
    function pickNode (n) {
      follow.value = false
      if (openNode.value === n) {
        openNode.value = openScenario.value = openUnit.value = null
        return
      }
      openNode.value = n
      const r = steps.value.find(x => x.node === n)
      if (!r || r.kind === 'scenarios') {
        // The fan-out has a level of its own; nothing is open until one of its
        // scenarios is chosen, which is not the page's to decide.
        openScenario.value = openUnit.value = null
        return
      }
      openIdent(r.ident)
    }

    function pickScenario (label) {
      follow.value = false          // a choice of their own outranks the run
      if (openScenario.value === label) { openScenario.value = openUnit.value = null; return }
      openIdent(label)
    }

    function pickUnit (u) { follow.value = false; openUnit.value = u }

    /** The unit key a number-free address names, looked up rather than built:
     *  a directory's number is when it ran, so `inject/Secrecy` cannot be
     *  turned into `inject/01_Secrecy` by any rule the page knows. */
    const unitKeyFor = (ident, tail) => {
      const sc = state.scenarios[ident]
      if (!sc) return null
      const bare = (k) => k.split('/').map(x => x.replace(/^\d+_/, '')).join('/')
      return Object.keys(sc.units).find(k => bare(k) === tail) || null
    }

    /** Open the page at a step path — the address the engine signs a failure
     *  with, and the one a retry is aimed by. Read left to right: node,
     *  identity, session. */
    function openPath (path) {
      const p = String(path || '').split('/').filter(Boolean)
      if (!p.length || !NODES.includes(p[0])) return
      openNode.value = p[0]
      const r = steps.value.find(x => x.node === p[0])
      if (p.length === 1) {
        if (r && r.kind !== 'scenarios') openIdent(r.ident)
        else openScenario.value = openUnit.value = null
        return
      }
      const ident = p[0] === 'scenarios' ? p[1]
        : p[0] === 'build_root' ? ROOT_IDENT
        : p[0] === 'build_world' ? WORLD_IDENT : null
      if (ident === null) return
      openIdent(ident)
      const tail = (p[0] === 'scenarios' ? p.slice(2) : p.slice(1)).join('/')
      if (tail) openUnit.value = unitKeyFor(ident, tail) || openUnit.value
    }

    // A run that stopped opens at the step that stopped it: the failure signs
    // itself with a step path, so the retry button lands within reach of the
    // reason. Never moves a reader who has already chosen a cell.
    watch(() => (state.failure
                 && (state.failure.where || state.failure.node)) || '',
          (w) => { if (w && !openNode.value) openPath(w) })

    async function show (path) {
      viewing.value = { path, text: '…' }
      viewing.value = await api.file(state.current, path)
    }

    /** Where a unit's evidence really is: the open identity's step directory
     *  plus the unit's own path — see store.evidence. */
    const at = (unitKey, filename) =>
      evidence(openScenario.value, unitKey, filename)

    async function openEvidence (unitKey, filename) {
      const path = at(unitKey, filename)
      if (path) return show(path)
      viewing.value = { path: filename, text: t.value.noFile(filename) }
    }

    // ── the session timeline ──────────────────────────────────────────────
    // Two of its lines have a full text behind them, and neither is on the
    // ledger: a prompt is a file the session wrote, a reply a line in its
    // transcript. Both are fetched when the reader asks — a run has hundreds.
    /** The first character of a timeline row: who did it. ◎ Orrery asked,
     *  ✳ the model answered, ◈ the model calling a tool, ▣ Orrery acted on it,
     *  ✓/✗ Orrery's verdict, ● ProVerif. */
    const GLYPH = { prompt: '◎', reply: '✳', tool: '◈', framework: '▣',
                    check: '·', checks: '✓', solve: '●' }
    const glyphOf = (it) =>
      it.kind === 'checks' ? (it.passed ? '✓' : '✗')
      : it.kind === 'check'
        ? (it.running ? '⟳' : it.passed ? '✓' : '✗')
        : (GLYPH[it.kind] || '·')
    /** Green when it went well, amber when a check said no, nothing when there
     *  is no such thing to say. A check refusing a submission is the repair
     *  loop working, not a crash, so it is amber — the same reason the strip
     *  paints `check_failed` amber and draws it `≠`. A tool answering `failed`
     *  keeps red: that is the machinery, not a verdict. Colour by actor stays
     *  in the stylesheet. */
    const glyphClass = (it) =>
      it.kind === 'checks' ? (it.passed ? 'ok' : 'warn')
      : it.kind === 'check'
        ? (it.running ? '' : it.passed ? (it.note ? 'warn' : 'ok') : 'warn')
      : it.kind === 'tool' ? (it.ok === false ? 'bad' : it.ok === true ? 'ok' : '')
      : ''

    /** A check finding is written for the model to repair from and opens with
     *  the cell it belongs to: `[Secrecy.basic] edit 2 (before '0.'): …`. Split
     *  so the tag can be a chip and the sentence can start at the sentence. */
    const findingCell = (f) => (String(f).match(/^\[([^\]]+)\]\s*/) || [])[1] || ''
    const findingBody = (f) => String(f).replace(/^\[[^\]]+\]\s*/, '')
    const opened = ref({})

    const streamed = (it) => (it.live.thinking + it.live.text).length || 0
    const baseName = (p) => (p || '').split('/').pop()
    const kb = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)}M`
                    : n >= 1024 ? `${Math.round(n / 1024)}K` : `${n}B`

    /** One key per line of one unit of one run: an index alone would show
     *  this unit's third line under the next unit's third line. */
    const oKey = (i) => `${state.current}/${openScenario.value}/${openUnit.value}/${i}`

    async function toggle (item, i) {
      const k = oKey(i)
      if (opened.value[k] !== undefined) { delete opened.value[k]; return }
      opened.value[k] = '…'
      opened.value[k] = await fullText(item)
    }

    /** The whole text behind one timeline line. */
    async function fullText (item) {
      const ident = openScenario.value, key = openUnit.value
      // The prompt's path came with the event that announced it, so there is
      // nothing to look up: during a run the file list this page holds is older
      // than the file.
      if (item.kind === 'prompt') return (await api.file(state.current, item.path)).text
      const path = evidence(ident, key, 'transcript.jsonl')
      if (!path) return t.value.noFile('transcript.jsonl')
      const raw = (await api.file(state.current, path)).text
      // One assistant message per round, in order, so the k-th is round k's.
      const says = raw.split('\n').filter(Boolean)
        .map(l => { try { return JSON.parse(l) } catch { return null } })
        .filter(x => x && x.t === 'assistant')
      const a = says[item.no - 1]
      if (!a) return t.value.noFile('transcript.jsonl')
      return [
        a.thinking ? `[${t.value.kThinking}]\n${a.thinking}` : '',
        a.content || '',
        (a.tool_calls || []).map(c => `[${t.value.kTool}] ${c.name}(${c.arguments})`).join('\n'),
      ].filter(Boolean).join('\n\n')
    }

    /** A step's own product, by the directory the tree reports for it — the
     *  numbering belongs to the run, not to this page. Null when the step wrote
     *  no directory, which keeps a link off a step with nothing behind it. */
    const stepPath = (node, ...rest) => {
      const dir = stepDir(node)
      return dir ? [dir, ...rest].join('/') : null
    }

    function openStepFile (node, ...rest) {
      const path = stepPath(node, ...rest)
      if (path) show(path)
    }

    return {
      state, route, runName, matrix, NODES, PHASES, VERDICT, lanePhase,
      ROOT_IDENT, steps, stepLabel, fanOut, pipe, stepTitle,
      groups, groupOpen, toggleGroup,
      runRows, standardOpen, toggleStandard, standardRuns, standardUnread, standardLatest,
      t, lang, setLang,
      line, marked, where, clock, day, tokens,
      openNode, openRow, pickNode, openPath,
      openScenario, openUnit, filter, viewing, feed, feedEl, stick, onFeedScroll,
      feedHidden, showEarlierFeed,
      inspect, openInspector, closeInspector, cellSide, showEvidence,
      showReference, referencePv, referenceAttacks, attackOn, askAboutCell, readingOf, colOf,
      stage, stages, openStage, diffLines, refLines, paneEls,
      refChoices, refShown, refPick,
      reviewFindings,
      armed, deleting, deleteErr, arm, removeRun,
      libRoot, picked, form, scanErr, starting, protoFilter, shownProtocols,
      sourceMode, browsing, browsePath, browseErr, target, openDir, pickTarget,
      toDocumentMode, chosenSubs,
      mainDoc, refDocs, docChoice, toggleRef, targetReady,
      protoVisible, protoGroupOpen, toggleProtoGroup,
      playbackMode, playbackOn, playbackHere, setMode, resultsEl, cfgOpen,
      tour, tourProto, showMark, endTour, shutMark,
      scan, pick, startRun, rows, knobAt, knobLabel, choicesFor, toggleInput,
      setInput, LIB_ROWS, END_POINTS, libRows, setLib, willRun, ranLib,
      saveKnob, cfgErr, saving, backend, ready, withCurrent,
      matrixEl, colw, idw, nameParts, agreeCount,
      dims: dimensions, targetOf, dimTip, dimNameTip, axisTip, goalTip, goalKind,
      GLYPH, glyphOf, glyphClass, findingCell, findingBody,
      opened, toggle, streamed, baseName, kb,
      scenarioNames, units, unitData, hasSessions, pickScenario, pickUnit, follow,
      uGoals, goalMark,
      show, at, openEvidence, openStepFile, stepPath, stepLog, stepFiles, openStep,
      openScenarioDir,
      toggleAttached, isAttached, attachFull, attachCap,
      laneText, laneAgree, laneStatClass,
      draft, ask, stopAsk, decide, attach, dropAttached, setReview, diedEarly,
      liveExpert,
      scenarioPv: () => openStepFile('scenarios', openScenario.value, 'apply/scenario.pv'),
      // The banner's two links both do the one thing there is to do: open the
      // strip at the step that stopped, by the address on the failure itself.
      openFailedStep: () => {
        const f = state.failure
        if (f) openPath(f.where || f.node)
      },
      interrupt: () => api.interrupt(state.current).catch(failed('the interrupt was not sent')),
      approve: () => api.approve(state.current).catch(failed('the release was not sent')),
      serverErr, oKey,
      // The step's current directory, and how much was re-worked inside it.
      // "" for a step that has none, which counts nothing.
      liveDir: (n) => stepDir(n) || '',
      reworksUnder: (d) => (d ? reworksUnder(d) : 0),
      expertOpen, setExpertOpen,
      retryable, pinnedStep, canRetry, stepAddr, retryStep, retryTitle, retrying, retryErr,
      reproIndex, reproErr, reproOpen, reproFiles, reproBy, reproCounts, reproPanel,
      reproOutside, summaryKey, summaryCell, openRepro, reproNoExplain,
      REPRO_GLYPH, reproCellClass, reproCellMark, reproCellTip, cellClick, inspectRepro,
      opensAttack, quoteParts, reproKey,
      reproSelecting, reproPicked, reproSending, reproNote, reproBusy, reproToolbar,
      toggleSelecting, pickCell, pickAllWaiting, askSelected, askOne, stopRepro,
      resummarize,
    }
  },

  template: `
<template v-if="!runName">
  <div class="shell">
  <header class="topbar">
    <span class="brand">{{ t.brand }}</span>
    <span class="dim">{{ t.console }}</span>
    <!-- Which console this is. Playback is the default: the published artifact
         ships with no key, so a reader can watch a run having configured
         nothing. -->
    <span class="modetoggle" :title="t.modeTip">
      <button :class="{on: playbackOn}" @click="setMode(true)">{{ t.recorded }}</button>
      <button :class="{on: !playbackOn}" @click="setMode(false)">{{ t.live }}</button>
    </span>
    <span class="grow"></span>
    <!-- A page of its own, in a new tab: the vocabulary is reference over the
         build, and navigating away would tear down a live run's stream. -->
    <a class="tiny ghost" href="/vocabulary" target="_blank" rel="noopener"
       :title="t.vocabularyTip"
       style="text-decoration:none;padding:5px 14px">{{ t.vocabulary }}</a>
    <!-- Hidden for now: the page is English-only until the Chinese half is
         worth showing again. The dictionary and setLang are still there, so
         bringing it back is dropping this comment's two ends.
    <span class="langtoggle">
      <button :class="{on: lang==='en'}" @click="setLang('en')">EN</button>
      <button :class="{on: lang==='zh'}" @click="setLang('zh')">中</button>
    </span>
    -->
  </header>
  <main class="body">
   <div class="cols leftrail">
    <div class="stack main-col">
    <div class="panel">
    <div class="head"><h2>{{ t.runsTitle }}</h2><span class="sub">{{ t.runsCount(state.runs.length) }}</span>
      <!-- What directory this table is: an empty list means nothing until the
           reader can see which tree was read. With no config file the built-in
           default applies, relative to wherever the server was started. -->
      <span class="grow"></span>
      <span v-if="state.cfg" class="wr">
        <!-- Not painted as a fault when it is absent: a fresh checkout has
             none and the first run creates it. A wrong path is refused the
             moment it is typed. -->
        <span class="mono"
              :title="state.cfg.work_root + (state.cfg.work_root_exists ? '' : ' — ' + t.workRootNew)"
        >{{ state.cfg.work_root }}<span v-if="!state.cfg.work_root_exists"
              class="dim"> · {{ t.workRootNew }}</span></span>
        <!-- The name of the setting that moves these runs, not the name of the
             file it lives in. -->
        <span class="dim sm">{{ t.workRootSetting }}</span>
      </span>
    </div>
    <table class="runs">
      <thead><tr><th>{{ t.colRun }}</th><th>{{ t.colProtocol }}</th><th>{{ t.colStatus }}</th><th>{{ t.colResult }}</th><th>{{ t.colAcc }}</th><th>{{ t.colStarted }}</th><th></th></tr></thead>
      <tbody>
        <template v-for="row in runRows" :key="row.group ? 'h:' + row.head : row.item.protocol">
        <!-- A standard, as a row you open, above the protocols that are its
             mechanisms. Only where it has more than one; a group of one is
             flattened into the protocol row itself. -->
        <tr v-if="row.group" class="grp std" :class="{open: standardOpen(row)}"
            @click="toggleStandard(row)">
          <!-- Same as the launch panel: the whole path, so the standard says
               which body published it. -->
          <td class="mono"><span class="caret">{{ standardOpen(row) ? '▾' : '▸' }}</span>{{
            row.head }}</td>
          <td class="muted">{{ t.mechanismsTag(row.children.length) }} ·
            {{ t.runsInGroup(standardRuns(row)) }}</td>
          <td>
            <span v-if="row.children.some(c => c.item.running)" class="pill run">
              <span class="dot"></span>running</span>
            <span v-if="standardUnread(row)" class="unread" :title="t.unreadTip">{{
              standardUnread(row) }}</span>
          </td>
          <td colspan="2"></td>
          <td class="muted num">{{ day(standardLatest(row)) }}</td>
          <td></td>
        </tr>
        <!-- Inside a standard the row is the mechanism, not the flat
             run-directory name: the standard is the line above it.

             No backticks in here, or anywhere else in this template: the whole
             thing is one template literal, and one in a comment ends it. -->
        <template v-for="g in (row.group
                                 ? (standardOpen(row)
                                      ? row.children.map(c => ({...c.item, leafName: c.leaf}))
                                      : [])
                                 : [row.item])" :key="g.protocol">
        <!-- The protocol, as a row you open, carrying what a collapsed group
             still has to answer: how many runs, whether any is moving or
             unread, and when the newest started. -->
        <tr class="grp" :class="{open: groupOpen(g), instd: row.group}" @click="toggleGroup(g)">
          <td class="mono" :title="g.leafName ? g.protocol : ''"><span class="caret">{{
            groupOpen(g) ? '▾' : '▸' }}</span>{{ g.leafName || g.protocol }}</td>
          <td class="muted">{{ t.runsInGroup(g.runs.length) }}</td>
          <td>
            <span v-if="g.running" class="pill run"><span class="dot"></span>running</span>
            <span v-if="g.unread" class="unread" :title="t.unreadTip">{{ g.unread }}</span>
          </td>
          <td colspan="2"></td>
          <td class="muted num">{{ day(g.latest.started) }}</td>
          <td></td>
        </tr>
        <tr v-for="r in (groupOpen(g) ? g.runs : [])" :key="r.name" class="sub"
            :class="{instd: row.group}">
          <td class="indent"><a :href="'#/run/' + r.name" class="mono">{{ r.name }}</a></td>
          <td class="mono muted">{{ r.protocol }}</td>
          <td>
            <span class="pill" :class="{ok: r.status==='ok', bad: r.status==='failed',
                                        warn: r.status==='check_failed', run: r.status==='running'}">
              <span class="dot"></span>{{ t.runStatus(r.status) }}</span>
            <!-- Which of these nobody has read yet. A sweep leaves dozens, and
                 how each ended says nothing about whether anyone looked. -->
            <span v-if="r.review === 'open' && r.status !== 'running'"
                  class="unread" :title="t.unreadTip">{{ t.unread }}</span>
          </td>
          <td class="mono num">
            <span v-for="(n, v) in r.verdicts" :key="v" class="v" :class="v">
              {{ n }}{{ VERDICT[v] || v }}&nbsp;</span>
            <span v-if="!Object.keys(r.verdicts).length" class="muted">—</span>
          </td>
          <td class="num">{{ r.acc === null ? '—' : (r.acc * 100).toFixed(1) + '%' }}</td>
          <td class="muted num">{{ day(r.started) }}</td>
          <td class="del">
            <!-- Armed in place: the name stays on screen while the question is
                 asked, which a dialog cannot promise. -->
            <template v-if="armed === r.name">
              <button class="tiny danger" :disabled="deleting === r.name"
                      @click="removeRun(r.name)">{{
                deleting === r.name ? t.deleting : t.deleteYes }}</button>
              <a href="#" class="dim sm" @click.prevent="arm('')">{{ t.cancel }}</a>
            </template>
            <a v-else-if="!playbackOn" href="#" class="dim sm" :title="t.deleteTip"
               @click.prevent="arm(r.name)">{{ t.delete }}</a>
          </td>
        </tr>
        </template>
        </template>
        <tr v-if="!state.runs.length"><td colspan="7" class="muted">{{ t.noRuns }}</td></tr>
        <tr v-if="deleteErr"><td colspan="7" class="muted"
            style="color:var(--v-bad)">{{ deleteErr }}</td></tr>
      </tbody>
    </table>
    </div>
    </div>

    <!-- The rail. Both sections are resident and collapsible: launching must
         never hide the runs, and the settings a run is about to spend money
         with belong beside the button that spends it. Playing back, the config
         is read-only and folds so the launch panel takes the room. -->
    <div class="stack side-col rail" :class="{recorded: playbackOn}">
      <details class="panel launch" open>
        <summary><span class="ttl">{{ t.newRun }}</span></summary>

        <!-- Two controls, because they are two questions: a corpus is a tree to
             choose from, your own document is a thing you already have. Live
             only — a recording is not a document. -->
        <div v-if="!playbackOn" class="srcmode" :title="t.srcTip">
          <button :class="{on: sourceMode === 'corpus'}"
                  @click="sourceMode = 'corpus'">{{ t.srcCorpus }}</button>
          <button :class="{on: sourceMode === 'document'}"
                  @click="toDocumentMode()">{{ t.srcDocument }}</button>
        </div>

        <template v-if="sourceMode === 'corpus'">
        <!-- One field, two trees. Playing back, it is the directory the recorded
             runs are in and the server has already found it; live, it is the
             protocol corpus to scan. -->
        <label class="fld">{{ playbackOn ? t.playbackRoot : t.libRoot }}
          <span class="row2">
            <input v-model="libRoot" class="mono"
                   :placeholder="playbackOn ? t.playbackRootHint : t.libRootHint"
                   @keydown.enter="scan()">
            <button class="tiny" @click="scan()">{{ t.scan }}</button>
          </span>
        </label>
        <p v-if="playbackOn" class="dim sm">{{ t.playbackNote }}</p>
        <p v-if="playbackOn && !state.protocols.length && !scanErr" class="dim sm">{{
          t.playbackNoRoot }}</p>
        <p v-if="scanErr" class="err">{{ scanErr }}</p>
        <p v-else-if="state.protocols.length" class="dim sm">{{
          t.foundProtocols(state.protocols.length) }}</p>

        <template v-if="state.protocols.length">
          <input v-model="protoFilter" class="mono flt" :placeholder="t.filter">
          <div class="plist">
            <!-- Keyed and compared by abs, not by dir: two corpora can hold the
                 same protocol at the same relative path, and on dir the two
                 rows share a key and picking one highlights both. -->
            <!-- A standard, as a row you open, but only where it has more than
                 one mechanism; a group of one lists as itself. -->
            <template v-for="r in protoVisible"
                      :key="r.kind === 'head' ? 'h:' + r.head : r.p.abs">
            <!-- The whole corpus path, not its last segment: cut down to
                 9798-2-symmetric-encipherment a standard no longer says it is
                 ISO. A leaf row spends two lines because its name and its path
                 are different things (IKEv2-signature against
                 rfc/IKEV2/subprotocols/signature); a standard has no declared
                 name, so the path is the name. -->
            <div v-if="r.kind === 'head'" class="prow phead"
                 :class="{open: protoGroupOpen(r.head)}" @click="toggleProtoGroup(r.head)">
              <span class="caret">{{ protoGroupOpen(r.head) ? '▾' : '▸' }}</span>
              <span class="mono nm" :title="r.head">{{ r.head }}</span>
              <span class="dim tags"><span class="num">{{ t.mechanismsTag(r.n) }}</span></span>
            </div>
            <div v-else class="prow" :class="{on: picked && picked.abs === r.p.abs, sub: r.sub}"
                 :data-tour="r.p.abs === tourProto ? 'proto' : null"
                 @click="pick(r.p)">
              <!-- Inside a standard the row is the mechanism, not the whole
                   path: the standard is already the line above it. -->
              <span class="mono nm" :class="{guessed: r.p.name_from === 'path'}"
                    :title="r.p.name_from === 'path' ? t.nameFromPath : r.p.name">{{
                r.sub ? r.leafName : r.p.name }}</span>
              <span v-if="!r.sub" class="dim pth" :title="r.p.dir">{{ r.p.dir }}</span>
              <!-- Four separate facts, ruled apart, each carrying its own unit:
                   two bare numbers side by side read as one quantity split in
                   half. -->
              <span class="dim tags">
                <span class="num" :title="t.goalsTip">{{ t.goalsTag(r.p.goals) }}</span>
                <span class="num" :title="t.scenariosTip">{{ t.scenariosTag(r.p.scenarios) }}</span>
                <span class="num" :title="t.docTip">{{ kb(r.p.doc) }}</span>
                <span v-if="r.p.subprotocols.length" :title="t.subTip">{{
                  r.p.subprotocols.length }}sub</span>
                <span v-if="r.p.ground_truth" class="gt" :title="t.gtTip">gt</span>
              </span>
            </div>
            </template>
            <!-- A filter that matched nothing says so, rather than leaving an
                 empty box that reads as "still loading". -->
            <p v-if="!protoVisible.length" class="dim sm pad">{{ t.filterNoHit }}</p>
          </div>
        </template>
        </template>

        <!-- ── your own document ────────────────────────────────────────────
             A browser, not a scan. The server walks it because the server is
             what will open the files, and a page cannot turn a native file
             dialog into a path anything here could read. Typing still works. -->
        <template v-else>
          <label class="fld">{{ t.libRoot }}
            <span class="row2">
              <input v-model="browsePath" class="mono"
                     :placeholder="browsing ? browsing.home : ''"
                     @keydown.enter="openDir(browsePath)">
              <button class="tiny" @click="openDir(browsePath)">{{ t.scan }}</button>
            </span>
          </label>
          <p v-if="browseErr" class="err">{{ browseErr }}</p>
          <template v-if="browsing">
            <div class="bcrumb">
              <a v-if="browsing.parent" href="#"
                 @click.prevent="openDir(browsing.parent)">{{ t.browseUp }}</a>
              <a href="#" @click.prevent="openDir(browsing.home)">{{ t.browseHome }}</a>
              <span class="grow"></span>
              <!-- The folder itself is a legitimate answer: a protocol
                   directory, or one document sitting in a folder of its own. -->
              <button class="tiny" @click="pickTarget(browsing.path)">{{ t.browseHere }}</button>
            </div>
            <div class="blist">
              <div v-for="d in browsing.dirs" :key="d.path" class="brow"
                   @click="openDir(d.path)">
                <span class="caret">▸</span>
                <span class="mono nm">{{ d.name }}</span>
                <span v-if="d.protocol" class="gt" :title="t.isProtocol">proto</span>
              </div>
              <div v-for="f in browsing.docs" :key="f.path" class="brow doc"
                   :class="{on: target && target.main === f.path}"
                   @click="pickTarget(f.path)">
                <span class="mono nm">{{ f.name }}</span>
                <span class="dim num">{{ kb(f.bytes) }}</span>
              </div>
              <p v-if="!browsing.dirs.length && !browsing.docs.length"
                 class="dim sm pad">{{ t.browseEmpty }}</p>
              <p v-if="browsing.truncated" class="dim sm pad">{{
                t.browseCut(browsing.truncated) }}</p>
            </div>
          </template>

          <template v-if="target">
            <div class="sep"></div>
            <p class="dim sm">{{ t.targetRoot }}
              <span class="mono">{{ target.root }}</span></p>
            <p v-if="target.layout === 'corpus'" class="dim sm">{{ t.targetCorpus }}</p>
            <template v-else>
              <p v-if="!target.docs.length" class="err">{{ t.noDocsHere }}</p>
              <!-- The one thing a directory cannot answer: which of five files
                   is the protocol. Asked, not guessed. -->
              <template v-else-if="docChoice.length">
                <p class="fld" style="margin-bottom:var(--s-1)">{{ t.pickMain }}
                  <span class="dim sm">{{ t.pickMainWhy }}</span></p>
                <div class="blist">
                  <div v-for="f in docChoice" :key="f.path" class="brow doc"
                       :class="{on: mainDoc === f.path}" @click="mainDoc = f.path">
                    <span class="mono nm">{{ f.name }}</span>
                    <span class="dim num">{{ kb(f.bytes) }}</span>
                    <!-- Off by default: sharing a folder is not a citation, and
                         an extra document is paid for in every round of every
                         session that reads the corpus block. -->
                    <a v-if="mainDoc !== f.path" href="#" class="pin"
                       :class="{on: refDocs.includes(f.path)}" :title="t.asRefTip"
                       @click.stop.prevent="toggleRef(f.path)">{{
                      refDocs.includes(f.path) ? '✓' : '+' }} {{ t.asRef }}</a>
                  </div>
                </div>
              </template>
              <p v-if="target.refs.length" class="dim sm">{{ t.refsFound(target.refs.length) }}</p>
            </template>
          </template>
        </template>

        <template v-if="sourceMode === 'corpus' ? picked : targetReady">
          <div class="sep"></div>
          <label class="fld">{{ t.protoName }}
            <input v-model="form.name" class="mono" :class="{need: !form.name.trim()}"
                   :placeholder="t.protoNameHint"></label>
          <p v-if="sourceMode === 'corpus' && picked.name_from === 'path'"
             class="dim sm">{{ t.nameNotDeclared }}</p>
          <label class="fld" v-if="!playbackOn">{{ t.protoVersion }}
            <input v-model="form.version" class="mono" placeholder="—"></label>
          <label v-if="chosenSubs.length" class="fld">{{ t.subprotocol }}
            <select v-model="form.subprotocol" class="mono">
              <option v-for="sp in chosenSubs" :key="sp" :value="sp">{{ sp }}</option>
            </select></label>
          <!-- A playback does not name its run: which recording plays is the
               recording's own business, and the panel offers one protocol
               row per protocol. -->
          <label class="fld" v-if="!playbackOn">{{ t.runNameField }}
            <input v-model="form.runName" class="mono" :placeholder="t.runNameHint"></label>
          <!-- Where each artifact comes from: the corpus's copy, or this run's
               own extraction. Independent choices with one real dependency, a
               mother model needing the principals.json it was written on. The
               question is not coupled to the model: lib claims with an
               extracted flow model measures the flow extraction on a fixed
               question. Written straight to config.yaml. -->
          <div class="sep"></div>
          <div class="picks" v-if="!playbackOn">
            <div v-for="r in libRows" :key="r.knob" class="pick">
              <span class="plabel">{{ r.label }}</span>
              <span class="pchoice">
                <button :class="{on: r.on}" :disabled="saving === r.knob || !r.can"
                        :title="r.can ? t.libTip : t.noSupply"
                        @click="setLib(r.knob, true)">{{ t.fromLib }}</button>
                <button :class="{on: !r.on}" :disabled="saving === r.knob"
                        :title="t.extractTip(r.makes)"
                        @click="setLib(r.knob, false)">{{ t.extractIt }}</button>
              </span>
            </div>
            <div class="pick">
              <span class="plabel">{{ t.endPoint }}</span>
              <span class="pchoice wide">
                <button v-for="e in END_POINTS" :key="e.id"
                        :class="{on: (knobAt('inputs.end_point') || 'scenarios') === e.id}"
                        :disabled="saving === 'inputs.end_point'"
                        :title="t.endTip(e.after)"
                        @click="setInput('inputs.end_point', e.id)">{{ e.id }}</button>
              </span>
            </div>
          </div>
          <p class="dim sm" v-if="!playbackOn">{{ t.willRun }} {{ willRun }}</p>
          <!-- Nothing to start without a key and a solver. Refused beside the
               button rather than accepted and failed a second later. -->
          <button class="go" data-tour="start" @click="startRun()"
                  :disabled="starting || !form.name.trim() ||
                             (!playbackOn && !(state.cfg && state.cfg.complete))">
            {{ starting ? t.starting : t.startIt(form.name || '?') }}</button>
          <p v-if="!playbackOn && state.cfg && !state.cfg.complete" class="dim sm">{{
            t.configFirst }}</p>
        </template>
      </details>

      <!-- Closed while playing back, open live, but bound rather than
           hard-coded so it stays a reader's control: it still shows the
           settings the recording ran under. Switching modes resets it. -->
      <details class="panel cfg" :open="cfgOpen" @toggle="cfgOpen = $event.target.open">
        <summary>
          <span class="ttl">{{ t.configTitle }}</span>
          <!-- The model actually about to be spent, which is the live slot's
               — llm.model is only the reading of it and is not in this list. -->
          <span class="dim sm" v-if="state.cfg">{{
            knobAt('llm.profiles.' + backend + '.model') }} · {{
            knobAt('pipeline.mode') }}</span>
        </summary>
        <!-- The one thing a fresh clone has to do, said where it is done. Not
             while playing back: nothing here is used. -->
        <p v-if="!playbackOn && state.cfg && !state.cfg.complete" class="err">{{
          t.fillThese }}<br><span class="mono">{{ state.cfg.unfilled.join(', ') }}</span></p>
        <p v-if="playbackOn" class="dim sm">{{ t.playbackLocked }}</p>
        <p v-if="cfgErr" class="err">{{ cfgErr }}</p>
        <div :class="{ro: playbackOn}">
        <template v-for="(k, i) in rows" :key="k.path">
          <div v-if="!i || rows[i-1].group !== k.group" class="grp">{{ k.group }}</div>
          <!-- The live slot's own rows, marked once at the top of the block so
               it is clear these belong to the backend above. -->
          <div v-if="k.profile && (!i || !rows[i-1].profile)" class="grp sub">{{
            t.slotOf(k.profile) }}</div>
          <div class="knob" :class="{busy: saving === k.path}">
            <!-- Every knob explains itself on hover, out of the engine's own
                 HELP table. The dotted underline is what says a label is worth
                 pointing at. -->
            <span class="mono kp" :class="{tip: k.help}" :title="k.help">{{
              knobLabel(k) }}</span>
            <span v-if="k.locked" class="mono dim kv" :title="k.value">{{
              k.secret ? (k.value || t.unset) : k.value }}</span>
            <!-- Closed lists commit on change, everything else on enter or on
                 leaving the field: half a path or half a key is not a value. -->
            <!-- A switch is one of two values, so it is picked rather than
                 typed. -->
            <select v-else-if="k.type === 'boolean'" class="mono kv"
                    :value="String(k.value)"
                    @change="saveKnob(k, $event.target.value)">
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
            <select v-else-if="k.closed" class="mono kv" :value="k.value"
                    @change="saveKnob(k, $event.target.value)">
              <option v-for="c in choicesFor(k)" :key="c" :value="c">{{
                c }}{{ k.path === 'llm.backend' && ready.includes(c) ? ' ✓' : '' }}</option>
            </select>
            <!-- A knob with a suggested list but no closed set — the model —
                 gets a real dropdown. The list is not a constraint: whatever
                 the config already holds is offered too, so a model id set by
                 hand for some gateway stays reachable. -->
            <select v-else-if="choicesFor(k).length" class="mono kv"
                    :value="k.value"
                    @change="saveKnob(k, $event.target.value)">
              <option v-for="c in withCurrent(k)" :key="c" :value="c">{{ c }}</option>
            </select>
            <input v-else class="mono kv" :value="k.value"
                   :type="k.secret ? 'password' : 'text'"
                   :placeholder="k.secret ? t.unset : ''"
                   @keydown.enter="saveKnob(k, $event.target.value)"
                   @blur="saveKnob(k, $event.target.value)">
          </div>
        </template>
        </div>
        <p class="dim sm note2">{{ t.savedTo(state.cfg && state.cfg.config_path) }}</p>
      </details>
    </div>
   </div>
  </main>

  <!-- The first visit. Drawn off the shell rather than beside the things they
       point at, which are inside scrolling boxes that would clip a nested
       bubble. Both ask for a click on one control, so both take the page dark
       behind it. Dismissing either ends the tour: on this page a mark is an
       instruction. -->
  <coach-mark v-if="showMark('proto', 'pick')" at="[data-tour='proto']" spotlight
              :head="t.tourPickHead" :text="t.tourPickText"
              @close="endTour"></coach-mark>
  <coach-mark v-if="showMark('start', 'start')" at="[data-tour='start']" spotlight
              :head="t.tourStartHead" :text="t.tourStartText"
              @close="endTour"></coach-mark>
  </div>
</template>

<template v-else>
  <div class="shell">
  <header class="topbar">
    <a href="#/" class="back">←</a>
    <span class="runname">{{ runName }}</span>
    <span class="pill" :class="{ok: state.status==='ok', bad: state.status==='failed',
                                warn: state.status==='check_failed', run: state.status==='running'}">
      <span class="dot"></span>{{ t.runStatus(state.status) }}</span>
    <!-- Stated either way: shown only when connected, a broken stream looks the
         same as a page that has simply not said anything. -->
    <span class="dim" :style="{fontSize: 'var(--t-sm)', color: state.connected ? null : 'var(--v-warn)'}">
      ● {{ state.connected ? t.connected : t.disconnected }}</span>
    <!-- Said plainly, because everything else on this page is the run's own and
         these two are not: a recording, played at a speed that is not the
         run's. -->
    <template v-if="playbackHere">
      <span class="pill" :title="t.playbackPillTip">{{ t.playbackPill }}</span>
      <span class="dim num" style="font-size:var(--t-sm)"
            :title="t.speedTip(playbackHere.factor)">{{ playbackHere.factor }}×</span>
    </template>
    <span class="grow"></span>
    <a class="tiny ghost" href="/vocabulary" target="_blank" rel="noopener"
       :title="t.vocabularyTip"
       style="text-decoration:none;padding:5px 14px">{{ t.vocabulary }}</a>
    <!-- Hidden for now: the page is English-only until the Chinese half is
         worth showing again. The dictionary and setLang are still there, so
         bringing it back is dropping this comment's two ends.
    <span class="langtoggle">
      <button :class="{on: lang==='en'}" @click="setLang('en')">EN</button>
      <button :class="{on: lang==='zh'}" @click="setLang('zh')">中</button>
    </span>
    -->
    <span v-if="state.usage.out" class="dim num" style="font-size:var(--t-sm)"
          :title="t.billTip(state.usage.in, state.usage.cached)">{{
      t.bill(tokens(state.usage.in), tokens(state.usage.out)) }}</span>
    <a href="#" class="tiny ghost" v-if="state.files.includes('work.md')"
       @click.prevent="show('work.md')"
       style="text-decoration:none;padding:5px 14px">{{ t.openWorkMd }}</a>
    <!-- Manual mode parks the engine at a node boundary. The release is a POST
         that already existed; without a button the run simply never resumes. -->
    <button v-if="state.awaiting" class="tiny" @click="approve()">{{
      t.releaseAt(state.awaiting) }}</button>
    <button v-if="state.status==='running'" class="tiny danger"
            @click="interrupt">{{ t.interrupt }}</button>
    <!-- The reader's own verdict on the run, kept apart from the pipeline's.
         Reversible: a run signed off in March is worth reopening in June. -->
    <template v-else-if="!playbackOn">
      <button v-if="state.review.state === 'open'" class="tiny"
              :title="t.archiveTip" @click="setReview('archived')">{{ t.archive }}</button>
      <button v-else class="tiny" @click="setReview('open')">{{ t.reopen }}</button>
    </template>
  </header>

  <main class="body stack">
    <div v-if="state.unknownTypes.length" class="banner">
      {{ t.unhandled }}
      <span class="mono">{{ state.unknownTypes.join(', ') }}</span>
    </div>
    <div v-if="serverErr" class="banner">{{ serverErr }}</div>
    <!-- The index and the directory tree disagree. Never repaired here: a
         directory nobody wrote down, or a record with nothing behind it, is
         something outside the pipeline did, and the answer is a person. -->
    <div v-if="state.problems.length" class="banner">
      {{ t.indexProblems(state.problems.length) }}
      <span class="mono">{{ state.problems.join(' · ') }}</span>
    </div>

    <section class="panel pipeline-panel">
      <div class="head"><h2>{{ t.pipeline }}</h2><span class="sub">{{ t.pipelineSub(NODES.length) }}</span>
        <!-- Where this run's artifacts came from, and where it stopped.
             Read-only: a finished run's inputs are a fact about it, not a
             control. Struck through = the corpus's copy, so this run did not
             write it. -->
        <span v-if="ranLib" class="ranrange" :title="t.ranLibTip">
          <span v-for="r in LIB_ROWS" :key="r.knob"
                :class="{on: !ranLib.lib.includes(r.knob.split('.')[1])}"
                >{{ r.knob.split('.')[1].slice(4) }}</span>
          <span class="here">→ {{ ranLib.end }}</span>
        </span>
      </div>
      <div class="pipe" data-tour="pipeline" :style="{
             gridTemplateColumns: 'repeat(' + pipe.cols + ', minmax(var(--pipe-col), 1fr))',
             gridTemplateRows: 'repeat(' + pipe.rows + ', auto)'}">
        <!-- The step that stopped the run carries the reason on hover, so the
             strip answers "which one, and why" without scrolling anywhere. -->
        <div v-for="c in pipe.cells" :key="c.node" class="step"
             :class="[state.nodes[c.node] || 'pending',
                      {sel: openNode === c.node, forked: c.forked, joined: c.col > 1,
                       pinned: pinnedStep(c.node), fanned: fanOut(c.node) > 1}]"
             :style="{gridColumn: c.col, gridRow: c.row + ' / span ' + c.span}"
             @click="pickNode(c.node)"
             :title="stepTitle(c.node)">
          <!-- A step that ran once per scenario is drawn as a stack. The layers
               are a real element rather than a pseudo-element, because
               .step.joined already spends ::before on the connector into its
               left edge. -->
          <span v-if="fanOut(c.node) > 1" class="fanlayers" aria-hidden="true"></span>
          <span class="label">{{ stepLabel(c.node) }}</span>
          <span v-if="fanOut(c.node) > 1" class="fanout"
                :title="t.fannedTip(fanOut(c.node))">×{{ fanOut(c.node) }}</span>
          <!-- Only where the upstream is complete. Re-entry destroys nothing:
               this step and everything after it run into new directories, and
               what came before is reused. The first step is the whole run over,
               and the most expensive address this page can aim at; the cheaper
               ones are the rows underneath. -->
          <a v-if="retryable(c.node)" href="#" class="retry" :title="retryTitle(c.node)"
             @click.stop.prevent="retryStep(c.node)">{{ t.retryHere }}</a>
          <span v-else-if="retrying === c.node" class="retry busy"
                          :title="t.retryStartingTip">{{ t.retryStarting }}</span>
          <!-- Something was re-worked inside this step, which leaves the step
               itself holding the directory it already had; without this the row
               reads as untouched. -->
          <span v-if="reworksUnder(liveDir(c.node))" class="inside"
                :title="t.insideTip">⤷ {{ reworksUnder(liveDir(c.node)) }}</span>
          <!-- What this step's product scored against the corpus, when the run
               was given one. Only on steps the corpus answers: no badge means
               not measured, which is not the same as scoring zero. -->
          <span v-if="state.scores[c.node]" class="score"
                :class="{bad: state.scores[c.node].num < state.scores[c.node].den}"
                :title="t.scoreTip(state.scores[c.node])">{{
                  state.scores[c.node].num }}/{{ state.scores[c.node].den }}</span>
          <span v-if="state.alignments[c.node]" class="score alignment"
                :class="{bad: state.alignments[c.node].status !== 'ok'}"
                :title="t.alignmentTip(state.alignments[c.node])">↔{{
                  (state.alignments[c.node].mappings || []).length }}</span>
          <!-- Not-equals, not a second cross: a step whose checks disagreed
               with the corpus ran to the end and wrote its report, and the
               cells that disagree carry that same sign one panel down. "The
               answers differ" is not "the node broke". (No backticks in this
               template — one in a comment ends the literal.) -->
          <span class="mark">{{ {ok:'✓', running:'●', failed:'✗',
                                 check_failed:'≠', skipped:'—'}[state.nodes[c.node]] || '' }}</span>
        </div>
      </div>
      <stage-timeline parent=""></stage-timeline>
      <!-- A refused re-entry says why here rather than vanishing: the usual
           reasons are answerable (the run is still in flight, the corpus moved,
           an upstream artifact was superseded and never re-run). -->
      <p v-if="retryErr" class="dim sm" style="color:var(--v-bad);margin:var(--s-2) 0 0">{{ retryErr }}</p>
      <!-- Why the run stopped, said where a reader lands rather than left as
           one line in a feed of twenty. Under the strip and above the step it
           opens, so the three read in the order a person asks them in: what
           stopped, where, then the step itself. Only for a crash — a run whose
           checks said no still produced an answer, and the table below reads
           it. -->
      <div v-if="state.failure && state.failure.kind !== 'check'" class="failbanner">
        <div class="fbhead">
          <span class="pill bad"><span class="dot"></span>{{ t.runFailed }}</span>
          <a v-if="state.failure.node" href="#" class="mono step-link"
             @click.prevent="openFailedStep()">{{ state.failure.node }}</a>
          <!-- Which branch of it, when the step that stopped fans out. The
               ledger cannot narrow it: siblings interleave, so the last line
               before the crash belongs to whichever happened to be talking.
               An identity path — the same address a fix is aimed by. -->
          <span v-if="state.failure.where" class="mono fbwhere"
                :title="t.failedAtHint">{{ state.failure.where }}</span>
          <span class="grow"></span>
          <!-- Everything the step wrote before it stopped: the prompt it was
               answering, and the rounds it got through. -->
          <a v-if="state.failure.node" href="#" class="dim sm"
             @click.prevent="openFailedStep()">{{ t.openFailedStep }}</a>
        </div>
        <pre class="fbwhy">{{ state.failure.reason }}</pre>
      </div>
    </section>

    <div class="cols" :class="{folded: !expertOpen}">
      <div class="stack main-col">
        <!-- ══ the selected step, opened ═════════════════════════════════════
             The step chosen in the strip above: its inside on the left, the
             session beside it. Node, identity and session are one tree and
             every level of it is a re-entry address, so nesting them puts the
             whole address space in one place. A panel in this column and not a
             block under the strip: the strip sits outside the scrolling column,
             so an unbounded timeline there takes the height instead of
             scrolling and squeezes the expert panel to nothing. -->
        <section v-if="openNode" class="panel opened">
          <div class="head">
            <h2 data-tour="inside">{{ t.insideOf(openNode) }}</h2>
            <!-- Only a scenario is worth naming beside the step: the
                 shared-base steps file their sessions under an ident of their
                 own, which repeats the node name. -->
            <span v-if="openRow && openRow.kind === 'scenarios' && openScenario"
                  class="sub mono">{{ openScenario }}</span>
            <span class="grow"></span>
            <!-- Off the moment they choose, and a way back: without it a single
                 click ends the following for the rest of the run. -->
            <button v-if="state.status === 'running'" class="tiny"
                    :class="follow ? '' : 'ghost'" @click="follow = !follow">{{
              follow ? t.following : t.followRun }}</button>
            <a href="#" class="dim sm" @click.prevent="pickNode(openNode)">{{ t.closeInside }}</a>
          </div>

          <!-- The strip lists the whole table; only some of it has run. -->
          <p v-if="!openRow" class="muted">{{ t.stepNotRun }}</p>

          <div v-else class="detail" :class="{solo: !hasSessions}">
            <div :key="'units/' + openNode">
              <!-- the fan-out: one row per scenario, opening its own sessions -->
              <template v-if="openRow.kind === 'scenarios'">
                <div class="lanes">
                  <template v-for="l in openRow.labels" :key="l">
                    <div class="lane" :class="{open: openScenario === l}"
                         @click="pickScenario(l)">
                      <!-- The column is finite and a label is not; the whole of
                         it stays reachable when the row has to cut it. -->
                    <span class="name" :title="l">{{ openScenario === l ? '▾' : '▸' }} {{ l }}</span>
                      <!-- No width beside the session for four phase labels, so
                           the track names them on hover and keeps the one thing
                           the column is for: how far this scenario got. -->
                      <span class="track" :title="PHASES.join(' → ')">
                        <i v-for="(ph, i) in PHASES" :key="ph"
                           :class="i < lanePhase(l).at ? 'done'
                                   : i === lanePhase(l).at && lanePhase(l).at < PHASES.length
                                     ? 'now' : 'queued'"></i>
                      </span>
                      <span class="stat" :class="laneStatClass(l)"
                            :title="laneAgree(l) ? t.laneMatchTip : t.laneStatTip">{{ laneText(l) }}</span>
                      <a v-if="canRetry" href="#" class="retry"
                         :title="retryTitle(stepAddr(l))"
                         @click.stop.prevent="retryStep(stepAddr(l))">{{ t.retryHere }}</a>
                      <span v-else-if="retrying === stepAddr(l)"
                            class="retry busy"
                          :title="t.retryStartingTip">{{ t.retryStarting }}</span>
                    </div>
                    <!-- the scenario's own sessions, under it rather than in a
                         column of their own: an apply point and a goal family
                         are inside this scenario. -->
                    <ul v-if="openScenario === l" class="units nested">
                      <template v-for="u in units" :key="u">
                      <li :class="{sel: openUnit === u}" @click="pickUnit(u)">
                        <span class="mono grow">{{ u }}</span>
                        <!-- How many of this family's goals the corpus agrees
                             with. Without it the lane's "4/5" sits above two
                             rows and nothing on screen says why. -->
                        <span v-if="uGoals(l, u) && uGoals(l, u).of"
                              class="stat" :class="uGoals(l, u).matched === uGoals(l, u).of ? 'ok' : 'bad'"
                        >{{ t.laneMatched(uGoals(l, u).matched, uGoals(l, u).of) }}</span>
                        <a v-if="canRetry" href="#" class="retry"
                           :title="retryTitle(stepAddr(l, u))"
                           @click.stop.prevent="retryStep(stepAddr(l, u))">{{ t.retryHere }}</a>
                        <span v-else-if="retrying === stepAddr(l, u)"
                              class="retry busy"
                          :title="t.retryStartingTip">{{ t.retryStarting }}</span>
                      </li>
                      <!-- The goals this row answered, under the row that
                           answered them. Not rows of their own: one session
                           injects the whole family and hands ProVerif all of it
                           at once. -->
                      <li v-for="g in (uGoals(l, u) ? uGoals(l, u).goals : [])"
                          :key="u + '/' + g.id" class="goalrow"
                          :title="g.cell ? t.goalVsTruth(String(g.verdict), String(g.cell.expected)) : ''">
                        <span class="mark" :class="g.cell ? (g.cell.match ? 'ok' : 'bad') : ''"
                        >{{ goalMark(g) }}</span>
                        <span class="mono grow">{{ g.id }}</span>
                        <span v-if="g.cell && !g.cell.match" class="stat bad"
                        >{{ t.goalExpected(String(g.cell.expected)) }}</span>
                      </li>
                      </template>
                      <li v-if="!units.length" class="muted">{{ t.noUnits }}</li>
                    </ul>
                  </template>
                </div>
              </template>

              <!-- a step whose sessions are its own: the units, straight away -->
              <template v-else-if="units.length">
                <div class="head"><h2 style="font-size:var(--t-md)">{{ t.units }}</h2></div>
                <ul class="units">
                  <li v-for="u in units" :key="u" :class="{sel: openUnit === u}"
                      @click="pickUnit(u)">
                    <span class="mono grow">{{ u }}</span>
                    <!-- A step that runs one session is its own unit, so its
                         address is the cell above and a second button here
                         would be the same button twice. -->
                    <template v-if="stepAddr(openScenario, u) !== openNode">
                      <a v-if="canRetry" href="#" class="retry"
                         :title="retryTitle(stepAddr(openScenario, u))"
                         @click.stop.prevent="retryStep(stepAddr(openScenario, u))">{{ t.retryHere }}</a>
                      <span v-else-if="retrying === stepAddr(openScenario, u)"
                            class="retry busy"
                          :title="t.retryStartingTip">{{ t.retryStarting }}</span>
                    </template>
                  </li>
                </ul>
              </template>

              <!-- a step that opened no session at all: what it reported -->
              <template v-else>
                <div class="head"><h2 style="font-size:var(--t-md)">{{ t.stepSaid }}</h2></div>
                <ul class="nodelog">
                  <li v-for="(l, i) in stepLog" :key="i" :class="l.t">
                    <span class="glyph">{{ l.t === 'finished' ? '✓' : '·' }}</span>
                    <span>{{ l.t === 'finished' ? t.stepEnded(l.text) : l.text }}</span>
                  </li>
                </ul>
                <p v-if="!stepLog.length" class="muted">{{ t.stepSaidNothing }}</p>
              </template>

              <p v-if="openRow.kind === 'scenarios' && openScenario" style="margin-top:.6rem">
                <a href="#" @click.prevent="scenarioPv()" style="font-size:.78rem">{{ t.seeScenarioPv }}</a>
                <a href="#" class="pin" :class="{on: isAttached(stepPath('scenarios', openScenario, 'apply/scenario.pv')), full: attachFull && !isAttached(stepPath('scenarios', openScenario, 'apply/scenario.pv'))}"
                   :title="isAttached(stepPath('scenarios', openScenario, 'apply/scenario.pv')) ? t.unpinTip : (attachFull ? t.pinFull(attachCap) : t.pinTip)"
                   @click.stop.prevent="toggleAttached(stepPath('scenarios', openScenario, 'apply/scenario.pv'))">{{ isAttached(stepPath('scenarios', openScenario, 'apply/scenario.pv')) ? '✓' : '+' }}</a>
              </p>

              <!-- What the step left, beside the sessions that produced it. Every
                   product is two things a reader wants: something to open, and
                   something to hand the expert. -->
              <template v-if="stepFiles.length">
                <div class="head" style="margin-top:var(--s-3)">
                  <h2 style="font-size:var(--t-md)">{{ t.stepProducts }}</h2></div>
                <ul class="nodelog">
                  <li v-for="f in stepFiles" :key="f" class="product">
                    <span class="glyph">·</span>
                    <a href="#" class="mono"
                       @click.prevent="openStepFile(openStep, f)">{{ f }} ↗</a>
                    <a href="#" class="pin" :class="{on: isAttached(stepPath(openStep, f)), full: attachFull && !isAttached(stepPath(openStep, f))}"
                       :title="isAttached(stepPath(openStep, f)) ? t.unpinTip : (attachFull ? t.pinFull(attachCap) : t.pinTip)"
                       @click.stop.prevent="toggleAttached(stepPath(openStep, f))">{{ isAttached(stepPath(openStep, f)) ? '✓' : '+' }}</a>
                  </li>
                </ul>
              </template>
            </div>

            <!-- Follows the foot of the timeline while the panel is following
                 the run: a step that makes a lot of tool calls otherwise pushes
                 what it is doing below the fold. Keyed on the session, so
                 moving to another one starts at that session's own beginning
                 rather than inheriting an offset. -->
            <div v-if="hasSessions" v-stick="follow"
                 :key="openNode + '/' + (openScenario || '') + '/' + (openUnit || '')">
              <div class="head">
                <h2 style="font-size:var(--t-md)" class="mono">{{ openUnit || t.pickUnit }}</h2>
                <span class="grow"></span>
                <span v-if="unitData && unitData.usage" class="dim num">{{
                  t.stepTokens(tokens(unitData.usage.in), tokens(unitData.usage.out)) }}</span>
              </div>
              <!-- The session as it happened, in order. One line per thing
                   that occurred; the two that have a full text behind them —
                   the prompt that opened a round, and the reply it got — open
                   in place from the files the run left. -->
              <div v-if="unitData" class="timeline">
                <div v-for="(it, i) in unitData.items" :key="i" class="tl"
                     :class="it.kind">
                  <span class="glyph" :class="glyphClass(it)">{{ glyphOf(it) }}</span>

                  <template v-if="it.kind === 'prompt'">
                    <a href="#" class="tlmain" @click.prevent="toggle(it, i)">{{
                      t.tlPrompt(it.no) }}</a>
                    <span class="dim">{{ baseName(it.path) }} · {{ it.chars }}
                      <a href="#" class="pin" :class="{on: isAttached(it.path), full: attachFull && !isAttached(it.path)}"
                         :title="isAttached(it.path) ? t.unpinTip : (attachFull ? t.pinFull(attachCap) : t.pinTip)"
                         @click.stop.prevent="toggleAttached(it.path)">{{ isAttached(it.path) ? '✓' : '+' }}</a></span>
                  </template>

                  <template v-else-if="it.kind === 'reply'">
                    <a href="#" class="tlmain" @click.prevent="toggle(it, i)">{{
                      it.streaming && streamed(it) ? t.tlWriting : t.tlReply(it.no) }}</a>
                    <span class="dim" v-if="it.streaming && streamed(it)">{{
                      streamed(it) }} {{ t.tlChars }}</span>
                    <!-- What this round cost, not what the session did. The
                         session's total is on the head above. -->
                    <span class="dim num" v-else-if="it.usage" :title="t.roundBillTip">{{
                      t.roundBill(tokens(it.usage.in), tokens(it.usage.out)) }}</span>
                  </template>

                  <template v-else-if="it.kind === 'tool'">
                    <span class="tlmain mono">{{ it.tool }}({{ it.args }})</span>
                    <span class="dim" :class="{bad: it.ok === false}">{{ it.result }}</span>
                  </template>

                  <template v-else-if="it.kind === 'framework'">
                    <span class="tlmain">{{ it.text }}</span><span></span>
                  </template>

                  <!-- One named check. The two that run ProVerif — a typecheck,
                       and flow's honest-reachability probe — take as long as
                       ProVerif takes. A pass with a note is neither green nor
                       red: goals_typecheck passes on a solver timeout by rule,
                       and nothing was verified. -->
                  <template v-else-if="it.kind === 'check'">
                    <span class="tlmain mono"
                          :class="{warn: it.running === false && !it.passed}">{{ it.check }}</span>
                    <!-- No backticks in here: the whole template is one JS
                         template literal, and one would end it. -->
                    <span class="dim">{{ it.running ? t.checkRunning
                      : (it.note ? t.checkNote(it.note) + ' · ' : '')
                        + (it.seconds != null ? it.seconds + 's' : '') }}</span>
                    <ul v-if="it.running === false && !it.passed && it.findings.length"
                        class="findings-why">
                      <li v-for="(f, k) in it.findings" :key="k">
                        <span v-if="findingCell(f)" class="fcell">{{ findingCell(f) }}</span>
                        <span class="fwhy">{{ findingBody(f) }}</span>
                      </li>
                    </ul>
                  </template>

                  <!-- Every finding, whole: the answer to "why did this not
                       pass" is what a reader came to the row for. -->
                  <template v-else-if="it.kind === 'checks'">
                    <span class="tlmain" :class="{warn: !it.passed}">{{
                      it.passed ? t.checksPassed
                                : t.checksFailed(it.count != null ? it.count : it.findings.length) }}</span>
                    <span></span>
                    <ul v-if="!it.passed && it.findings.length" class="findings-why">
                      <li v-for="(f, k) in it.findings" :key="k">
                        <span v-if="findingCell(f)" class="fcell">{{ findingCell(f) }}</span>
                        <span class="fwhy">{{ findingBody(f) }}</span>
                      </li>
                    </ul>
                  </template>

                  <!-- How much of what the corpus declares this step's product
                       matched. Under the checks verdict: a step can pass every
                       check and still have read the document differently, which
                       is the one thing the checks cannot say. Not tinted like a
                       failure — it is a measurement. -->
                  <template v-else-if="it.kind === 'scored'">
                    <span class="tlmain">{{ t.tlScored(it) }}</span>
                    <span class="dim">{{ it.extra ? t.tlScoredExtra(it.extra) : '' }}</span>
                  </template>

                  <!-- The solver writes at the family level (pipeline/scenarios.py
                       cell_dir, solve/node.py log_to): a unit is one family, and
                       there is no directory below it named after the cell. -->
                  <template v-else-if="it.kind === 'solve'">
                    <span class="tlmain">{{ t.tlSolve(it.cell, it.seconds) }}
                      <span v-for="(v, g) in it.verdicts" :key="g" class="v" :class="v">
                        {{ g }}={{ v }}&nbsp;</span></span>
                    <span>
                      <a class="open" href="#"
                         @click.prevent="openEvidence(unitData.key, '01_proverif.txt')">↗</a>
                      <a href="#" class="pin" :class="{on: isAttached(at(unitData.key, '01_proverif.txt')), full: attachFull && !isAttached(at(unitData.key, '01_proverif.txt'))}"
                         :title="isAttached(at(unitData.key, '01_proverif.txt')) ? t.unpinTip : (attachFull ? t.pinFull(attachCap) : t.pinTip)"
                         @click.stop.prevent="toggleAttached(at(unitData.key, '01_proverif.txt'))">{{ isAttached(at(unitData.key, '01_proverif.txt')) ? '✓' : '+' }}</a>
                    </span>
                  </template>

                  <!-- while it is being written, and after it is opened -->
                  <pre v-if="it.kind === 'reply' && it.live.thinking" v-stick
                       class="think live">{{ it.live.thinking }}</pre>
                  <pre v-if="it.kind === 'reply' && it.live.text" v-stick
                       class="live">{{ it.live.text }}</pre>
                  <pre v-if="opened[oKey(i)] !== undefined" class="body">{{ opened[oKey(i)] }}</pre>
                </div>
                <p v-if="!unitData.items.length" class="muted">{{ t.noRounds }}</p>
              </div>
            </div>
          </div>

          <!-- What this scenario did, when it did more than one thing: its
               apply chain in order, and its goal families by generation. Under
               the panel rather than inside a column, because it is about the
               scenario and a chain of six points needs the width. One is a
               fold, the other a fan-out, so the two are drawn differently. -->
          <stage-timeline v-if="openScenarioDir"
                          :parent="openScenarioDir + '/apply'"
                          band="apply"></stage-timeline>
          <stage-timeline v-if="openScenarioDir"
                          :parent="openScenarioDir + '/inject'"
                          band="inject"></stage-timeline>
        </section>

        <!-- Folded shut when the run died before producing any of it: what is
             inside is then not "not yet" but "never". -->
        <section class="panel" ref="resultsEl">
          <!-- Not a <details>: one without a <summary> renders the browser's
               own disclosure widget, localised, above the panel. Two
               presentations of one panel, chosen outright. -->
          <div v-if="diedEarly" class="head foldhead">
            <h2>{{ t.results }}</h2>
            <span class="dim sm">{{ t.nothingProduced(state.failure && state.failure.node) }}</span>
          </div>
          <div v-else class="head">
            <h2>{{ t.results }}</h2><span class="sub">{{ t.resultsSub }}</span>
            <span class="grow"></span>
            <!-- The head's own empty half, put to work: the shape of the matrix
                 and, when there is ground truth, how much of it came out right —
                 the one number a reader wants before reading any cell. -->
            <span class="sub num" v-if="matrix().rows.length">{{
              t.matrixShape(matrix().labels.length, matrix().rows.length) }}</span>
            <span v-if="state.crossCheck" class="tally"
                  :class="agreeCount.all ? 'ok' : 'bad'">{{
              t.agreeStat(agreeCount.hit, agreeCount.of) }}</span>
          </div>
          <template v-if="!diedEarly">
          <!-- What every scenario carries, in the two tiers the pipeline builds:
               the world model first (who exists, who is honest, how roles bind,
               how many sessions), then the root model applied onto it. Side by
               side because two different steps build them. Their own band and
               not rows in the grid: these are the same in every column. Both
               always drawn, even empty — "this protocol assumes nothing here"
               is a fact about it. -->
          <div class="carried">
            <details class="fixedband" open v-for="tier in ['world', 'root']" :key="tier">
              <summary>{{ tier === 'world' ? t.worldAssumptions : t.rootAssumptions }}
                <span class="dim n" :title="tier === 'world' ? t.worldTip : t.rootTip">{{
                  dims()[tier].length }}</span></summary>
              <div class="fixedlist">
                <span v-for="d in dims()[tier]" :key="d.id"
                      :title="dimNameTip(d) + '\\n\\n' + dimTip(d, d.by[matrix().labels[0]])">
                  {{ d.id }} = {{ d.by[matrix().labels[0]].subtype }}</span>
                <span v-if="!dims()[tier].length" class="dim">{{ t.noneHere }}</span>
              </div>
            </details>
          </div>

          <!-- Asking for the attacks the step left waiting. Shown and inert
               while playing back, so a reader sees the console can do it. The
               button to send is never greyed for an empty choice: pressing it
               says what to do first. -->
          <div v-if="reproToolbar && matrix().rows.length" class="rp-toolbar">
            <button class="tiny" :class="{ghost: !reproSelecting}"
                    :aria-pressed="reproSelecting" :disabled="playbackOn"
                    @click="toggleSelecting()">{{ reproSelecting
                      ? t.rpSelecting(reproPicked.size) : t.rpSelect }}</button>
            <button class="tiny ghost" :disabled="playbackOn || !reproBy.pending.length"
                    @click="pickAllWaiting()">{{ t.rpSelectAll(reproBy.pending.length) }}</button>
            <button class="tiny" :disabled="playbackOn || reproSending"
                    @click="askSelected()">{{ t.rpAskSelected(reproPicked.size) }}</button>
            <button v-if="reproBusy" class="tiny danger" :disabled="playbackOn"
                    @click="stopRepro()">{{ t.rpStop }}</button>
            <span v-if="reproIndex.queue && reproIndex.queue.length" class="dim sm num">{{
              t.rpQueueLeft(reproIndex.queue.length) }}</span>
            <span v-if="playbackOn" class="dim sm">{{ t.rpPlaybackNo }}</span>
            <span v-if="reproNote" class="rp-note">{{ reproNote }}</span>
          </div>

          <div class="matrixwrap" ref="matrixEl" v-if="matrix().rows.length">
          <table class="matrix" :style="{'--colw': colw + 'px', '--idw': idw + 'px'}">
            <thead>
              <tr>
                <th>{{ t.dimension }}</th>
                <!-- A scenario is identified by the grid below it, not by its name.
                     The name is an address (the directory it wrote), so it is a
                     tooltip and a click, the same treatment a goal id gets. -->
                <th v-for="(w, i) in matrix().scenarios" :key="w.label" class="mono sc"
                    :title="w.label">S{{ i + 1 }}</th>
                <th v-if="matrix().hasTruth" class="concl">{{ t.matchesIn }}</th>
              </tr>
            </thead>

            <!-- The two halves of the table answer different questions, so each
                 opens with a band of its own; without them the axis headings
                 read as the only structure. -->
            <tbody>
              <tr class="side">
                <td :colspan="(matrix().hasTruth ? 2 : 1) + matrix().labels.length">{{ t.sideAssumptions }}
                  <span class="dim">{{ t.sideAssumptionsSub }}</span></td>
              </tr>
            </tbody>

            <!-- The assumption side, grouped by axis. One protocol can hang
                 several dimensions off one axis, told apart only by their
                 target, so the axis is a heading and the dimension is a row. -->
            <tbody v-for="g in dims().groups" :key="g.axis">
              <tr class="axis">
                <td :colspan="(matrix().hasTruth ? 2 : 1) + matrix().labels.length"
                    :title="axisTip(g.axis)">
                  <span class="mono">{{ g.axis }}</span>
                  <span class="dim">{{ g.seen.join(' | ') }}</span>
                </td>
              </tr>
              <tr v-for="d in g.rows" :key="d.id" class="dim-row">
                <td class="mono dimname" :title="dimNameTip(d)">{{ d.id }}
                  <span class="dim" v-if="d.target">· {{ targetOf(d.target) }}</span></td>
                <!-- A subtype is long and joined by underscores, so it wraps at
                     its own joints. -->
                <td v-for="w in matrix().scenarios" :key="w.label" class="sc val"
                    :title="dimTip(d, d.by[w.label])"
                    :class="{declared: d.by[w.label] && d.by[w.label].from === 'condition'}">
                  <span v-if="d.by[w.label]" class="colname"><template
                    v-for="(p, i) in nameParts(d.by[w.label].subtype)"
                    :key="i">{{ p }}<wbr></template></span>
                </td>
                <td v-if="matrix().hasTruth" class="concl"></td>
              </tr>
            </tbody>

            <!-- The goal side, one tbody per block. A block is the goals the
                 claims asked in the same set of scenarios; the columns it does not
                 use are drawn once, merged down the block, instead of a
                 placeholder in every row. -->
            <tbody>
              <tr class="side">
                <td :colspan="(matrix().hasTruth ? 2 : 1) + matrix().labels.length">{{ t.sideGoals }}
                  <span class="dim">{{ t.sideGoalsSub }}</span></td>
              </tr>
            </tbody>
            <tbody v-for="(b, bi) in matrix().blocks" :key="bi" class="goals">
              <tr v-for="(row, ri) in b.rows" :key="row.id">
                <td class="mono" :title="goalTip(row.id)">{{ row.id }}
                  <span class="kind" v-if="goalKind(row.id)">{{ goalKind(row.id) }}</span></td>
                <!-- The comparison sits on the cell it is about. A wrong answer
                     shows what the right one was, right where it is wrong. -->
                <template v-for="(w, i) in matrix().scenarios" :key="w.label">
                  <td v-if="b.uses[i]" class="cell sc"
                      :class="[{miss: row.cells[i].match === false,
                                hit: row.cells[i].match === true,
                                attacked: Boolean(attackOn(row.id, w.label))},
                               reproCellClass(row.id, w.label, row.cells[i])]"
                      :title="[reproCellTip(row.id, w.label, row.cells[i]),
                               attackOn(row.id, w.label)
                                 ? t.attackTip(attackOn(row.id, w.label).name)
                                   + (attackOn(row.id, w.label).summary
                                      ? '\\n' + attackOn(row.id, w.label).summary : '')
                                   + (attackOn(row.id, w.label).reference
                                      ? '\\n' + t.attackSource + ': '
                                        + attackOn(row.id, w.label).reference : '')
                                   + (attackOn(row.id, w.label).abstraction_gap
                                      ? '\\n' + t.attackGap : '')
                                 : '',
                               row.cells[i].match === false
                                 ? t.cellDiffers(VERDICT[row.cells[i].expected] || '?')
                                 : (row.cells[i].match ? t.agreesTip : ''),
                               row.cells[i].kind === 'verdict'
                                 && !opensAttack(row.id, w.label, row.cells[i]) ? t.clickCell : '']
                              .filter(Boolean).join('\\n\\n')"
                      @click="cellClick(row.id, w.label, row.cells[i])">
                    <!-- A cell with an answer opens that answer's own file; one
                         without is still the scenario's. -->
                    <span v-if="row.cells[i].kind === 'verdict'" class="v"
                          :class="row.cells[i].v">{{ VERDICT[row.cells[i].v] }}</span>
                    <span v-else class="v none">·</span>
                    <!-- Where the attack behind a false stands: played back,
                         waiting its turn, being replayed, or not replayable.
                         The shape says it as well as the ground does. -->
                    <span v-if="reproCellMark(row.id, w.label, row.cells[i])"
                          class="rpmark">{{ reproCellMark(row.id, w.label, row.cells[i]) }}</span>
                    <!-- Always ours, the operator, then the ground truth's: the
                         same shape whether they agree or not. Each answer keeps
                         its own verdict colour, so an expected ✓ is never
                         painted red. -->
                    <template v-if="row.cells[i].match !== undefined && row.cells[i].match !== null"
                      ><span class="ne">{{ row.cells[i].match ? '=' : '≠' }}</span><span
                        class="v want" :class="row.cells[i].expected">{{
                        VERDICT[row.cells[i].expected] || '?' }}</span></template>
                    <!-- Whether anything has explained this cell, and how it
                         read it. A disagreement with a diagnosis and one
                         without are different situations for a reader. -->
                    <span v-if="readingOf(row.id, w.label)" class="reading"
                          :class="readingOf(row.id, w.label)"
                          :title="t.readingTip(readingOf(row.id, w.label))">{{
                      t.readingShort(readingOf(row.id, w.label)) }}</span>
                    <!-- The corpus's name for what this cell's false is about,
                         carried on the cell so it is legible while reading the
                         table. Only cells the literature documents get one. -->
                    <span v-if="attackOn(row.id, w.label)" class="attackmark">⚔<span
                      class="an">{{ attackOn(row.id, w.label).short
                                    || attackOn(row.id, w.label).name }}</span></span>
                  </td>
                  <td v-else-if="ri === 0" class="unasked" :rowspan="b.rows.length">
                    {{ t.notAsked }}</td>
                </template>
                <td v-if="matrix().hasTruth" class="concl num"
                    :class="{off: row.matched < row.compared}"
                    :title="row.why">{{ row.matched }}/{{ row.compared }}</td>
              </tr>
            </tbody>
          </table>
          </div>
          <p v-else class="empty">{{ t.noVerdicts }}</p>
          <p v-if="state.crossCheck" class="note">
            {{ t.truthRule(state.crossCheck.filter(c => c.match).length,
                           state.crossCheck.length) }}
          </p>
          </template>
          <!-- One cell, and everything that answers for it. A panel in the
               column, not a modal: the expert sits to the right, and asking
               about a cell while looking at it is the point. -->
          <section v-if="inspect" class="inspector">
            <div class="ins-top">
              <strong class="mono">{{ inspect.goal }}</strong>
              <span class="dim">@ {{ colOf(inspect.label) }} · {{ inspect.label }}</span>
              <span class="v" :class="inspect.verdict">{{ VERDICT[inspect.verdict] }}</span>
              <span class="dim sm">{{ t.ourAnswer }}</span>
              <template v-if="inspect.expected !== null">
                <span class="ne">{{ inspect.match ? '=' : '≠' }}</span>
                <span class="v want" :class="inspect.expected">{{ VERDICT[inspect.expected] }}</span>
                <span class="dim sm">{{ t.corpusAnswer }}</span>
              </template>
              <!-- A run given no corpus compares against nothing. Said, rather
                   than left as a gap where the comparison would be. -->
              <span v-else class="dim sm">{{ t.noCorpusForCell }}</span>
              <span class="grow"></span>
              <button class="tiny" @click="askAboutCell()">{{ t.askAboutThis }}</button>
              <a href="#" class="dim closex" @click.prevent="closeInspector()">×</a>
            </div>

            <!-- Where this false cell's attack reproduction stands. The
                 reproduced one is watched in the panel below the table. -->
            <div v-if="inspectRepro" class="ins-repro" :class="'rp-' + inspectRepro.look">
              <span class="rpmark">{{ REPRO_GLYPH[inspectRepro.look] || '\u00b7' }}</span>
              <span class="ins-why">{{ t.rpInspect(inspectRepro) }}</span>
              <a v-if="inspectRepro.look === 'done'" href="#"
                 @click.prevent="openRepro(inspectRepro.key, true)">{{ t.rpWatch }}</a>
              <button v-if="inspectRepro.look === 'pending'
                            || (inspectRepro.look === 'failed' && inspectRepro.manual)"
                      class="tiny" :disabled="playbackOn || reproSending"
                      :title="playbackOn ? t.rpPlaybackNo : ''"
                      @click="askOne(inspect.goal, inspect.label)">{{
                inspectRepro.look === 'pending' ? t.rpAskOne : t.rpAskAgain }}</button>
              <span v-if="reproNote" class="rp-note">{{ reproNote }}</span>
            </div>

            <!-- What the corpus records this cell's false as being about. Above
                 the construction chain, because it is the answer to the
                 question a reader opens the cell with. -->
            <div v-if="attackOn(inspect.goal, inspect.label)" class="ins-attack">
              <div class="ins-h">
                <span class="attackmark">⚔</span>
                <span class="ins-ah">{{ t.attackHeading }}</span>
                <b>{{ attackOn(inspect.goal, inspect.label).name }}</b>
              </div>
              <p class="ins-why">{{ t.attackTip(attackOn(inspect.goal, inspect.label).name) }}</p>
              <p v-if="attackOn(inspect.goal, inspect.label).summary" class="ins-why">{{
                attackOn(inspect.goal, inspect.label).summary }}</p>
              <p v-if="attackOn(inspect.goal, inspect.label).abstraction_gap" class="ins-why gap">{{
                t.attackGap }}</p>
              <dl v-if="attackOn(inspect.goal, inspect.label).reference" class="ins-quotes">
                <dt>{{ t.attackSource }}</dt>
                <dd>{{ attackOn(inspect.goal, inspect.label).reference }}</dd>
              </dl>
            </div>

            <!-- The construction chain. Each step is the same file one step on,
                 so the difference between two of them is a real diff and reads
                 as "what this step did". The step the diagnosis blames is
                 marked, and is the one open when the panel first appears. -->
            <div class="ins-stages" v-if="stages.length">
              <span class="ins-label">{{ t.builtBy }}</span>
              <a v-for="st in stages" :key="st.step" href="#" class="chip mono"
                 :class="{on: stage && stage.step === st.step, blamed: st.blamed}"
                 :title="st.blamed ? t.blamedTip : t.stageTip"
                 @click.prevent="openStage(st)">{{ st.step }}{{ st.blamed ? ' ◂' : '' }}</a>
            </div>

            <div v-if="stage" class="ins-diff">
              <!-- The two file names sit over their own panes, on the same
                   grid, so a name is above the file it names. -->
              <div class="ins-diffhead">
                <span class="mono dim">{{ baseName(stage.after) }}
                  <span class="sm">{{ t.against(baseName(stage.before)) }}</span>
                  <span class="legend">
                  <span class="key add"></span>{{ t.legendStep(stage.step) }}
                  <span class="key ap-add"></span>{{ t.legendApply }}</span></span>
                <!-- The corpus's model, the same one for every stage: it is what
                     ours is being judged against, so it stays put while the
                     left pane walks the construction chain. -->
                <span class="mono dim">
                  <span class="sm">{{ t.corpusModel }}</span>
                  <select v-if="refChoices.length > 1" class="refpick mono"
                          :value="refShown"
                          @change="refPick = $event.target.value">
                    <option v-for="f in refChoices" :key="f" :value="f">{{
                      baseName(f) }}</option>
                  </select>
                  <template v-else>{{ baseName(refShown) || '—' }}</template>
                </span>
              </div>
              <!-- Two panes, each scrolling on its own. Not synchronised: past a
                   few dozen lines the two files no longer correspond row for
                   row, and a scroll that pretends they do moves the pane a
                   reader is not looking at. -->
              <div class="panes">
                <!-- Ours, as this step left it, with what the step changed
                     marked in place: a minus for the line it took out, a plus for the
                     one it put there. -->
                <div class="pane" :ref="el => paneEls.left = el">
                  <p v-if="!diffLines" class="dim sm pad">…</p>
                  <div v-else v-for="l in diffLines" :key="l.key" class="ln"
                       :class="[l.tone, {q: l.quoted}]">
                    <span class="lno">{{ l.n || '' }}</span><span class="sgn">{{ l.sign }}</span
                    ><code v-html="l.html"></code>
                  </div>
                </div>
                <div class="pane" :ref="el => paneEls.right = el">
                  <p v-if="!refShown" class="dim sm pad">{{ t.noCorpusModel }}</p>
                  <p v-else-if="!refLines" class="dim sm pad">…</p>
                  <div v-else v-for="l in refLines" :key="l.key" class="ln"
                       :class="{q: l.quoted}">
                    <span class="lno">{{ l.n }}</span><span class="sgn"></span
                    ><code v-html="l.html"></code>
                  </div>
                </div>
              </div>
            </div>

            <!-- The diagnosis, under the change it is about. -->
            <div v-if="inspect.finding" class="ins-finding" :class="inspect.finding.reading">
              <div class="ins-h">
                <span class="reading" :class="inspect.finding.reading">{{
                  t.readingShort(inspect.finding.reading) }}</span>
                <span>{{ t.readingTip(inspect.finding.reading) }}</span>
                <span class="dim" v-if="inspect.finding.responsible_step
                                        && inspect.finding.responsible_step !== 'none'">
                  · {{ t.responsibleStep }}: <b class="mono">{{ inspect.finding.responsible_step }}</b></span>
              </div>
              <p class="ins-why">{{ inspect.finding.why }}</p>
            </div>
            <p v-else-if="inspect.match === false" class="ins-none">{{ t.noDiagnosis }}</p>

            <div class="ins-files">
              <div class="ins-col">
                <div class="ins-label">{{ t.oursSide }}</div>
                <a v-for="[k, path] in inspect.evidence" :key="path" href="#" class="chip mono"
                   :title="path" @click.prevent="showEvidence(path)">{{ t.ev(k) }}</a>
              </div>
              <div class="ins-col" v-if="referencePv || referenceAttacks.length">
                <div class="ins-label">{{ t.corpusSide }}</div>
                <a v-if="referencePv" href="#" class="chip mono corpus" :title="referencePv"
                   @click.prevent="showReference(referencePv)">{{ t.refModel }}</a>
                <a v-for="a in referenceAttacks" :key="a" href="#" class="chip mono corpus"
                   :title="a" @click.prevent="showReference(a)">{{ t.refAttack }}</a>
              </div>
            </div>

            <div v-if="cellSide" class="ins-pane">
              <div class="ins-panehead">
                <span class="mono">{{ cellSide.path }}</span>
                <span class="dim">{{ cellSide.side === 'corpus' ? t.corpusSide : t.oursSide }}</span>
                <a href="#" class="dim" @click.prevent="cellSide = null">×</a>
              </div>
              <pre>{{ cellSide.text }}</pre>
            </div>
            <p class="dim sm" v-if="cellSide && cellSide.side === 'corpus'">{{ t.whyNotDiff }}</p>
          </section>

          <!-- Every reading anybody has filed on this run, collected. They
               arrive one at a time, as a reader asks about a cell and the
               expert concludes something. -->
          <div v-if="reviewFindings().length" class="findings">
            <div class="fhead">{{ t.reviewTitle }}
              <span class="dim">{{ t.reviewSub(reviewFindings().length) }}</span></div>
            <a v-for="(f, i) in reviewFindings()" :key="i" href="#" class="frow"
               @click.prevent="openInspector(f.goal, f.scenario)">
              <span class="reading" :class="f.reading"
                    :title="t.readingTip(f.reading)">{{ t.readingShort(f.reading) }}</span>
              <span class="mono fgoal">{{ f.goal }}</span>
              <span class="dim fat">@ {{ colOf(f.scenario) }} · {{ f.scenario }}</span>
              <span class="dim fstep" v-if="f.responsible_step && f.responsible_step !== 'none'"
                    :title="t.responsibleTip">→ {{ f.responsible_step }}</span>
              <span class="fwhy dim">{{ f.why }}</span>
            </a>
          </div>
        </section>

        <!-- ══ the attacks behind the false cells ═══════════════════════════
             Below the table they came from. Each reproduced cell plays as a
             message sequence; the others say why they were not played. -->
        <section v-if="reproPanel" class="panel attacks">
          <div class="head">
            <h2>{{ t.rpTitle }}</h2><span class="sub">{{ t.rpSub }}</span>
            <span class="grow"></span>
            <span v-if="reproCounts.all" class="sub num">{{ t.rpCounts(reproCounts) }}</span>
          </div>
          <p v-if="reproErr" class="err">{{ reproErr }}</p>
          <p v-if="reproIndex.step && !reproIndex.step.enabled" class="muted">{{ t.rpOff }}</p>
          <p v-else-if="!reproCounts.all" class="muted">{{
            reproIndex.step && reproIndex.step.complete ? t.rpNone : t.rpWaiting }}</p>

          <!-- What the reproduced cells come down to, in one paragraph and a
               group per problem. -->
          <div v-if="reproIndex.summary" class="rp-summary">
            <div class="rp-h">{{ t.rpSummaryTitle(reproIndex.summary.covered.length) }}</div>
            <p class="rp-text"><template v-for="(q, k) in quoteParts(reproIndex.summary.summary)"
              :key="k"><code v-if="q.code">{{ q.text }}</code><template v-else>{{ q.text }}</template></template></p>
            <div v-for="(g, i) in reproIndex.summary.groups" :key="i" class="rp-group">
              <p class="rp-text"><template v-for="(q, k) in quoteParts(g.problem)"
                :key="k"><code v-if="q.code">{{ q.text }}</code><template v-else>{{ q.text }}</template></template></p>
              <a v-for="n in g.cells" :key="n" href="#" class="chip mono"
                 @click.prevent="openRepro(summaryKey(n), true)">{{ summaryCell(n) }}</a>
            </div>
            <p v-if="reproIndex.summary.pending" class="dim sm">{{
              t.rpSummaryPending(reproIndex.summary.pending) }}</p>
            <p v-if="reproOutside.length" class="dim sm rp-outside">{{ t.rpOutside(reproOutside.length) }}
              <button v-if="!reproIndex.summarizing" class="tiny ghost"
                      :disabled="playbackOn || reproBusy"
                      :title="reproBusy ? t.rpWaitQueue : ''"
                      @click="resummarize()">{{ t.rpResummarize(reproOutside.length) }}</button></p>
            <p v-if="reproIndex.summarizing" class="dim sm">{{ t.rpSummarizing }}</p>
            <p v-if="reproIndex.queue_error" class="err">{{ t.rpSummaryFailed(reproIndex.queue_error) }}</p>
          </div>

          <!-- One row per reproduced cell; the open one plays. -->
          <div v-for="c in reproBy.done" :key="c.key" class="rp-item"
               :class="{open: reproOpen === c.key}">
            <a href="#" class="rp-ihead" @click.prevent="openRepro(c.key)">
              <span class="caret">{{ reproOpen === c.key ? '\u25BE' : '\u25B8' }}</span>
              <span class="rpmark">{{ REPRO_GLYPH.done }}</span>
              <span class="mono">{{ c.goal }}</span>
              <span class="dim">@ {{ colOf(c.label) }} · {{ c.label }}</span>
              <span v-if="c.manual" class="rp-tag">{{ t.rpManual }}</span>
              <span class="grow"></span>
              <span class="dim num">{{ t.rpSteps(c.steps || 0) }}</span>
            </a>
            <template v-if="reproOpen === c.key">
              <div class="rp-itools">
                <span v-if="c.weakened && c.weakened.length" class="dim sm">{{ t.rpWeakened }}
                  <span class="mono">{{ c.weakened.join(' \u00b7 ') }}</span></span>
                <span v-else class="dim sm">{{ t.rpNotWeakened }}</span>
                <span class="grow"></span>
                <a href="#" class="dim sm" @click.prevent="openInspector(c.goal, c.label)">{{ t.rpInspectCell }}</a>
                <a v-if="c.home" href="#" class="dim sm"
                   @click.prevent="show(c.home + '/trace.txt')">{{ t.rpRawTrace }}</a>
                <button v-if="c.manual && c.explain_error" class="tiny ghost"
                        :disabled="playbackOn || reproSending"
                        @click="askOne(c.goal, c.label)">{{ t.rpAskAgain }}</button>
              </div>
              <p v-if="reproFiles && reproFiles.error" class="err">{{ reproFiles.error }}</p>
              <attack-player v-else-if="reproFiles && reproFiles.script" :key="c.key"
                             :script="reproFiles.script" :explanation="reproFiles.explanation"
                             :no-explanation="reproNoExplain(c)" :replay="Boolean(c.replay)"
                             :display="c.display || 'long'"></attack-player>
              <p v-else class="dim sm">\u2026</p>
            </template>
          </div>

          <div v-if="reproBy.flying.length" class="rp-list">
            <div class="rp-lh">{{ t.rpFlyingHead(reproBy.flying.length) }}</div>
            <div v-for="c in reproBy.flying" :key="c.key" class="rp-li">
              <span class="rpmark" :class="'rp-' + c.look">{{ REPRO_GLYPH[c.look] }}</span>
              <span class="mono">{{ c.goal }}</span>
              <span class="dim">@ {{ colOf(c.label) }} · {{ c.label }}</span>
              <span class="dim sm">{{ t.rpLook(c.look) }}</span>
            </div>
          </div>

          <!-- Why a chosen cell has nothing to play, said in full. -->
          <div v-if="reproBy.failed.length" class="rp-list">
            <div class="rp-lh">{{ t.rpFailedHead(reproBy.failed.length) }}</div>
            <div v-for="c in reproBy.failed" :key="c.key" class="rp-li wrap">
              <span class="rpmark rp-failed">!</span>
              <span class="mono">{{ c.goal }}</span>
              <span class="dim">@ {{ colOf(c.label) }} · {{ c.label }}</span>
              <a v-if="c.home" href="#" class="dim sm"
                 @click.prevent="show(c.home + '/trace.txt')">{{ t.rpRawTrace }}</a>
              <span class="rp-why">{{ c.look === 'unfinished' ? t.rpUnfinished : c.reason }}</span>
            </div>
          </div>

          <div v-if="reproBy.pending.length" class="rp-list">
            <div class="rp-lh">{{ t.rpPendingHead(reproBy.pending.length,
                                                  reproIndex.step && reproIndex.step.limit) }}
              <a v-if="!playbackOn" href="#" class="dim sm"
                 @click.prevent="pickAllWaiting()">{{ t.rpSelectAllShort }}</a></div>
            <label v-for="c in reproBy.pending" :key="c.key" class="rp-li rp-pick">
              <input type="checkbox" :checked="reproPicked.has(c.key)"
                     :disabled="playbackOn" :title="t.rpPickTip"
                     @change="pickCell(c.key)">
              <span class="v false">{{ VERDICT.false }}</span>
              <span class="mono">{{ c.goal }}</span>
              <span class="dim">@ {{ colOf(c.label) }} · {{ c.label }}</span>
              <span v-if="c.stale" class="rp-tag">{{ t.rpStale }}</span>
              <span class="dim sm">{{ c.weakened && c.weakened.length
                ? t.rpWeakenedN(c.weakened.length) : t.rpNotWeakened }}</span>
            </label>
            <div class="rp-li">
              <button class="tiny" :disabled="playbackOn || reproSending"
                      @click="askSelected()">{{ t.rpAskSelected(reproPicked.size) }}</button>
              <span v-if="reproNote" class="rp-note">{{ reproNote }}</span>
            </div>
          </div>

          <details v-if="reproBy.skipped.length" class="rp-list">
            <summary class="rp-lh">{{ t.rpSkippedHead(reproBy.skipped.length) }}</summary>
            <div v-for="c in reproBy.skipped" :key="c.key" class="rp-li wrap">
              <span class="v false">{{ VERDICT.false }}</span>
              <span class="mono">{{ c.goal }}</span>
              <span class="dim">@ {{ colOf(c.label) }} · {{ c.label }}</span>
              <span class="rp-why">{{ t.rpWhy(c.reason, c.expected) }}</span>
            </div>
          </details>
        </section>

        <section class="panel feedwrap">
          <div class="head"><h2>{{ t.feed }}</h2><span class="sub">{{ t.feedCount(state.feed.length) }}</span></div>
          <div class="filters">
            <button :class="{on: filter === null}" @click="filter = null">{{ t.filterAll }}</button>
            <button v-for="l in scenarioNames" :key="l"
                    :class="{on: filter === l}" @click="filter = l">{{ l }}</button>
          </div>
          <div class="feed" ref="feedEl" @scroll="onFeedScroll">
            <!-- An empty feed says which kind of empty it is. Silence here read
                 as "nothing happened" for a run whose events never arrived. -->
            <p v-if="!state.feed.length" class="empty">
              {{ state.connected ? t.feedEmpty : t.feedNoStream }}
            </p>
            <!-- What the window is not showing, said rather than left to be
                 inferred from a scrollbar that stops early. A cap nobody
                 mentions reads as a run that began at line 301. -->
            <p v-if="feedHidden" class="earlier">
              <a href="#" @click.prevent="showEarlierFeed()">{{ t.feedEarlier(feedHidden) }}</a>
            </p>
            <div v-for="e in feed" :key="e.seq">
              <span class="ts">{{ clock(e.ts) }}</span>
              <span class="at">{{ where(e) }}</span>
              <span class="body" v-html="marked(e)"></span>
            </div>
          </div>
        </section>
      </div>

      <div class="stack side-col">
        <button v-if="!expertOpen" class="expert-tab" :title="t.expertOpen"
                :aria-label="t.expertOpen" @click="setExpertOpen(true)">
          <span class="chev">‹</span><span class="word">{{ t.expert }}</span>
        </button>
        <section v-else class="panel expert">
          <div class="head"><h2>{{ t.expert }}</h2><span class="sub">{{ t.expertSub }}</span>
            <span class="grow"></span>
            <button class="tiny ghost" :title="t.expertClose" :aria-label="t.expertClose"
                    @click="setExpertOpen(false)">›</button></div>

          <article v-if="state.pending" class="pending">
            <strong style="color:var(--accent)">{{ t.pendingTitle }}</strong>
            <p v-if="state.pending.plan" class="mono" style="font-size:.8rem;margin:.4rem 0 0">
              {{ state.pending.plan.step }} / {{ state.pending.plan.mode }}</p>
            <p v-if="state.pending.plan" style="font-size:.85rem;margin:.3rem 0">
              {{ state.pending.plan.message }}</p>
            <p class="cost" style="margin:.3rem 0 .6rem">
              {{ state.pending.plan
                   ? t.pendingCost(state.pending.plan.reruns.length,
                                   state.pending.plan.superseded.length) : '…' }}</p>
            <div class="two">
              <button @click="decide(true)">{{ t.execute }}</button>
              <button class="ghost" @click="decide(false)">{{ t.cancel }}</button>
            </div>
          </article>

          <div class="chatlog">
            <div v-for="(m, i) in state.chat" :key="i" class="msg" :class="m.who">
              {{ m.text }}</div>
            <div v-if="liveExpert" class="msg it live">
              <!-- Folded by default: thinking is how the answer was reached,
                   not the answer, and a reader who wants it opens it. The
                   summary still moves while it is closed, so the panel says
                   the model is working without saying it in words. -->
              <details v-if="liveExpert.thinking" class="fold">
                <summary>{{ t.thinkingFold(liveExpert.thinking.length) }}</summary>
                <pre v-stick class="think live">{{ liveExpert.thinking }}</pre>
              </details>
              <pre v-if="liveExpert.text" v-stick
                   class="live">{{ liveExpert.text }}</pre>
              <span v-if="state.expertRound" class="sub">{{ t.thinkingRound(state.expertRound) }}</span>
            </div>
            <div v-else-if="state.asking" class="msg it muted">
              {{ state.expertRound ? t.thinkingRound(state.expertRound) : t.thinking }}
            </div>
            <p v-if="!state.chat.length && !state.asking" class="empty">
              {{ t.expertEmpty }}
            </p>
          </div>

          <!-- What is riding with the next message, visible and removable: a
           reader has to be able to see what the model was given. -->
      <div v-if="attach" class="attached">
        <span class="dim sm">{{ attach.goal
          ? t.attachedTo(attach.goal, colOf(attach.scenario), attach.stage)
          : t.attachedFiles(attach.paths.length) }}</span>
        <a v-for="p in attach.paths" :key="p" href="#" class="chip mono"
           :title="p" @click.prevent="dropAttached(p)">{{ baseName(p) }} ×</a>
      </div>
      <div class="composer">
            <!-- Asking is the one thing on this page that spends a model call,
                 so a playback cannot offer it. Shown and inert rather than
                 removed, so a reader sees the console can do this. -->
            <textarea v-model="draft" rows="3"
                      :disabled="state.asking || playbackOn"
                      :placeholder="playbackOn ? t.playbackNoExpert : t.composerPlaceholder"
                      @keydown.meta.enter="ask" @keydown.ctrl.enter="ask"></textarea>
            <div class="send">
              <span class="hint">{{ t.sendHint }}</span>
              <!-- While a question is in flight, Stop takes Send's place: it is
                   the only thing that ends a turn the model will not end
                   itself, so it must be where the eye already is. -->
              <button v-if="state.asking" class="tiny danger" @click="stopAsk">{{
                t.stopAsk }}</button>
              <button v-else class="tiny" @click="ask"
                      :disabled="!draft.trim() || playbackOn">{{ t.send }}</button>
            </div>
          </div>
        </section>
      </div>
    </div>
  </main>

  <!-- The other half of the first visit, both at once: what the strip is, and
       what opening one of its boxes shows. The second waits for its panel to
       exist, so it appears a few seconds after the first. Each is dismissed on
       its own — two different answers, not two steps. -->
  <coach-mark v-if="showMark('pipe', 'run')" at="[data-tour='pipeline']"
              side="below" align="end"
              :head="t.tourPipeHead" :text="t.tourPipeText"
              @close="shutMark('pipe')"></coach-mark>
  <coach-mark v-if="showMark('inside', 'run')" at="[data-tour='inside']"
              :head="t.tourInsideHead" :text="t.tourInsideText"
              @close="shutMark('inside')"></coach-mark>
  </div>

  <dialog :open="!!viewing" v-if="viewing">
    <article>
      <header><strong class="mono">{{ viewing.path }}</strong>
        <a href="#" aria-label="Close" class="close" @click.prevent="viewing = null"></a></header>
      <pre>{{ viewing.text }}</pre>
    </article>
  </dialog>
</template>
`,
}

/** Keep a scrolling box showing its newest line, for text that arrives a
 *  fragment at a time. Whether to follow is decided before the update: after
 *  it, the new content has already moved the reader away from the bottom and
 *  every box would look scrolled up. A reader who scrolled up is left there,
 *  and scrolling back to the foot re-attaches. */
const stickBottom = {
  mounted (el, binding) {
    if (binding.value !== false) el.scrollTop = el.scrollHeight
  },
  beforeUpdate (el, binding) {
    el._follow = binding.value !== false
      && el.scrollHeight - el.scrollTop - el.clientHeight < 40
  },
  updated (el) { if (el._follow !== false) el.scrollTop = el.scrollHeight },
}

createApp(App)
  .component('stage-timeline', StageTimeline)
  .component('coach-mark', CoachMark)
  .component('attack-player', AttackPlayer)
  .directive('stick', stickBottom)
  .mount('#app')
