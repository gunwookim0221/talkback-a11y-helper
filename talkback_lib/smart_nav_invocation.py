"""Currentness for the existing SMART_NEXT invocation result slot.

Invocation generations are host call identities, never Helper request IDs,
dispatch evidence, focus success, or visit authority.
"""
from contextlib import contextmanager
from contextvars import ContextVar


_collection_call = ContextVar("smart_nav_collection_call", default=None)
_result_producer = ContextVar("smart_nav_result_producer", default=None)


def current_generation(client):
    value = getattr(client, "_smart_nav_invocation_generation", None)
    return value if type(value) is int and value > 0 else None


def begin_invocation(client):
    generation = (current_generation(client) or 0) + 1
    client._smart_nav_invocation_generation = generation
    client._last_smart_nav_invocation_result = {}
    client._smart_nav_result_generation = None
    return generation


@contextmanager
def collection_call(client, generation):
    """Let exactly one nested move adopt its collector's invocation."""
    token = _collection_call.set({"client": client, "generation": generation, "claimed": False})
    try:
        yield
    finally:
        _collection_call.reset(token)


def begin_move(client):
    binding = _collection_call.get()
    if (binding is not None and binding["client"] is client
            and not binding["claimed"]
            and binding["generation"] == current_generation(client)):
        binding["claimed"] = True
        return binding["generation"]
    return begin_invocation(client)


@contextmanager
def result_producer(client, generation):
    token = _result_producer.set((client, generation))
    try:
        yield
    finally:
        _result_producer.reset(token)


def producing_generation(client):
    binding = _result_producer.get()
    return binding[1] if binding is not None and binding[0] is client else None


def publish_result(client, generation, result):
    if generation is None or generation != current_generation(client):
        return
    client._last_smart_nav_invocation_result = result if isinstance(result, dict) else {}
    client._smart_nav_result_generation = generation if isinstance(result, dict) and result else None


def current_result(client, generation):
    if (generation is None or generation != current_generation(client)
            or generation != getattr(client, "_smart_nav_result_generation", None)):
        return {}
    result = getattr(client, "_last_smart_nav_invocation_result", {})
    return result if isinstance(result, dict) else {}
