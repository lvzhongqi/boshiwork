"""The local filesystem, as the launch panel walks it.

``listing`` says what is in one directory, one level and no recursion;
``resolve`` says what the path the reader pointed at is and fills the launch
form from it. The one thing that cannot be derived — which document is the
subject when a folder holds several — is asked rather than guessed.
"""

from __future__ import annotations

from pathlib import Path

from orrery.api.corpus_inputs import supplies
from orrery.modules.document import (bundle_reads_text, is_document,
                                     is_text_document, prefer_text)

__all__ = ["listing", "resolve", "is_protocol_dir"]

#: How many entries of each kind one listing draws. Anything cut is reported in
#: the listing's ``truncated`` count.
MAX_ENTRIES = 400

#: Dot-prefixed names are hidden by platform convention; underscore-prefixed
#: ones are the corpus's own bookkeeping, which ``/api/protocols`` also skips.
def _hidden(name: str) -> bool:
    return name.startswith(".") or name.startswith("_")


def is_protocol_dir(d: Path) -> bool:
    """Whether this directory is a protocol in its own right rather than a
    folder that happens to contain one. Either mark counts: the document loader
    keys on ``source/main/`` and the corpus scan on ``claims/claims.json``, and
    one mark without the other is still a protocol directory.
    """
    return (d / "source" / "main").is_dir() or (d / "claims" / "claims.json").is_file()


def _doc_entry(p: Path) -> dict:
    return {"name": p.name, "path": str(p), "bytes": p.stat().st_size}


def listing(path: Path) -> dict:
    """One directory: the sub-directories to descend into, and the documents
    that can be analysed here.

    Raises NotADirectoryError if the path is not a directory. Only files
    ``modules.document.is_document`` accepts are offered.
    """
    path = Path(path).expanduser()
    if not path.is_dir():
        raise NotADirectoryError(f"not a directory: {path}")
    path = path.resolve()
    dirs, docs, cut = [], [], 0
    for p in sorted(path.iterdir(), key=lambda x: x.name.lower()):
        if _hidden(p.name):
            continue
        try:
            if p.is_dir():
                if len(dirs) >= MAX_ENTRIES:
                    cut += 1
                    continue
                dirs.append({"name": p.name, "path": str(p),
                             "protocol": is_protocol_dir(p)})
            elif is_document(p):
                if len(docs) >= MAX_ENTRIES:
                    cut += 1
                    continue
                docs.append(_doc_entry(p))
        except OSError:
            # A dangling symlink, a vanished mount, an entry this user cannot
            # stat: leave it out rather than refuse the whole listing.
            continue
    parent = path.parent
    return {"path": str(path),
            # None at the filesystem root, so the page draws "up" only where
            # there is one.
            "parent": str(parent) if parent != path else None,
            "home": str(Path.home()),
            "protocol": is_protocol_dir(path),
            "dirs": dirs, "docs": docs,
            # How many entries the MAX_ENTRIES cap dropped, so a capped listing
            # does not read as a smaller directory.
            "truncated": cut}


def _refs_in(root: Path) -> list[Path]:
    """The documents this bundle declares as references: the ones under
    ``source/refs/`` or ``refs/``, and nothing else.

    A neighbouring file is not a reference. Pulling one in on the strength of
    its position enlarges the corpus block the four reader nodes share, and a
    wrong guess is silent — the model reads about another protocol.
    """
    # The same rule the loader applies, so the panel lists what will be read:
    # a bundle whose subject is text is read as text throughout.
    text_bundle = bundle_reads_text(root)
    for d in (root / "source" / "refs", root / "refs"):
        if d.is_dir():
            refs = [p for p in sorted(d.iterdir()) if is_document(p)]
            if text_bundle:
                return [p for p in refs if is_text_document(p)]
            return prefer_text(refs)
    return []


def resolve(path: Path) -> dict:
    """What the reader pointed at, as the launch form needs it.

    A file is the subject and its directory the protocol root; a corpus-layout
    directory answers for itself with ``main`` null, and any other directory
    lists its readable documents with ``main`` set only when there is exactly
    one. Raises FileNotFoundError for a missing path, ValueError for a file the
    pipeline cannot read.
    """
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"no such file or directory: {path}")
    path = path.resolve()

    if path.is_file():
        if not is_document(path):
            raise ValueError(
                f"{path.name} is not a document this pipeline can read. It "
                f"reads .md, .markdown, .txt, .pdf, .docx and .doc")
        # A document under `source/main/` belongs to a corpus entry whose root
        # is three levels up; the literal parent would be a root with neither
        # claims nor ground truth.
        root, main, docs = path.parent, path, [_doc_entry(path)]
        if root.name == "main" and root.parent.name == "source":
            root = root.parent.parent
        layout = "documents"
    elif path.is_dir():
        root = path
        if is_protocol_dir(path):
            layout, main, docs = "corpus", None, []
        else:
            layout = "documents"
            docs = sorted((_doc_entry(p) for p in path.iterdir()
                           if not _hidden(p.name) and is_document(p)),
                          key=lambda d: d["name"].lower())
            main = Path(docs[0]["path"]) if len(docs) == 1 else None
    else:
        raise ValueError(f"neither a file nor a directory: {path}")

    subs = sorted(p.name for p in (root / "subprotocols").iterdir()
                  if p.is_dir()) if (root / "subprotocols").is_dir() else []
    # With exactly one sub-protocol the switches are answered against its own
    # directory, matching resolve_subprotocol_name's defaulting. Several means
    # the choice is still open and there is no single directory to ask.
    home = root / "subprotocols" / subs[0] if len(subs) == 1 else root
    return {
        "root": str(root),
        "layout": layout,
        # A suggestion only; the form still asks, since this name goes on the
        # run directory and no later step can correct it.
        "name": (main.stem if main is not None else root.name),
        "main": str(main) if main is not None else None,
        "docs": docs,
        "refs": [str(p) for p in _refs_in(root)],
        "subprotocols": subs,
        "supplies": supplies(home),
        "ground_truth": (home / "results").is_dir(),
    }
