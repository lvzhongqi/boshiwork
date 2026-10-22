"""Config loading: the merge levels including a stack of user files, backend
slot resolution, the required-value check, and the shapes that are refused.

Also the two contracts that keep config.example.yaml and HELP from drifting
away from DEFAULTS."""

import re
from pathlib import Path

import pytest

from orrery.pipeline.config import MissingConfigError, load_config

# The minimum that loads: the live backend's slot filled, plus a solver path.
# The backend name has to be a declared slot.
_FILL = {"llm": {"backend": "remote-claude",
                 "profiles": {"remote-claude": {"api_key": "k"}}},
         "proverif": {"executable": "/bin/true"}}


def test_three_level_merge_precedence(tmp_path):
    user_file = tmp_path / "u.yaml"
    user_file.write_text("agent:\n  max_rounds: 5\npaths:\n  work_root: /u\n")
    cfg = load_config(user_file, overrides={
        **_FILL, "paths": {"work_root": "/override"}})
    assert cfg["agent"]["max_rounds"] == 5          # the user file overrides the defaults
    assert cfg["paths"]["work_root"] == "/override"   # the overrides beat the user file
    assert cfg["agent"]["max_repairs"] == 6         # untouched defaults survive


def test_user_level_is_a_stack_and_later_wins(tmp_path):
    """Several user files layer in order, each stating only what it changes,
    so a batch file can sit beside the private file holding credentials and
    machine paths."""
    base = tmp_path / "base.yaml"
    base.write_text("agent:\n  max_rounds: 5\nproverif:\n  timeout_s: 200\n")
    batch = tmp_path / "batch.yaml"
    batch.write_text("proverif:\n  timeout_s: 300\n")
    cfg = load_config([base, batch], overrides=_FILL)
    assert cfg["proverif"]["timeout_s"] == 300      # the later file wins
    assert cfg["agent"]["max_rounds"] == 5          # what it does not mention survives
    assert cfg["agent"]["max_repairs"] == 6         # and so do untouched defaults


def test_only_the_merged_result_has_to_be_complete(tmp_path):
    """A file in the stack may be a fragment; only the merged result has to
    satisfy the required-value check."""
    fragment = tmp_path / "batch.yaml"
    fragment.write_text("inputs:\n  end_point: claims\n")
    cfg = load_config([fragment], overrides=_FILL)
    assert cfg["inputs"]["end_point"] == "claims"


def test_a_string_path_is_one_layer_not_a_pile_of_characters(tmp_path):
    """str is iterable, so a bare path string is the trap case: it is one
    source, not one layer per character."""
    user_file = tmp_path / "u.yaml"
    user_file.write_text("agent:\n  max_rounds: 5\n")
    assert load_config(str(user_file), overrides=_FILL)["agent"]["max_rounds"] == 5


def test_missing_mandatory_is_loud():
    # Reported at the slot key that is actually edited, not at llm.api_key,
    # which is where the value is read and does not exist in the file.
    with pytest.raises(MissingConfigError,
                       match=r"llm\.profiles\.remote-claude\.api_key"):
        load_config(overrides={"llm": {"backend": "remote-claude"},
                               "proverif": {"executable": "/bin/true"}})


def test_missing_names_the_file_to_edit(tmp_path):
    """The message names a file as well as the key, because on a fresh checkout
    the reader does not yet know ensure_config created config.yaml. The file
    named is the first layer, where every stack puts the private one."""
    first = tmp_path / "config.yaml"
    first.write_text("proverif:\n  executable: /bin/true\n")
    second = tmp_path / "batch.yaml"
    second.write_text("agent:\n  max_rounds: 5\n")
    with pytest.raises(MissingConfigError) as e:
        load_config([str(first), str(second)])
    assert str(first.resolve()) in str(e.value)
    assert "the first of 2 config files" in str(e.value)


def test_shipped_default_demands_a_key():
    """Every backend talks to a vendor, so the live slot's key is the one
    thing a fresh checkout has to fill in before anything runs."""
    with pytest.raises(MissingConfigError, match=r"api_key"):
        load_config()


def test_only_the_live_slot_is_required():
    """Only the selected backend's key is required; the other slots keep their
    ??? sentinel and do not block a run."""
    cfg = load_config(overrides=_FILL)
    assert cfg["llm"]["api_key"] == "k"
    assert cfg["llm"]["profiles"]["remote-gemini"]["api_key"] == "???"


