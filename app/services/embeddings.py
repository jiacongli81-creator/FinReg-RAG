import hashlib
import math
import re


DIMENSION = 512


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    tokens: list[str] = []
    for word in words:
        tokens.append(word)
        if len(word) > 1 and all("\u4e00" <= char <= "\u9fff" for char in word):
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tokens


def embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSION
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % DIMENSION
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))
