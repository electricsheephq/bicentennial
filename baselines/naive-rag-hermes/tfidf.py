"""Apache-2.0: exact integer hashed TF-IDF for the developer baseline."""

import re
from fractions import Fraction as F
from hashlib import sha256

TOP_K = 5
CHUNK_CHARS = 240


def words(text):
    return re.findall(r"\w+", text.lower())


def feature(word):
    d = sha256(word.encode()).digest()
    return int.from_bytes(d[:8], "big"), -1 if d[8] & 1 else 1


def ln_fixed(x):
    shifts = 0
    while x >= 2:
        x /= 2
        shifts += 1

    def series(z):
        return 2 * sum((z ** (2 * k + 1) / (2 * k + 1) for k in range(24)), F(0))

    return int(1_000_000 * (shifts * series(F(1, 3)) + series((x - 1) / (x + 1))))


def idf_fixed(n, df):
    return ln_fixed(1 + F(2 * (n - df) + 1, 2 * df + 1))


def vector(word_list, idf):
    result = {}
    for word in sorted(set(word_list)):
        coordinate, sign = feature(word)
        result[coordinate] = result.get(coordinate, 0) + sign * word_list.count(word) * idf[word]
    return {j: result[j] for j in sorted(result)}


def chunks(text):
    result, start, end = [], None, 0
    for word in re.finditer(r"\S+", text):
        if start is not None and word.end() - start > CHUNK_CHARS:
            result.append(text[start:end])
            start = None
        if start is None:
            start = word.start()
        end = word.end()
    if start is not None:
        result.append(text[start:end])
    return result


def scored(memories, prompt):
    visible = [(mid, ordinal, text, words(text)) for mid in sorted(memories)
               for ordinal, text in enumerate(chunks(memories[mid]))]
    vocabulary = sorted(set(words(prompt)) | {w for _, _, _, ws in visible for w in ws})
    idf = {w: idf_fixed(len(visible), sum(w in ws for _, _, _, ws in visible)) for w in vocabulary}
    q, ranked = vector(words(prompt), idf), []
    for mid, ordinal, text, ws in visible:
        c = vector(ws, idf)
        norm = sum(c[j] ** 2 for j in sorted(c))
        dot = sum(q[j] * c.get(j, 0) for j in sorted(q))
        if norm > 0 and dot > 0:
            ranked.append((F(dot * dot, norm), mid, ordinal, text))
    # The numeric id counter preserves insertion order beyond six digits too.
    return sorted(ranked, key=lambda r: (-r[0], int(r[1][1:]), r[2]))
