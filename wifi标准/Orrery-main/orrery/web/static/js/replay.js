import { computed, ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { t } from './i18n.js'

/* One reproduced attack, played back as a message sequence chart.
 *
 * The script (msc.json, modules/attacks/script.py) carries the facts: the
 * sessions, each message with the kind of move it was, and the goal that
 * broke. The explanation carries the words, one note per step. Everything
 * drawn is derived from the two, and both belong to the player: they are read
 * when it opens and dropped when it closes, never kept in the page's state.
 *
 * Frames: 0 is before the first message, 1..N are the messages, N+1 is the
 * goal breaking. */

export const ATTACKER = 'attacker'
/** How many steps are drawn. Past it the chart says what it left out rather
 *  than growing without bound. */
export const MAX_STEPS = 120

const ROW = 30           // one step's height
const TOP = 62           // the lane heads
const LINE = 14          // one line of a definition box
const PAD = 6            // inside a definition box
const CH = 6.6           // one monospace character at the box's size
const LEFT = 30          // the step numbers
const MIN_GAP = 150      // between two lifelines
const MAX_GAP = 280
const STEP_MS = 2200     // how long autoplay holds a step
const FLY_MS = 750
const PULSE_MS = 450

/** The control glyphs, each held to its text form: several are emoji by
 *  default on some platforms. */
const GLYPH = { restart: '\u23EE\uFE0E', play: '\u25B6\uFE0E',
                pause: '\u23F8\uFE0E', end: '\u23ED\uFE0E' }

const reducedMotion = () => typeof matchMedia === 'function'
  && matchMedia('(prefers-reduced-motion: reduce)').matches

/** The lanes in drawing order: the sessions as the script lists them, named
 *  S1, S2, … the way the explanation names them, with the attacker's lane
 *  among them rather than at an edge, since nearly every arrow touches it. */
export function laneOrder (lanes) {
  const honest = lanes.map((l, i) => ({
    id: l.id, name: `S${i + 1}`, role: l.role || '', bindings: l.bindings || [],
    attacker: false }))
  const at = Math.max(1, Math.floor(honest.length / 2))
  const x = { id: ATTACKER, name: 'X', role: '', bindings: [], attacker: true }
  return [...honest.slice(0, at), x, ...honest.slice(at)]
}

/** A string cut to `max` characters, the cut marked. */
export const clip = (text, max) =>
  text.length <= max ? text : text.slice(0, Math.max(1, max - 1)) + '…'

/** The few characters a message is carried as while it moves: the whole value
 *  when it is short, else its outermost constructor. */
export function token (value) {
  if (value.length <= 14) return value
  const head = value.match(/^[^(,]*\(/)
  return head ? head[0] + '…)' : clip(value, 14)
}

/** Prose split at its backticks, so the pieces a model quoted are drawn as
 *  code. An unmatched backtick is left as text. */
export function quoteParts (text) {
  const out = []
  const re = /`([^`\n]+)`/g
  let at = 0
  for (let m; (m = re.exec(text || '')); ) {
    if (m.index > at) out.push({ text: text.slice(at, m.index), code: false })
    out.push({ text: m[1], code: true })
    at = m.index + m[0].length
  }
  if (at < (text || '').length) out.push({ text: text.slice(at), code: false })
  return out
}

/** One definition as a line: a stand-in reads `name = body`, what the
 *  attacker worked out `name ← how`, what it made up `new names`. */
export function defLine (d) {
  if (d.kind === 'new') return `new ${d.name}`
  return `${d.name} ${d.kind === 'derive' ? '←' : '='} ${d.body}`
}

/** Text cut at the stand-in names it mentions, so they can be drawn apart
 *  from the terms ProVerif printed. */
export function nameParts (text, names) {
  const out = []
  for (const piece of String(text || '').split(/([A-Za-z_][\w′']*)/)) {
    if (!piece) continue
    out.push({ text: piece, name: names.has(piece) })
  }
  return out
}

/** A term's top-level arguments: `f(a,g(b,c))` is `f` and `[a, g(b,c)]`. */
export function splitCall (text) {
  const open = text.indexOf('(')
  if (open < 0 || !text.endsWith(')')) return { head: text, args: null }
  const args = []
  let depth = 0, from = open + 1
  for (let i = from; i < text.length - 1; i++) {
    const c = text[i]
    if (c === '(') depth++
    else if (c === ')') depth--
    else if (c === ',' && depth === 0) { args.push(text.slice(from, i)); from = i + 1 }
  }
  args.push(text.slice(from, text.length - 1))
  return { head: text.slice(0, open), args }
}

/** What the attacker holds at frame `k`: what it started with, then each
 *  value it worked out, with the frame it first had it at. */
export function knowledgeAt (script, k) {
  const out = script.initial.map(v => ({ value: v, at: 0 }))
  const seen = new Set(script.initial)
  const add = (v, at) => { if (!seen.has(v)) { seen.add(v); out.push({ value: v, at }) } }
  const n = Math.min(k, script.steps.length)
  for (let i = 0; i < n; i++) for (const v of script.steps[i].computed) add(v, i + 1)
  if (k > script.steps.length && script.outcome.kind === 'knowledge') {
    for (const v of script.outcome.computed) add(v, k)
  }
  return out
}

/** What each session has checked and recorded by frame `k`: the rows it ran,
 *  in order, each with the frame it appeared at. A step's rows ran before its
 *  message, so they are there once the step is. */
export function recordsAt (script, k) {
  const by = Object.fromEntries(script.lanes.map(l => [l.id, []]))
  const put = (r, at) => (by[r.lane] || (by[r.lane] = [])).push({ ...r, at })
  const n = Math.min(k, script.steps.length)
  for (let i = 0; i < n; i++) for (const r of script.steps[i].notes) put(r, i + 1)
  if (k > script.steps.length) for (const r of script.outcome.notes) put(r, k)
  return by
}

export const AttackPlayer = {
  props: {
    script: { type: Object, required: true },
    explanation: { type: Object, default: null },
    // Why there is no explanation, when there is none: still being written,
    // or the session that should have written it failed.
    noExplanation: { type: String, default: '' },
    replay: { type: Boolean, default: false },
    display: { type: String, default: 'long' },
    autoplay: { type: Boolean, default: true },
  },
  setup (props) {
    const stageEl = ref(null)
    const fx = ref(null)
    const width = ref(0)
    const frame = ref(0)
    const playing = ref(false)
    let timer = 0
    let raf = 0
    let observer = null
    let seen = null

    const lanes = computed(() => laneOrder(props.script.lanes))
    const nameOf = computed(() =>
      Object.fromEntries(lanes.value.map(l => [l.id, l.name])))
    const drawn = computed(() => props.script.steps.slice(0, MAX_STEPS))
    const hidden = computed(() => props.script.steps.length - drawn.value.length)
    const last = computed(() => drawn.value.length + 1)

    const gap = computed(() => Math.round(Math.max(MIN_GAP, Math.min(MAX_GAP,
      (width.value - LEFT) / lanes.value.length))))
    const W = computed(() => LEFT + gap.value * lanes.value.length)
    const at = computed(() =>
      Object.fromEntries(lanes.value.map((l, i) =>
        [l.id, LEFT + gap.value * i + gap.value / 2])))

    /** The chart top to bottom. A step's row is its arrow, preceded by the
     *  names it brings in, boxed on the lifeline of whoever made them; what
     *  the initial process made is one box before the first step. Rows are
     *  as tall as their boxes, so every position is worked out here. */
    const layout = computed(() => {
      // Each definition wrapped to the box, not cut: a name's body is the one
      // place it is written in full, so nothing of it may go missing.
      const fit = (lines, width) => {
        const room = Math.max(12, Math.floor((width - 2 * PAD) / CH))
        return lines.flatMap(d => {
          const text = defLine(d)
          const full = d.kind === 'new' ? t.value.rpMadeUp
            : `${text}\n= ${d.value}`
          const out = []
          let i = 0
          while (i < text.length) {
            const cont = out.length > 0
            let take = room - (cont ? 2 : 0)
            if (i + take < text.length) {
              // break after a comma where one falls in the second half
              const cut = text.lastIndexOf(',', i + take - 1)
              if (cut >= i + take / 2) take = cut + 1 - i
            }
            out.push({ text: text.slice(i, i + take), full, cont })
            i += take
          }
          return out
        })
      }
      let cursor = TOP
      let setup = null
      const pre = props.script.setup || []
      if (pre.length) {
        const w = W.value - LEFT - 4
        const lines = fit(pre, w)
        setup = { x: LEFT, y: cursor + 2, w, h: (lines.length + 1) * LINE + 2 * PAD, lines }
        cursor += setup.h + 10
      }
      const rows = {}
      const boxes = []
      for (const s of drawn.value) {
        // Only what has been played takes room: laying out every box from the
        // first frame leaves the chart mostly blank and turns the scroll into
        // a hunt. Rows already drawn keep their place as later ones arrive.
        if (s.n > frame.value) { rows[s.n] = cursor + ROW - 8; cursor += ROW; continue }
        const byLane = {}
        for (const d of s.defs || []) (byLane[d.lane] = byLane[d.lane] || []).push(d)
        let tall = 0
        for (const [lane, ds] of Object.entries(byLane)) {
          const x0 = at.value[lane] ?? at.value[ATTACKER]
          const want = Math.max(...ds.map(d => d.name.length + d.body.length + 3)) * CH + 2 * PAD
          const w = Math.min(want, gap.value * 1.9)
          const x = Math.max(4, Math.min(x0 - w / 2, W.value - w - 4))
          const lines = fit(ds, w)
          tall = Math.max(tall, lines.length)
          boxes.push({ n: s.n, lane, x, y: cursor + 4, w, h: lines.length * LINE + 2 * PAD, lines })
        }
        if (tall) cursor += tall * LINE + 2 * PAD + 10
        rows[s.n] = cursor + ROW - 8
        cursor += ROW
      }
      const end = frame.value >= last.value ? (props.script.outcome.defs || []) : []
      if (end.length) {
        const x0 = at.value[ATTACKER]
        const want = Math.max(...end.map(d => defLine(d).length)) * CH + 2 * PAD
        const w = Math.min(want, gap.value * 1.9)
        const x = Math.max(4, Math.min(x0 - w / 2, W.value - w - 4))
        const lines = fit(end, w)
        boxes.push({ n: last.value, lane: ATTACKER, x, y: cursor + 4, w,
                     h: lines.length * LINE + 2 * PAD, lines })
        cursor += lines.length * LINE + 2 * PAD + 10
      }
      rows.goal = cursor + ROW - 8
      return { rows, boxes, setup, height: cursor + 2 * ROW }
    })
    const H = computed(() => layout.value.height)
    /** Every stand-in name the script defines, drawn apart wherever it
     *  appears. */
    const standIns = computed(() => new Set([
      ...(props.script.setup || []),
      ...props.script.steps.flatMap(st => st.defs || []),
    ].filter(d => (d.kind || 'name') === 'name').map(d => d.name)))
    const parts = (text) => nameParts(text, standIns.value)
    const y = (n) => n >= last.value ? layout.value.rows.goal
      : (layout.value.rows[n] ?? TOP)

    const notes = computed(() => Object.fromEntries(
      ((props.explanation && props.explanation.steps) || []).map(s => [s.n, s.note])))

    /** One arrow, as the template draws it. A message a session sends itself
     *  is a loop to the right of its lifeline. */
    const arrows = computed(() => drawn.value.map(s => {
      const x1 = at.value[s.src], x2 = at.value[s.dst], yy = y(s.n)
      const self = x1 === x2
      const end = self ? x1 : x2 + (x2 > x1 ? -5 : 5)
      const room = self ? gap.value * 0.9 : Math.abs(x2 - x1) + gap.value * 0.5
      return {
        n: s.n, kind: s.kind, attacker: s.kind === 'inject' || s.kind === 'forge',
        d: self ? `M ${x1} ${yy - 5} h 34 v 10 h -32`
                : `M ${x1} ${yy} L ${end} ${yy}`,
        lx: self ? x1 + 40 : (x1 + x2) / 2,
        anchor: self ? 'start' : 'middle',
        label: clip(s.label || s.value, Math.max(8, Math.floor(room / 6.8))),
        value: (s.label && s.label !== s.value ? s.label + '\n= ' : '') + s.value, y: yy,
      }
    }))

    /** Where the goal breaks, drawn on the last row: at the session that ran
     *  the goal's event, or on the attacker's lane for what it came to know. */
    /** What a secrecy goal lost, said as whose value it was: the holder's
     *  session and the target's name there, with the value it had when that
     *  differs from the name. */
    const lost = (withRole) => {
      const o = props.script.outcome
      const sec = o.secret || {}
      if (!sec.holder) return t.value.rpObtains(o.text)
      const lane = lanes.value.find(l => l.id === o.probe_lane)
      const who = !lane ? sec.holder
        : lane.name + (withRole && lane.role ? ` (${lane.role})` : '')
      if (!sec.name) return t.value.rpObtainsHeld(who, sec.value)
      return t.value.rpObtainsOf(sec.name, who, sec.value === sec.name ? '' : sec.value)
    }
    // the caption names the session's role too; the mark on the chart has
    // one lane of room
    const obtained = computed(() => lost(true))
    const obtainedShort = computed(() => lost(false))

    /** What an authentication goal asked for beside the end that ran, said in
     *  one line: an agreement is broken by a begin that never ran, ran saying
     *  something else, or — injectively — ran once and answered twice. */
    const missed = computed(() => {
      const e = props.script.outcome.expected || {}
      if (!e.status) return ''
      const name = e.event || t.value.rpTheBegin
      const role = (e.roles || []).join(', ')
      return e.status === 'missing' ? t.value.rpBeginMissing(name, role)
        : e.status === 'reused' ? t.value.rpBeginReused(name)
        : t.value.rpBeginDiffers(name)
    })

    const goalMark = computed(() => {
      const o = props.script.outcome
      const lane = o.kind === 'event' && o.lane ? o.lane : ATTACKER
      const text = o.kind === 'knowledge' ? obtainedShort.value
        : o.kind === 'guess' ? t.value.rpGuessMark(o.text) : o.text
      const on = at.value[lane] ?? at.value[ATTACKER]
      // Written over the whole stage rather than one lane's width — what
      // broke is the one thing every reader is here for — and slid inside it
      // when the lane it belongs to sits near an edge.
      const cut = (s) => clip(s, Math.max(8, Math.floor((W.value - 40) / 7.2)))
      const lines = [cut(text)]
      if (missed.value) lines.push(cut(missed.value))
      const w = Math.min(W.value - 8,
                         Math.max(...lines.map(l => l.length)) * 7.2 + 28)
      const x = Math.max(4 + w / 2, Math.min(on, W.value - 4 - w / 2))
      return { x, y: y(last.value), w, text: lines[0], lines }
    })

    const known = computed(() => knowledgeAt(props.script, frame.value))
    const secret = computed(() => {
      const o = props.script.outcome
      return frame.value === last.value && o.kind === 'knowledge'
        ? new Set([o.text, ...o.computed]) : new Set()
    })
    const records = computed(() => recordsAt(props.script, frame.value))
    const honest = computed(() => lanes.value.filter(l => !l.attacker))

    /** A weak secret's offline test, with ProVerif's name for the guess
     *  spelled as a word. */
    const guess = computed(() => {
      const g = props.script.outcome.guess
      if (props.script.outcome.kind !== 'guess' || !g) return null
      const say = (v) => v.split(g.name).join(t.value.rpGuessWord)
      return {
        test: g.test === 'fail' ? t.value.rpGuessFails(say(g.left))
                                : `${say(g.left)} = ${say(g.right)}`,
        known: g.known,
      }
    })

    /** The goal's own line and the ones it is measured against, split into
     *  arguments so the ones that differ can be marked. */
    const verdict = computed(() => {
      const o = props.script.outcome
      if (o.kind !== 'event') return null
      const mine = splitCall(o.text)
      const diff = new Set(o.counterparts.flatMap(c => c.differ || []))
      return {
        lane: nameOf.value[o.lane] || '?',
        head: mine.head,
        args: (mine.args || []).map((a, i) => ({ a, off: diff.has(i) })),
        against: o.counterparts.map(c => {
          const theirs = splitCall(c.event)
          const off = new Set(c.differ || [])
          return { point: c.point, head: theirs.head, arity: c.differ === null,
                   args: (theirs.args || []).map((a, i) => ({ a, off: off.has(i) })) }
        }),
      }
    })

    const step = computed(() =>
      frame.value >= 1 && frame.value <= drawn.value.length
        ? drawn.value[frame.value - 1] : null)

    // ── motion ─────────────────────────────────────────────────────────
    const svgNS = 'http://www.w3.org/2000/svg'
    const make = (name, attrs, parent) => {
      const el = document.createElementNS(svgNS, name)
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v)
      parent.appendChild(el)
      return el
    }
    const still = () => {
      cancelAnimationFrame(raf)
      if (fx.value) fx.value.replaceChildren()
    }
    const animate = (ms, draw, done) => {
      const t0 = performance.now()
      const tick = (now) => {
        const p = Math.min(1, (now - t0) / ms)
        draw(p)
        if (p < 1) raf = requestAnimationFrame(tick)
        else if (done) done()
      }
      raf = requestAnimationFrame(tick)
    }
    /** Carry step `s`'s message along its arrow; an attacker's own
     *  construction flashes on its lane first. */
    function fly (s) {
      still()
      if (reducedMotion() || !fx.value) return
      const x1 = at.value[s.src], x2 = at.value[s.dst], yy = y(s.n)
      if (x1 === x2) return
      const move = () => {
        const g = make('g', { class: 'rp-token ' + s.kind }, fx.value)
        const label = token(s.label || s.value)
        const w = Math.max(38, label.length * 6.8 + 14)
        make('rect', { x: -w / 2, y: -9, width: w, height: 18, rx: 5 }, g)
        make('text', { x: 0, y: 4, 'text-anchor': 'middle' }, g).textContent = label
        animate(FLY_MS, (p) => {
          const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2
          g.setAttribute('transform', `translate(${x1 + (x2 - x1) * e},${yy})`)
        }, () => { g.remove() })
      }
      if (s.kind !== 'forge') { move(); return }
      const ring = make('circle', { class: 'rp-pulse', cx: at.value[ATTACKER], cy: yy, r: 4 }, fx.value)
      animate(PULSE_MS, (p) => {
        ring.setAttribute('r', 4 + 12 * p)
        ring.setAttribute('opacity', 1 - p)
      }, () => { ring.remove(); move() })
    }

    /** Keep the current row inside the scrolling stage. */
    function reveal () {
      const box = stageEl.value
      if (!box) return
      const row = y(Math.min(frame.value, last.value))
      const top = box.scrollTop, bottom = top + box.clientHeight
      if (row - ROW * 2 < top) box.scrollTop = Math.max(0, row - ROW * 2)
      else if (row + ROW * 2 > bottom) box.scrollTop = row + ROW * 2 - box.clientHeight
    }

    function show (k, moving) {
      frame.value = Math.max(0, Math.min(last.value, k))
      still()
      nextTick(() => {
        reveal()
        if (moving && step.value) fly(step.value)
      })
    }
    const halt = () => { clearTimeout(timer); timer = 0; playing.value = false }
    function play () {
      if (frame.value >= last.value) show(0, false)
      playing.value = true
      const tick = () => {
        if (frame.value >= last.value) { halt(); return }
        show(frame.value + 1, true)
        timer = setTimeout(tick, STEP_MS)
      }
      tick()
    }
    const toggle = () => (playing.value ? halt() : play())
    const next = () => { halt(); show(frame.value + 1, true) }
    const prev = () => { halt(); show(frame.value - 1, false) }
    const restart = () => { halt(); show(0, false) }
    const end = () => { halt(); show(last.value, false) }

    // A new script is a new attack: start it over.
    watch(() => props.script, () => { halt(); show(0, false) })

    onMounted(() => {
      observer = new ResizeObserver(() => {
        if (stageEl.value) width.value = stageEl.value.clientWidth
      })
      if (stageEl.value) {
        width.value = stageEl.value.clientWidth
        observer.observe(stageEl.value)
      }
      // Played once by itself, when it first comes into view: a player opened
      // below the fold would otherwise have finished before anyone saw it.
      if (props.autoplay && stageEl.value) {
        seen = new IntersectionObserver((entries) => {
          if (!entries.some(e => e.isIntersecting)) return
          seen.disconnect()
          seen = null
          if (!playing.value && frame.value === 0) timer = setTimeout(play, 400)
        }, { threshold: 0.3 })
        seen.observe(stageEl.value)
      }
    })
    onUnmounted(() => {
      halt()
      still()
      if (observer) observer.disconnect()
      if (seen) seen.disconnect()
    })

    const bindingsOf = (l) => l.bindings.join('\n')

    return { t, stageEl, fx, frame, playing, lanes, nameOf, drawn, hidden, last,
             W, H, at, y, TOP, LEFT, ROW, LINE, PAD, CH, layout, parts, defLine, obtained, arrows, goalMark, known, secret,
             records, honest, verdict, guess, missed, step, notes,
             toggle, next, prev, restart, end, bindingsOf, GLYPH, quoteParts }
  },
  template: `
  <div class="rp-player">
    <div class="rp-controls">
      <button class="tiny ghost" :aria-label="t.rpRestart" :title="t.rpRestart"
              @click="restart()">{{ GLYPH.restart }}</button>
      <button class="tiny ghost" :aria-label="t.rpPrev" :title="t.rpPrev"
              :disabled="frame === 0" @click="prev()">‹</button>
      <button class="tiny" :aria-label="playing ? t.rpPause : t.rpPlay"
              :title="playing ? t.rpPause : t.rpPlay"
              @click="toggle()">{{ playing ? GLYPH.pause : GLYPH.play }}</button>
      <button class="tiny ghost" :aria-label="t.rpNext" :title="t.rpNext"
              :disabled="frame === last" @click="next()">›</button>
      <button class="tiny ghost" :aria-label="t.rpEnd" :title="t.rpEnd"
              @click="end()">{{ GLYPH.end }}</button>
      <span class="num rp-count" :class="{broken: frame === last}">{{
        frame === last ? t.rpAtGoal : t.rpFrame(frame, drawn.length) }}</span>
      <span class="grow"></span>
      <span class="rp-legend">
        <span><i class="send"></i>{{ t.rpKind('send') }}</span>
        <span><i class="relay"></i>{{ t.rpKind('relay') }}</span>
        <span><i class="inject"></i>{{ t.rpKind('inject') }}</span>
        <span><i class="forge"></i>{{ t.rpKind('forge') }}</span>
        <span v-if="script.steps.some(s => s.kind === 'private')"><i class="private"></i>{{ t.rpKind('private') }}</span>
      </span>
    </div>

    <!-- The chart scrolls inside its own box, both ways: a long attack is
         taller than the panel, and many sessions are wider than it. -->
    <div class="rp-stage" ref="stageEl">
      <svg class="rp-svg" :width="W" :height="H" :viewBox="'0 0 ' + W + ' ' + H"
           role="img" :aria-label="t.rpChartLabel(drawn.length, lanes.length - 1)">
        <defs>
          <marker id="rp-arrow" class="rp-mk" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z"></path></marker>
          <marker id="rp-arrow-atk" class="rp-mk atk" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z"></path></marker>
        </defs>
        <g v-for="l in lanes" :key="l.id" class="rp-lane" :class="{atk: l.attacker}">
          <title>{{ l.attacker ? t.rpAttackerTip : (l.role + (l.bindings.length ? '\\n' + bindingsOf(l) : '')) }}</title>
          <rect :x="at[l.id] - 52" y="8" width="104" height="40" rx="5"></rect>
          <text class="rp-lname" :x="at[l.id]" y="26" text-anchor="middle">{{ l.name }}</text>
          <text class="rp-lrole" :x="at[l.id]" y="41" text-anchor="middle">{{
            l.attacker ? t.rpAttacker : (l.role || '—') }}</text>
          <line class="rp-life" :x1="at[l.id]" :x2="at[l.id]" y1="50" :y2="H - 6"></line>
        </g>
        <g v-if="layout.setup" class="rp-defs setup">
          <rect :x="layout.setup.x" :y="layout.setup.y" :width="layout.setup.w"
                :height="layout.setup.h" rx="4"></rect>
          <text class="rp-defs-head" :x="layout.setup.x + PAD + 2"
                :y="layout.setup.y + PAD + LINE - 3">{{ t.rpSetup }}</text>
          <text v-for="(l, i) in layout.setup.lines" :key="i" :x="layout.setup.x + PAD + 2 + (l.cont ? 2 * CH : 0)"
                :y="layout.setup.y + PAD + (i + 2) * LINE - 3"><title>{{ l.full }}</title><tspan
                v-for="(q, k) in parts(l.text)" :key="k" :class="{'rp-name': q.name}">{{ q.text }}</tspan></text>
        </g>
        <g v-for="b in layout.boxes" :key="b.n + ':' + b.lane" v-show="b.n <= frame"
           class="rp-defs" :class="{atk: b.lane === 'attacker', now: b.n === frame}">
          <rect :x="b.x" :y="b.y" :width="b.w" :height="b.h" rx="3"></rect>
          <text v-for="(l, i) in b.lines" :key="i" :x="b.x + PAD + (l.cont ? 2 * CH : 0)"
                :y="b.y + PAD + (i + 1) * LINE - 3"><title>{{ l.full }}</title><tspan
                v-for="(q, k) in parts(l.text)" :key="k" :class="{'rp-name': q.name}">{{ q.text }}</tspan></text>
        </g>
        <g v-for="a in arrows" :key="a.n" v-show="a.n <= frame"
           class="rp-step" :class="[a.kind, {now: a.n === frame}]">
          <title>{{ a.n + '. ' + a.value }}</title>
          <text class="rp-n" :x="LEFT / 2" :y="a.y + 4" text-anchor="middle">{{ a.n }}</text>
          <path class="rp-line" :d="a.d"
                :marker-end="a.attacker ? 'url(#rp-arrow-atk)' : 'url(#rp-arrow)'"></path>
          <text class="rp-label" :x="a.lx" :y="a.y - 7" :text-anchor="a.anchor"><tspan
            v-for="(q, k) in parts(a.label)" :key="k" :class="{'rp-name': q.name}">{{ q.text }}</tspan></text>
        </g>
        <g v-if="frame === last" class="rp-goal">
          <rect :x="goalMark.x - goalMark.w / 2" :y="goalMark.y - 12"
                :width="goalMark.w" :height="goalMark.lines.length * 17 + 7" rx="5"></rect>
          <text v-for="(l, i) in goalMark.lines" :key="i" :x="goalMark.x"
                :y="goalMark.y + 4 + i * 17" text-anchor="middle"
                :class="{'rp-goal-miss': i > 0}">{{ l }}</text>
        </g>
        <g ref="fx"></g>
      </svg>
    </div>
    <p v-if="hidden" class="dim sm rp-cut">{{ t.rpNotDrawn(hidden) }}</p>

    <!-- What the current frame says, in words, then the message itself. -->
    <div class="rp-caption" aria-live="polite">
      <template v-if="frame === 0">
        <p v-if="explanation" class="rp-say"><template v-for="(q, k) in quoteParts(explanation.opening)"
          :key="k"><code v-if="q.code">{{ q.text }}</code><template v-else>{{ q.text }}</template></template></p>
        <p v-else class="rp-say dim">{{ noExplanation || t.rpPressPlay }}</p>
      </template>
      <template v-else-if="step">
        <p class="rp-say"><b class="num">{{ step.n }}.</b>
          <span class="mono rp-who">{{ nameOf[step.src] }} → {{ nameOf[step.dst] }}</span>
          <span class="rp-kind" :class="step.kind">{{ t.rpKind(step.kind) }}</span>
          <template v-if="notes[step.n]"><template v-for="(q, k) in quoteParts(notes[step.n])"
            :key="k"><code v-if="q.code">{{ q.text }}</code><template v-else>{{ q.text }}</template></template></template>
          <template v-else-if="!explanation">{{ noExplanation }}</template></p>
        <p class="mono rp-value"><span v-for="(q, k) in parts(step.label || step.value)" :key="k"
          :class="{'rp-name': q.name}">{{ q.text }}</span></p>
        <p v-for="d in step.defs || []" :key="d.kind + d.name" class="mono rp-def"><span
          v-for="(q, k) in parts(defLine(d))" :key="k" :class="{'rp-name': q.name}">{{ q.text }}</span></p>
        <details v-if="step.label && step.label !== step.value" class="rp-how">
          <summary>{{ t.rpWrittenOut }}</summary>
          <p class="mono">{{ step.value }}</p>
        </details>
        <p v-if="step.computed.length" class="rp-sub">{{ t.rpWorkedOut }}
          <span v-for="v in step.computed" :key="v" class="rp-chip mono new">{{ v }}</span></p>
        <details v-if="step.recipe" class="rp-how">
          <summary>{{ t.rpHowBuilt }}</summary>
          <p class="mono">{{ step.recipe }}</p>
          <p v-for="r in step.reads" :key="r" class="mono dim">{{ r }}</p>
        </details>
      </template>
      <template v-else>
        <p class="rp-say rp-broken">{{ t.rpGoalBroken }}
          <span class="mono">{{ script.outcome.kind === 'knowledge'
            ? obtained
            : script.outcome.kind === 'guess' ? t.rpGuesses(script.outcome.text)
            : script.outcome.text }}</span></p>
        <template v-if="guess">
          <p class="rp-sub">{{ t.rpGuessTest }}</p>
          <p class="mono rp-value">{{ guess.test }}</p>
          <p v-for="k in guess.known" :key="k" class="mono rp-value dim">{{ t.rpGuessKnowing }} {{ k }}</p>
          <p class="rp-sub">{{ t.rpGuessTells }}</p>
        </template>
        <p v-if="missed" class="rp-sub rp-missed">{{ missed }}</p>
        <p v-if="script.outcome.expected && script.outcome.expected.status" class="rp-sub dim">{{
          t.rpAuthRule(script.outcome.expected.injective) }}</p>
        <p v-if="script.outcome.probe" class="rp-sub">{{
          t.rpProbe(script.outcome.probe, nameOf[script.outcome.probe_lane] || '') }}</p>
        <p v-if="replay" class="rp-sub">{{ t.rpReplay }}</p>
        <p v-if="explanation" class="rp-say"><template v-for="(q, k) in quoteParts(explanation.conclusion)"
          :key="k"><code v-if="q.code">{{ q.text }}</code><template v-else>{{ q.text }}</template></template></p>
        <p v-else-if="noExplanation" class="rp-say dim">{{ noExplanation }}</p>
      </template>
    </div>

    <div class="rp-two">
      <div class="rp-box">
        <p class="rp-lbl">{{ t.rpKnows }}</p>
        <span v-for="k in known" :key="k.value" class="rp-chip mono"
              :class="{start: k.at === 0, new: k.at > 0 && k.at === frame,
                       got: k.at > 0 && k.at !== frame, secret: secret.has(k.value)}"
              :title="k.at === 0 ? t.rpFromStart : t.rpSince(k.at)">{{ k.value }}</span>
      </div>
      <div class="rp-box">
        <p class="rp-lbl">{{ t.rpSessions }} · {{ t.rpSessionsSub }}</p>
        <div v-for="l in honest" :key="l.id" class="rp-sess">
          <div class="rp-sh"><b class="mono">{{ l.name }}</b>
            <span class="mono dim">{{ l.role }}</span>
            <span v-if="l.bindings.length" class="mono dim rp-bind">{{ l.bindings.join(' · ') }}</span></div>
          <div v-for="(r, i) in records[l.id] || []" :key="i" class="mono rp-row"
               :class="{now: r.at === frame, event: r.word === 'event'}">
            <span class="dim">{{ '{' + r.point + '}' }}</span> {{ r.word }} {{ r.text }}</div>
          <div v-if="!(records[l.id] || []).length" class="dim rp-row">{{ t.rpNothingYet }}</div>
        </div>
        <div v-if="verdict && frame === last" class="rp-verdict">
          <div class="mono"><b>{{ verdict.lane }}</b> {{ verdict.head }}(<template
            v-for="(x, i) in verdict.args" :key="i"><span :class="{off: x.off}">{{ x.a }}</span><template
            v-if="i < verdict.args.length - 1">, </template></template>)</div>
          <div v-for="(c, j) in verdict.against" :key="j" class="mono dim">
            {{ t.rpAgainst(c.point) }} {{ c.head }}(<template
            v-for="(x, i) in c.args" :key="i"><span :class="{off: x.off}">{{ x.a }}</span><template
            v-if="i < c.args.length - 1">, </template></template>)<template
            v-if="c.arity"> · {{ t.rpArity }}</template></div>
          <div v-if="!verdict.against.length" class="dim">{{ t.rpNoBegin }}</div>
        </div>
      </div>
    </div>
    <p v-if="display !== 'long'" class="dim sm">{{ t.rpShortDisplay }}</p>
    <details v-if="script.omitted.length" class="rp-omitted">
      <summary class="dim sm">{{ t.rpOmitted(script.omitted.length) }}</summary>
      <p v-for="(o, i) in script.omitted" :key="i" class="mono dim sm">
        {{ o.value || o.role || o.lane }} — {{ t.rpWhyOmitted(o.why) }}</p>
    </details>
  </div>`,
}
