"""Make the run tree publishable: redact what is ours to hide, replace what is
not ours to give.

    python3 release/usenix/latest_3_to_remove_sensitive_open.py \
        a_experiments_3/experiments a_experiments_open/experiments \
        --verify-against $LIB

Second of three steps; both published trees descend from this one, so a rule
applied here cannot be missing from either. Privacy is ours: credentials, the
account name, the machine's paths. Copyright is not: three publishers forbid
redistributing the specifications some runs quote, so that text is replaced
rather than deleted and the run stays whole. Corpus prose a run copied while
the corpus was still Chinese is refreshed from the corpus's own current
English. Nothing is removed here; deciding what a tree keeps is step 3's job.
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# ── Which specifications may not be republished ──────────────────────────────

#: Corpus prefixes whose documents may not be redistributed, and why. The
#: reasons are the publishers' own words, so whoever judges a new source has
#: the test rather than the verdict.
RESTRICTED = {
    "ISO/": "ISO/IEC 9798 and 11770 are sold; their terms forbid "
            "redistributing the documents or a normalised copy of them",
    "3gpp/": "3GPP: you may not reproduce any part of a Technical "
             "Specification without permission from 3GPP",
    "informal/FIDO": "FIDO Alliance grants no right to prepare derivative "
                     "works, and the corpus holds a Markdown conversion",
}

#: Sources with no redistribution bar, recorded so the decision is visible
#: rather than implied by absence.
UNRESTRICTED = {
    "academic/": "written for the corpus from the original publications",
    "rfc/": "distribution of IETF RFCs and Internet-Drafts is unlimited",
    "informal/Signal": "PQXDH is placed in the public domain (§5, IPR)",
}

#: The corpus repository's directory name. Paths may be anonymised down to this
#: and no further: it is the anchor ``sync_data.py::local_gt`` uses to recover
#: which unit a run analysed, and a run it cannot identify is dropped from the
#: paper's tables silently.
CORPUS_NAME = "VerdictBench"

_LIB = re.compile(r"(?:^|/)%s/(.+)$" % re.escape(CORPUS_NAME))


# ── Privacy ──────────────────────────────────────────────────────────────────

#: Keys whose whole name says "credential". Narrow, and it has to stay narrow:
#: this is a cryptographic-protocol corpus, where ``token``, ``secret``,
#: ``client_secret`` and ``Authorization`` are protocol vocabulary. Widening it
#: rewrites ProVerif declarations such as ``client_secret: key;`` and the models
#: stop parsing. A credential under some other key is caught by ``_TOKENISH``,
#: which reads the value's shape instead of its name.
CREDENTIAL_KEYS = ("api_key", "apikey", "api-key")
_KEY_FIELD = re.compile(
    r"(?<![A-Za-z0-9_\-])"
    r"([\"']?(?:" + "|".join(CREDENTIAL_KEYS) + r")[\"']?\s*[:=]\s*)"
    r"([\"']?)(?!<redacted>)([^\s\"',}\]]+)\2",
    re.IGNORECASE,
)
#: Credentials by shape, whatever key they hang under. The word boundary keeps
#: it off the model's reasoning signatures, which are long base64 blobs that
#: contain ``sk-`` by chance.
_TOKENISH = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}|\bAIza[A-Za-z0-9_\-]{30,}")

#: 身份词表，和 anonymous_release.py 的门禁读同一份 identity.toml。补的是形状
#: 认不出来的那一半：``_TOKENISH`` 认凭据的形状，``_HOME`` 认家目录的形状，而
#: 「某个人叫什么」没有形状，只能靠名单。
_IDENTITY = [
    re.compile(p, re.I)
    for p in tomllib.loads(
        (Path(__file__).resolve().parent / "identity.toml").read_text("utf-8")
    )["sensitive"]
]
#: Home directories, the one identifying thing that really is everywhere. What
#: lies below the home directory stays: it points at no one.
_HOME = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")
#: Private and CGNAT ranges. Public addresses are content, not identity.
_PRIVATE_IP = re.compile(
    r"\b(?:10(?:\.\d{1,3}){3}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})\b"
)
#: Links into the operator's own account at a model provider. Neither a
#: credential nor a path, so no other rule reaches them, yet they say whose
#: account this was: a run that exhausted its credits recorded the provider's
#: reply verbatim, billing link and all. Anchored on the account-page part of
#: the path, so the provider's docs and API endpoints stay as content.
_ACCOUNT_URL = re.compile(
    r"https?://[A-Za-z0-9.-]+/[^\s\"']*"
    r"(?:billing|settings/organization|account/api-keys)[^\s\"']*")

#: Email addresses have a shape but are not rewritten: nearly all are content
#: (RFC authors, test accounts the model invented). They are printed for a
#: human to look at instead.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")


@dataclass
class Scrubber:
    """Replace identifying text, and say what it did not manage to.

    Order matters: ``literals`` run first and longest-first, or an artefact root
    under a home directory is eaten halfway by the home-directory rule. Every
    rule but the paths is guarded by a substring test for whether it could match
    at all, because the tree is hundreds of megabytes and a regular expression
    that cannot match still has to scan.
    """

    literals: dict[str, str] = field(default_factory=dict)

    def __call__(self, text: str) -> str:
        for old in sorted(self.literals, key=len, reverse=True):
            text = text.replace(old, self.literals[old])
        if "/home/" in text or "/Users/" in text:
            text = _HOME.sub("<HOME>", text)
        low = None
        if any(k in (low := text.lower()) for k in CREDENTIAL_KEYS):
            text = _KEY_FIELD.sub(r"\1\2<redacted>\2", text)
        if "sk-" in text or "AIza" in text:
            text = _TOKENISH.sub("<redacted>", text)
        if "10." in text or "192.168" in text or "172." in text \
                or "100." in text:
            text = _PRIVATE_IP.sub("<HOST>", text)
        if "billing" in text or "settings/organization" in text \
                or "account/api-keys" in text:
            text = _ACCOUNT_URL.sub("<account page>", text)
        return text

    def residue(self, text: str) -> list[str]:
        """What should have gone and is still here, as one line per hit.

        The rules are the ones ``__call__`` applies, so this is normally empty;
        what sets it off is a write path that skipped redaction. Checked on
        every file this script writes rather than trusted.
        """
        found = [f"literal {old!r}" for old in self.literals if old in text]
        if ("sk-" in text or "AIza" in text) and (m := _TOKENISH.search(text)):
            found.append(f"credential-shaped {m.group()[:16]}…")
        if ("/home/" in text or "/Users/" in text) and (m := _HOME.search(text)):
            found.append(f"home directory {m.group()}")
        if m := _PRIVATE_IP.search(text):
            found.append(f"private address {m.group()}")
        if m := _ACCOUNT_URL.search(text):
            found.append(f"provider account link {m.group()[:40]}…")
        for rx in _IDENTITY:
            if m := rx.search(text):
                found.append(f"identity term {m.group()!r}")
                break
        return found


def build_scrubber(pairs: list[str], root: Path) -> Scrubber:
    """A scrubber built from ``--scrub OLD=NEW`` pairs plus ``root``'s path.

    Raises SystemExit on a malformed pair, and on any pair that would erase
    ``CORPUS_NAME``: ``run.json``'s ground truth is the only thing telling the
    paper's script which unit a run analysed.
    """
    literals = {str(root): "<ARTIFACT_ROOT>"}
    for pair in pairs:
        if pair.count("=") != 1 or pair.startswith("=") or pair.endswith("="):
            raise SystemExit(f"--scrub takes OLD=NEW, got {pair!r}")
        old, new = pair.split("=")
        if CORPUS_NAME in old and CORPUS_NAME not in new:
            raise SystemExit(
                f"--scrub {pair!r} would erase the corpus name "
                f"{CORPUS_NAME!r} from paths.\n"
                f"  run.json's ground truth is how tools/sync_data.py "
                f"identifies which unit a run analysed.\n"
                f"  Erase it and the paper's tables cannot be reproduced from "
                f"this artefact. The account\n"
                f"  name is already handled by the home-directory rule; drop "
                f"this --scrub.")
        literals[old] = new
    return Scrubber(literals)


# ── Copyright ────────────────────────────────────────────────────────────────

#: The marker a withheld passage leaves behind. One string, greppable, the same
#: in every file and every format, so a reader never has to tell a redaction
#: apart from a truncation or a bug.
WITHHELD_TAG = "[withheld: third-party specification text]"

#: Files whose shape is the artefact. A ledger, a verdict, an extracted model:
#: something reads these back, so replacing one with prose destroys it rather
#: than redacting it. Their quoted sentences go where they stand
#: (``sweep_quotations``) and the file stays loadable.
STRUCTURED = (".json", ".jsonl")

#: A restricted run's prose carriers, replaced whole whether or not anything
#: matched. Matching cannot decide this: these files hold previews of the
#: document rather than the document — ``events.jsonl`` caps a tool result at
#: 120 characters in ``data.result_digest`` and ``work.md`` renders the same
#: digests — so a sentence arrives with both ends cut off and a literal
#: replacement finds nothing to replace. The cost is that these runs cannot be
#: played back and their logs cannot be read; their models, verdicts and
#: structured results stay. ``reply.md`` is the one-shot baseline's model reply.
PROSE_WHOLE = ("quotes.md", "run.log", "work.md", "notes.md", "reply.md")

#: The same policy for the carriers something reads back. A ledger that became
#: a paragraph is not a redacted run, so their prose is blanked value by value
#: and the shape stays.
PROSE_STRUCTURED = ("transcript.jsonl", "events.jsonl",
                    "facts.jsonl", "gaps.jsonl")

#: How long a string value must be to count as prose rather than a path, an id,
#: a node name or an enum. Paired with a three-space floor, because the values
#: that must survive are single tokens however long: a scenario path runs to
#: eighty characters with no space in it, and ``open_to_thin.py`` reads it back
#: to pair a ledger with its transcript.
PROSE_FLOOR = 40


def _is_prose(s: str) -> bool:
    return len(s) >= PROSE_FLOOR and s.count(" ") >= 3


def _blank_tree(node):
    """Every prose string under ``node``, replaced by the tag."""
    if isinstance(node, str):
        return WITHHELD_TAG if _is_prose(node) else node
    if isinstance(node, list):
        return [_blank_tree(v) for v in node]
    if isinstance(node, dict):
        return {k: _blank_tree(v) for k, v in node.items()}
    return node


def blank_prose_values(text: str, suffix: str) -> str:
    """A structured file with its prose gone and its shape intact.

    ``suffix`` picks JSON or JSON Lines. Keys, numbers, timestamps, ids and
    every short or unspaced value stay, so the file still loads and the run
    still reads as a run: which sessions ran, in what order, how many rounds
    each took. Only the words go.
    """
    if suffix == ".jsonl":
        out = [line if not line.strip()
               else json.dumps(_blank_tree(json.loads(line)),
                               ensure_ascii=False)
               for line in text.splitlines()]
        return "\n".join(out) + ("\n" if text.endswith("\n") else "")
    return json.dumps(_blank_tree(json.loads(text)),
                      ensure_ascii=False, indent=2)


def substitute(rel: Path, text: str, unit: str | None, why: str,
               probe: list[str] | None = None,
               where: str | None = None) -> str | None:
    """This file's stand-in, or None when it keeps its text.

    Called only for a run whose specification is restricted, and split by what
    the file is rather than what it was caught holding: prose goes whole,
    ``PROSE_STRUCTURED`` is blanked value by value, everything else structured
    comes back as None for the caller to sweep in place, and ``.pv`` and solver
    output stay. ``where`` is ``source_home``'s answer, the unit whose
    ``source/`` actually holds the document.
    """
    name = rel.name
    if (name.endswith("prompt.md") or name.endswith("checks.md")
            or name in PROSE_WHOLE):
        return withheld_note(unit, why, name, where)
    if name in PROSE_STRUCTURED:
        # Prose out, shape kept. See PROSE_STRUCTURED.
        return blank_prose_values(text, rel.suffix)
    if rel.suffix in STRUCTURED:
        # A verdict, a result, an extracted model's own JSON: kept, and swept
        # in place by the caller. See STRUCTURED.
        return None
    # Any other file of a restricted run: replaced whole if it quotes.
    body, blanked = blank_quoting_text(text, probe or [], unit, why, where)
    return body if blanked else None


#: What stands where a provider's reasoning resume token stood. Greppable, and
#: it keeps the block, so a reader still sees that the model reasoned there,
#: how many times and in what order.
DROPPED_SIGNATURE = "<dropped: provider reasoning resume token>"


#: The same field seen as text, for the one line that will not parse. Runs to
#: the closing quote or to the end of the line, so a truncated value goes too.
_ENCRYPTED_FIELD = re.compile(r'"encrypted_content"\s*:\s*"[^"\\]*(?:\\.[^"\\]*)*"?')


def drop_signatures(text: str) -> tuple[str, int]:
    """Empty every ``thinking_blocks[].encrypted_content``; return text and count.

    These are the provider's opaque resume signatures, multi-kilobyte base64url
    that nothing reading a published tree reads. Emptying them here rather than
    in step 3 keeps the identity gate strict: base64url spells with ``-``, so
    such a blob holds ``sk-`` plus sixteen alphanumerics often enough by chance
    to fire ``identity.toml``'s patterns. The cost is that a restored session
    can be read and replayed but no longer continued against the API.
    """
    if '"encrypted_content"' not in text:
        return text, 0
    out, dropped = [], 0
    for line in text.splitlines():
        if '"encrypted_content"' not in line:
            out.append(line)
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # A run killed mid-write leaves a torn tail. The line stays -- this
            # script does not decide what a tree keeps -- but half a ciphertext
            # trips the identity gate like a whole one, so the field goes as
            # text, there being no object to edit.
            fixed, n = _ENCRYPTED_FIELD.subn(
                f'"encrypted_content": "{DROPPED_SIGNATURE}"', line)
            out.append(fixed)
            dropped += n
            continue
        for block in row.get("thinking_blocks") or []:
            if isinstance(block, dict) and block.get("encrypted_content"):
                block["encrypted_content"] = DROPPED_SIGNATURE
                dropped += 1
        out.append(json.dumps(row, ensure_ascii=False))
    return "".join(l + "\n" for l in out), dropped


def quoted(text: str, probe: list[str]) -> list[str]:
    """Which of ``probe``'s sentences stand in this text, longest first.

    Containment, not chunk equality: a clause usually arrives inside a JSON
    string with the model's own words on both sides, so chunk comparison misses
    it. Longest first, because ``sweep_quotations`` replaces in this order and a
    short sentence can be a substring of a longer one. The caller keeps the cost
    down by scoping ``probe`` to the standard the run read; the ``any`` gate
    does the rest, most files holding nothing from it.
    """
    if not any(s in text for s in probe):
        return []
    return sorted((s for s in probe if s in text), key=len, reverse=True)


def sweep_quotations(text: str, probe: list[str],
                     owner: dict[str, str]) -> tuple[str, int]:
    """Replace each quoted sentence of a restricted document where it stands.

    The fine-grained level, for a document arriving a sentence at a time inside
    the model's own reply. Only the quoted span goes, so the reasoning around it
    survives and the console can still play the reply back. ``owner`` maps each
    probe sentence to the unit whose ``source/`` holds it, and names it in the
    stand-in. Returns the text and how many sentences were replaced.
    """
    hits = quoted(text, probe)
    if not hits:
        return text, 0
    for line in hits:
        text = text.replace(
            line,
            f"{WITHHELD_TAG} (one sentence quoted from {owner[line]} "
            f"stood here and is withheld for copyright reasons: that "
            f"specification may not be redistributed. The surrounding "
            f"reasoning is the run's own and is unchanged.)")
    return text, len(hits)


def blank_quoting_text(text: str, probe: list[str], unit: str | None,
                       why: str, where: str | None = None) -> tuple[str, bool]:
    """Replace a whole passage that quotes a restricted document.

    Returns the text and whether anything was replaced. The stand-in is padded
    to about the length it replaces by repeating one line, because the console
    streams a reply back over the time the original call took and a passage
    shrunk to one sentence would play as a flash and a stall. Each repeated line
    restates the reason, the document and the route back, for a reader landing
    in the middle of the padding.
    """
    if not quoted(text, probe):
        return text, False
    what = unit or "a third-party specification"
    route = f"`{where}/source/README.md`" if where else "the corpus"
    head = (f"{WITHHELD_TAG}\n\n"
            f"This passage is withheld for copyright reasons. It is not "
            f"missing, truncated or broken: the words that stood here were "
            f"quoted from {what}, a third-party specification whose licence "
            f"forbids redistributing it — {why} — so the passage quoting it "
            f"cannot ship with this artefact.\n\n"
            f"Nothing else was removed. Everything the run produced — its "
            f"prompts' structure, its models, its artefacts and its verdicts — "
            f"is here in full, and so is the pipeline that produced them.\n\n"
            f"To read what stood here, obtain the document from its "
            f"publisher: {route} records "
            f"this document's catalogue entry, its edition and the retrieval "
            f"route, and the preprocessing in this repository turns that "
            f"document back into the exact bytes this passage held.\n\n")
    line = (f"{WITHHELD_TAG} Withheld for copyright reasons: the text here "
            f"was quoted from {what}, which may not be redistributed. See the "
            f"note above for how to obtain it. (This line repeats only to "
            f"keep the passage its original length, so playback keeps the "
            f"run's timing.)\n")
    if len(head) >= len(text):
        return head, True
    return head + line * (1 + (len(text) - len(head)) // len(line)), True


def withheld_note(unit: str | None, why: str, what: str,
                  where: str | None = None) -> str:
    """The note that stands where a document was.

    ``what`` is the file's name and picks the opening sentence; ``unit`` and
    ``why`` name the specification and its licence terms. Its first line of
    prose says the emptiness is deliberate, so a reviewer can tell a licence
    decision from a packaging bug. ``where`` must be ``source_home``'s answer,
    not the analysed unit, whose own path resolves to nothing.
    """
    where = f"{where}/source/README.md" if where else "the corpus"
    subject = {"quotes.md": "This file quoted the protocol document",
               "run.log": "This log echoed the prompts, which carried the "
                          "protocol document"}.get(
        what, "The prompt recorded here carried the protocol document in "
              "full")
    return (
        f"{WITHHELD_TAG}\n"
        "\n"
        "# Withheld for copyright reasons: third-party specification text\n"
        "\n"
        "This file is empty on purpose. It was not lost, truncated or\n"
        "broken by the packaging.\n"
        "\n"
        f"{subject}, which is {unit or 'a third-party specification'}. That\n"
        "document's licence forbids redistributing it, so it cannot ship\n"
        f"with this artefact: {why}.\n"
        "\n"
        "To read what stood here, obtain the document from its publisher.\n"
        f"`{where}` records this document's catalogue entry, its edition and\n"
        "the retrieval route, and the preprocessing in this repository turns\n"
        "that document back into the exact bytes this file held.\n"
        "\n"
        "Everything the run produced is here unchanged: its replies, its\n"
        "artefacts and its verdicts. Only the specification's own words are\n"
        "gone.\n"
    )


# ── Which unit a run analysed ────────────────────────────────────────────────

def unit_of(run_dir: Path) -> str | None:
    """The corpus unit this run analysed, relative to the corpus."""
    meta_path = run_dir / "run.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    got = (meta.get("ground_truth") or meta.get("protocol_dir") or "").rstrip("/")
    sub = meta.get("subprotocol")
    if sub and not got.endswith(f"/subprotocols/{sub}"):
        got = f"{got}/subprotocols/{sub}"
    m = _LIB.search(got)
    return m.group(1) if m else None


def restriction(unit: str | None) -> str | None:
    """Why this unit's document may not be republished, or None if it may."""
    if unit is None:
        # A run that does not say which unit it analysed counts as restricted:
        # the alternative is publishing a document on a missing field.
        return "the run records no corpus unit, so its document is unknown"
    for prefix, why in RESTRICTED.items():
        if unit == prefix.rstrip("/") or unit.startswith(prefix):
            return why
    return None


