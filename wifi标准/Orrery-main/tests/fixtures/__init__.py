"""Paths into the toy protocol the suite reads instead of VerdictBench.

A complete protocol directory (document, annotations, principals, model,
claims, results) that lives inside the package at
``orrery/utils/prompts/fixture``, so ``orrery prompt`` renders its previews
from the same bytes the suite asserts on. The verdicts in results/ are
internally consistent, not claims about any real protocol.
"""

from pathlib import Path

import orrery

TOY_PROTOCOL = (Path(orrery.__file__).resolve().parent
                / "utils" / "prompts" / "fixture")

CLAIMS = TOY_PROTOCOL / "claims"
RESULTS = TOY_PROTOCOL / "results"
MAIN_PV = TOY_PROTOCOL / "formal" / "proverif" / "main.pv"
# The same protocol before goal injection: what apply edits.
FLOW_PV = TOY_PROTOCOL / "formal" / "proverif" / "flow.pv"
PRINCIPALS = TOY_PROTOCOL / "principals" / "principals.json"
DOCUMENT = TOY_PROTOCOL / "source" / "main" / "TAP.md"

#: A solver stand-in for tests that build a real run and never solve: it
#: passes the check a run makes on its solver before starting.
PROVERIF_STUB = Path(__file__).resolve().parent / "proverif_stub"

#: Attack graphs ``proverif -graph`` drew under the long trace display, from
#: real runs: Lowe's attack on NSPK against a secrecy goal and an agreement
#: goal, and an ISO 9798-2 mechanism 6 run whose shared key K_AP was disclosed.
#: Beside the toy protocol, since the prompt preview explains one of them.
ATTACK_GRAPHS = TOY_PROTOCOL / "attack_graphs"
