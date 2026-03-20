"""Tests for pipeline/git_ops.py."""

import hashlib
import os
import subprocess
import sys

import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.git_ops import compute_checksum, git_commit_and_push, write_checksums_file


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


# ---------------------------------------------------------------------------
# git_commit_and_push
# ---------------------------------------------------------------------------

def _ok_result():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail_result(stderr="error"):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


class TestGitCommitAndPush:
    def test_success_runs_all_three_commands(self):
        with patch("pipeline.git_ops.subprocess.run", return_value=_ok_result()) as mock_run:
            git_commit_and_push("Update DB: 3 new recordings")

        assert mock_run.call_count == 3
        cmds = [call.args[0] for call in mock_run.call_args_list]
        assert cmds[0][:2] == ["git", "add"]
        assert cmds[1][:2] == ["git", "commit"]
        assert cmds[2] == ["git", "push"]

    def test_commit_message_passed_through(self):
        with patch("pipeline.git_ops.subprocess.run", return_value=_ok_result()) as mock_run:
            git_commit_and_push("Update DB: 5 new recordings")

        commit_cmd = mock_run.call_args_list[1].args[0]
        assert commit_cmd == ["git", "commit", "-m", "Update DB: 5 new recordings"]

    def test_git_add_failure_aborts_before_commit(self):
        with patch("pipeline.git_ops.subprocess.run", return_value=_fail_result("fatal: not a repo")) as mock_run, \
             pytest.raises(SystemExit):
            git_commit_and_push("msg")

        # Only git add was attempted
        assert mock_run.call_count == 1

    def test_git_commit_failure_aborts_before_push(self):
        side_effects = [_ok_result(), _fail_result("nothing to commit")]

        with patch("pipeline.git_ops.subprocess.run", side_effect=side_effects) as mock_run, \
             pytest.raises(SystemExit):
            git_commit_and_push("msg")

        assert mock_run.call_count == 2

    def test_git_push_failure_prints_manual_retry_message(self, capsys):
        side_effects = [_ok_result(), _ok_result(), _fail_result("connection refused")]

        with patch("pipeline.git_ops.subprocess.run", side_effect=side_effects), \
             pytest.raises(SystemExit):
            git_commit_and_push("msg")

        output = capsys.readouterr().out
        assert "git push" in output.lower()
        assert "manually" in output.lower()

    def test_git_add_failure_does_not_print_manual_push_message(self, capsys):
        with patch("pipeline.git_ops.subprocess.run", return_value=_fail_result("fatal")), \
             pytest.raises(SystemExit):
            git_commit_and_push("msg")

        output = capsys.readouterr().out
        assert "manually" not in output.lower()