def test_switching_backend_brings_its_whole_slot():
    """A key, url and model move together as one slot, and the slot left
    behind is untouched, so switching back needs no re-editing."""
    two = {"llm": {"backend": "remote-claude", "profiles": {
                "remote-claude": {"api_key": "k1"},
                "remote-openai-compatible": {"api_key": "k2",
                                             "url": "https://relay/v1",
                                             "model": "glm-4.5-flash"}}},
           "proverif": {"executable": "/bin/true"}}
    a = load_config(overrides=two)
    assert (a["llm"]["api_key"], a["llm"]["url"], a["llm"]["model"]) == (
        "k1", None, "claude-opus-5")
    two["llm"]["backend"] = "remote-openai-compatible"
    b = load_config(overrides=two)
    assert (b["llm"]["api_key"], b["llm"]["url"], b["llm"]["model"]) == (
        "k2", "https://relay/v1", "glm-4.5-flash")


def test_unknown_backend_names_the_declared_slots():
    with pytest.raises(MissingConfigError, match="no slot under llm.profiles"):
        load_config(overrides={**_FILL, "llm": {"backend": "stub"}})


def test_one_off_model_override_survives_resolution():
    """An override at llm.model applies to this run only; the slot keeps its
    own model."""
    cfg = load_config(overrides={**_FILL,
                                 "llm": {**_FILL["llm"], "model": "other"}})
    assert cfg["llm"]["model"] == "other"
    assert cfg["llm"]["profiles"]["remote-claude"]["model"] == "claude-opus-5"


@pytest.mark.parametrize("removed, message", [
    ({"llm": {"max_concurrency": 8}}, "llm.max_concurrency has been removed"),
    ({"proverif": {"max_concurrency": 8}},
     "proverif.max_concurrency has been removed"),
    ({"pipeline": {"max_concurrency": 4}},
     "pipeline.max_concurrency has been replaced"),
])
def test_removed_concurrency_settings_are_loud(removed, message):
    with pytest.raises(MissingConfigError, match=message):
        load_config(overrides={**_FILL, **removed})


@pytest.mark.parametrize("overrides, path", [
    ({"pipeline": {"max_scenarios_concurrency": 0}},
     "pipeline.max_scenarios_concurrency"),
    ({"pipeline": {"max_scenarios_concurrency": 1.5}},
     "pipeline.max_scenarios_concurrency"),
    ({"scenarios": {"inject_cells_per_call": 0}},
     "scenarios.inject_cells_per_call"),
])
def test_scheduling_values_are_positive_integers(overrides, path):
    with pytest.raises(MissingConfigError, match=path):
        load_config(overrides={**_FILL, **overrides})


def test_relative_work_root_is_project_relative_not_cwd_relative():
    from orrery.pipeline.config import PROJECT_ROOT
    cfg = load_config(overrides=_FILL)
    assert cfg["paths"]["work_root"] == str(PROJECT_ROOT / "a_runs")


def test_example_yaml_in_sync_with_defaults():
    """config.example.yaml against DEFAULTS: identical key sets, every
    non-required value equal to its default, and every required value left as
    "???" with a "required" annotation on its line."""
    from pathlib import Path

    import yaml

    from orrery.pipeline.config import DEFAULTS

    root = Path(__file__).resolve().parents[3]
    text = (root / "config.example.yaml").read_text(encoding="utf-8")
    example = yaml.safe_load(text)

    def flat(d, prefix=""):
        for k, v in d.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                yield from flat(v, p)
            else:
                yield p, v

    dflt = dict(flat(DEFAULTS))
    ex = dict(flat(example))
    assert set(dflt) == set(ex), (
        f"key sets drift: only in DEFAULTS {sorted(set(dflt) - set(ex))}; "
        f"only in example {sorted(set(ex) - set(dflt))}")

    from orrery.pipeline.config import BACKENDS
    mandatory = {k for k, v in dflt.items() if v == "???"}
    # The slots' api_keys and nothing else: every other field ships with a
    # working value.
    assert mandatory == {f"llm.profiles.{b}.api_key" for b in BACKENDS}
    # Every required api_key line has to carry the marker, not just the first:
    # an unmarked line in an unused vendor slot reads as a value to invent.
    for line in text.splitlines():
        if line.strip().startswith('api_key: "???"'):
            assert "required" in line, f"unmarked required field: {line.strip()}"
    # A required field keeps the ??? sentinel. config.yaml is a copy of this
    # file, so a lifelike placeholder would pass the required check and fail at
    # the first request instead of at startup.
    for k in mandatory:
        assert ex[k] == "???", (
            f"example.{k}={ex[k]!r} looks filled in; a required field must stay "
            f'"???" so a seeded config.yaml reports itself incomplete')
    for k, v in dflt.items():
        if k in mandatory:
            continue
        assert ex[k] == v, f"example.{k}={ex[k]!r} != default {v!r} (the example has drifted)"


def test_legacy_shapes_rejected():
    """Two config shapes the loader refuses outright, naming the shape rather
    than half-loading it."""
    # a top-level infra section
    with pytest.raises(MissingConfigError, match="old shape"):
        load_config(overrides={"infra": {"llm": {"name": "x"}}})
    # llm.name plus nested entries, the model-library shape
    with pytest.raises(MissingConfigError, match="model-library shape"):
        load_config(overrides={
            "llm": {"name": "remote-claude",
                    "remote-claude": {"api_key": "k", "name": "m"}},
            "proverif": {"executable": "/bin/true"}})


