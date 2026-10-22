"""The identity modeling idiom library and its one lookup tool: the idiom set
is closed, retrieval keys on operational description rather than protocol
names, and a resume rebuilds what the tool offered from the tool messages."""
from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.modeling_tools import (
    IDENTITY_MODELING_TOOLS, identity_modeling_miss_from_messages,
    offered_identity_idioms_from_messages,
)
from orrery.infra.llm.client import ChatMessage, Role
from orrery.modules.kbase.modeling_idioms import (
    identity_idiom, identity_idioms, search_identity_idioms,
)


def test_identity_library_is_closed():
    ids = {x.id for x in identity_idioms()}
    assert ids == {
        "identity.authenticated_key_binding", "identity.key_registry",
        "identity.private_provisioning", "identity.signed_certificate",
    }
    for item in identity_idioms():
        assert item.prompt
        assert identity_idiom(item.id, item.version) is item


def test_retrieval_uses_operational_description_not_protocol_hardcoding():
    registry = search_identity_idioms(
        "A received identity selects a peer authentication key by runtime key lookup")
    provisioned = search_identity_idioms(
        "ID_CRED is an opaque credential identifier for a pre-provisioned peer key")
    omitted = search_identity_idioms(
        "PKA and PKB are public keys of named principals; the binding mechanism is unspecified")
    assert registry[0].id == "identity.key_registry"
    assert provisioned[0].id == "identity.private_provisioning"
    assert omitted[0].id == "identity.authenticated_key_binding"
    assert all(len(x) <= 3 for x in (registry, provisioned, omitted))


def test_one_tool_returns_candidates_and_records_only_what_it_offered():
    ctx = ToolContext(node="extract_flow", prompt_lang="zh")
    result = IDENTITY_MODELING_TOOLS[0].handler(
        ctx, query="ID_CRED is an opaque credential identifier for a pre-provisioned peer key")
    assert result.startswith("[identity-modeling-candidates:")
    assert "These candidates are mutually exclusive" in result
    assert ctx.offered_identity_idioms
    assert len(ctx.offered_identity_idioms) <= 3


def test_resume_restores_successful_candidate_headers():
    messages = [ChatMessage(
        Role.TOOL,
        "[identity-modeling-candidates: identity.key_registry@1,identity.signed_certificate@1]\nbody",
        tool_call_id="t1")]
    assert offered_identity_idioms_from_messages(messages) == {
        ("identity.key_registry", 1), ("identity.signed_certificate", 1)}
    assert not identity_modeling_miss_from_messages(messages)


def test_a_lookup_miss_is_durable_until_a_later_success():
    miss = ChatMessage(Role.TOOL, "[identity-modeling-coverage-gap]\nnone",
                       tool_call_id="t1")
    hit = ChatMessage(Role.TOOL,
                      "[identity-modeling-candidates: identity.key_registry@1]",
                      tool_call_id="t2")
    assert identity_modeling_miss_from_messages([miss])
    assert not identity_modeling_miss_from_messages([miss, hit])
