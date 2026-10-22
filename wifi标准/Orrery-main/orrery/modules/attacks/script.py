"""An attack graph as a script a person can step through.

Lanes are the honest sessions — one per named process start — plus the
attacker. Steps are the messages in the order the attacker's clock gives them,
each one of four kinds:

- ``send``   an honest session sends and the attacker takes it;
- ``relay``  the attacker hands a session's message to another session unchanged;
- ``inject`` the attacker hands over something it already knew;
- ``forge``  the attacker computed the message;
- ``private`` one session hands another a message on a channel the attacker
  cannot see (a step the attacker takes no part in, but the attack runs
  through).

What is left out, and why, so the script reads as the attack and not as the
whole execution — everything left out is listed in ``omitted``:

- an output whose first use is a relay: the relay shows both ends;
- a session that never receives anything and whose outputs nothing reads: it
  took no part;
- an output read only by the goal (a secrecy probe): it is shown as part of
  the goal, not as a protocol message;
- an output nothing reads, once the attacker's last message has been sent.

What the attacker computed for a forged message comes from lining its recipe up
against the value (``terms.computed``). The rows a session executed between
messages — comparisons, events, table reads — travel as notes on that
session's next step. The goal closes the script: for a knowledge goal, the
values the attacker's final recipe computed; for an event goal, the event and
the executed events it should have matched, argument by argument; for a weak
secret, the offline test the attacker runs on a guess (``guess``). An offline
guessing attack is still a message sequence up to that test: what the attacker
collects is the attack, so an output only the test reads is a step of its own
and its session takes part even if it never receives anything.

Everything shown carries ``terms.display`` names, except the names the
attacker made up — those that no session ever wrote — which keep ProVerif's
suffixes, since ``a`` and ``a_1`` are different values; ``printed`` keeps
ProVerif's own form beside it. A recipe's slots are spelled out in ``reads``
(``~M_3 = K_AP``), so a reader sees what the attacker used without looking up
where each slot came from.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from orrery.modules.attacks.graph import Graph, Message, within
from orrery.modules.attacks.names import Definition, bindings, stand_ins
from orrery.modules.pvtext.parse import event_raisers, injective_events
from orrery.modules.attacks.terms import (
    Term, TermError, computed, display, names, parse, slots, split_top,
)

ATTACKER = "attacker"
#: Row keywords worth showing on a step: what a session checked or recorded.
_NOTED = ("if", "event", "get", "insert")
_KNOWS = re.compile(r"^The attacker has the message (.*)$", re.S)
#: ProVerif's weak-secret goal (display.ml, WeakSecrGoal), its line breaks
#: already joined: the test on the guess, what the attacker knows, and which
#: guess the test tells apart from the secret.
_GUESS = re.compile(
    r"^The attacker tests whether\s*(?P<test>.*?)\s*(?P<fail>is fail\s*)?knowing"
    r"\s*(?P<known>.*?)\.\s*This allows the attacker to know whether\s*"
    r"(?P<guess>.*?)\s*=\s*(?P<secret>.*?)\.?$", re.S)
_END_OR_BEGIN = re.compile(r"^(end|begin)_?")


@dataclass
class Lane:
    id: str
    role: str                   #: the named process; "" when the model names none
    bindings: list[str] = field(default_factory=list)   #: its start parameters


@dataclass
class Note:
    lane: str                   #: the session that executed the row
    point: int | None
    word: str
    text: str


@dataclass
class Step:
    n: int
    kind: str                   #: send | relay | inject | forge | private
    src: str                    #: lane id
    dst: str                    #: lane id
    value: str                  #: the message, display form
    recipe: str = ""            #: how the attacker built it (inject / forge)
    reads: list[str] = field(default_factory=list)      #: ``slot = value``
    computed: list[str] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    printed: str = ""           #: the message as ProVerif printed it
    #: The message with stand-in names (``modules/attacks/names``), and the
    #: names it brings in, each drawn on the lifeline of whoever made it.
    label: str = ""
    defs: list[Definition] = field(default_factory=list)


@dataclass
class Outcome:
    kind: str                   #: knowledge | event | guess | other
    text: str
    lane: str = ""              #: the session the goal fired in, if any
    computed: list[str] = field(default_factory=list)
    probe: str = ""             #: the output the knowledge goal reads
    #: The session that sent that probe: whose view of the secret the goal
    #: checks, which the probe's value alone does not say.
    probe_lane: str = ""
    counterparts: list[dict] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    #: A weak secret's offline test: ``test`` is ``equal`` (``left`` =
    #: ``right``) or ``fail`` (``left`` fails), ``known`` spells out the slots
    #: it reads, and ``name`` is how the guess is written in both.
    guess: dict = field(default_factory=dict)
    #: The attacker's last work on the way to the goal (``names.Definition``).
    defs: list[Definition] = field(default_factory=list)
    #: An authentication goal's other half: ``{"event", "roles", "injective",
    #: "status"}`` — the ``begin`` the goal asks for, the processes that raise
    #: it in the model, whether the query is injective, and what became of it
    #: (``missing`` | ``differs`` | ``reused``).
    expected: dict = field(default_factory=dict)
    #: A secrecy goal observed at one holder: ``{"name", "holder", "value"}``,
    #: the target as the model names it, the principal holding it, and the
    #: value it had in the session the probe came from.
    secret: dict = field(default_factory=dict)


@dataclass
class Script:
    lanes: list[Lane]
    initial: list[str]          #: what the attacker knew before any session ran
    steps: list[Step]
    outcome: Outcome
    omitted: list[dict]         #: what the script leaves out, and why
    #: Names for what the initial process made, drawn before the first step.
    setup: list[Definition] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


class ScriptError(ValueError):
    """A graph whose messages do not fit together as one execution."""


def build(graph: Graph, goal: str | None = None,
          model: str | None = None) -> Script:
    """The script of one attack graph. ``goal`` is the goal id the graph
    answers, which spells out a secrecy witness's name (``_secret``);
    ``model`` is the solver file it ran, which says which process should have
    answered an authentication goal (``_expected``)."""
    lanes = _lanes(graph)

    def lane_of(path: str) -> str | None:
        hits = [ln.id for ln in lanes if within(path, ln.id)]
        return max(hits, key=len) if hits else None

    msgs = graph.messages
    made_up = _made_up(graph)

    def show(text: str) -> str:
        return display(text, made_up)

    goal_recipe, goal_value = _goal_terms(graph)
    guess = _guess_terms(graph)
    goal_slots = set(slots(goal_recipe)) if goal_recipe is not None else set()
    if guess is not None:
        goal_slots = {x for t in guess["terms"] for x in slots(t)}
    uses: dict[str, list[int]] = {}             # slot → inputs reading it
    for i, msg in enumerate(msgs):
        if msg.direction == "in":
            for slot in slots(_parse(msg.recipe)):
                uses.setdefault(slot, []).append(i)
    receiving = {lane_of(m.path) for m in msgs if m.direction == "in"}
    # A session takes part when it receives, or when something reads what it
    # sent: an input, or a weak secret's offline test.
    read = set(uses) | (goal_slots if guess is not None else set())
    taking_part = receiving | {
        lane_of(m.path) for m in msgs if m.direction == "out"
        and {x for x, _ in _output_slots(m)} & read}
    handed = [(p, lane_of(p.src), lane_of(p.dst)) for p in graph.private]
    taking_part |= {x for _, a, b in handed if a and b for x in (a, b)}
    last_input = max((i for i, m in enumerate(msgs) if m.direction == "in"),
                     default=-1)

    produced: dict[str, str | None] = {}       # slot → lane that output it
    held: dict[str, str] = {}                  # slot → the value it holds
    initial: list[str] = []
    memo: dict[str, str] = {}                  # sub-recipe → value
    timed: list[tuple[float, Step]] = []
    omitted: list[dict] = []
    read_values: dict[int, list[tuple[str, str]]] = {}   # step → (slot, printed)
    recipe_of: dict[int, str] = {}                       # step → printed recipe
    probe, probe_lane, probe_printed = "", "", ""
    for i, msg in enumerate(msgs):
        lane = lane_of(msg.path)
        if msg.direction == "out":
            bound = _output_slots(msg)
            for slot, value in bound:
                produced[slot] = lane
                held[slot] = value
            bound = [slot for slot, _ in bound]
            if lane is None:
                initial.append(show(msg.value))
                continue
            first = [uses[s][0] for s in bound if s in uses]
            if len(bound) == 1 and first and \
                    _single_slot(msgs[first[0]].recipe) == bound[0]:
                continue            # the relay that first reads it shows both ends
            if lane not in taking_part:
                omitted.append(_left_out(msg, lane, "session took no part", show))
                continue
            read_by_goal = not first and set(bound) & goal_slots
            if read_by_goal and guess is None:
                probe, probe_lane, probe_printed = show(msg.value), lane, msg.value
                continue
            if not first and not read_by_goal and i > last_input:
                omitted.append(_left_out(msg, lane, "read by nothing after the attack",
                                         show))
                continue
            timed.append((msg.time, Step(0, "send", lane, ATTACKER,
                                         show(msg.value), printed=msg.value)))
            continue
        if lane is None:
            raise ScriptError(f"an input to {msg.path}, which runs no session")
        recipe, value = _parse(msg.recipe), _parse(msg.value)
        missing = [x for x in slots(recipe) if x not in produced]
        if missing:
            raise ScriptError(f"{missing[0]} is read before any output bound it")
        reads = [f"{x} = {show(held[x])}" for x in slots(recipe)]
        raw_reads = [(x, held[x]) for x in slots(recipe)]
        if recipe.is_slot and produced[recipe.head] is not None:
            step = Step(0, "relay", produced[recipe.head], lane,
                        show(msg.value), printed=msg.value)
        elif recipe.is_slot or recipe.args is None:
            step = Step(0, "inject", ATTACKER, lane, show(msg.value),
                        recipe=show(msg.recipe), reads=reads,
                        printed=msg.value)
        else:
            found = computed(recipe, value)
            for sub, val in found:
                memo[str(sub)] = str(val)
            step = Step(0, "forge", ATTACKER, lane, show(msg.value),
                        recipe=show(msg.recipe), reads=reads,
                        computed=_unique(show(str(v)) for _, v in found),
                        printed=msg.value)
        read_values[id(step)] = raw_reads
        recipe_of[id(step)] = msg.recipe
        timed.append((msg.time, step))

    for p, src, dst in handed:
        if src is None or dst is None:
            omitted.append({"lane": src or dst or "", "value": show(p.value),
                            "why": "handed over outside the sessions"})
            continue
        timed.append((p.time, Step(0, "private", src, dst, show(p.value),
                                   printed=p.value)))
    timed.sort(key=lambda x: x[0])
    kept = [ln for ln in lanes if ln.id in taking_part]
    for ln in lanes:
        if ln.id not in taking_part:
            omitted.append({"lane": ln.id, "role": ln.role,
                            "why": "session took no part"})
    for n, (_, step) in enumerate(timed, 1):
        step.n = n
    sources = bindings(((nd.time, nd.path, nd.rows) for nd in graph.nodes.values()),
                       lane_of)
    labels, brought, setup, named = stand_ins(
        [(st.n, st.src, st.kind in ("inject", "forge"), st.printed)
         for _, st in timed], sources, show,
        read=[v for pairs in read_values.values() for _, v in pairs])
    for (_, st), label, defs in zip(timed, labels, brought):
        st.label, st.defs = label, defs
        if id(st) in read_values:
            st.reads = [f"{x} = {named.get(v) or show(v)}"
                        for x, v in read_values[id(st)]]
    carried = {st.printed: st.label for _, st in timed}

    def recipe_text(t: Term) -> str:
        """A recipe the way a person reads it: each slot as the name or the
        label of the message it holds, a projection as ``.k``."""
        if t.is_slot:
            v = held[t.head]
            return named.get(v) or carried.get(v) or show(v)
        if t.args is None:
            return show(t.head)
        m = _PROJECTION.fullmatch(t.head)
        if m and len(t.args) == 1:
            return f"{recipe_text(t.args[0])}.{m.group(1)}"
        inner = ",".join(recipe_text(a) for a in t.args)
        return f"{t.head}({inner})" if t.head else f"({inner})"

    announced: set[str] = set()

    def work(recipe: Term, value: Term) -> list[Definition]:
        """What the attacker did to build ``value`` from ``recipe``: the
        names it made up, first time each, then what it worked out."""
        out = []
        order = re.findall(r"[A-Za-z][\w']*", str(recipe))
        fresh = [x for x in dict.fromkeys(order)
                 if x in names(recipe) and x in made_up and x not in announced]
        if fresh:
            announced.update(fresh)
            out.append(Definition(ATTACKER, ", ".join(show(x) for x in fresh), "",
                                  "", kind="new"))
        for sub, val in computed(recipe, value):
            v = str(val)
            out.append(Definition(ATTACKER, named.get(v) or carried.get(v) or show(v),
                                  recipe_text(sub), show(v), kind="derive"))
        return out

    for _, st in timed:
        if st.kind != "forge":
            continue
        recipe = _parse(recipe_of[id(st)])
        st.defs = work(recipe, _parse(st.printed)) + st.defs
        if not any(d.name == st.label for d in st.defs):
            # the attacker's own message is always boxed, however short
            st.defs.append(Definition(ATTACKER, f"msg{st.n}", st.label, st.value))
            st.label = f"msg{st.n}"
    outcome = (_guess_outcome(guess, held, show) if guess is not None
               else _outcome(graph, goal_recipe, goal_value, memo, lane_of, show))
    outcome.probe, outcome.probe_lane = probe, probe_lane
    if goal_recipe is not None and goal_value is not None:
        outcome.defs = [d for d in work(goal_recipe, goal_value)
                        if d.kind == "new" or d.value != outcome.text]
    # A direct query names its target itself; only a witness needs reading.
    if outcome.kind == "event":
        outcome.expected = _expected(outcome, model)
    if probe_printed and goal is not None and outcome.text.startswith("witness_"):
        outcome.secret = _secret(goal, outcome.text, probe_printed,
                                 lambda v: named.get(v) or carried.get(v) or show(v))
    _attach_notes(graph, lane_of, timed, outcome, show)
    return Script(lanes=_ordered(kept, timed), initial=_unique(initial),
                  steps=[s for _, s in timed], outcome=outcome, omitted=omitted,
                  setup=setup)


# ── lanes ────────────────────────────────────────────────────────────────

def _lanes(graph: Graph) -> list[Lane]:
    starts = sorted((n for n in graph.nodes.values() if n.begins),
                    key=lambda n: (n.path.count("_"), n.path))
    lanes: list[Lane] = []
    for node in starts:
        if any(within(node.path, ln.id) for ln in lanes):
            continue                # a process called from inside a session
        lanes.append(Lane(node.path, node.begins, [
            display(r.text) for r in node.rows if r.word == "let"]))
    # A process the model runs without naming it — a whole model written that
    # way, or a replicated server inlined beside named roles — is a lane of its
    # own, named by nothing, once it receives or is handed something.
    acting = [m.path for m in graph.messages if m.direction == "in"]
    acting += [x for p in graph.private for x in (p.src, p.dst)]
    for path in sorted(set(acting), key=lambda x: (x.count("_"), x)):
        if not any(within(path, ln.id) for ln in lanes):
            lanes.append(Lane(path, ""))
    return lanes


def _ordered(lanes: list[Lane], timed: list[tuple[float, Step]]) -> list[Lane]:
    """Lanes in the order they first take part."""
    first: dict[str, int] = {}
    for n, (_, step) in enumerate(timed):
        for lane in (step.src, step.dst):
            first.setdefault(lane, n)
    return sorted(lanes, key=lambda ln: first.get(ln.id, len(timed)))


# ── messages ─────────────────────────────────────────────────────────────

def _parse(text: str) -> Term:
    try:
        return parse(text)
    except TermError as e:
        raise ScriptError(f"cannot read the term {text!r}: {e}") from None


def _single_slot(recipe: str) -> str | None:
    t = _parse(recipe)
    return t.head if t.is_slot else None


def _output_slots(msg: Message) -> list[tuple[str, str]]:
    """``~M_3 = v`` binds one slot; ``(~M_10,~M_11) = (A,I)`` binds each, and
    so does a tuple nested in the output, ``((~M_1,~M_2),~M_3)``, or a data
    constructor ProVerif takes apart the same way, ``f(~M_1,~M_2) = f(a,b)``."""
    def bind(r: Term, v: Term) -> list[tuple[str, str]] | None:
        if r.is_slot:
            return [(r.head, str(v))]
        if not (r.args and r.head == v.head and v.args
                and len(v.args) == len(r.args)):
            return None
        out = []
        for a, b in zip(r.args, v.args):
            got = bind(a, b)
            if got is None:
                return None
            out += got
        return out

    if _parse(msg.recipe).is_slot:
        return [(msg.recipe, msg.value)]
    found = bind(_parse(msg.recipe), _parse(msg.value))
    if found is None:
        raise ScriptError(f"an output bound by {msg.recipe!r}, which is not slots")
    return found


def _made_up(graph: Graph) -> frozenset[str]:
    """The names the attacker made up: those that first appear in one of its
    recipes. A session that received such a name binds and echoes it later,
    so only the order tells the two apart."""
    first: dict[str, tuple[float, bool]] = {}     # name → (time, in a recipe)

    def seen(name: str, time: float, by_attacker: bool) -> None:
        if name not in first or time < first[name][0]:
            first[name] = (time, by_attacker)

    for node in graph.nodes.values():
        for r in node.rows:
            for name in re.findall(r"[A-Za-z][\w']*", r.text):
                seen(name, node.time, False)
    for msg in graph.messages:
        if msg.direction == "out":
            for name in names(_parse(msg.value)):
                seen(name, msg.time, False)
        else:
            for name in names(_parse(msg.recipe)):
                seen(name, msg.time - 0.25, True)
    return frozenset(n for n, (_, attacker) in first.items() if attacker)


def _left_out(msg: Message, lane: str, why: str, show) -> dict:
    return {"lane": lane, "value": show(msg.value), "why": why}


def _unique(items) -> list[str]:
    out: list[str] = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


# ── the goal ─────────────────────────────────────────────────────────────

def _goal_terms(graph: Graph) -> tuple[Term | None, Term | None]:
    if graph.goal_path:
        return None, None
    m = _KNOWS.match(graph.goal_text)
    if m is None:
        return None, None
    parts = split_top(m.group(1))
    if parts is None:
        raise ScriptError(f"the goal {graph.goal_text!r} names no value")
    return _parse(parts[0]), _parse(parts[1])


_PROJECTION = re.compile(r"(\d+)-proj-\d+-tuple")


def _expected(outcome: Outcome, model: str | None) -> dict:
    """The ``begin`` an authentication goal asks for beside the ``end`` that
    ran. An agreement holds when every end has a begin saying the same thing,
    and an injective one when they pair off one to one, so an attack is one of
    three things: no begin ran at all, one ran but says something else, or one
    ran and was matched twice. The model names the process that raises it."""
    parsed = _event_parts(outcome.text)
    head = parsed[0] if parsed else ""
    stem = _END_OR_BEGIN.sub("", head)
    name, roles, injective = "", [], False
    if model:
        raisers = event_raisers(model)
        same = [n for n in raisers
                if n != head and _END_OR_BEGIN.sub("", n) == stem]
        if len(same) == 1:
            name, roles = same[0], raisers[same[0]]
        injective = head in injective_events(model)
    matched = [c for c in outcome.counterparts if c["differ"] == []]
    status = ("missing" if not outcome.counterparts
              else "reused" if matched else "differs")
    return {"event": name, "roles": roles, "injective": injective,
            "status": status}


def _secret(goal: str, witness: str, probe: str, say) -> dict:
    """What a secrecy witness stands for. The injector names it
    ``witness_<goal>_<value>_<holder>`` (``_<value>`` absent from earlier
    runs, which leaves ``name`` empty) and sends it wrapped under the
    holder's value of the target, ``wenc_<type>(witness, value)`` (see the
    Secrecy injectors' rules), so the name gives the target and the holder
    and the probe gives what the target was in that session, said by
    ``say`` (a stand-in name where there is one). Raises
    ScriptError on a witness or a probe of any other shape."""
    head = f"witness_{goal}_"
    if not witness.startswith(head) or not witness[len(head):]:
        raise ScriptError(f"the secrecy witness {witness!r} is not named "
                          f"{head}[<value>_]<holder>")
    # Earlier injectors left the value out: witness_<goal>_<holder>.
    rest = witness[len(head):]
    target, holder = rest.rsplit("_", 1) if "_" in rest else ("", rest)
    t = _parse(probe)
    if not (t.args and len(t.args) == 2 and t.head.startswith("wenc_")):
        raise ScriptError(f"the probe {probe!r} is not wenc_<type>(witness, value)")
    return {"name": target, "holder": holder, "value": say(str(t.args[1]))}


def _guess_terms(graph: Graph) -> dict | None:
    """A weak-secret goal's parts, or None for any other goal. Raises
    ScriptError on a weak-secret goal it cannot read."""
    if graph.goal_path or not graph.goal_text.startswith("The attacker tests whether"):
        return None
    m = _GUESS.match(graph.goal_text)
    if m is None:
        raise ScriptError(f"the weak-secret goal {graph.goal_text!r} is not in "
                          f"the form ProVerif prints")
    if m["fail"]:
        test, terms = "fail", [_parse(m["test"])]
    else:
        parts = split_top(m["test"])
        if parts is None:
            raise ScriptError(f"the offline test {m['test']!r} compares nothing")
        test, terms = "equal", [_parse(x) for x in parts]
    known, rest = [], m["known"]
    while rest:
        head = split_top(rest, ",")
        item, rest = (head if head is not None else (rest, ""))
        sides = _sides(item)
        if sides is None:
            raise ScriptError(f"the known value {item!r} names no slot")
        known.append(sides)
    return {"test": test, "terms": terms, "known": known,
            "name": m["guess"], "secret": m["secret"]}


def _sides(item: str) -> tuple[str, str] | None:
    """``~M = t`` (or ProVerif's ``x = ~M = t``) as ``(slot recipe, value)``."""
    parts, rest = [], item
    while (cut := split_top(rest)) is not None:
        parts.append(cut[0])
        rest = cut[1]
    return (parts[-1], rest) if parts else None


def _guess_outcome(guess: dict, held: dict[str, str], show) -> Outcome:
    terms = [show(str(t)) for t in guess["terms"]]
    return Outcome("guess", show(guess["secret"]), guess={
        "test": guess["test"], "name": guess["name"],
        "left": terms[0], "right": terms[1] if len(terms) > 1 else "",
        "known": [f"{r} = {show(held.get(r, v))}" for r, v in guess["known"]]})


def _outcome(graph: Graph, recipe: Term | None, value: Term | None,
             memo: dict[str, str], lane_of, show) -> Outcome:
    if graph.goal_path:
        node = graph.nodes[graph.goal_node]
        events = [r for r in node.rows if r.word == "event"]
        if not events:
            raise ScriptError(f"the goal node {node.id} executed no event")
        goal = events[-1].text
        return Outcome("event", show(goal), lane=lane_of(node.path) or "",
                       counterparts=_counterparts(graph, goal, show))
    if recipe is None or value is None:
        return Outcome("other", show(graph.goal_text))
    used: list[str] = []

    def walk(t: Term) -> None:
        if str(t) in memo:
            used.append(show(memo[str(t)]))
            return
        for a in t.args or ():
            walk(a)

    walk(recipe)
    return Outcome("knowledge", show(str(value)),
                   computed=_unique([*used, show(str(value))]))


def _event_parts(text: str) -> tuple[str, list[str]] | None:
    try:
        t = parse(text)
    except TermError:
        return None
    return t.head, [str(a) for a in (t.args or ())]


def _counterparts(graph: Graph, goal: str, show) -> list[dict]:
    """Executed events the goal event answers to — same name once a leading
    ``end``/``begin`` word is set aside — and where their arguments differ.
    Empty when the model names its events otherwise, or when no such event ran."""
    parsed = _event_parts(goal)
    if parsed is None:
        return []
    name, args = parsed
    stem = _END_OR_BEGIN.sub("", name)
    if stem == name:
        return []
    out = []
    for node in sorted(graph.nodes.values(), key=lambda n: n.time):
        for r in node.rows:
            if r.word != "event":
                continue
            other = _event_parts(r.text)
            if other is None or other[0] == name \
                    or _END_OR_BEGIN.sub("", other[0]) != stem:
                continue
            same_arity = len(args) == len(other[1])
            out.append({
                "event": show(r.text), "point": r.point,
                "differ": [i for i, (a, b) in enumerate(zip(args, other[1]))
                           if a != b] if same_arity else None})
    return out


# ── notes ────────────────────────────────────────────────────────────────

def _attach_notes(graph: Graph, lane_of, timed: list[tuple[float, Step]],
                  outcome: Outcome, show) -> None:
    """Each noted row travels on its session's first step at or after it; a
    row after the last such step belongs to the goal."""
    for node in sorted(graph.nodes.values(), key=lambda n: n.time):
        if node.begins or node.id == graph.goal_node:
            continue
        lane = lane_of(node.path)
        rows = [r for r in node.rows if r.word in _NOTED]
        if lane is None or not rows:
            continue
        target = next((s for t, s in timed
                       if t >= node.time and lane in (s.src, s.dst)), None)
        notes = [Note(lane, r.point, r.word, show(r.text)) for r in rows]
        (target.notes if target is not None else outcome.notes).extend(notes)
