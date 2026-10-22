import { lines } from './i18n.js'

// How an event reads on the feed. The sentences live in i18n.js, one table per
// language; this module decides the address, the clock and which words get
// coloured.

const shortNode = (ev) => {
  const n = ev.unit || ev.node || ''
  return ev.scenario ? n.replace(`:${ev.scenario}`, '') : n
}

export function line (ev) {
  const fn = lines.value[ev.t]
  // An unknown type still shows: the raw type is more use than a blank row.
  return fn ? fn(ev.data || {}, ev) : `${ev.t} ${JSON.stringify(ev.data || {})}`
}

// The words a reader scans a feed for, in both languages, since the ledger is
// one stream. Three families are kept apart: a verdict is what the analysis
// answered (`false` is a finding), a fault is the machinery breaking, and a
// check saying no is neither — the model goes round again. Red is spent on
// faults alone.
//
// Order matters: `did not pass` is tried before the bare words, and the verdict
// words are anchored on word boundaries so `failed` never matches the `false`
// rule. `未通过` contains `通过`, so the Chinese rule carries a lookbehind.
const MARK = [
  // a check saying no — amber, tried first so `passed` cannot claim it
  [/\b(did not pass|not accepted)\b/gi, 'warn'],
  [/(未通过|未过|被驳回)/g, 'warn'],
  // faults
  [/\bfailed\b/gi, 'fault'],
  [/失败/g, 'fault'],
  // verdicts — answers, not failures
  [/\bfalse\b/gi, 'false'],
  [/\b(true|passed|ok)\b/gi, 'true'],
  [/(?<!未)(通过|完成)/g, 'true'],
  // the solver declining to answer, and the run working around something
  [/\b(unknown|timeout|rejected|repair|warning)\b/gi, 'warn'],
  [/(超时|修复|中断|不一致|警告)/g, 'warn'],
]

const ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;' }

/** The same line with the scanned words wrapped, so CSS can colour them in
 *  place. Escaped first: event text is model output and file paths. */
export function marked (ev) {
  let s = line(ev).replace(/[&<>]/g, c => ESCAPE[c])
  for (const [re, cls] of MARK) s = s.replace(re, m => `<em class="${cls}">${m}</em>`)
  return s
}

// The address a line belongs to, as scenario/step.
export const where = (ev) =>
  [ev.scenario, shortNode(ev)].filter(Boolean).join('/') || ev.node || ''

// The two halves of an ISO stamp, each offered where it is the whole answer:
// the run list asks which day, the feed asks when inside one run.
export const day = (ts) => (ts || '').slice(0, 10)
export const clock = (ts) => (ts || '').slice(11, 19)

export const tokens = (n) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n ?? 0)
