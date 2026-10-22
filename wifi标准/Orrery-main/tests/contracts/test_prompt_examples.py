"""Every ProVerif block in the flow prompts must typecheck as a file.

The flow prompt's examples are what the model imitates most literally, so a type
error in one comes back as the same error in generated models, costing a repair
round every time. The invariant: every ```proverif block in these two prompts is
a complete, runnable file that ProVerif accepts. Prompts elsewhere (the apply
realizers, the injectors) fence edit snippets on purpose and are out of scope.

Needs a ProVerif binary: the test skips when the config does not name one this
machine has.
"""

import re
import subprocess
from pathlib import Path

import pytest

from orrery.pipeline.config import CONFIG_PATH, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]

PROMPTS = [
    REPO_ROOT / "orrery/nodes/flow/prompts/main.sys.md",
    REPO_ROOT / "orrery/nodes/flow/prompts/main_zh.sys.md",
]

BLOCK = re.compile(r"```proverif\n(.*?)```", re.S)


def _proverif() -> str:
    if not CONFIG_PATH.exists():
        pytest.skip(f"no {CONFIG_PATH.name} in this checkout, so no ProVerif "
                    f"binary to typecheck with")
    exe = load_config(CONFIG_PATH, require=False)["proverif"]["executable"]
    if "/" in exe and not Path(exe).is_file():
        pytest.skip(f"configured ProVerif is not on this machine: {exe}")
    return exe


def _blocks():
    for path in PROMPTS:
        assert path.exists(), path
        found = BLOCK.findall(path.read_text())
        assert found, f"{path} has no ```proverif block"
        for i, body in enumerate(found):
            yield pytest.param(path.name, i, body, id=f"{path.name}#{i}")


@pytest.mark.parametrize("name,index,body", list(_blocks()))
def test_prompt_example_typechecks(tmp_path, name, index, body):
    """Write one fenced block to a .pv file and run ProVerif over it; any
    ``Error:`` line in its output fails the case."""
    exe = _proverif()
    pv = tmp_path / f"{name}.{index}.pv"
    pv.write_text(body)
    out = subprocess.run([exe, str(pv)], capture_output=True, text=True,
                         timeout=120)
    errors = [line for line in (out.stdout + out.stderr).splitlines()
              if line.startswith("Error:")]
    assert not errors, f"{name} block {index} is not valid ProVerif:\n" + \
        "\n".join(errors) + "\n\n" + body
