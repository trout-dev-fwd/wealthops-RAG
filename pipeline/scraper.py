"""Circle.so API scraper for WealthOps call recordings."""

import time

import requests

BASE_URL = "https://community.wealthops.io"
SPACE_ID = 2310701


def validate_cookie(session: requests.Session, base_url: str, space_id: int) -> bool:
    """Fetch page 1 with per_page=1 to check if the cookie is valid.

    Returns True if the response has a "records" key (authenticated).
    Returns False if the response looks like a login form or is non-200.
    """
    url = f"{base_url}/internal_api/spaces/{space_id}/posts"
    try:
        resp = session.get(url, params={"page": 1, "per_page": 1}, timeout=15)
    except requests.RequestException:
        return False

    if resp.status_code != 200:
        return False

    try:
        data = resp.json()
    except ValueError:
        return False

    return "records" in data


def fetch_all_posts(session: requests.Session, base_url: str, space_id: int) -> list:
    """Paginate through all posts, 15 per page, with a 1-second delay between pages.

    Raises RuntimeError immediately if any page returns non-200 or a login-form
    response ({"email": ..., "password": ...} without a "records" key).
    Never returns partial results on failure.
    """
    url = f"{base_url}/internal_api/spaces/{space_id}/posts"
    posts = []
    page = 1

    while True:
        resp = session.get(url, params={"page": page, "per_page": 15}, timeout=30)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Page {page} returned HTTP {resp.status_code}. "
                "Cookie may have expired mid-scrape. No changes saved."
            )

        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(
                f"Page {page} returned invalid JSON. "
                "Cookie may have expired mid-scrape. No changes saved."
            )

        if "records" not in data:
            raise RuntimeError(
                f"Auth failed on page {page}. Cookie may have expired mid-scrape. "
                "No changes saved."
            )

        records = data["records"]
        print(f"  Page {page}: {len(records)} posts")
        posts.extend(records)

        if not data.get("has_next_page", False):
            break

        page += 1
        time.sleep(1)

    return posts
