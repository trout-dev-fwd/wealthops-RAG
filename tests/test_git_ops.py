"""Tests for pipeline/git_ops.py."""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.git_ops import compute_checksum, write_checksums_file


# ---------------------------------------------------------------------------
# compute_checksum
# ---------------------------------------------------------------------------

class TestComputeChecksum:
    def test_known_value(self, tmp_path):
        content = b"hello world"
        db_file = tmp_path / "wealthops.db"
        db_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        assert compute_checksum(str(db_file)) == expected

    def test_empty_file(self, tmp_path):
        db_file = tmp_path / "empty.db"
        db_file.write_bytes(b"")

        expected = hashlib.sha256(b"").hexdigest()
        assert compute_checksum(str(db_file)) == expected

    def test_returns_hex_string(self, tmp_path):
        db_file = tmp_path / "test.db"
        db_file.write_bytes(b"test")

        result = compute_checksum(str(db_file))
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_different_content_different_checksum(self, tmp_path):
        file_a = tmp_path / "a.db"
        file_b = tmp_path / "b.db"
        file_a.write_bytes(b"content A")
        file_b.write_bytes(b"content B")

        assert compute_checksum(str(file_a)) != compute_checksum(str(file_b))

    def test_same_content_same_checksum(self, tmp_path):
        file_a = tmp_path / "a.db"
        file_b = tmp_path / "b.db"
        content = b"identical content"
        file_a.write_bytes(content)
        file_b.write_bytes(content)

        assert compute_checksum(str(file_a)) == compute_checksum(str(file_b))

    def test_large_file_chunked_correctly(self, tmp_path):
        """Files larger than the read-block size must still hash correctly."""
        content = b"x" * (128 * 1024)  # 128 KB, larger than 65536-byte blocks
        db_file = tmp_path / "large.db"
        db_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        assert compute_checksum(str(db_file)) == expected


# ---------------------------------------------------------------------------
# write_checksums_file
# ---------------------------------------------------------------------------

class TestWriteChecksumsFile:
    def test_format(self, tmp_path):
        db_file = tmp_path / "wealthops.db"
        db_content = b"fake db content"
        db_file.write_bytes(db_content)

        checksums_file = tmp_path / "checksums.txt"
        write_checksums_file(str(db_file), str(checksums_file))

        expected_hash = hashlib.sha256(db_content).hexdigest()
        content = checksums_file.read_text()
        assert content == f"sha256:{expected_hash}  wealthops.db\n"

    def test_ends_with_newline(self, tmp_path):
        db_file = tmp_path / "wealthops.db"
        db_file.write_bytes(b"data")
        checksums_file = tmp_path / "checksums.txt"
        write_checksums_file(str(db_file), str(checksums_file))

        content = checksums_file.read_text()
        assert content.endswith("\n")

    def test_hash_matches_compute_checksum(self, tmp_path):
        db_file = tmp_path / "wealthops.db"
        db_file.write_bytes(b"database content here")
        checksums_file = tmp_path / "checksums.txt"

        write_checksums_file(str(db_file), str(checksums_file))

        computed = compute_checksum(str(db_file))
        content = checksums_file.read_text()
        assert f"sha256:{computed}" in content

    def test_filename_in_checksums_is_wealthops_db(self, tmp_path):
        """The filename in the checksums line is always 'wealthops.db'."""
        db_file = tmp_path / "some_other_name.db"
        db_file.write_bytes(b"data")
        checksums_file = tmp_path / "checksums.txt"

        write_checksums_file(str(db_file), str(checksums_file))

        content = checksums_file.read_text()
        assert "wealthops.db" in content

    def test_creates_file(self, tmp_path):
        db_file = tmp_path / "wealthops.db"
        db_file.write_bytes(b"data")
        checksums_file = tmp_path / "checksums.txt"

        assert not checksums_file.exists()
        write_checksums_file(str(db_file), str(checksums_file))
        assert checksums_file.exists()

    def test_overwrites_existing_file(self, tmp_path):
        db_file = tmp_path / "wealthops.db"
        checksums_file = tmp_path / "checksums.txt"
        checksums_file.write_text("old content\n")

        db_file.write_bytes(b"new data")
        write_checksums_file(str(db_file), str(checksums_file))

        content = checksums_file.read_text()
        assert "old content" not in content
