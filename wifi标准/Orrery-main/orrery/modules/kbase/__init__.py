"""The value shapes of the project's vocabularies, plus the primitive library.

The assumption and goal vocabularies live in code, as the realizer and injector
class declarations under ``nodes/apply/realizers`` and ``nodes/inject/injectors``.
This package defines the shapes those declarations are packed into
(``assumptions.catalog.Vocabulary``, ``properties.catalog.PropertyVocabulary``);
the registries build them at import time and hand them down as parameters to
consumers below the nodes layer.

``primitives/`` stays a data library (``orrery/kb/primitives/PRIMITIVES_KB.yaml``):
one new YAML entry delivers a new primitive with no per-entry code.
"""
