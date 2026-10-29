"""A fake embedder for the memory tests: no MiniLM, deterministic.

Words map to concepts (so 'browser' and 'opera' point the same way, like meaning does);
anything else gets its own axis from a hash. Vectors are unit length.
"""
import hashlib
import math
import re

CONCEPTS = {
    "browser": "web", "opera": "web", "firefox": "web", "gx": "web", "chrome": "web",
    "tea": "tea", "bench": "tea", "kettle": "tea",
    "dog": "pet", "birdie": "pet", "puppy": "pet",
}
DIM = 128


def embed_one(text: str) -> list[float]:
    v = [0.0] * DIM
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        key = CONCEPTS.get(w, w)
        v[int(hashlib.md5(key.encode()).hexdigest(), 16) % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeEmbed:
    def __init__(self):
        self.calls = 0

    def __call__(self, texts):
        self.calls += 1
        return [embed_one(t) for t in texts]
