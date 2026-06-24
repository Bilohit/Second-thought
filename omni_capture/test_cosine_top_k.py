import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from vector_store import _cosine_top_k


def _old_cosine_top_k(query_vec, rows, top_k):
    q = np.array(query_vec, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    q = q / q_norm

    results = []
    for doc_id, emb_blob, document, _ in rows:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        norm = np.linalg.norm(emb)
        if norm == 0:
            continue
        sim = float(np.dot(q, emb / norm))
        results.append((sim, doc_id, document))

    results.sort(key=lambda x: x[0], reverse=True)
    return results[:top_k]


def test_vectorized_matches_loop_version():
    rng = np.random.default_rng(0)
    query = rng.random(16).tolist()
    rows = [
        (f"id{i}", rng.random(16).astype(np.float32).tobytes(), f"doc{i}", "cat")
        for i in range(25)
    ]
    new = _cosine_top_k(query, rows, 5)
    old = _old_cosine_top_k(query, rows, 5)
    assert [(r[1], r[2]) for r in new] == [(r[1], r[2]) for r in old]
    for (sim_new, *_), (sim_old, *_) in zip(new, old):
        assert abs(sim_new - sim_old) < 1e-5


def test_zero_norm_rows_excluded():
    query = [1.0, 0.0]
    rows = [
        ("a", np.array([0.0, 0.0], dtype=np.float32).tobytes(), "doc_a", "cat"),
        ("b", np.array([1.0, 0.0], dtype=np.float32).tobytes(), "doc_b", "cat"),
    ]
    out = _cosine_top_k(query, rows, 5)
    assert [r[1] for r in out] == ["b"]
