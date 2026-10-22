"""Starts the console. ``orrery`` with no subcommand is the entry point and
calls ``serve`` below; every switch lives on the click group, not here.

The console opens in playback mode, replaying recorded runs with no model call
at all, so nothing has to be configured first — the top-left switch turns it
live, and that is where a key is needed. With no config.yaml at the project
root the server writes one from config.example.yaml and starts anyway.
"""

from __future__ import annotations

import os
import threading
import webbrowser

import uvicorn


def _banner(url: str, config_path: str) -> None:
    """Print the address, the config in use and what live mode still lacks.

    uvicorn runs at warning level, so this is the only thing the terminal says
    before the server takes it over.
    """
    from orrery.api import playback, settings

    s = settings.summary(config_path)
    # Playback mode reads paths.playback_root, not the work root live mode
    # writes into; both are in this config, and both are printed below.
    mode = playback.Mode(config_path)
    root = mode.root
    found = (len(mode.protocols()["protocols"]) if root.is_dir() else 0)
    print(f"Orrery console  {url}")
    # "recorded" is the word the page's toggle uses for playback mode. Two of
    # the lines below are directories of runs, so each says which it is.
    print("  mode        recorded -- no model call, nothing written")
    print(f"  recordings  {root}"
          + (f"  ({found} protocol{'s' if found != 1 else ''})" if found
             else "  -- nothing to play back here; set paths.playback_root, "
                  "or type a path into the panel"))
    print(f"  config      {s['config_path']}")
    print(f"  work root   {s['work_root']}  (where live mode writes)")
    print(f"  llm         {s['backend']} / {s['model']}")
    print(f"  proverif    {s['proverif']}")
    if s["proverif_problem"]:
        # Said at start, not at the first solve: a live run is refused until
        # this is fixed, and the reason is the setting, not a missing file.
        print(f"  ! proverif.executable cannot run ProVerif: "
              f"{s['proverif_problem']}; live runs refuse to start until it can")
    if s["missing"]:
        # Playback needs none of these; switching to live is one click away.
        print(f"  ! live mode still needs: {', '.join(s['missing'])} "
              f"-- the settings panel writes them back to the config file")
    print("Ctrl-C to stop.", flush=True)


def serve(config: str | None = None, host: str = "127.0.0.1",
          port: int = 8000, reload: bool = False,
          verbose: bool = False) -> None:
    """Start the server. The CLI's default subcommand calls this."""
    from orrery.api import setup_logger
    from orrery.api import settings

    # The console handler goes in here, or a run started from the page narrates
    # itself to run.log alone. Under --reload the app lives in a child process
    # this call cannot reach, so --reload is for development only.
    setup_logger("debug" if verbose else "info")

    # Resolved here so the banner names the file the server will read. It
    # travels in the environment because --reload re-imports the app in a fresh
    # process and only the environment survives that.
    path = config or settings.default_config_path()
    os.environ["ORRERY_CONFIG"] = path
    # 0.0.0.0 is a bind address, not somewhere a browser can go.
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}"
    _banner(url, path)
    # uvicorn.run blocks, so a short timer opens the page once the server is
    # listening. On a headless box webbrowser finds no opener and returns False
    # silently; the banner has already printed the URL.
    opener = threading.Timer(1.0, webbrowser.open, args=(url,))
    opener.daemon = True
    opener.start()
    uvicorn.run("orrery.web.server:app", host=host, port=port,
                reload=reload, log_level="warning")
