import hashlib
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.updater import (
    check_and_update,
    download_db,
    get_latest_release_info,
    get_local_checksum,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_release_response(db_data: bytes, checksums_text: str | None = None):
    """Return a fake JSON API response dict and a matching checksums.txt content."""
    checksum = _make_checksum(db_data)
    if checksums_text is None:
        checksums_text = f"sha256:{checksum}  wealthops.db\n"

    release_json = {
        "assets": [
            {
                "name": "checksums.txt",
                "browser_download_url": "https://example.com/checksums.txt",
            },
            {
                "name": "wealthops.db",
                "browser_download_url": "https://example.com/wealthops.db",
            },
        ]
    }
    return release_json, checksums_text, checksum


# ---------------------------------------------------------------------------
# get_latest_release_info
# ---------------------------------------------------------------------------

class TestGetLatestReleaseInfo:
    def test_returns_checksum_and_url(self):
        db_data = b"fake db content"
        release_json, checksums_text, checksum = _make_release_response(db_data)

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            resp = MagicMock()
            if "releases" in str(url):
                resp.read.return_value = json.dumps(release_json).encode()
            else:
                resp.read.return_value = checksums_text.encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("app.updater.urllib.request.urlopen", side_effect=fake_urlopen):
            result = get_latest_release_info("owner/repo")

        assert result is not None
        assert result["checksum"] == checksum
        assert result["db_download_url"] == "https://example.com/wealthops.db"

    def test_returns_none_on_network_error(self):
        import urllib.error
        with patch(
            "app.updater.urllib.request.urlopen",
            side_effect=urllib.error.URLError("no route"),
        ):
            assert get_latest_release_info("owner/repo") is None

    def test_returns_none_when_assets_missing(self):
        release_json = {"assets": []}

        resp = MagicMock()
        resp.read.return_value = json.dumps(release_json).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        with patch("app.updater.urllib.request.urlopen", return_value=resp):
            assert get_latest_release_info("owner/repo") is None

    def test_returns_none_on_bad_json(self):
        resp = MagicMock()
        resp.read.return_value = b"not json"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        with patch("app.updater.urllib.request.urlopen", return_value=resp):
            assert get_latest_release_info("owner/repo") is None


# ---------------------------------------------------------------------------
# get_local_checksum
# ---------------------------------------------------------------------------

class TestGetLocalChecksum:
    def test_returns_none_for_missing_file(self, tmp_path):
        assert get_local_checksum(str(tmp_path / "nope.db")) is None

    def test_returns_sha256_for_existing_file(self, tmp_path):
        data = b"hello world"
        p = tmp_path / "wealthops.db"
        p.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert get_local_checksum(str(p)) == expected


# ---------------------------------------------------------------------------
# download_db
# ---------------------------------------------------------------------------

class TestDownloadDb:
    def test_downloads_and_verifies(self, tmp_path):
        data = b"real db bytes"
        checksum = _make_checksum(data)
        dest = str(tmp_path / "wealthops.db")

        resp = MagicMock()
        resp.read.return_value = data
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        with patch("app.updater.urllib.request.urlopen", return_value=resp):
            result = download_db("https://example.com/wealthops.db", dest, checksum)

        assert result is True
        assert os.path.exists(dest)
        assert open(dest, "rb").read() == data

    def test_fails_on_checksum_mismatch(self, tmp_path):
        data = b"real db bytes"
        dest = str(tmp_path / "wealthops.db")

        resp = MagicMock()
        resp.read.return_value = data
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        with patch("app.updater.urllib.request.urlopen", return_value=resp):
            result = download_db("https://example.com/wealthops.db", dest, "wrongchecksum")

        assert result is False
        assert not os.path.exists(dest)

    def test_fails_on_network_error(self, tmp_path):
        import urllib.error
        dest = str(tmp_path / "wealthops.db")
        with patch(
            "app.updater.urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            result = download_db("https://example.com/wealthops.db", dest, "abc")
        assert result is False


# ---------------------------------------------------------------------------
# check_and_update
# ---------------------------------------------------------------------------

class TestCheckAndUpdate:
    def _patch_release(self, db_data: bytes):
        checksum = _make_checksum(db_data)
        return {
            "checksum": checksum,
            "db_download_url": "https://example.com/wealthops.db",
        }, checksum

    def test_downloaded_on_first_launch(self, tmp_path):
        db_data = b"fresh db"
        release_info, checksum = self._patch_release(db_data)
        dest = str(tmp_path / "wealthops.db")

        with patch("app.updater.get_latest_release_info", return_value=release_info):
            with patch("app.updater.download_db", return_value=True) as mock_dl:
                result = check_and_update("owner/repo", dest)

        assert result == "downloaded"
        mock_dl.assert_called_once()

    def test_updated_when_checksums_differ(self, tmp_path):
        db_data_old = b"old db"
        db_data_new = b"new db"
        dest = tmp_path / "wealthops.db"
        dest.write_bytes(db_data_old)

        release_info, _ = self._patch_release(db_data_new)

        with patch("app.updater.get_latest_release_info", return_value=release_info):
            with patch("app.updater.download_db", return_value=True):
                result = check_and_update("owner/repo", str(dest))

        assert result == "updated"

    def test_up_to_date_when_checksums_match(self, tmp_path):
        db_data = b"current db"
        dest = tmp_path / "wealthops.db"
        dest.write_bytes(db_data)

        release_info, _ = self._patch_release(db_data)

        with patch("app.updater.get_latest_release_info", return_value=release_info):
            result = check_and_update("owner/repo", str(dest))

        assert result == "up_to_date"

    def test_no_internet(self, tmp_path):
        dest = str(tmp_path / "wealthops.db")
        import urllib.error

        with patch("app.updater.get_latest_release_info", return_value=None):
            with patch(
                "app.updater.urllib.request.urlopen",
                side_effect=urllib.error.URLError("no route"),
            ):
                result = check_and_update("owner/repo", dest)

        assert result == "no_internet"

    def test_failed_when_download_fails(self, tmp_path):
        db_data_old = b"old db"
        db_data_new = b"new db"
        dest = tmp_path / "wealthops.db"
        dest.write_bytes(db_data_old)

        release_info, _ = self._patch_release(db_data_new)

        with patch("app.updater.get_latest_release_info", return_value=release_info):
            with patch("app.updater.download_db", return_value=False):
                result = check_and_update("owner/repo", str(dest))

        assert result == "failed"
