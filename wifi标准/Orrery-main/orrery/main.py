"""The command line. A bare ``orrery`` starts the web console; the subcommands
are ``run`` (one protocol), ``kb``, ``config`` and ``prompt``.

Every command is a shell over ``orrery.api`` or ``orrery.utils`` and holds no
rule of its own. One Ctrl-C during ``run`` leaves the run resumable.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

import click

from orrery.api.corpus_inputs import (
    END_NODE, check_inputs, resolve_lib_inputs, to_node_for,
)
from orrery.pipeline.config import (
    ConfigSource, MissingConfigError, ensure_config, load_config,
)
from orrery.pipeline.main import Run, RunResult
from orrery.services.logs import setup_logger

_DIR = click.Path(exists=True, file_okay=False, path_type=Path)
_FILE = click.Path(exists=True, dir_okay=False, path_type=Path)
_LEVELS = ["debug", "info", "warning", "error"]

#: Inputs a corpus layout answers for, so they are resolved rather than passed
#: through. A flag naming a file outright still wins.
_RESOLVED = ("assumptions", "properties", "claims", "ground_truth",
             "flow", "principals")


async def _drive(r: Run) -> RunResult:
    """Start the run, print where it is going, and let one Ctrl-C stop it."""
    # Printed before any work starts, so an external process scheduler can bind
    # this child to the automatically allocated run.
    click.echo(f"run: {r.run_dir}")
    loop = asyncio.get_running_loop()
    task = loop.create_task(r.start())

    # A signal handler, because try/except on KeyboardInterrupt is unreliable
    # under asyncio. Removing it lets a second Ctrl-C force-quit.
    def _sigint() -> None:
        click.echo("\n■ interrupt received, stopping... "
                   "(press Ctrl-C again to force quit)")
        loop.remove_signal_handler(signal.SIGINT)
        r.control.interrupt()

    loop.add_signal_handler(signal.SIGINT, _sigint)
    return await task


def launch(protocol_name: str, protocol_dir: str | Path,
           config: ConfigSource | Sequence[ConfigSource] | None, *,
           log_level: str = "info",
           overrides: dict | None = None, **options) -> int:
    """Run one protocol and return the process exit code.

    Entry point for any host that wants this behaviour without going through
    argv.
    """
    # Log handlers are installed here; the engine adds the run's own log file
    # once it knows the run directory.
    setup_logger(log_level)
    protocol_dir = Path(protocol_dir)
    cfg = load_config(config or ensure_config(), overrides)

    # Which bands to take from the corpus is a config setting; a flag naming a
    # file outright wins over it.
    ins = cfg["inputs"]
    lib = {k: ins[k] for k in ("lib_principals", "lib_flow", "lib_claims")}
    # --to-node names a node outright and wins; otherwise the configured end
    # point says where to stop. The check below asks about the stop the run
    # will actually make, so a flag cannot turn an end point whose artifacts
    # are all supplied into a run that walks the table doing nothing.
    to_node = options.get("to_node") or to_node_for(ins["end_point"])
    end_point = next((k for k, v in END_NODE.items() if v == to_node),
                     ins["end_point"])
    check_inputs(end_point, **lib)
    given = {k: options.pop(k, None) for k in _RESOLVED}
    resolved = resolve_lib_inputs(
        protocol_dir, options.get("subprotocol"),
        given["assumptions"], given["properties"], given["claims"],
        given["ground_truth"],
        given["flow"] or ins["flow"], given["principals"] or ins["principals"],
        **lib)
    options["to_node"] = to_node

    llm = cfg["llm"]
    key = str(llm.get("api_key") or "")
    # Which credential is about to be spent, printed before anything is spent.
    click.echo(f"llm: {llm['backend']} / {llm['model']} / "
               f"{llm.get('url') or 'official endpoint'} / key {key[:6]}…")
    # Constructed outside the loop and apart from the run itself: what the
    # constructor refuses (an unknown node, a fork without a re-entry point, a
    # taken name) is a usage error and reads as one line, while an exception
    # out of the run is a crash and keeps its traceback.
    try:
        run_obj = Run(protocol_name, protocol_dir, cfg, **options, **resolved)
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        raise click.UsageError(str(e)) from None
    try:
        r = asyncio.run(_drive(run_obj))
    except (asyncio.CancelledError, KeyboardInterrupt):
        # The engine has already closed the run out as interrupted and written
        # work.md.
        click.echo("Interrupted. Re-enter this run with --run-name <its "
                   "directory name> --from-node <node>.", err=True)
        return 130
    click.echo(f"artifacts: {r.run_dir}")
    click.echo(f"{r.status}: {r.run_dir}")
    if r.status != "ok":
        # "check_failed" is a node that ran and answered no; "failed" is a node
        # that broke.
        word = ("differs from the corpus at" if r.status == "check_failed"
                else "failed at")
        click.echo(f"{word} {r.failed_node}: {r.failure}", err=True)
    return 0 if r.status == "ok" else 1


class _CLI(click.Group):
    """The command group, which turns an unfilled config into a plain message.

    ``MissingConfigError`` is an answer rather than a fault, so it leaves as a
    one-line ``ClickException`` carrying the message verbatim, exit code 1. It
    sits on the group, so every command gets it.
    """

    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except MissingConfigError as e:
            raise click.ClickException(
                f"{e}\nThe console fills them in for you: start `orrery` (with "
                f"the same --config) and type them on the settings panel, "
                f"which writes them back to the file it opened.") from None


@click.group(cls=_CLI,
             context_settings={"help_option_names": ["-h", "--help"]},
             invoke_without_command=True)
@click.option("--config", "configs", multiple=True, type=_FILE,
              help="config file; the default is config.yaml at the project "
                   "root, created from config.example.yaml on first use. "
                   "Repeatable: each file is merged over the one before, so a "
                   "later one states only what it changes")
# The console's own options sit on the group, because a bare `orrery` is what
# starts the console.
@click.option("--port", default=8000, show_default=True,
              help="console port (no subcommand)")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="console bind address; the default is this machine only")
@click.option("--reload", is_flag=True,
              help="console: restart on a source change (development)")
@click.option("-v", "--verbose", is_flag=True,
              help="console: also log every round and every tool call")
@click.pass_context
def cli(ctx: click.Context, configs: tuple[Path, ...], port: int,
        host: str, reload: bool, verbose: bool) -> None:
    """Turn a protocol specification into a ProVerif model and run it."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = configs
    if ctx.invoked_subcommand is None:
        # No subcommand starts the console. Imported here so the other
        # commands do not pay for uvicorn and the console's imports.
        from orrery.web.serve import serve

        # `configs`, not `config`: the latter is this module's own `config`
        # subcommand, which is in scope here and would be passed as a path.
        if len(configs) > 1:
            raise click.UsageError(
                f"the console reads one config file; --config was given "
                f"{len(configs)} times. Name the one to open on.")
        serve(str(configs[0]) if configs else None, host=host, port=port,
              reload=reload, verbose=verbose)