def test_every_knob_explains_itself():
    """HELP and DEFAULTS carry the same knobs in both directions. The console
    shows HELP on hover, so a knob with no entry has nothing to show and an
    entry with no knob is a sentence that will never appear."""
    from orrery.pipeline.config import DEFAULTS, HELP, generic

    def leaves(d, prefix=""):
        for k, v in d.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                yield from leaves(v, path)
            else:
                yield path

    missing = sorted({generic(p) for p in leaves(DEFAULTS)} - set(HELP))
    assert not missing, f"knobs with no HELP entry: {missing}"
    # and nothing left over, which is how a renamed knob leaves HELP stale
    orphan = sorted(set(HELP) - {generic(p) for p in leaves(DEFAULTS)})
    assert not orphan, f"HELP entries for knobs that no longer exist: {orphan}"


@pytest.mark.parametrize("layer, key", [
    ({"pipline": {"gap_budget": 0}}, "pipline"),                    # a section
    ({"pipeline": {"max_scenario_concurrency": 9}},
     "pipeline.max_scenario_concurrency"),                          # a knob
    ({"llm": {"profiles": {"remote-claude": {"apikey": "k"}}}},
     "llm.profiles.remote-claude.apikey"),                          # a slot key
    ({"pipeline": 4}, "pipeline (must be a mapping)"),
])
def test_a_key_nothing_reads_is_refused(layer, key):
    """Merged silently, a misspelt knob leaves the run at the default while
    the file says otherwise."""
    with pytest.raises(MissingConfigError, match=re.escape(key)):
        load_config(overrides={**_FILL, **layer})


def test_the_engine_keys_outside_defaults_are_still_legal(tmp_path):
    cfg = load_config(overrides={**_FILL, "prompt_lang": "en",
                                 "llm": {**_FILL["llm"], "model": "one-off",
                                         "extra_headers": {"X-Relay": "1"}}})
    assert cfg["prompt_lang"] == "en" and cfg["llm"]["model"] == "one-off"


@pytest.mark.parametrize("overrides, path", [
    ({"pipeline": {"mode": "Manual"}}, "pipeline.mode"),
    ({"agent": {"max_rounds": "12"}}, "agent.max_rounds"),
    ({"agent": {"max_repairs": True}}, "agent.max_repairs"),
    ({"proverif": {"timeout_s": 0}}, "proverif.timeout_s"),
    ({"inputs": {"lib_flow": "true"}}, "inputs.lib_flow"),
])
def test_values_of_the_wrong_shape_are_refused(overrides, path):
    """A string "12" would reach the loop budget as text and a mode spelt
    Manual would run auto; both are refused while the config is read."""
    with pytest.raises(MissingConfigError, match=re.escape(path)):
        load_config(overrides={**_FILL, **overrides})


def test_nullable_numbers_take_null():
    cfg = load_config(overrides={**_FILL, "agent": {"max_rounds": None},
                                 "pipeline": {"approval_timeout_s": 2.5}})
    assert cfg["agent"]["max_rounds"] is None
    assert cfg["pipeline"]["approval_timeout_s"] == 2.5


def test_orrery_home_moves_the_data_but_not_the_example(tmp_path):
    """An installed copy keeps its data where ORRERY_HOME names: the default
    config and the anchor for relative paths move there, while the example
    config stays with the source it documents. Checked in a fresh process,
    since the module reads the variable once, at import."""
    import os
    import subprocess
    import sys
    code = ("from orrery.pipeline import config as c; "
            "print(c.PROJECT_ROOT); print(c.CONFIG_PATH); print(c.EXAMPLE_PATH); "
            "cfg = c.load_config({'paths': {'work_root': './runs'}}, require=False); "
            "print(cfg['paths']['work_root'])")
    repo = Path(__file__).resolve().parents[3]       # import this checkout's orrery
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True, cwd=repo,
                         env={**os.environ, "ORRERY_HOME": str(tmp_path)}).stdout.split()
    home = str(tmp_path.resolve())
    assert out[0] == home and out[1] == f"{home}/config.yaml"
    assert out[2].endswith("config.example.yaml") and not out[2].startswith(home)
    assert out[3] == f"{home}/runs"


def test_an_orrery_home_that_is_not_a_directory_is_loud(tmp_path):
    import os
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-c", "import orrery.pipeline.config"],
                       capture_output=True, text=True,
                       cwd=Path(__file__).resolve().parents[3],
                       env={**os.environ, "ORRERY_HOME": str(tmp_path / "absent")})
    assert r.returncode != 0 and "is not a directory" in r.stderr
