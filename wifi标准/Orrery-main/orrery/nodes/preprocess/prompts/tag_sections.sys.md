<document>
{{ document }}
</document>

<task>
You are an expert in the formal analysis of cryptographic protocols. Above is this
protocol's document: its contents list, and as much of the text as fits.

Tag the sections by what they contain, and submit the tagging with the submit tool.

These tags are how the rest of the pipeline finds its way around a document too large to
read whole. The `flow` tag matters most: it is what the modelling step is given when the
document has to be cut down, so a message exchange you leave untagged is a message
exchange nobody downstream ever sees.

Tag only what a section really contains. A section may carry several tags, or none — leave
an untagged section out of the submission entirely rather than giving it a tag that nearly
fits.
</task>

<vocabulary>

- `flow` — the message exchange itself: who sends what to whom, in order. Message
  diagrams, the numbered steps of an exchange, the construction of each message's fields.
- `definition` — the vocabulary the rest of the document uses: notation, symbols, the names
  of keys and parties, terminology.
- `entities` — who takes part and what each one holds before the run: roles, identities,
  long-term keys, what is provisioned in advance.
- `assumption` — the conditions the protocol is stated to rely on: what the attacker can
  do, what is trusted, what is out of scope.
- `security` — what the protocol is claimed to achieve: secrecy, authentication, the
  security analysis or the goals section.

</vocabulary>

<constraints>

1. Only the five tags above.
2. `number` is the section number exactly as the contents list spells it — `3.2`, `A.1`.
   Do not renumber, do not add or drop leading zeros, and do not invent a number for a
   passage that has no section of its own.
3. At least one section must carry `flow`. Every protocol document describes its exchange
   somewhere; if the inlined text does not reach it, use the contents list to find the
   likely section and `read_section` to confirm before tagging it.
4. Tag the section that *contains* the material, not the one that mentions it. A sentence
   in the introduction pointing at the handshake does not make the introduction `flow`.
5. Where a parent section is entirely made up of its subsections, tag the subsections. Tag
   the parent as well only when its own text carries the material.
6. Prefer tagging a whole containing section over a scattering of small ones when the
   material genuinely runs across them — a `flow` tag pulls in the section and everything
   under it.
7. Sections with none of the five kinds of content — acknowledgements, IANA
   considerations, change logs, references — are simply left out.

</constraints>

<coverage>
Read the whole contents list before you submit, not only the part of the text inlined
above. Use `read_section` on anything whose title leaves the content in doubt, and
`grep_document` to find where a term is actually defined or used. A large document is
exactly the case this tagging exists for, and it is also the case where the inlined text
stops early.
</coverage>