@cli.command()
@click.option("--yaml", "as_yaml", is_flag=True,
              help="emit YAML instead: the same vocabularies plus the corpus "
                   "read backwards, protocol -> the subtypes it declares")
@click.option("--out", default=None,
              help="write the vocabulary page to this .html file and open it")
@click.pass_context
def kb(ctx: click.Context, as_yaml: bool, out: str | None) -> None:
    """The assumption and goal vocabularies, generated from the declarations
    that own them, so there is no stored file to go stale."""
    from orrery.api import vocabulary

    if out:
        if not out.endswith(".html"):
            raise click.UsageError(
                f"kb writes an HTML page; {out!r} does not end in .html")
        import webbrowser

        from orrery.api.kb_graph import write_kb_html
        path = write_kb_html(Path(out), corpus_roots=_corpus_roots(ctx))
        click.echo(path)
        webbrowser.open(path.resolve().as_uri())
        return
    click.echo(vocabulary.as_yaml(_corpus_roots(ctx)) if as_yaml
               else vocabulary.as_text(), nl=False)


@cli.command()
@click.pass_context
def config(ctx: click.Context) -> None:
    """The effective config: defaults, the file and any overrides, merged, with
    every credential masked because this output ends up pasted into issues. It
    answers whatever state the config is in, incomplete included, and exits 0.
    """
    from orrery.api import settings

    click.echo(settings.as_yaml(ctx.obj["config"]), nl=False)
    if missing := settings.unfilled(ctx.obj["config"]):
        # On stderr, so `orrery config > somewhere.yaml` stays a config file.
        click.echo(f"\n! still unfilled (???): {', '.join(missing)}\n"
                   f"  the console's settings panel writes them back to the "
                   f"file this was read from: start `orrery`.", err=True)


@cli.command()
@click.option("--out", default=None, type=click.Path(file_okay=False, path_type=Path),
              help="where to write; the default is a prompts/ directory in the "
                   "working directory. Rebuilt on every render, so it must be "
                   "empty or a previous rendering")
def prompt(out: Path | None) -> None:
    """Every request the pipeline can send, one file each, as the model gets
    them and without paying for a run. Reads the test fixture, so it needs a
    source checkout."""
    from orrery.utils.prompts import OUT_DEFAULT, write_all

    write_all(out or OUT_DEFAULT)


