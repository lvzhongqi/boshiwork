"""Running ProVerif as a subprocess: execute a .pv file under a timeout and a
hard kill, and parse nothing. This layer reports stdout, stderr, the return code
and whether it timed out; interpretation belongs to outcome.py. Every call
leaves both halves on disk with no temporary copy — ``<log_to>.pv`` is the file
that was executed, ``<log_to>.txt`` the raw output — so a solve is reproducible.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import time

from dataclasses import dataclass
from pathlib import Path

# infra logs directly rather than emitting events: a subprocess call belongs to
# no run and no node, so there is no event that could carry it.
logger = logging.getLogger(__name__)


_MEMORY_FRACTION = 0.65
_MIN_MEMORY_LIMIT_BYTES = 8 * 1024 ** 3
#: The most of its memory one solver may take, whatever the floor says: the
#: rest is the console's, the other solvers' and the kernel's, and it is the
#: margin that lets this runner stop a solver before the kernel does.
_MAX_MEMORY_FRACTION = 0.9
_MEMORY_POLL_S = 0.25

#: Where a cgroup filesystem is mounted, and where this process's own cgroup
#: is named. Module attributes so a test can point them at a fixture tree.
_CGROUP_ROOT = Path("/sys/fs/cgroup")
_SELF_CGROUP = Path("/proc/self/cgroup")


def _physical_memory_bytes() -> int:
    """Return installed physical memory, or fail before starting the solver."""
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError) as e:
        raise RuntimeError(
            "cannot determine physical memory for the ProVerif limit") from e
    total = int(page_size) * int(page_count)
    if total <= 0:
        raise RuntimeError(
            f"invalid physical memory size for the ProVerif limit: {total}")
    return total


def solver_problem(executable: str) -> str | None:
    """Why ``executable`` cannot serve as the solver, as a clause, or None when
    it can.

    Asked before a run spends anything. ProVerif is first called only once the
    flow model has been extracted, so a solver that is missing or wrong would
    otherwise surface after two paid model sessions, as the operating system's
    bare "No such file or directory" with no word of which setting it was. A
    bare name is looked up on PATH, a path has to be an executable file, and
    the program has to answer ``-help`` the way ProVerif does, which catches a
    path naming some other program.
    """
    if not executable:
        return "it is empty"
    if "/" not in executable and os.sep not in executable:
        found = shutil.which(executable)
        if found is None:
            return f"it is {executable!r}, and no program of that name is on PATH"
        path = Path(found)
    else:
        path = Path(executable)
        if not path.exists():
            return f"it is {executable}, which does not exist"
        if path.is_dir():
            return (f"it is {executable}, which is a directory; the proverif "
                    f"binary is a file inside it")
        if not os.access(path, os.X_OK):
            return f"it is {executable}, which is not executable"
    try:
        probe = subprocess.run([str(path), "-help"], capture_output=True,
                               text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return f"it is {executable}, which could not be run ({type(e).__name__}: {e})"
    said = (probe.stdout or "") + (probe.stderr or "")
    if "proverif" not in said.lower():
        first = next((ln.strip() for ln in said.splitlines() if ln.strip()),
                     "nothing")
        return (f"it is {executable}, which does not answer like ProVerif: "
                f"asked for -help, it printed {first[:80]!r}")
    return None


def _cgroup_memory_limit() -> int | None:
    """The memory cap the cgroup this process runs in imposes, in bytes, or
    None when there is none: no cgroup filesystem (macOS), or no limit set.

    A container is a cgroup, and ``sysconf`` inside one still reports the
    whole host's (or Docker Desktop's VM's) memory. A solver sized off that
    number grows past the container's cap, and the kernel kills it before
    this runner's poll can: a memory limit then reads as a solver crash.
    Every level from this process's own cgroup up to the root is read and the
    smallest cap wins, since a parent's limit binds its children. cgroup v2
    (``memory.max``) and v1 (``memory.limit_in_bytes``) are both read.
    Raises RuntimeError on a limit file that does not hold a number.
    """
    try:
        lines = _SELF_CGROUP.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None                     # not Linux, or no /proc: nothing caps us
    candidates: list[Path] = []
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        _, controllers, rel = parts
        rel = rel.lstrip("/")
        if controllers == "":           # v2: one unified hierarchy
            base, name = _CGROUP_ROOT, "memory.max"
        elif "memory" in controllers.split(","):
            base, name = _CGROUP_ROOT / "memory", "memory.limit_in_bytes"
        else:
            continue
        d = base / rel if rel else base
        while True:
            candidates.append(d / name)
            if d == base:
                break
            d = d.parent
    caps = []
    for f in candidates:
        try:
            text = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue                    # this level is not visible from here
        if text == "max":
            continue
        try:
            caps.append(int(text))
        except ValueError as e:
            raise RuntimeError(
                f"{f} does not hold a memory limit: {text[:40]!r}") from e
    return min(caps) if caps else None


def _usable_memory_bytes() -> int:
    """What this process can actually use: installed memory, or the cgroup's
    cap when that is smaller. A v1 cgroup with no limit reports a number far
    above any real machine, which the min() absorbs."""
    physical = _physical_memory_bytes()
    cap = _cgroup_memory_limit()
    return physical if cap is None else min(physical, cap)


def _memory_limit_bytes() -> int:
    """Built-in per-ProVerif ceiling: 65% of the memory this process can use,
    at least 8 GiB where that leaves headroom, never more than 90%.

    The floor keeps a mid-sized machine from starving a legitimate large
    proof; the 90% ceiling keeps the floor from exceeding a small machine or
    a container, where it used to mean no ceiling at all.
    """
    usable = _usable_memory_bytes()
    return max(int(usable * _MEMORY_FRACTION),
               min(_MIN_MEMORY_LIMIT_BYTES, int(usable * _MAX_MEMORY_FRACTION)))


def _rss_bytes(pid: int) -> int | None:
    """Read one process's RSS in bytes, or ``None`` if it is already exiting.

    Linux briefly keeps ``/proc/<pid>/status`` for a zombie that has released
    its address space, and that file has no ``VmRSS`` line — an expected race
    with ``proc.communicate()`` completing, not malformed solver output.
    """
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        try:
            lines = status.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return None  # it exited between exists() and read_text()
        state = ""
        for line in lines:
            if line.startswith("State:"):
                state = line.split(":", 1)[1].strip()
            if line.startswith("VmRSS:"):
                fields = line.split()
                if len(fields) != 3 or fields[2] != "kB":
                    raise RuntimeError(
                        f"unexpected VmRSS format for ProVerif pid {pid}: {line!r}")
                return int(fields[1]) * 1024
        if state.startswith(("Z", "X")):
            return None
        raise RuntimeError(f"VmRSS is missing for live ProVerif pid {pid}")

    # macOS has no /proc; psutil supplies the same fact without shelling out.
    try:
        import psutil
    except ImportError as e:
        raise RuntimeError(
            "psutil is required to enforce the ProVerif memory limit on "
            "platforms without /proc") from e
    try:
        return int(psutil.Process(pid).memory_info().rss)
    except psutil.NoSuchProcess:
        return None  # it exited between communicate() and this sample


@dataclass(frozen=True)
class RawRun:
    """The raw facts of one ProVerif subprocess call, with no interpretation."""

    stdout: str
    stderr: str
    returncode: int
    duration_s: float
    timed_out: bool
    memory_limited: bool = False
    peak_rss_bytes: int = 0
    memory_limit_bytes: int | None = None


class ProVerifRunner:
    """Runs ProVerif on a source string. Instances hold no mutable state and are
    safe to use concurrently."""

    def __init__(self, executable: str, timeout_s: int = 180) -> None:
        self.executable = executable
        self.timeout_s = timeout_s

    async def run(self, pv_source: str, log_to: Path,
                  extra_args: tuple[str, ...] = (),
                  timeout_s: int | None = None) -> RawRun:
        """Write the source to ``<log_to>.pv``, run ProVerif on that file, write
        the raw output to ``<log_to>.txt``, and return the raw facts.

        ``extra_args`` precedes the file on the command line (``-parse-only``
        checks syntax only) and is recorded in the ``.txt`` header, so a stored
        result says which question it answers; ``timeout_s`` overrides this
        instance's budget for one call. A timeout returns ``timed_out=True``
        rather than raising, cancellation kills the subprocess and propagates
        CancelledError, and a missing binary lets FileNotFoundError propagate.
        """
        src = Path(f"{log_to}.pv")
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(pv_source, encoding="utf-8")

        budget = self.timeout_s if timeout_s is None else timeout_s
        # Worked out before the process exists: a failure in here must not
        # leave a solver running with nothing waiting on it.
        limit = _memory_limit_bytes()
        start = time.monotonic()
        # start_new_session gives it its own process group so a kill can killpg
        # the whole group: orphaned children keep the stdout pipe open, and
        # asyncio's transport will not release wait() until that pipe closes.
        proc = await asyncio.create_subprocess_exec(
            self.executable,
            *extra_args,
            str(src),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        async def communicate_bounded():
            peak_rss = 0
            communicate = asyncio.create_task(proc.communicate())
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {communicate}, timeout=_MEMORY_POLL_S)
                    if communicate in done:
                        out, err = communicate.result()
                        return out, err, False, peak_rss
                    rss = _rss_bytes(proc.pid)
                    if rss is None:
                        # It has released its address space and communicate()
                        # is about to complete; no sample to compare this tick.
                        continue
                    peak_rss = max(peak_rss, rss)
                    if rss >= limit:
                        self._kill_group(proc)
                        out, err = await communicate
                        return out, err, True, peak_rss
            except asyncio.CancelledError:
                communicate.cancel()
                await asyncio.gather(communicate, return_exceptions=True)
                raise

        try:
            out, err, memory_limited, peak_rss = await asyncio.wait_for(
                communicate_bounded(), timeout=budget)
        except asyncio.TimeoutError:
            self._kill_group(proc)
            await proc.wait()
            # An explicit per-call budget means the caller chose the cut-off, so
            # reaching it is expected rather than a warning.
            logger.log(logging.DEBUG if timeout_s is not None else logging.WARNING,
                       "proverif timed out after %ss: %s", budget, src)
            return self._record(log_to, RawRun(
                stdout="",
                stderr="",
                returncode=-1,
                duration_s=time.monotonic() - start,
                timed_out=True,
                memory_limit_bytes=limit,
            ), extra_args)
        except BaseException:
            # Cancellation, or a fault of this runner's own (the memory probe
            # refusing): either way the solver is not left running on its own.
            self._kill_group(proc)
            await proc.wait()
            raise
        if memory_limited:
            logger.warning(
                "proverif exceeded memory limit %.1f GiB (peak %.1f GiB): %s",
                limit / 1024 ** 3, peak_rss / 1024 ** 3, src)
        raw = RawRun(
            stdout=(out or b"").decode("utf-8", errors="replace"),
            stderr=(err or b"").decode("utf-8", errors="replace"),
            returncode=proc.returncode if proc.returncode is not None else -1,
            duration_s=time.monotonic() - start,
            timed_out=False,
            memory_limited=memory_limited,
            peak_rss_bytes=peak_rss,
            memory_limit_bytes=limit,
        )
        logger.debug("proverif %s: exit=%d in %.1fs",
                     src.name, raw.returncode, raw.duration_s)
        return self._record(log_to, raw, extra_args)

    @staticmethod
    def _record(log_to: Path, raw: RawRun,
                extra_args: tuple[str, ...] = ()) -> RawRun:
        """Write the run's evidence beside its source and return ``raw``
        unchanged. The header carries what the output alone cannot say: a
        timeout has empty output, and an exit code tells a crash from a refusal."""
        facts = (f"exit={raw.returncode} duration={raw.duration_s:.1f}s "
                 f"timed_out={raw.timed_out} "
                 f"memory_limited={raw.memory_limited}")
        if raw.memory_limit_bytes is not None:
            facts += (f" peak_rss_mib={raw.peak_rss_bytes / 1024 ** 2:.1f} "
                      f"memory_limit_mib="
                      f"{raw.memory_limit_bytes / 1024 ** 2:.1f}")
        head = (f"# proverif {' '.join(extra_args) + ' ' if extra_args else ''}"
                f"{Path(log_to).name}.pv\n# {facts}\n")
        body = f"\n--- stdout ---\n{raw.stdout}"
        if raw.stderr.strip():
            body += f"\n--- stderr ---\n{raw.stderr}"
        Path(f"{log_to}.txt").write_text(head + body, encoding="utf-8")
        return raw

    @staticmethod
    def _kill_group(proc: asyncio.subprocess.Process) -> None:
        """SIGKILL the whole process group; silently fine if it is already dead."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
