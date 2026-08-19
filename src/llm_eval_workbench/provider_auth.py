from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from .secrets import ResolvedModel, uses_anthropic_wire_protocol

_ANTHROPIC_ENV_LOCK = threading.Lock()
_ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
_ANTHROPIC_AUTH_TOKEN_ENV = "ANTHROPIC_AUTH_TOKEN"


def provider_api_key(model: ResolvedModel) -> str | None:
    """Return the explicit SDK key, or defer Anthropic relay auth to its env token."""
    if uses_anthropic_wire_protocol(model.model_name):
        return None
    return model.api_key.get_secret_value()


def _install_anthropic_auth(model: ResolvedModel) -> dict[str, str | None]:
    previous = {
        _ANTHROPIC_API_KEY_ENV: os.environ.get(_ANTHROPIC_API_KEY_ENV),
        _ANTHROPIC_AUTH_TOKEN_ENV: os.environ.get(_ANTHROPIC_AUTH_TOKEN_ENV),
    }
    # ANTHROPIC_API_KEY takes precedence inside LiteLLM. Clear it so a custom
    # relay token is sent exactly as Authorization: Bearer, matching Claude Code.
    os.environ.pop(_ANTHROPIC_API_KEY_ENV, None)
    os.environ[_ANTHROPIC_AUTH_TOKEN_ENV] = model.api_key.get_secret_value()
    return previous


def _restore_anthropic_auth(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@contextmanager
def provider_auth_context(model: ResolvedModel) -> Iterator[None]:
    if not uses_anthropic_wire_protocol(model.model_name):
        yield
        return
    _ANTHROPIC_ENV_LOCK.acquire()
    previous = _install_anthropic_auth(model)
    try:
        yield
    finally:
        _restore_anthropic_auth(previous)
        _ANTHROPIC_ENV_LOCK.release()


@asynccontextmanager
async def provider_auth_context_async(model: ResolvedModel) -> AsyncIterator[None]:
    if not uses_anthropic_wire_protocol(model.model_name):
        yield
        return
    await asyncio.to_thread(_ANTHROPIC_ENV_LOCK.acquire)
    previous = _install_anthropic_auth(model)
    try:
        yield
    finally:
        _restore_anthropic_auth(previous)
        _ANTHROPIC_ENV_LOCK.release()