def _corpus_roots(ctx: click.Context) -> list[Path]:
    """The corpus root to measure protocol usage in; it may be absent."""
    from orrery.api import settings

    c = settings.corpus(ctx.obj["config"] or settings.default_config_path())
    return [c["lib"]]


@cli.command()
@click.option("--name", "protocol_name", required=True,
              help="the protocol's name (NSSK, EDHOC). The directory cannot "
                   "supply it: its last segment is the protocol for "
                   "academic/NSSK and the version for rfc/EDHOC/draft-08")
@click.option("--dir", "protocol_dir", required=True, type=_DIR,
              help="the protocol directory")
@click.option("--config", "configs", multiple=True, type=_FILE,
              help="config file; the default is config.yaml at the project root, "
                   "created from config.example.yaml on first use. The values it "
                   "must fill in are proverif.executable and the api_key of the "
                   "backend llm.backend names. Repeatable: each file is merged "
                   "over the one before. A caller with settings of its own passes "
                   "them to launch(overrides=...) rather than through a file")
@click.option("--version", default=None,
              help="the protocol version (draft-08, 8446), for a corpus entry "
                   "that has a version layer")
@click.option("--subprotocol", default=None,
              help="analysis target; omitted when the bundle has one target, which is selected by default")
@click.option("--run-name", default=None,
              help="run directory name; omitted allocates the next free "
                   "<protocol><NN>, and an existing run is never overwritten")
@click.option("--work-root", default=None,
              help="where the run directory goes, instead of the configured "
                   "paths.work_root. A relative path is relative to the project "
                   "root, like every path in config, not to the shell's directory")
@click.option("--backend", default=None,
              help="use this llm backend for this run only, instead of the one "
                   "in config; its slot must already hold a key")
@click.option("--manual", is_flag=True,
              help="stop at every node boundary and wait for Enter (same as "
                   "pipeline.mode=manual)")
@click.option("--assumptions", type=_FILE, default=None,
              help="assumptions vocabulary (JSON)")
@click.option("--properties", type=_FILE, default=None,
              help="properties vocabulary (JSON)")
@click.option("--claims", type=_FILE, default=None,
              help="claims — goal x scenario (JSON); defaults to "
                   "claims/claims.json in the protocol directory")
@click.option("--flow", type=_FILE, default=None,
              help="hand extract_flow this mother model .pv instead of "
                   "extracting one; needs --principals. Set inputs.lib_flow: "
                   "true (with inputs.lib_principals: true) in config to take "
                   "the protocol's own flow/flow.pv")
@click.option("--principals", type=_FILE, default=None,
              help="the semantic principals/value inventory the mother model is "
                   "written on. On its own it is legal and leaves the flow model "
                   "to be extracted on it, which is how the flow extraction gets "
                   "measured by itself")
@click.option("--ground-truth", type=_DIR, default=None,
              help="ground-truth directory. A corpus entry answers for itself: "
                   "when the protocol directory carries results/, that is the "
                   "default and cross_check runs without this flag")
@click.option("--from-node", default=None,
              help="resume: continue from this node and reuse the earlier "
                   "artifacts (needs --run-name)")
@click.option("--to-node", default=None,
              help="stop after this node completes; a flow-only run is "
                   "--to-node extract_flow")
@click.option("--fork-from", default=None,
              help="seed this run's upstream artifacts from another run of the "
                   "same protocol, leaving it untouched (needs --from-node)")
@click.option("--log-level", default="info", show_default=True,
              type=click.Choice(_LEVELS, case_sensitive=False),
              help="this package's log level; other libraries stay at warning")
@click.pass_context
def run(ctx: click.Context, protocol_name: str, protocol_dir: Path,
        configs: tuple[Path, ...], work_root: str | None, backend: str | None,
        manual: bool, **options) -> None:
    """Run one protocol: extract the model from its documents, apply the stated
    assumptions, and answer each security property."""
    # --config is accepted on either side of the subcommand, and both sides
    # stack in the order they were written.
    configs = tuple(ctx.obj["config"]) + tuple(configs)
    # The three switches that are config overrides rather than run arguments.
    # A caller with more settings of its own calls `launch(overrides=...)`.
    overrides: dict = {}
    if work_root:
        overrides.setdefault("paths", {})["work_root"] = work_root
    # The slot's own key and url come with the backend: config.py lifts the
    # whole slot.
    if backend:
        overrides.setdefault("llm", {})["backend"] = backend
    if manual:
        overrides.setdefault("pipeline", {})["mode"] = "manual"
    sys.exit(launch(protocol_name, protocol_dir, configs,
                    overrides=overrides or None, **options))

