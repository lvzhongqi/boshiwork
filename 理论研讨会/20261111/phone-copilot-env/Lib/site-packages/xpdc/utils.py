import platform
import subprocess
from datetime import datetime
from tempfile import SpooledTemporaryFile

from loguru import logger


def exec_cmd(
    cmd: list[str],
    *,
    timeout: float | int = 60 * 1,
    redirect: bool = False,
) -> str:
    """Execute a command in a subprocess.

    Args:
        cmd: The command to execute, as a list of strings.
        timeout: The timeout for the command execution in seconds.
        redirect: If True, redirect stdout and stderr to a temporary file.
            When cmd return larger than 10KB, it will be written to a file instead of PIPE.

    Raises:
        subprocess.TimeoutExpired: If the command times out.
        CalledProcessError: If the command returns a non-zero exit code.

    Returns:
        stdout & stderr
    """
    close_fds = False if platform.system() == 'Darwin' else True

    if redirect:
        temp = SpooledTemporaryFile(max_size=1024 * 10)
        file_no = temp.fileno()
        output_kwargs = {'stdout': file_no, 'stderr': file_no}
    else:
        output_kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.STDOUT}

    logger.debug(f'Executing command: {cmd}')

    proc = subprocess.run(  # noqa: S603
        cmd,
        text=True,
        errors='replace',
        close_fds=close_fds,
        timeout=timeout,
        check=True,
        encoding='utf-8',
        **output_kwargs,
    )

    if redirect:
        with temp:
            temp.seek(0)
            return temp.read().decode('utf-8').strip() or ''

    return proc.stdout.strip() or ''


def now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f')
