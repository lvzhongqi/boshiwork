/** Which lines one construction step introduced, as line *content*.
 *
 *  The panes are two independent scrolls of the whole file rather than an
 *  aligned diff, so what a step did is carried as a set of lines to mark.
 *  Matching on content instead of line numbers keeps a mark valid after
 *  downstream steps have pushed those lines elsewhere in the file.
 */

const norm = (l) => l.trim()

/** Lines present in `after` that are not in `before`, as a Set of trimmed
 *  strings. Multiplicity is ignored: a line repeated in both stays unmarked. */
export function introduced (before, after) {
  const was = new Map()
  for (const l of String(before ?? '').split('\n')) {
    const k = norm(l)
    if (k) was.set(k, (was.get(k) || 0) + 1)
  }
  const out = new Set()
  for (const l of String(after ?? '').split('\n')) {
    const k = norm(l)
    if (!k) continue
    if (was.get(k)) was.set(k, was.get(k) - 1)
    else out.add(k)
  }
  return out
}

/** Lines `before` had that `after` does not; shown in the left pane. */
export function removed (before, after) {
  return introduced(after, before)
}

/** The two files of one construction step, aligned into a single column of
 *  `ctx` / `add` / `del` rows. Two neighbouring steps are the same file one
 *  step apart, so they do align row for row.
 *
 *  A plain LCS over trimmed lines; the quadratic table is milliseconds on
 *  models of a few hundred lines.
 */
export function lineDiff (before, after) {
  const A = String(before ?? '').split('\n')
  const B = String(after ?? '').split('\n')
  const n = A.length, m = B.length
  // dp[i][j] = length of the longest common subsequence of A[i:] and B[j:]
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = norm(A[i]) === norm(B[j])
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out = []
  let i = 0, j = 0
  while (i < n && j < m) {
    if (norm(A[i]) === norm(B[j])) {
      out.push({ kind: 'ctx', text: B[j], n: j + 1 }); i++; j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      // Deletions before insertions at the same point, so the outgoing line
      // reads above the line that replaced it.
      out.push({ kind: 'del', text: A[i], n: null }); i++
    } else {
      out.push({ kind: 'add', text: B[j], n: j + 1 }); j++
    }
  }
  while (i < n) { out.push({ kind: 'del', text: A[i], n: null }); i++ }
  while (j < m) { out.push({ kind: 'add', text: B[j], n: j + 1 }); j++ }
  return out
}

/** The code a review finding quotes, as exact strings to mark.
 *
 *  Backticked spans only: the prose is model output and carries no line
 *  numbers, but what it backticks is copied verbatim off the file, so plain
 *  substring matching marks exactly that and marks nothing when it misses.
 */
export function quoted (finding) {
  if (!finding) return []
  // `why` is the one prose field a finding carries (services/events/interact
  // FindingRecorded); nothing else on it quotes code.
  const text = finding.why || ''
  const out = new Set()
  for (const m of text.matchAll(/`([^`\n]{4,120})`/g)) out.add(m[1].trim())
  return [...out]
}

/** Does this line carry any of the quoted spans? */
export function hasQuote (line, spans) {
  if (!line) return false
  return spans.some(q => line.includes(q))
}
