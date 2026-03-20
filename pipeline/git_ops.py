"""Checksum computation and git operations for the pipeline."""

import hashlib
import os
import subprocess
import sys

# Repo root is one level above this file's directory
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def compute_checksum(db_path: str) -> str:
    """Return the SHA256 hex digest of the file at db_path."""
    h = hashlib.sha256()
    with open(db_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def write_checksums_file(db_path: str, checksums_path: str) -> None:
    """Write checksums.txt with the SHA256 of db_path.

    Format: "sha256:{hex}  wealthops.db\\n"
    """
    checksum = compute_checksum(db_path)
    with open(checksums_path, "w") as f:
        f.write(f"sha256:{checksum}  wealthops.db\n")


def git_commit_and_push(message: str) -> None:
    """Stage wealthops.db and checksums.txt, commit, then push.

    Runs all git commands from the repo root.  If any step fails the error is
    printed and the function exits immediately without continuing to push.
    """
    steps = [
        (["git", "add", "wealthops.db", "checksums.txt"], "git add"),
        (["git", "commit", "-m", message], "git commit"),
        (["git", "push"], "git push"),
    ]

    for cmd, label in steps:
        result = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"{label} failed:\n{result.stderr.strip()}")
            if label == "git push":
                print(
                    "\nThe database was updated locally but the push to "
                    "GitHub failed.\nRun 'git push' manually to complete "
                    "the update."
                )
            sys.exit(1)
