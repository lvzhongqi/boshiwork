"""data.disclosed: the attacker reads the named value from the start of the
run, before its first use — the unrestricted-read rung. It covers a value
public by protocol definition, a secret exposed by compromise (Basin-Cremers
LKR unrestricted), and the broken-RNG setting for a per-session draw.

The lifetime projection (pvtext.lifetime) picks the writing. ``long_lived``
takes ``branch_leak``, one unreplicated ``out(c, v)`` branch in the main
process's parallel group inside the value's scope; ``per_session`` takes
``draw_leak``, an ``out(c, v)`` right after the ``new`` that draws it. Either
way the leak adds a branch or a line and never renames what the roles run on.

Extraction trigger: "compromised", "leaked", "the attacker knows", "stolen
key"; "P may be dishonest" expands to one entry per long-lived secret of P.
"""

from orrery.nodes.apply.realizers.base import Realizer


class Disclosed(Realizer):
    axis = "data"
    obj = "value"
    subtype = "disclosed"
    instance_key = "of"
    structural = False
    stronger_than = ("chosen",)
    writings = ("branch_leak", "draw_leak")
    writings_by_lifetime = {"long_lived": "branch_leak",
                            "per_session": "draw_leak"}
    params = {
        "of": {"kind": "value_name",
               "note": "which value, named as the model spells it"},
    }
    description = ('The attacker reads the named value from the start of the run — '
     'before its first use. A long-lived value leaks as a main-process '
     'branch; a per-session value leaks at its draw.')

    def verify_applied(self, base_pv: str, new_pv: str,
                       targets: list[dict]) -> list[str]:
        """Check that every out added on the public channel carries a declared
        target term; an added ``out(c, X)`` whose X is not a target leaks a
        value the assumption never named, typically the private exponent
        behind a declared public share. Returns one message per offending
        term, empty when there is nothing this text check can judge."""
        import re
        from orrery.modules.pvtext.parse import blank_comments
        base_pv, new_pv = blank_comments(base_pv), blank_comments(new_pv)
        allowed = {" ".join(str(t.get("of", "")).split()) for t in targets}
        # A target the base model does not spell is a naming question this
        # check cannot adjudicate, so it stands down for the whole round.
        for name in allowed:
            if not re.search(rf"\b{re.escape(name)}\b", base_pv):
                return []
        added = _public_outs(new_pv) - _public_outs(base_pv)
        # Only bare identifiers are judged. A compound term (a tuple covering
        # several batch targets, a wrapped term) passes through to the
        # ordinary checks.
        bare = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")
        return [
            f"disclosed added out(c, {term}) but the target(s) here are "
            f"{sorted(allowed)}; leak exactly the named term, never a value "
            f"it derives from"
            for term in sorted(added)
            if bare.match(term) and term not in allowed
        ]


def _public_outs(pv: str):
    """Multiset of terms sent on the public channel ``c``, whitespace-normalised.
    Balanced-paren scan, so compound terms (``senc((x, A), K)``) come out whole."""
    from collections import Counter
    outs: Counter = Counter()
    i = 0
    while (j := pv.find("out(", i)) >= 0:
        k, depth, buf, args = j + 4, 1, [], []
        while k < len(pv) and depth > 0:
            ch = pv[k]
            if ch == "(":
                depth += 1
                buf.append(ch)
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    args.append("".join(buf))
                else:
                    buf.append(ch)
            elif ch == "," and depth == 1:
                args.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
            k += 1
        i = k
        if len(args) == 2 and args[0].strip() == "c":
            outs[" ".join(args[1].split())] += 1
    return outs
