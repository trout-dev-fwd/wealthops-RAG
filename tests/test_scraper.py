"""Tests for pipeline/scraper.py."""

import os
import sys

import pytest
import requests
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.scraper import validate_cookie, fetch_all_posts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resp(status_code, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    if data is not None:
        resp.json.return_value = data
    else:
        resp.json.side_effect = ValueError("no body")
    return resp


def _records_resp(records, has_next_page=False):
    return _make_resp(200, {"records": records, "has_next_page": has_next_page})


def _login_form_resp():
    return _make_resp(200, {"email": "", "password": None})


# ---------------------------------------------------------------------------
# validate_cookie
# ---------------------------------------------------------------------------

class TestValidateCookie:
    def test_valid_cookie_returns_true(self):
        session = requests.Session()
        with patch.object(session, "get", return_value=_records_resp([])):
            assert validate_cookie(session, "https://example.com", 123) is True

    def test_login_form_response_returns_false(self):
        session = requests.Session()
        with patch.object(session, "get", return_value=_login_form_resp()):
            assert validate_cookie(session, "https://example.com", 123) is False

    def test_non_200_status_returns_false(self):
        session = requests.Session()
        with patch.object(session, "get", return_value=_make_resp(401)):
            assert validate_cookie(session, "https://example.com", 123) is False

    def test_network_error_returns_false(self):
        session = requests.Session()
        with patch.object(session, "get", side_effect=requests.RequestException("timeout")):
            assert validate_cookie(session, "https://example.com", 123) is False

    def test_invalid_json_returns_false(self):
        session = requests.Session()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(session, "get", return_value=resp):
            assert validate_cookie(session, "https://example.com", 123) is False

    def test_uses_correct_endpoint(self):
        session = requests.Session()
        with patch.object(session, "get", return_value=_records_resp([])) as mock_get:
            validate_cookie(session, "https://community.example.com", 9999)
            call_args = mock_get.call_args
            assert call_args[0][0] == "https://community.example.com/internal_api/spaces/9999/posts"

    def test_uses_per_page_1(self):
        session = requests.Session()
        with patch.object(session, "get", return_value=_records_resp([])) as mock_get:
            validate_cookie(session, "https://example.com", 123)
            params = mock_get.call_args[1]["params"]
            assert params["per_page"] == 1
            assert params["page"] == 1


# ---------------------------------------------------------------------------
# fetch_all_posts
# ---------------------------------------------------------------------------

class TestFetchAllPosts:
    def test_single_page(self):
        posts = [{"slug": "post-1", "name": "Post One"}]
        session = requests.Session()
        with patch.object(session, "get", return_value=_records_resp(posts)):
            result = fetch_all_posts(session, "https://example.com", 123)
        assert result == posts

    def test_pagination_collects_all_pages(self):
        page1 = [{"slug": f"post-{i}"} for i in range(15)]
        page2 = [{"slug": "post-15"}]

        side_effects = [
            _records_resp(page1, has_next_page=True),
            _records_resp(page2, has_next_page=False),
        ]

        session = requests.Session()
        with patch.object(session, "get", side_effect=side_effects), \
             patch("pipeline.scraper.time.sleep"):
            result = fetch_all_posts(session, "https://example.com", 123)

        assert len(result) == 16
        assert result[0]["slug"] == "post-0"
        assert result[15]["slug"] == "post-15"

    def test_pagination_sleeps_between_pages(self):
        page1 = [{"slug": "p1"}]
        page2 = [{"slug": "p2"}]

        side_effects = [
            _records_resp(page1, has_next_page=True),
            _records_resp(page2, has_next_page=False),
        ]

        session = requests.Session()
        with patch.object(session, "get", side_effect=side_effects), \
             patch("pipeline.scraper.time.sleep") as mock_sleep:
            fetch_all_posts(session, "https://example.com", 123)

        mock_sleep.assert_called_once_with(1)

    def test_no_sleep_on_single_page(self):
        session = requests.Session()
        with patch.object(session, "get", return_value=_records_resp([{"slug": "p1"}])), \
             patch("pipeline.scraper.time.sleep") as mock_sleep:
            fetch_all_posts(session, "https://example.com", 123)

        mock_sleep.assert_not_called()

    def test_mid_scrape_non_200_raises(self):
        """A non-200 on page 2 must raise RuntimeError immediately."""
        side_effects = [
            _records_resp([{"slug": "p1"}], has_next_page=True),
            _make_resp(401),
        ]

        session = requests.Session()
        with patch.object(session, "get", side_effect=side_effects), \
             patch("pipeline.scraper.time.sleep"):
            with pytest.raises(RuntimeError, match="(?i)page 2"):
                fetch_all_posts(session, "https://example.com", 123)

    def test_mid_scrape_login_form_raises(self):
        """A login-form response on page 2 must raise RuntimeError immediately."""
        side_effects = [
            _records_resp([{"slug": "p1"}], has_next_page=True),
            _login_form_resp(),
        ]

        session = requests.Session()
        with patch.object(session, "get", side_effect=side_effects), \
             patch("pipeline.scraper.time.sleep"):
            with pytest.raises(RuntimeError, match="(?i)page 2"):
                fetch_all_posts(session, "https://example.com", 123)

    def test_mid_scrape_raises_on_first_page_login_form(self):
        """Even page 1 can fail if the cookie was sneakily invalid."""
        session = requests.Session()
        with patch.object(session, "get", return_value=_login_form_resp()):
            with pytest.raises(RuntimeError, match="(?i)page 1"):
                fetch_all_posts(session, "https://example.com", 123)

    def test_uses_per_page_15(self):
        session = requests.Session()
        with patch.object(session, "get", return_value=_records_resp([])) as mock_get:
            fetch_all_posts(session, "https://example.com", 123)
        params = mock_get.call_args[1]["params"]
        assert params["per_page"] == 15

    def test_three_pages(self):
        pages = [
            _records_resp([{"slug": f"p{i}"} for i in range(15)], has_next_page=True),
            _records_resp([{"slug": f"p{i}"} for i in range(15, 30)], has_next_page=True),
            _records_resp([{"slug": "p30"}], has_next_page=False),
        ]

        session = requests.Session()
        with patch.object(session, "get", side_effect=pages), \
             patch("pipeline.scraper.time.sleep"):
            result = fetch_all_posts(session, "https://example.com", 123)

        assert len(result) == 31
