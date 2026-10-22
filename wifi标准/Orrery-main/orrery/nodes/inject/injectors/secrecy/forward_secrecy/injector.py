"""Injector for Secrecy.forward_secrecy. The logic lives in base; this file only
declares its identity, and the prompt is the .md of the same name."""
from orrery.nodes.inject.injectors.secrecy.base import SecrecyType


class ForwardSecrecy(SecrecyType):
    subtype = "forward_secrecy"
    # The phase split is itself the model change: `phase 1; out(c, sk)` hands
    # the attacker the long-term key partway through, which answers every other
    # secrecy question sharing the file. So this subtype gets its own .pv.
    perturbs_model = True
    description = (
        "Forward secrecy: the long-term key reaches the attacker after the "
        "session completes, and the question is whether the earlier session's "
        "secrets stay safe.")
    requires_assumption = {
        "axis": "data",
        # Any rung on which the key actually reaches the attacker. The premise
        # is "the key leaks", not "it leaks at this particular moment": a key
        # the attacker holds from the start satisfies it a fortiori, and that
        # world is still a real question (TLS 1.3's 1-RTT data stays secret
        # under a compromised server signing key).
        "subtypes": ("disclosed", "leaked_after_session",
                     "leaked_after_correct_session"),
        "why": (
            'Forward secrecy **means** "the long-term key reaches the attacker '
            "and the secrets of earlier sessions are still safe\". That leak is "
            "not an optional piece of environment, it is the goal's own "
            "premise: without it in the claim there is no phase in the model, "
            "the query degenerates into plain secrecy, and the resulting true "
            "says nothing at all (EDHOC symmetric once produced exactly such a "
            "false positive). The premise is written as an assumption rather "
            "than invented by the injector because **which key leaks is "
            "protocol information**: symmetric leaks one PSK, asymmetric leaks "
            "both skU and skV, and an injector that guesses wrong still "
            "produces a verdict."),
    }
