"""Tests for pipeline/db_builder.py."""

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.db_builder import get_existing_slugs, insert_new_posts
from shared.schema import create_knowledge_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_post(slug, title="Test Post", published_at="2026-01-01", n_items=1):
    """Build a minimal post dict with a Format B tiptap body."""
    items = []
    for i in range(n_items):
        items.append({
            "type": "listItem",
            "content": [{
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": f"Heading {i + 1}", "marks": [{"type": "bold"}]},
                    {"type": "text", "text": f" Content for chunk {i + 1}."},
                ],
            }],
        })

    return {
        "slug": slug,
        "name": title,
        "published_at": published_at,
        "url": f"https://example.com/posts/{slug}",
        "tiptap_body": {
            "type": "doc",
            "content": [{"type": "bulletList", "content": items}],
        },
    }


# ---------------------------------------------------------------------------
# get_existing_slugs
# ---------------------------------------------------------------------------

class TestGetExistingSlugs:
    def test_nonexistent_file_returns_empty_set(self, tmp_path):
        db_path = str(tmp_path / "does_not_exist.db")
        assert get_existing_slugs(db_path) == set()

    def test_empty_db_returns_empty_set(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        create_knowledge_db(db_path)
        assert get_existing_slugs(db_path) == set()

    def test_returns_all_slugs(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        create_knowledge_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO calls (title, slug) VALUES ('A', 'slug-a')")
        conn.execute("INSERT INTO calls (title, slug) VALUES ('B', 'slug-b')")
        conn.commit()
        conn.close()

        slugs = get_existing_slugs(db_path)
        assert slugs == {"slug-a", "slug-b"}

    def test_returns_set_not_list(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        create_knowledge_db(db_path)
        result = get_existing_slugs(db_path)
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# insert_new_posts
# ---------------------------------------------------------------------------

class TestInsertNewPosts:
    def test_inserts_single_post_single_chunk(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        count = insert_new_posts(db_path, [_make_post("post-1")])
        assert count == 1

    def test_inserts_multiple_chunks_per_post(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        count = insert_new_posts(db_path, [_make_post("post-1", n_items=3)])
        assert count == 3

    def test_returns_total_chunk_count_across_posts(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        posts = [_make_post("p1", n_items=2), _make_post("p2", n_items=4)]
        count = insert_new_posts(db_path, posts)
        assert count == 6

    def test_calls_row_inserted(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        insert_new_posts(db_path, [_make_post("my-post", title="My Post")])

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT title, slug FROM calls WHERE slug='my-post'").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "My Post"

    def test_chunks_rows_inserted(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        insert_new_posts(db_path, [_make_post("post-x", n_items=2)])

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT topic_heading FROM chunks ORDER BY id").fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0][0] == "Heading 1"
        assert rows[1][0] == "Heading 2"

    def test_speakers_stored_as_json_array(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        insert_new_posts(db_path, [_make_post("post-s")])

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT speakers FROM chunks LIMIT 1").fetchone()
        conn.close()
        speakers = json.loads(row[0])
        assert isinstance(speakers, list)

    def test_timestamps_stored_as_json_array(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        insert_new_posts(db_path, [_make_post("post-t")])

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT timestamps FROM chunks LIMIT 1").fetchone()
        conn.close()
        timestamps = json.loads(row[0])
        assert isinstance(timestamps, list)

    def test_creates_db_if_not_exists(self, tmp_path):
        db_path = str(tmp_path / "brand_new.db")
        assert not os.path.exists(db_path)
        insert_new_posts(db_path, [_make_post("p1")])
        assert os.path.exists(db_path)

    def test_additive_only_second_batch_adds_not_replaces(self, tmp_path):
        """Calling insert_new_posts twice must only ever add rows, never delete."""
        db_path = str(tmp_path / "test.db")

        insert_new_posts(db_path, [_make_post("post-1", n_items=2)])

        conn = sqlite3.connect(db_path)
        chunks_after_first = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        conn.close()
        assert chunks_after_first == 2

        insert_new_posts(db_path, [_make_post("post-2", n_items=3)])

        conn = sqlite3.connect(db_path)
        chunks_after_second = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        calls_count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        conn.close()

        assert chunks_after_second == 5   # 2 + 3, nothing deleted
        assert calls_count == 2

    def test_incremental_skip_workflow(self, tmp_path):
        """Simulate the full pipeline incremental flow: new posts not already in DB."""
        db_path = str(tmp_path / "test.db")
        all_posts = [_make_post("p1"), _make_post("p2"), _make_post("p3")]

        # First run: insert p1
        insert_new_posts(db_path, [all_posts[0]])

        # Simulate pipeline logic: only insert posts not already present
        existing = get_existing_slugs(db_path)
        assert existing == {"p1"}

        new_posts = [p for p in all_posts if p["slug"] not in existing]
        assert len(new_posts) == 2
        assert {p["slug"] for p in new_posts} == {"p2", "p3"}

        count = insert_new_posts(db_path, new_posts)
        assert count == 2  # one chunk each

        conn = sqlite3.connect(db_path)
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        total_calls = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        conn.close()
        assert total_chunks == 3
        assert total_calls == 3

    def test_fts5_index_populated(self, tmp_path):
        """FTS5 trigger must fire on insert so chunks are searchable."""
        db_path = str(tmp_path / "test.db")
        post = {
            "slug": "fts-test",
            "name": "FTS Test",
            "published_at": "2026-01-01",
            "url": "https://example.com/fts-test",
            "tiptap_body": {
                "type": "doc",
                "content": [{
                    "type": "bulletList",
                    "content": [{
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Philanthropy Strategies", "marks": [{"type": "bold"}]},
                                {"type": "text", "text": " Discussion about donor advised funds."},
                            ],
                        }],
                    }],
                }],
            },
        }

        insert_new_posts(db_path, [post])

        conn = sqlite3.connect(db_path)
        results = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'philanthropy'"
        ).fetchall()
        conn.close()
        assert len(results) == 1
