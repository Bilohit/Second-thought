"""
test_vector_store_wal.py
-------------------------
Verifies vectors.db opens with WAL journal mode and a busy_timeout so
concurrent readers/writers wait instead of raising
"database is locked" (P0 hardening in vector_store._get_conn).
"""
import sqlite3
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import vector_store


def test_journal_mode_is_wal(tmp_path: Path):
    conn = vector_store._get_conn(tmp_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_busy_timeout_avoids_database_locked(tmp_path: Path):
    # Prime the db file (creates table, sets WAL) before spinning up threads.
    conn0 = vector_store._get_conn(tmp_path)
    conn0.close()

    errors: list[BaseException] = []

    def writer_holds_lock():
        conn1 = vector_store._get_conn(tmp_path)
        try:
            conn1.execute("BEGIN IMMEDIATE")
            conn1.execute(
                "INSERT INTO embeddings (id, embedding, document, category) "
                "VALUES ('a', X'00', 'doc-a', '')"
            )
            time.sleep(0.5)
            conn1.commit()
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)
        finally:
            conn1.close()

    t = threading.Thread(target=writer_holds_lock)
    t.start()
    time.sleep(0.1)  # let the writer grab the lock first

    conn2 = vector_store._get_conn(tmp_path)
    try:
        conn2.execute(
            "INSERT INTO embeddings (id, embedding, document, category) "
            "VALUES ('b', X'00', 'doc-b', '')"
        )
        conn2.commit()
    except sqlite3.OperationalError as exc:
        errors.append(exc)
    finally:
        conn2.close()

    t.join(timeout=5)

    assert not errors, f"expected no lock errors, got: {errors}"


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_journal_mode_is_wal(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_busy_timeout_avoids_database_locked(Path(d))
    print("OK")
