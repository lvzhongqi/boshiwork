# Orrery

Orrery turns a protocol specification into a ProVerif model and runs it, so that
a security question stated against a document is answered by a machine-checked
verdict instead of by hand.

## Run it

Install first (needs Python 3.11+ and a ProVerif binary on disk):

```bash
pip install -e .
```

Configuration lives in `config.yaml`, created from `config.example.yaml` on
first use — that example file is the annotated reference, and `config.yaml` is
gitignored because it holds your API key. Only two things must be filled in:

- `proverif.executable` — absolute path to the ProVerif binary.
- the `api_key` of the profile named by `llm.backend`, under
  `llm.profiles.<backend>` (each backend keeps its own `api_key` / `url` /
  `model`, so switching backends and switching back costs nothing).

Both can be typed on the console's page, which writes them straight back to
`config.yaml`. Start it with:

```bash
orrery
```

## Reproduce the paper results

No API key is needed. This reads the published `runs/` and VerdictBench, then
writes the paper macros plus Markdown, LaTeX, CSV, and JSON tables to
`reproduced/`:

```bash
python -m experiments.reproduce
```


某一个轮次：
RunningA(会话密钥x) -> CommitB(会话密钥x) 

另一轮次：
RunningA(会话密钥y) -> CommitB(会话密钥y)

inj 不满足
inj ==> inj 