"""Integer canonical vectors; scaling to floats happens only at the HTTP edge."""

from copy import deepcopy

from bicentennial.canon import canon


def parse_request(body: dict) -> dict:
    """Accept text or token IDs, singly or batched; only float wire encoding."""
    def tokens(value):
        return isinstance(value, list) and bool(value) and all(type(x) is int and x >= 0 for x in value)
    if not isinstance(body, dict):
        raise ValueError("invalid_embeddings_request")
    value = body.get("input")
    valid = isinstance(value, str) and bool(value) or tokens(value) or (
        isinstance(value, list) and bool(value) and
        (all(isinstance(x, str) and x for x in value) or all(tokens(x) for x in value)))
    if (not valid or not isinstance(body.get("model"), str) or not body["model"]
            or set(body) - {"input", "model", "encoding_format", "dimensions", "user"}
            or body.get("encoding_format", "float") != "float"
            or "dimensions" in body and (type(body["dimensions"]) is not int or body["dimensions"] <= 0)
            or "user" in body and not isinstance(body["user"], str)):
        raise ValueError("invalid_embeddings_request")
    canon(body)
    return deepcopy(body)


def to_wire(vectors: list[list[int]], scale: int) -> list[list[float]]:
    """Divide integer components by a positive integer denominator; never mutate inputs."""
    if (type(scale) is not int or scale <= 0 or not isinstance(vectors, list) or not vectors
            or not all(isinstance(v, list) and v and all(type(x) is int for x in v) for v in vectors)
            or len({len(v) for v in vectors}) != 1):
        raise ValueError("invalid_integer_vectors")
    return [[x / scale for x in vector] for vector in vectors]


def build_response(vectors: list[list[int]], scale: int, model: str, *, prompt_tokens: int = 0) -> dict:
    """Build an HTTP response only; store/hash the integer vectors, never this output."""
    if not isinstance(model, str) or not model or type(prompt_tokens) is not int or prompt_tokens < 0:
        raise ValueError("invalid_embeddings_metadata")
    return {"object": "list", "data": [{"object": "embedding", "index": i, "embedding": v}
                                       for i, v in enumerate(to_wire(vectors, scale))],
            "model": model, "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens}}
