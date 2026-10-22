"""Mechanical checking of counterfactual assertions: the reviewer is not
trusted, only its citations are verified.

Every finding carries a counterfactual — what should appear in the text if the
conclusion holds. The check is a plain text search, so it under-reports: an
equivalent renaming it cannot recognise kills a real finding.
"""

from __future__ import annotations


def verify_findings(findings: list[dict], pv_text: str) -> list[dict]:
    """Stamp each finding: a counterfactual found in ``pv_text`` is confirmed,
    anything else unverified. A counterfactual may offer alternative spellings
    separated by ``|``, and any one hit confirms the finding.
    """
    flat = " ".join(pv_text.split())  # so multi-line assertions still match
    out = []
    for fd in findings:
        needles = [n.strip() for n in str(fd.get("counterfactual", "")).split("|")
                   if n.strip()]
        hit = any(" ".join(n.split()) in flat for n in needles)
        out.append({**fd, "status": "confirmed" if hit else "unverified"})
    return out
