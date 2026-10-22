"""Where tool handlers get their data, and where the visibility rules are
enforced.

The context holds only what this agent may see: no ground-truth path, no
underscore domain, no path outside the run. A field that is None means the node
lacks that capability, and the matching tool says so rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orrery.modules.document.model.document_set import DocumentSet
from orrery.services.transcript.prompt import ROUNDS, is_session_file


# A directory or file starting with an underscore is invisible to every agent
# (the expert's own transcript, review's _review.json). Every segment of the
# path is checked, so a nested underscore directory is invisible too.
def _hidden_path(parts: tuple[str, ...]) -> bool:
    return any(seg.startswith("_") for seg in parts)


@dataclass
class ToolContext:
    node: str
    scenario: str | None = None
    doc_set: DocumentSet | None = None
    artifacts_root: Path | None = None            # the run directory's canonical (current) state
    transcript_paths: dict[str, Path] = field(default_factory=dict)  # upstream node → its transcript
    # Nodes that ran before this one: the legal targets of report_gap. Kept as
    # data rather than tool schema so the tool block stays byte-identical
    # across nodes and the shared cache prefix survives.
    upstream_nodes: tuple[str, ...] = ()
    # The corpus this run is checked against, when it has one. Only the
    # expert's context ever carries it, so no pipeline node can reach the
    # expected answers.
    ground_truth: Path | None = None
    # (runner, timeout_s) for the one tool that runs a solver — the expert
    # asking for a longer counter-example. None when this session has none
    # configured, and the tool then says so.
    proverif: tuple | None = None
    # Where a tool may put an event of its own. Only record_finding uses it:
    # its product is a fact about the run that has to outlive the conversation.
    emitter: object | None = None
    tool_return_chars: int = 20_000
    # Flow-only retrieval state. The lookup offers candidate modelling
    # contracts; the submitted .pv selects one by its marker, and the
    # acceptance check refuses a marker the session was never shown.
    prompt_lang: str = "en"
    offered_identity_idioms: set[tuple[str, int]] = field(default_factory=set)
    identity_modeling_miss: bool = False
    # Same contract for the role-body-structure library, which has no miss
    # state: that lookup always answers.
    offered_structure_idioms: set[tuple[str, int]] = field(default_factory=set)

    def resolve_artifact(self, rel: str) -> Path:
        """Resolve a tool's relative path inside the run directory.

        Raises RuntimeError when the context has no artifact directory, when
        the path escapes the run, when it lands in a hidden domain, or when it
        names a session file rather than an artifact.
        """
        if self.artifacts_root is None:
            raise RuntimeError(f"node {self.node}: the context has no artifact directory")
        p = (self.artifacts_root / rel).resolve()
        root = self.artifacts_root.resolve()
        if not p.is_relative_to(root):
            raise RuntimeError(f"path escapes the run directory: {rel!r}")
        parts = p.relative_to(root).parts
        if not parts:
            raise RuntimeError("need a concrete file path inside the run directory, not the root itself")
        if _hidden_path(parts):
            raise RuntimeError(f"path {rel!r} is in an invisible domain")
        if is_session_file(parts[-1]) or ROUNDS in parts:
            # The prompts filed under rounds/ are the session's record too: a
            # step's system prompt carries the corpus, and read_prompt is the
            # door to it, opening only the authorised upstream.
            raise RuntimeError(
                "a session is not an artifact; use read_transcript for what it "
                "did and read_prompt for what it was told, both of which open "
                "only the authorised upstream")
        return p

    def visible_artifacts(self) -> list[str]:
        """The current artifacts as relative paths, excluding hidden domains
        and the files of a session (its transcript and its prompt)."""
        if self.artifacts_root is None:
            raise RuntimeError(f"node {self.node}: the context has no artifact directory")
        root = self.artifacts_root.resolve()
        out = []
        for p in sorted(root.rglob("*")):
            if not p.is_file() or is_session_file(p.name):
                continue
            rel = p.relative_to(root)
            if _hidden_path(rel.parts) or ROUNDS in rel.parts:
                continue
            out.append(str(rel))
        return out
