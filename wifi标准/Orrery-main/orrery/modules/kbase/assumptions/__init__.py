"""The shape of the security-assumption vocabulary.

The truth source is the realizer class declarations in
``nodes/apply/realizers`` (one directory per subtype); the registry there
builds a ``catalog.Vocabulary`` value from them at import time. This package
holds the shape and its constructor-time validation — see ``catalog``.
"""
