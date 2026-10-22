<task>
An automatic analysis found that a security goal of a cryptographic protocol does not hold in one scenario, and the attack it found has been replayed. You are given the attack as a numbered script: the honest sessions that take part, what the attacker knows from the start, each message in order, and the point where the goal breaks. Explain the attack to a reader who knows the protocol but has not seen the trace.

Write three things:

- `opening`: what this scenario gives the attacker beyond an ordinary network attacker, read off the scenario's assumptions; or that it gives nothing more.
- `steps`: one note per step of the script, saying in plain words what happens and why it matters.
- `conclusion`: why the goal fails as a result.

The script is ProVerif's own execution, cut down to the messages that matter. When it does not show why a session accepted a message, read the long trace or the model with the tools.
</task>

<constraints>
1. Write exactly one note for each step number in the script, and none for a number it does not have.
2. Say only what the script, the long trace or the model shows. Do not add messages, keys, checks or parties.
3. Put anything taken from the long trace or the model in backticks, copied exactly: a line, a term, a comparison. Names may be written as the script writes them (`I_A` rather than `I_A_3`).
4. The conclusion says what the failure rests on: the protocol's own messages or checks (for example a message that does not name its recipient), or a value the scenario handed the attacker and the goal depends on (for example the long-term key a party authenticates with). Say it in words; do not label it.
5. When the input says the solver reported a replay, the conclusion says that the attacker makes a party accept the same message more than once.
6. When the goal is a weak secret, it breaks by an offline guessing test: the conclusion says what the test computes from the collected messages and why its result tells a right guess from a wrong one. The script may then have no steps at all, when the attacker needs nothing beyond what it knew from the start.
</constraints>

<success_criteria>
- The opening names what the scenario gives the attacker, or says it gives nothing more.
- Every step number of the script has exactly one note.
- Every backticked text appears in the script, the long trace or the model.
- The conclusion names the goal, says why it fails, and says what the failure rests on.
</success_criteria>

<example>
Three steps of Lowe's attack on Needham–Schroeder public key, written the way a reader needs them:

- opening: The attacker is a registered participant with its own key pair, so an honest party may choose it as a peer.
- step 1: A starts a session with the attacker and sends `aenc((I_A,A),pk(I))`, which only the attacker can open.
- step 2: The attacker opens it and encrypts the same content for B, so B receives a message that claims to come from A.
- step 3: B answers with `aenc((I_A,I_B),pk(A))`; the attacker passes it to A unchanged, and nothing in it names B.
- conclusion: auth_b_to_a fails: B finishes believing it talked to A, while A talked to the attacker. It rests on the protocol's messages: the reply in step 3 does not name its sender, so A cannot tell it did not come from the attacker.
</example>
