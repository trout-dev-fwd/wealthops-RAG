import hashlib
import os
import urllib.error
import urllib.request
import json


def get_latest_release_info(github_repo: str) -> dict | None:
    """
    Hit GitHub Releases API and find the latest DB release (tag starts with "db-").
    Returns {checksum: str, db_download_url: str} or None on failure.
    """
    url = f"https://api.github.com/repos/{github_repo}/releases"
    req = urllib.request.Request(url, headers={"User-Agent": "WealthOps-Updater/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return None

    # Find the first release whose tag starts with "db-"
    data = None
    for release in releases:
        if release.get("tag_name", "").startswith("db-"):
            data = release
            break

    if data is None:
        return None

    assets = data.get("assets", [])

    # Find checksums.txt asset and download it
    checksums_url = None
    db_url = None
    for asset in assets:
        name = asset.get("name", "")
        if name == "checksums.txt":
            checksums_url = asset.get("browser_download_url")
        elif name == "wealthops.db":
            db_url = asset.get("browser_download_url")

    if not checksums_url or not db_url:
        return None

    # Download and parse checksums.txt
    try:
        req2 = urllib.request.Request(
            checksums_url, headers={"User-Agent": "WealthOps-Updater/1.0"}
        )
        with urllib.request.urlopen(req2, timeout=10) as resp:
            checksums_text = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return None

    # Format: "sha256:<hex>  wealthops.db\n"
    checksum = None
    for line in checksums_text.splitlines():
        line = line.strip()
        if "wealthops.db" in line:
            # e.g. "sha256:abc123  wealthops.db" or "abc123  wealthops.db"
            parts = line.split()
            if parts:
                raw = parts[0]
                checksum = raw.replace("sha256:", "")
            break

    if not checksum:
        return None

    return {"checksum": checksum, "db_download_url": db_url}


def get_local_checksum(db_path: str) -> str | None:
    """Return SHA256 hex digest of the local file, or None if file doesn't exist."""
    if not os.path.exists(db_path):
        return None
    h = hashlib.sha256()
    with open(db_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_db(url: str, dest_path: str, expected_checksum: str) -> bool:
    """
    Download file from url to dest_path atomically.
    Verify SHA256 against expected_checksum.
    Returns True on success, False on checksum mismatch or network error.
    Uses a temp file + os.replace() so a crash mid-write never leaves a
    corrupt file at dest_path.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "WealthOps-Updater/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False

    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_checksum:
        return False

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    tmp_path = dest_path + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, dest_path)
    except OSError:
        # Clean up temp file if replace failed
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False
    return True


def check_and_update(github_repo: str, db_path: str) -> str:
    """
    Orchestrate the update check.
    Returns one of: "updated", "up_to_date", "downloaded" (first launch), "failed", "no_internet"
    """
    release = get_latest_release_info(github_repo)
    if release is None:
        # Distinguish network failure from missing release
        # Try a simple connectivity check
        try:
            urllib.request.urlopen("https://api.github.com", timeout=5)
            # Reachable but no release info (e.g. no releases yet)
            return "failed"
        except (urllib.error.URLError, OSError):
            return "no_internet"

    remote_checksum = release["checksum"]
    local_checksum = get_local_checksum(db_path)

    first_launch = local_checksum is None

    if local_checksum == remote_checksum:
        return "up_to_date"

    success = download_db(release["db_download_url"], db_path, remote_checksum)
    if not success:
        return "failed"

    return "downloaded" if first_launch else "updated"
