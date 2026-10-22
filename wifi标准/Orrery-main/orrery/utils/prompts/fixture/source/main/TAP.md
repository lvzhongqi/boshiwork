# Toy Authentication Protocol (TAP)

Fixture specification — not a real protocol, and never analysed for its own
sake. It exists so the tests and the prompt preview have a corpus that does not
come from VerdictBench: a change here changes the fixture, and nothing about any
real protocol. It is deliberately short, because the corpus is data and a full
specification would bury whatever is being looked at.

## 1 Introduction

TAP establishes mutual authentication between an initiator A and a responder B
that already know each other's public keys. Both parties are registered with a
key directory before any run begins. The protocol is three messages long and
assumes no online trusted third party.

## 2 Protocol Participants

Two principals take part. A is the initiator: it starts every run and chooses
the peer it wants to talk to. B is the responder: it answers whoever reaches
it. Both are honest principals running the protocol as specified.

## 3 Notation

- `A`, `B` — party identities.
- `PKA`, `PKB` — the parties' public keys; `SKA`, `SKB` the matching private keys.
- `KAB` — a long-term symmetric key shared by A and B.
- `I_A`, `I_B` — fresh random values, one per party per run.
- `{m}K` — encryption of `m` under key `K`.

## 4 Protocol Description

The message flow is:

    1. A -> B :  {I_A, A}PKB
    2. B -> A :  {I_A, I_B}PKA
    3. A -> B :  {I_B}KAB

Message 1 carries A's fresh value and its identity, encrypted under B's public
key. Message 2 returns A's value together with B's own fresh value, encrypted
under A's public key; A accepts only if the returned value equals the one it
sent. Message 3 confirms receipt of B's value under the shared key, at which
point B accepts.

## 5 Assumptions

Before any run, A holds `SKA`, its own `PKA`, the peer identity `B`, B's public
key `PKB`, and the shared key `KAB`. B holds the mirror image. The key
directory maps each identity to its public key.

The key directory is open: any party may register an identity and a public key
with it, so the binding between an identity and its key is not vouched for by
any authority. Long-term keys are not assumed to survive indefinitely — a run
should be analysed both with and without the disclosure of `KAB` after the
session ends.

## 6 Security Properties

The protocol is intended to keep `I_A` and `I_B` secret from anyone other than
A and B, and to give each party injective agreement with the other on the run
they have just completed.

## 7 References

None. This document is self-contained.
