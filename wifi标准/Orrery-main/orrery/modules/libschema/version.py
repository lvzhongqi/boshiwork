"""Version gating for the five LIB JSON files, plus the exception hierarchy that
io / model / resolve / validate share under one base class.

Every LIB file carries ``vocab_version``, naming the vocabulary it was written
against. Only equality passes, in both directions: a vocabulary change migrates
the whole corpus at once, so no range of versions is mutually compatible. The
rules for moving the number live in orrery/version.py. The document annotation
format and the primitive library are versioned separately.
"""
from __future__ import annotations

from orrery.version import VOCAB_VERSION

# The five kinds of file under version gating; the values are diagnostic labels.
LIB_JSON_KINDS = ("assumptions", "properties", "claims", "results", "cases_results")


class LibSchemaError(RuntimeError):
    """Base class for every LIB schema error."""


class LibSchemaVersionError(LibSchemaError):
    """A LIB JSON's vocab_version is missing or is not the one this build
    speaks."""


class LibParseError(LibSchemaError):
    """A LIB JSON's structure is wrong: a required field is missing, or a type
    does not match."""


class LibResolveError(LibSchemaError):
    """A point does not resolve to a legal coordinate in the assumptions axis
    space."""


class LibValidationError(LibSchemaError):
    """Semantic validation failed: KB consistency, cross-file goal ids, or
    verdict consistency."""


def require_vocab_version(data, *, kind, path=None):
    """Check one parsed LIB JSON: the top level is an object and
    ``vocab_version == VOCAB_VERSION``, or LibSchemaVersionError is raised.

    ``kind`` is one of :data:`LIB_JSON_KINDS` and only locates the error;
    ``path`` is optional and is attached to the message. Returns ``data``, so
    calls can be chained.
    """
    if kind not in LIB_JSON_KINDS:
        raise LibSchemaVersionError(
            f"unknown LIB JSON kind {kind!r}; expected one of {LIB_JSON_KINDS}"
        )
    where = f" ({path})" if path else ""
    if not isinstance(data, dict):
        raise LibSchemaVersionError(
            f"{kind}: top level must be an object, got {type(data).__name__}{where}"
        )
    version = data.get("vocab_version")
    if version != VOCAB_VERSION:
        raise LibSchemaVersionError(
            f"{kind}: vocab_version must be {VOCAB_VERSION!r}, got {version!r}{where}"
            f" — this file was written against a different vocabulary. Migrate "
            f"the corpus to {VOCAB_VERSION!r} (see orrery/version.py for what "
            f"changed between versions); the two are never made compatible."
        )
    return data
