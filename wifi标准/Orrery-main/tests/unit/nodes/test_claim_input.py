"""load_claim_input rejects a supplied artifact whose JSON is not an object."""

import pytest

from orrery.nodes.base import NodeError
from orrery.nodes.claims.load import load_claim_input


def test_json_file_must_contain_an_object(tmp_path):
    path = tmp_path / "principals.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(NodeError, match="must contain a JSON object, got list"):
        load_claim_input(path, "principals", "extract_principals")
