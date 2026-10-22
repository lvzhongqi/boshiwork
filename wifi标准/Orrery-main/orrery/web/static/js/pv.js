/** ProVerif syntax highlighting for the console's code views.
 *
 *  The word lists come from the ProVerif 2.05 manual, "Syntax of the input
 *  language"; anything off them renders as a plain identifier. Highlighting is
 *  per line and stateless, so a block comment spanning several lines is shaded
 *  only on the lines carrying its delimiters.
 */

// Reserved words, declaration and process syntax in one set.
const KEYWORDS = new Set([
  'among', 'axiom', 'channel', 'choice', 'clauses', 'const', 'def', 'diff',
  'do', 'elimtrue', 'else', 'equation', 'equivalence', 'event', 'expand',
  'fail', 'for', 'forall', 'foreach', 'free', 'fun', 'get', 'if',
  'implementation', 'in', 'inj-event', 'insert', 'lemma', 'let', 'letfun',
  'letproba', 'new', 'noninterf', 'noselect', 'not', 'nounif', 'or',
  'otherwise', 'out', 'param', 'phase', 'pred', 'proba', 'process', 'proof',
  'public_vars', 'putbegin', 'query', 'reduc', 'restriction', 'secret',
  'select', 'set', 'suchthat', 'sync', 'table', 'then', 'type', 'weaksecret',
  'yield',
])

// Built-in types plus the two constants, coloured apart from keywords.
const TYPES = new Set(['bitstring', 'bool', 'channel', 'nat', 'true', 'false'])

// Declaration attributes, which only ever appear inside brackets.
const ATTRS = new Set(['private', 'data', 'typeConverter', 'memberOptim',
                       'block', 'precise'])

const esc = (s) => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))

/** One line of ProVerif as escaped HTML; null or undefined gives ''. */
export function highlight (line) {
  if (line == null) return ''
  const src = String(line)
  // A whole-line comment short-circuits the rest: its contents are prose, and
  // tokenising prose produces false keywords.
  const only = src.match(/^(\s*)\(\*(.*)\*\)\s*$/)
  if (only) return `${only[1]}<span class="pv-c">(*${esc(only[2])}*)</span>`

  let out = ''
  // Identifiers may carry - and ' (inj-event, X'), so they are one token.
  // The lone `"` at the end: an unpaired quote on a line matches nothing
  // else here, and matchAll skips what it cannot match, which dropped the
  // character from the rendering.
  const re = /(\(\*|\*\)|[A-Za-z_][A-Za-z0-9_'-]*|"[^"]*"|\d+|==>|<->|&&|\|\||[^\sA-Za-z0-9_"]+|\s+|")/g
  let inComment = false
  for (const [tok] of src.matchAll(re)) {
    if (tok === '(*') { inComment = true; out += '<span class="pv-c">(*'; continue }
    if (tok === '*)' && inComment) { inComment = false; out += '*)</span>'; continue }
    if (inComment) { out += esc(tok); continue }
    if (/^\s+$/.test(tok)) { out += tok; continue }
    if (KEYWORDS.has(tok)) out += `<span class="pv-k">${esc(tok)}</span>`
    else if (TYPES.has(tok)) out += `<span class="pv-t">${esc(tok)}</span>`
    else if (ATTRS.has(tok)) out += `<span class="pv-a">${esc(tok)}</span>`
    else if (/^"/.test(tok)) out += `<span class="pv-s">${esc(tok)}</span>`
    else if (/^\d+$/.test(tok)) out += `<span class="pv-n">${esc(tok)}</span>`
    else if (/^[^\sA-Za-z0-9_"]+$/.test(tok)) out += `<span class="pv-p">${esc(tok)}</span>`
    else out += esc(tok)
  }
  if (inComment) out += '</span>'
  return out
}