# ── Language ─────────────────────────────────────────────────────────────────

#: Han characters. A run that copied corpus prose while the corpus was still
#: Chinese carries text the corpus no longer holds, which leaves the artefact
#: disagreeing with its own source. Written as escapes so this file stays ASCII
#: and grepping the tree for Han does not report the rule that takes it out.
_CJK = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

#: The sub-protocol scope block ``modules/document/sections.py`` puts in front
#: of a narrowed document: one generated sentence, then the unit's own
#: ``subprotocol.md`` body on the next line, then a blank line. Only the second
#: line is the corpus's, so only it is replaced. Both newline forms are matched
#: because the block reaches the tree as prompt text and again as a JSON string
#: value, where every newline is an escape.
_SCOPE_NOTE = re.compile(
    r"(\[scope\] This protocol has several sub-protocols; this run models"
    r"[^\n\\]*?Shared background sections are kept\.)"
    r"(\\n|\n)([^\n]*?)(\\n\\n|\n\n)"
)


def _bones(doc: dict) -> dict:
    """One ``principals.json`` with every ``description`` removed.

    What is left is the skeleton: names, edges, ordering. Two files with the
    same skeleton are the same file in two languages.
    """
    return {key: [{k: v for k, v in row.items() if k != "description"}
                  for row in rows] for key, rows in doc.items()}


