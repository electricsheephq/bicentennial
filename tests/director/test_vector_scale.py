"""Independent cosine checks for the declared synthetic embedding scale."""

import math
import re
from hashlib import sha256

import pytest

from bicentennial.director.responder import Call
from bicentennial.director.scripted import ScriptedResponder


def token_counts(text, dimension):
    counts = [0] * (dimension - 1)
    for token in re.findall(r"\w+", text.lower()):
        digest = sha256(token.encode("utf-8")).hexdigest()
        bucket = int(digest[:16], 16) % len(counts)
        counts[bucket] += 1 if int(digest[16:18], 16) % 2 == 0 else -1
    return counts


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right, strict=True)) / math.sqrt(
        sum(a * a for a in left) * sum(b * b for b in right))


def vectors(texts, dimension):
    responder = ScriptedResponder({"name": "mem0-oss", "embedding_dim": dimension})
    return responder.respond(Call("embeddings", "embedding", "embeddings", {"input": texts},
                                  "embed", {"session": 1, "turn": 1}, "one")).embedding


def test_cosine_is_affine_token_cosine():
    pairs = [
        ("alpha beta 猫 one", "red five"),              # no shared words
        ("alpha beta 猫 one", "ALPHA red five"),        # one shared word
        ("alpha beta 猫 one", "alpha beta 猫"),          # several shared words
        ("alpha beta 猫 one", "alpha beta 猫 one"),      # identical
        ("alpha alpha beta", "alpha beta"),            # repeated word
        ("beta", "two"),                              # negative signed collision at D=8
    ]
    for dimension in (8, 64, 1536):
        for left, right in pairs:
            c = cosine(token_counts(left, dimension), token_counts(right, dimension))
            actual = cosine(*vectors([left, right], dimension))
            assert actual == pytest.approx((1 + c) / 2, abs=1e-8, rel=0)


def test_similarity_preserves_token_cosine_order_including_ties():
    query = "alpha beta 猫 one"
    candidates = ["four", "red five", "alpha red five", "alpha beta 猫", query,
                  "alpha alpha beta", "five red", "one 猫 beta alpha"]
    raw = [cosine(token_counts(query, 8), token_counts(text, 8)) for text in candidates]
    embedded = vectors([query, *candidates], 8)
    scores = [cosine(embedded[0], value) for value in embedded[1:]]
    assert sorted(range(len(raw)), key=raw.__getitem__) == sorted(range(len(scores)), key=scores.__getitem__)
    for i in range(len(raw)):
        for j in range(len(raw)):
            assert (abs(raw[i] - raw[j]) < 1e-8) == (abs(scores[i] - scores[j]) < 1e-8)


def test_embedding_dimension_one_is_refused():
    with pytest.raises(ValueError, match="embedding_dim"):
        vectors(["alpha"], 1)
