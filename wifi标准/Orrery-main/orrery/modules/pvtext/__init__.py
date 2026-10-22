"""pvtext: reads and writes `.pv` as text, with no intermediate representation.

Applying assumptions and injecting goals are edits on the flow model's text, so
this layer answers only concrete questions: which roles the text defines and
what their process signatures are (``parse``), plus mechanical rewrites such as
making named channels private (``edits``). Only what a regex can extract
reliably is extracted; anything else raises. Running ProVerif lives in the
checks layer, and this layer depends on the standard library alone.
"""