def corpus_prose(source: Path, corpus: Path,
                 runs: dict[Path, str | None]) -> dict[str, str]:
    """Corpus descriptions as this tree holds them, mapped to the corpus's own
    current English.

    Derived, never transcribed here: the English comes from ``corpus``, the
    Chinese from ``source``, paired by the two files' shared skeleton
    (``_bones``). Only corpus artefacts a run copied pair up, since rewriting a
    model's own extraction from the corpus would be a forgery. Raises SystemExit
    if the corpus is itself untranslated, or gives two Englishes for one Chinese.
    """
    table: dict[str, str] = {}
    for path in sorted(source.rglob("principals.json")):
        home = path.parent
        while home != source and home not in runs:
            home = home.parent
        unit = runs.get(home)
        if unit is None:
            continue
        gold = corpus / unit / "flow" / "principals.json"
        if not gold.is_file():
            continue
        try:
            mine = json.loads(path.read_text(encoding="utf-8"))
            theirs = json.loads(gold.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            if set(mine) != set(theirs) or _bones(mine) != _bones(theirs):
                continue
        except AttributeError:
            continue                    # not the shape at all: not a copy
        for key, rows in mine.items():
            for row, ref in zip(rows, theirs[key]):
                old, new = row.get("description") or "", ref.get("description") or ""
                if not _CJK.search(old):
                    continue
                if _CJK.search(new):
                    raise SystemExit(
                        f"{gold} still describes {row.get('name')!r} in "
                        f"Chinese.\n  The corpus is the source of the English "
                        f"here; translate it there and re-run, rather than "
                        f"writing the translation into this script.")
                if table.setdefault(old, new) != new:
                    raise SystemExit(
                        f"two corpus units give different English for the same "
                        f"Chinese description:\n  {old[:60]}…\n  -> "
                        f"{table[old][:60]}…\n  -> {new[:60]}…")
    return table


def source_home(corpus: Path, unit: str | None) -> str | None:
    """Which corpus unit holds this one's document, or None if none does.

    The unit itself where it has a ``source/``, else the nearest ancestor that
    does — the same walk ``forbidden_sentences`` makes, because one ``source/``
    serves a whole standard and its sub-protocols. This is the route every
    withheld note offers, so it has to resolve; a note pointing nowhere fails
    silently, the file it sits in still looking right.
    """
    if unit is None:
        return None
    here = Path(unit)
    while True:
        if (corpus / here / "source").is_dir():
            return str(here)
        if here == here.parent:
            return None
        here = here.parent


def subprotocol_note(corpus: Path, unit: str | None) -> str | None:
    """A sub-protocol's scope note as the corpus states it now, or None.

    Raises SystemExit if the corpus still states that scope in Chinese; this
    script carries no translations of its own.
    """
    if unit is None:
        return None
    md = corpus / unit / "subprotocol.md"
    if not md.is_file():
        return None
    text = md.read_text(encoding="utf-8")
    body = (text.split("---", 2)[2] if text.startswith("---") else text).strip()
    if not body:
        return None
    if _CJK.search(body):
        raise SystemExit(
            f"{md} still states its scope in Chinese.\n  Translate it in the "
            f"corpus and re-run; this script does not carry translations.")
    return body


def retranslate(text: str, table: dict[str, str], note: str | None) -> str:
    """Corpus prose in this file, refreshed from the corpus's current English.

    ``table`` comes from ``corpus_prose`` and is applied longest first, since
    one description can be a prefix of another. ``note`` replaces the scope
    block only where the note standing there is Chinese: an English one is left
    as the run received it, because restating what a run was told is a
    different act from repairing an abandoned language.
    """
    for old in sorted(table, key=len, reverse=True):
        text = text.replace(old, table[old])
    if note:
        text = _SCOPE_NOTE.sub(
            lambda m: (m.group(1) + m.group(2) + note + m.group(4)
                       if _CJK.search(m.group(3)) else m.group(0)), text)
    return text


# ── Checking, on the same pass ───────────────────────────────────────────────

def parseable(text: str, suffix: str) -> int:
    """How many JSON units this text yields, for JSON or JSON Lines.

    A count rather than a verdict, so the caller can compare before against
    after: a torn tail fails on both sides and cancels out, while a line an edit
    really damaged makes the difference negative.
    """
    if suffix == ".json":
        try:
            json.loads(text)
            return 1
        except json.JSONDecodeError:
            return 0
    n = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
            n += 1
        except json.JSONDecodeError:
            pass
    return n


def malformed(text: str, suffix: str) -> str | None:
    """Why this file will not load, or None. Absolute, not a comparison.

    ``parseable`` asks whether an edit made things worse; this asks whether the
    file loads at all, which is the artefact's own promise. The input tree
    parses completely, so a torn tail is not excused here: one that appears came
    from this script.
    """
    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return f"not valid JSON ({exc})"
        return None
    lines = [l for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            return f"line {i} of {len(lines)} is not valid JSON ({exc})"
    return None


#: The decoration a quotation puts in front of the words it quotes: blockquote
#: marks, bullets, typographic quotes, a leading ellipsis. Stripped before a
#: chunk is compared, because it is not the specification's text and it is
#: precisely what makes a quotation look unlike the original.
_QUOTE_LEAD = re.compile(r'^[\s>\-*•"“”‘’\'`…]*'
                         r'(?:\.\.\.)?\s*')

#: Markdown emphasis around words that are otherwise the document's own. The
#: corpus's transcriptions keep the standard's emphasis and a model quoting the
#: same sentence drops it, so both spellings go into the probe rather than one
#: normalised form: ``sweep_quotations`` replaces literally, and a probe form
#: the text does not hold matches nothing and removes nothing.
_MARKUP = re.compile(r"\*\*|__|`")


def sentences(text: str, floor: int = 60) -> set[str]:
    """Sentence-ish fragments of at least ``floor`` characters, as a set.

    Shorter fragments collide by chance, a heading turning up in a model's own
    words as readily as in the document. Each chunk is stripped of what a
    quotation put in front of it (``_QUOTE_LEAD``), and both sides of a
    comparison go through this function, so nothing matches that would not have
    matched verbatim. Stripping only a prefix leaves each chunk a substring of
    its line, which lets ``sweep_quotations`` replace it in place.
    """
    out = set()
    for line in text.split("\n"):
        line = " ".join(line.split())
        if not line:
            continue
        # The line whole, and then cut at sentence ends. Either alone has a
        # hole: cutting only at sentence ends loses a line whose halves are each
        # under the floor, and taking only whole lines loses a clause quoted out
        # of a paragraph that was one line.
        for piece in (line, *re.split(r"(?<=[.;:])\s+", line)):
            piece = _QUOTE_LEAD.sub("", " ".join(piece.split()))
            for form in (piece, _MARKUP.sub("", piece)):
                if len(form) >= floor:
                    out.add(form)
    return out


class Checker:
    """Every exit check, run on text the writer already has in hand.

    There is no second pass over the finished tree, because re-reading it is the
    whole cost. Five questions per file, reported at the end: did the declared
    substitutions happen; which email addresses are here (printed, never
    rewritten); does any restricted sentence survive; is any Chinese left; does
    every structured file still load. ``report`` raises SystemExit on all but
    the email listing.
    """

    def __init__(self, scrubber: Scrubber, forbidden: dict[str, str]) -> None:
        self.scrubber, self.forbidden = scrubber, forbidden
        self.leftover: list[str] = []
        self.damaged: list[str] = []
        self.emails: dict[str, str] = {}
        self.survived: list[str] = []
        self.chinese: list[str] = []
        self.malformed: list[str] = []

    def __call__(self, rel: Path, text: str,
                 probe: list[str] | None = None) -> None:
        if found := self.scrubber.residue(text):
            self.leftover.append(f"{rel}: {'; '.join(found)}")
        # A redaction marker in a ProVerif model means a rule reached protocol
        # vocabulary and the model has stopped parsing.
        if rel.suffix == ".pv" and "<redacted>" in text:
            self.damaged.append(f"{rel}")
        if "@" in text:
            for addr in _EMAIL.findall(text):
                self.emails.setdefault(addr, str(rel))
        # Every file, with no list of which kinds could carry a document or a
        # Chinese sentence: naming the kinds would freeze one scan's answer into
        # an assumption, and the hole it hides is a licence breach.
        if rel.suffix in STRUCTURED and (why := malformed(text, rel.suffix)):
            self.malformed.append(f"{rel}: {why}")
        if m := _CJK.search(text):
            start = max(0, m.start() - 20)
            self.chinese.append(f"{rel}: …{text[start:m.start() + 50]}…")
        if self.forbidden:
            # The same containment test the sweep uses, on the same scoped
            # probe. A check asking a narrower question than the rule it
            # verifies reports clean on a tree the rule did not clean.
            common = quoted(text, probe if probe is not None
                            else list(self.forbidden))
            if common:
                line = common[0]
                self.survived.append(
                    f"{rel}: {len(common)} sentence(s) of "
                    f"{self.forbidden[line]} survive — {line[:70]}…")

    def report(self) -> None:
        if self.leftover:
            raise SystemExit(
                f"{len(self.leftover)} redaction leak(s); this tree may not be "
                f"published:\n  " + "\n  ".join(self.leftover[:10])
                + (f"\n  …and {len(self.leftover) - 10} more"
                   if len(self.leftover) > 10 else ""))
        if self.damaged:
            raise SystemExit(
                f"{len(self.damaged)} ProVerif model(s) carry a redaction "
                f"marker and no longer parse:\n  "
                + "\n  ".join(self.damaged[:10])
                + (f"\n  …and {len(self.damaged) - 10} more"
                   if len(self.damaged) > 10 else "")
                + "\n  A rule matched protocol vocabulary. Narrow "
                  "CREDENTIAL_KEYS; never widen it.")
        if self.survived:
            raise SystemExit(
                f"{len(self.survived)} file(s) still carry restricted "
                f"specification text:\n  " + "\n  ".join(self.survived[:10])
                + (f"\n  …and {len(self.survived) - 10} more"
                   if len(self.survived) > 10 else ""))
        if self.malformed:
            raise SystemExit(
                f"{len(self.malformed)} structured file(s) no longer load; "
                f"the runs they belong to cannot be replayed:\n  "
                + "\n  ".join(self.malformed[:10])
                + (f"\n  …and {len(self.malformed) - 10} more"
                   if len(self.malformed) > 10 else ""))
        if self.chinese:
            raise SystemExit(
                f"{len(self.chinese)} file(s) still carry Chinese:\n  "
                + "\n  ".join(self.chinese[:10])
                + (f"\n  …and {len(self.chinese) - 10} more"
                   if len(self.chinese) > 10 else "")
                + "\n  Corpus prose is replaced by pairing a run's copy of a "
                  "corpus artefact with the corpus's\n  current English, so "
                  "this means either --verify-against was not given, or the "
                  "text\n  arrived by a route that pairing does not reach. It "
                  "is not fixed by editing this tree.")
        if self.emails:
            print(f"to eyeball: {len(self.emails)} distinct email address(es). "
                  f"Almost all are content — RFC authors, test accounts the "
                  f"model invented; recognise one as yours and re-run with "
                  f"--scrub it=<email>:")
            for addr, where in list(self.emails.items())[:12]:
                print(f"    {addr}  ({where})")
            if len(self.emails) > 12:
                print(f"    …and {len(self.emails) - 12} more")


def forbidden_sentences(corpus: Path,
                        units: set[str]) -> tuple[dict[str, str],
                                                  dict[str, list[str]]]:
    """``({sentence: the unit whose source/ holds it},
    {that unit: all of its sentences, longest first})``.

    The document sits at the analysed unit or above it, since a sub-protocol
    shares its parent's ``source/``; both maps are keyed by that holder, so
    every mechanism of one standard shares one probe. ``README.md`` is ours and
    ships on purpose, so it is excluded and cannot become its own evidence.
    """
    owner: dict[str, str] = {}
    by_home: dict[str, list[str]] = {}
    for unit in sorted(units):
        here = Path(unit)
        while True:
            source = corpus / here / "source"
            if source.is_dir() or here == here.parent:
                break
            here = here.parent
        if not source.is_dir() or str(here) in by_home:
            continue
        text = [d.read_text(encoding="utf-8", errors="replace")
                for d in sorted(source.rglob("*"))
                if d.is_file() and d.suffix in (".md", ".txt")
                and d.name != "README.md"]
        if not text:
            continue
        mine = sentences("\n".join(text))
        # Every standard gets its own source's sentences whole, rather than the
        # flat ``owner`` map grouped: sibling standards restate each other's
        # general model word for word, and grouping puts a shared sentence in
        # one probe and no other.
        by_home[str(here)] = sorted(mine, key=len, reverse=True)
        for line in mine:
            owner.setdefault(line, str(here))
    return owner, by_home


# ── The reader's way in, and the entry point ─────────────────────────────────

#: The manifest's own name, written beside ``experiments/`` rather than inside
#: it. Step 3 reads everything under that directory as some run's, so a file at
#: the top of it would be the one entry belonging to nobody.
MANIFEST_NAME = "MANIFEST.txt"

#: What the deposit is. It names no author, no institution and no tool, because
#: the manifest travels with the archive into an anonymous review and is the
#: first file a reader opens.
MANIFEST_TITLE = ("Experimental data: automated formal analysis of "
                  "cryptographic protocols")


def manifest(dest: Path, title: str) -> tuple[str, int]:
    """Describe the written tree; return the description and the tree's size.

    The artefact is deposited as one archive, which answers no question until it
    is unpacked, so counts of runs, protocols and batches stand beside it as a
    file. Generated rather than transcribed, since a hand-written manifest goes
    stale the next time the selection changes. One walk, sharing the ``stat``
    that totals the size. Symlinks are counted and never followed: following one
    counts every file under its target twice.
    """
    files = dirs = links = 0
    size = 0
    suffixes: Counter = Counter()
    runs: Counter = Counter()
    protocols: dict[str, set[str]] = {}
    present: dict[str, set[tuple[str, str]]] = {}
    states: dict[str, list[Path]] = {}

    for path in dest.rglob("*"):
        rel = path.relative_to(dest)
        if path.is_symlink():
            links += 1
            continue
        if path.is_dir():
            dirs += 1
            continue
        if not path.is_file():
            continue
        files += 1
        size += path.stat().st_size
        suffixes[path.suffix.lstrip(".") or "(no suffix)"] += 1
        # Both counts come off the run's own marker rather than off the shape of
        # the tree, because a batch holds one directory that is not a
        # protocol: ``_batch``, the scheduler's record of the launch.
        if path.name == "run.json":
            runs[rel.parts[0]] += 1
            protocols.setdefault(rel.parts[0], set()).add(rel.parts[1])
            present.setdefault(rel.parts[0], set()).add(
                (rel.parts[1], rel.parts[2]))
        elif path.parent.name == "_batch" and path.suffix == ".json":
            states.setdefault(rel.parts[0], []).append(path)

    out = [title, "=" * len(title), "",
           f"{files} files in {dirs} directories, "
           f"{size / 2**20:.0f} MB uncompressed"
           + (f", {links} symbolic links." if links else "."), ""]

    out += ["Batches", "-------"]
    for batch in sorted(protocols):
        out.append(f"  {batch:<10} {len(protocols[batch]):>4} protocols"
                   f"{runs[batch]:>6} runs")
    out += [""]

    out += ["File types", "----------"]
    for suffix, n in suffixes.most_common():
        out.append(f"  {suffix:<12} {n:>6}")
    out += [""]

    if states:
        # The heading carries what the columns mean: without it "published here"
        # reads as a defect rather than as the batch's record of a later
        # attempt that failed after the published run completed.
        title_ = "Batch state (_batch/ — the last attempt at each protocol)"
        out += [title_, "-" * len(title_),
                f"  {'':<10}{'state':>8}{'ok':>8}{'failed':>8}{'running':>9}"
                f"{'published':>12}",
                f"  {'':<10}{'files':>8}{'':>8}{'':>8}{'':>9}{'here':>12}"]
        for batch in sorted(states):
            ok = failed = running = named = matched = 0
            for state in states[batch]:
                # Parsing is safe to assume: every structured file here has been
                # through the checker, which refuses to finish if one stopped
                # loading. A failure is that check having missed something.
                record = json.loads(state.read_text(encoding="utf-8"))
                code = record.get("exit_code")
                if code == 0:
                    ok += 1
                elif code is None:
                    running += 1
                else:
                    failed += 1
                unit, run = record.get("protocol_id"), record.get("run_name")
                if unit and run:
                    named += 1
                    matched += (unit, run) in present.get(batch, ())
            out.append(f"  {batch:<10}{len(states[batch]):>8}"
                       f"{ok:>8}{failed:>8}{running:>9}{matched:>12}")
        out += [""]

    out += ["Protocols", "---------"]
    for batch in sorted(protocols):
        out.append(f"  [{batch}]")
        out += [f"    {unit}" for unit in sorted(protocols[batch])]
        out.append("")

    return "\n".join(out).rstrip() + "\n", size


def main() -> None:
    """Copy ``source`` to ``dest`` file by file, redacting and checking as it
    goes, then write the manifest beside the tree.

    Every file is scrubbed, swept and retranslated in one pass and handed
    straight to the checker, so there is no second read of the finished tree.
    Any check that fails raises SystemExit and nothing more is written.
    """
    ap = argparse.ArgumentParser(
        description="Make the run tree publishable: redact what is ours to "
                    "hide, replace what is not ours to give")
    ap.add_argument("source", type=Path, help="the selected run tree")
    ap.add_argument("dest", type=Path, help="where to write it; must not exist")
    ap.add_argument("--scrub", action="append", default=[], metavar="OLD=NEW",
                    help="identifying text to replace; repeatable. The source "
                         "root's absolute path is added automatically")
    ap.add_argument("--verify-against", type=Path, default=None, metavar="LIB",
                    help="the corpus. Every restricted specification's own "
                         "sentences are searched for in what is written, and a "
                         "single hit is fatal. It is also where the English "
                         "for corpus prose a run copied before the corpus was "
                         "translated is read from")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the classification; write nothing")
    args = ap.parse_args()

    args.source = args.source.resolve()
    if not args.source.is_dir():
        raise SystemExit(f"no such tree: {args.source}")
    if args.verify_against and not args.verify_against.is_dir():
        raise SystemExit(f"no such corpus: {args.verify_against}")

    runs = {m.parent: unit_of(m.parent) for m in sorted(args.source.rglob("run.json"))}
    if not runs:
        raise SystemExit(f"no run.json anywhere under {args.source}")
    restricted = {r: why for r, u in runs.items() if (why := restriction(u))}

    print(f"{len(runs)} runs; {len(restricted)} carry a restricted specification")
    for why, n in Counter(restricted.values()).most_common():
        print(f"    {n:4d}  {why}")
    for prefix, why in UNRESTRICTED.items():
        n = sum(1 for u in runs.values()
                if u and (u == prefix.rstrip("/") or u.startswith(prefix)))
        if n:
            print(f"    {n:4d}  kept: {why}")
    if args.dry_run:
        print("dry run: nothing written")
        return
    if args.dest.exists():
        raise SystemExit(f"destination exists; refusing to overwrite: {args.dest}")

    scrubber = build_scrubber(args.scrub, args.source)
    forbidden, by_home = (forbidden_sentences(
        args.verify_against.resolve(),
        {u for r, u in runs.items() if r in restricted and u})
        if args.verify_against else ({}, {}))
    check = Checker(scrubber, forbidden)

    # The corpus's current English, paired with the text this tree holds. Built
    # before the write pass, so a corpus that is itself untranslated stops the
    # run before a byte is written rather than at the exit check.
    corpus = args.verify_against.resolve() if args.verify_against else None
    prose = corpus_prose(args.source, corpus, runs) if corpus else {}
    notes = ({run: subprotocol_note(corpus, unit)
              for run, unit in runs.items()} if corpus else {})
    if prose or any(notes.values()):
        print(f"{len(prose)} corpus description(s) and "
              f"{sum(1 for n in notes.values() if n)} scope note(s) available "
              f"in the corpus's current English")

    # The route back every withheld note offers, resolved before the write pass.
    # A restricted run that cannot name one stops everything below: the note is
    # what the artefact's copyright position rests on, and one pointing at a
    # path the corpus does not have is worse than none.
    sources = ({run: source_home(corpus, unit)
                for run, unit in runs.items()} if corpus else {})

    #: The whole forbidden set, for a file belonging to no run -- the batch's
    #: batch logs, which echo whatever their protocol's prompts carried. A file
    #: inside a run is asked only about its own standard's sentences, which is
    #: what keeps the containment test in ``quoted`` affordable.
    all_sentences = sorted(check.forbidden, key=len, reverse=True)
    if corpus:
        blind = sorted({runs[run] for run in restricted
                        if not sources.get(run)})
        if blind:
            raise SystemExit(
                f"{len(blind)} restricted unit(s) have no source/ anywhere at "
                f"or above them in {corpus}, so the\n  withheld notes for them "
                f"would name a path that does not exist:\n  "
                + "\n  ".join(str(b) for b in blind[:10]))
        print(f"{len(set(filter(None, sources.values())))} corpus unit(s) hold "
              f"the documents these runs quote; that is the route the withheld "
              f"notes name")

    tally: Counter = Counter()
    for src in sorted(args.source.rglob("*")):
        rel = src.relative_to(args.source)
        out = args.dest / rel
        if src.is_symlink():
            # Dropped, and tested before ``is_dir()``, which answers True for a
            # symlink to a directory and would turn a pointer into an empty
            # directory reading as a run that lost its files. Step 1 delivers no
            # symlink; this covers a tree from somewhere else, whose link target
            # is a path no rule below would redact.
            tally["symbolic link, dropped"] += 1
            continue
        if src.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        if not src.is_file():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        raw = src.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Redaction cannot reach inside it and the checks cannot see it.
            tally["binary, copied verbatim"] += 1
            out.write_bytes(raw)
            continue

        # First, and on every transcript whatever its run: the rules below read
        # the text they are handed, and one of them re-serialises it.
        if rel.name == "transcript.jsonl":
            text, n = drop_signatures(text)
            if n:
                tally["provider reasoning signatures emptied"] += n

        # Which run this file belongs to, and whether that run's specification
        # is restricted. Found by walking up, because a file can be several
        # levels below its run.
        home = src.parent
        while home != args.source and not (home / "run.json").is_file():
            home = home.parent
        why = restricted.get(home)
        # Which sentences this file could possibly be quoting. A run quotes its
        # own unit's document; a file outside every run has no unit, so it is
        # asked the whole question.
        probe = (by_home.get(sources.get(home) or "", [])
                 if home in runs else all_sentences)
        # A restricted run is not searched at all: no branch below decides
        # anything by matching for it, since its prose goes for what the file is
        # and the rest is kept for what it is. ``quoted`` is a containment test
        # over every sentence of the run's standard, which is the most expensive
        # thing here, so skipping it costs nothing and saves most of the run.
        if why:
            probe = []
        #: Whether anything below rewrote this file after the sweep read it.
        #: The exit check re-reads only those; see the call ending the loop.
        swept = False

        if why and (stand_in := substitute(rel, text, runs.get(home), why,
                                           probe, sources.get(home))):
            body = scrubber(stand_in)
            tally[f"{rel.name}: specification text replaced by a note"] += 1
            # A stand-in is a whole-file replacement, the one edit that can turn
            # a loadable file into prose with nothing noticing. Structured files
            # only: counting "JSON units" in prose finds every bare number.
            was, now = ((parseable(text, src.suffix), parseable(body, src.suffix))
                        if src.suffix in STRUCTURED else (0, 0))
            if now < was:
                raise SystemExit(
                    f"the stand-in for {src} is not the shape the file was: "
                    f"{was} JSON units parsed before, {now} after.\n"
                    f"  A file something reads back may not be replaced whole; "
                    f"add its suffix to STRUCTURED so its\n"
                    f"  quoted sentences are swept out in place instead.")
            # And then swept anyway. For a ``PROSE_STRUCTURED`` file this finds
            # nothing left, but ``PROSE_WHOLE`` files pass through here too, and
            # a sweep running on everything cannot be the step forgotten when a
            # new carrier is added.
            if check.forbidden:
                body, n = sweep_quotations(body, probe, check.forbidden)
                if n:
                    tally["quoted sentences replaced where they stood"] += n
                    swept = True
        else:
            # A file of an unrestricted run, or of no run at all. The text has
            # the last word rather than the file's place in the tree: a
            # batch's `_batch` logs sit above every run.json, so deciding by run
            # alone would pass them over while they echo the prompts.
            if src.suffix in STRUCTURED:
                body, blanked = text, False
            else:
                body, blanked = blank_quoting_text(
                    text, probe, runs.get(home),
                    why or "its publisher's terms forbid redistribution",
                    sources.get(home))
            if blanked:
                tally["passage quoting a specification, replaced whole"] += 1
            body = scrubber(body)
            # Not guarded on ``why``: a run of an unrestricted unit can still
            # quote a restricted document, and that sentence may not ship.
            if check.forbidden:
                body, n = sweep_quotations(body, probe, check.forbidden)
                if n:
                    tally["quoted sentences replaced where they stood"] += n
                    swept = True
            # Structured files only, as in the stand-in branch: ``parseable``
            # counts lines that happen to be valid JSON, and in prose that is
            # every bare number, so a swept batch log would look damaged.
            if (body is not text and body != text
                    and src.suffix in STRUCTURED):
                was, now = parseable(text, src.suffix), parseable(body, src.suffix)
                if now < was:
                    raise SystemExit(
                        f"redaction damaged {src}: {was} JSON units parsed "
                        f"before substitution, {now} after.\n"
                        f"  Most likely a credential rule matched protocol "
                        f"vocabulary. Narrow CREDENTIAL_KEYS; never widen it.")

        # Last, so the rules above see the run as it was: a withheld note counts
        # the characters that stood where it does, and retranslating first would
        # make that a count of the replacement.
        if _CJK.search(body):
            fixed = retranslate(body, prose, notes.get(home))
            if fixed != body:
                was, now = parseable(body, src.suffix), parseable(fixed, src.suffix)
                if now < was:
                    raise SystemExit(
                        f"retranslation damaged {src}: {was} JSON units parsed "
                        f"before it, {now} after. A corpus description "
                        f"carrying a quote or a backslash would do this.")
                tally["corpus prose refreshed to the corpus's English"] += 1
                body = fixed
                swept = True

        out.write_text(body, encoding="utf-8")
        # The probe goes to the check only for a file the sweep rewrote. For
        # anything else the two would run the same containment test over the
        # same bytes, and the sweep already removed every sentence it found.
        # What is worth re-asking of a rewritten file is whether the replacement
        # landed: ``str.replace`` is a no-op when the probe matched a form the
        # text does not literally hold.
        check(rel, body, probe if swept else [])

    check.report()

    # Last, and outside the tree it describes. Scrubbed like everything else,
    # since it is made of directory names and that is where an account name
    # reaches a path.
    card, size = manifest(args.dest, MANIFEST_TITLE)
    card = scrubber(card)
    if _CJK.search(card):
        raise SystemExit(
            "the manifest carries Chinese: a directory in the written tree is "
            "named in a language the\n  published tree may not be in. The name "
            "is the run's, so fixing it here would only hide it.")
    listing = args.dest.parent / MANIFEST_NAME
    listing.write_text(card, encoding="utf-8")

    print()
    for what, n in tally.most_common():
        print(f"    {n:6d}  {what}")
    print(f"wrote {size / 2**20:.0f} MB -> {args.dest}")
    print(f"wrote {MANIFEST_NAME} -> {listing}")
    if args.verify_against:
        print(f"verified against {args.verify_against}: no restricted "
              f"specification text survives")


if __name__ == "__main__":
    main()
