"""Instantiate a chat backend from the flat llm config section
({backend, model, api_key, url, extra_headers, ...}); a null url means the
backend's own official endpoint. `extra_headers` reaches the adapter exactly as
configured — no hostname is inspected and nothing is added, so a relay needing
specific headers declares them in the config.
"""

from orrery.infra.llm.client import ChatClient

#: Where each SDK silently looks when handed no key, so the error below can name
#: the variable that would otherwise have taken over.
_SDK_ENV_FALLBACK = {
    "remote-claude": "ANTHROPIC_API_KEY",
    "remote-gemini": "GOOGLE_API_KEY",
    "remote-openai-responses": "OPENAI_API_KEY",
    "remote-openai-compatible": "OPENAI_API_KEY",
}


def _require_api_key(config: dict, backend: str) -> str:
    """Return config["api_key"], raising ValueError if it is missing or blank.

    Handed None (or "" on google-genai) every vendor SDK falls back to its own
    environment variable, so the run would succeed on a credential the config
    never names. `api_key:` with nothing after it is YAML for None.
    """
    key = config.get("api_key")
    if isinstance(key, str) and key.strip():
        return key
    env = _SDK_ENV_FALLBACK.get(backend, "the vendor's API-key variable")
    raise ValueError(
        f"llm.api_key is empty (got {key!r}) for backend={backend!r}. It must be "
        f"set in config: with no key the vendor SDK would silently fall back to "
        f"${env}, and the run would use a credential the config does not name. "
        f"Note that `api_key:` with no value is YAML for null."
    )


def build_chat_client(config: dict) -> ChatClient:
    return _build(config)


def _build(config: dict) -> ChatClient:
    backend = config.get("backend")
    if not backend:
        raise ValueError(
            "llm config missing 'backend'; e.g. llm: {backend: remote-claude, "
            "model: 'claude-opus-5', api_key: ..., url: ...}"
        )
    # The four adapters are three vendors' native protocols plus the universal
    # OpenAI-compatible one; each remote/*.py class docstring says which is which.
    model = config.get("model")
    if not model:
        raise ValueError(f"llm config missing 'model' (the model id); backend={backend!r}")
    api_key = _require_api_key(config, backend)
    url = config.get("url")
    timeout_s = config.get("timeout_s")
    match backend:
        case "remote-claude":
            from orrery.infra.llm.remote.claude import RemoteChatClaude

            return RemoteChatClaude(
                api_key=api_key,
                model_name=model,
                url=url,
                extra_headers=config.get("extra_headers"),
                cache_ttl=config.get("cache_ttl"),
                timeout_s=timeout_s,
            )
        case "remote-openai-responses":
            from orrery.infra.llm.remote.openai import RemoteChatOpenAI

            return RemoteChatOpenAI(
                api_key=api_key,
                model_name=model,
                url=url,
                extra_headers=config.get("extra_headers"),
                timeout_s=timeout_s,
            )
        case "remote-openai-compatible":
            from orrery.infra.llm.remote.openai_compatible import (
                RemoteChatOpenAICompatible,
            )

            return RemoteChatOpenAICompatible(
                api_key=api_key,
                model_name=model,
                url=url,
                extra_headers=config.get("extra_headers"),
                timeout_s=timeout_s,
            )
        case "remote-openai":
            # The name is ambiguous between the two OpenAI protocols, whose
            # capabilities differ.
            raise ValueError(
                "llm backend 'remote-openai' no longer exists: OpenAI's own API "
                "(/v1/responses) and the universal OpenAI-compatible API "
                "(/v1/chat/completions) are now separate backends, because from "
                "gpt-5.5 onwards the latter cannot combine tools with "
                "reasoning. Choose one:\n"
                "  remote-openai-responses   — OpenAI models (gpt-5.x); needed "
                "for any agent loop that uses tools and effort together\n"
                "  remote-openai-compatible  — everything else that speaks the "
                "OpenAI protocol (deepseek, glm, grok, qwen, vLLM, relays)"
            )
        case "remote-gemini":
            from orrery.infra.llm.remote.gemini import RemoteChatGemini

            return RemoteChatGemini(
                api_key=api_key,
                model_name=model,
                url=url,
                extra_headers=config.get("extra_headers"),
                timeout_s=timeout_s,
            )
        case _:
            raise ValueError(f"Unrecognized llm backend: {backend}")
