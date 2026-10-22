"""The two version numbers this system maintains; imports nothing, so every
layer may read it.

PROJECT_VERSION is the software release, moved by hand and mirrored in
pyproject.toml. VOCAB_VERSION is the assumption and property vocabulary every
LIB JSON is written against, compared for equality only
(modules/libschema/version.py): bumping it stops the whole corpus loading
until each file is bumped too. The two move independently.
"""
from __future__ import annotations

#: The software release. Manual; mirrored in pyproject.toml.
PROJECT_VERSION = "1.0.1"

#: The vocabulary every LIB JSON is written against. Manual; bumping it means
#: bumping every corpus file too, or they stop loading.
VOCAB_VERSION = "2.2.0"
