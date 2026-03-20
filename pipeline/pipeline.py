"""WealthOps Pipeline — interactive entry point.

Usage:
    python pipeline/pipeline.py [--dry-run]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from pipeline.db_builder import get_existing_slugs, insert_new_posts
from pipeline.git_ops import compute_checksum, git_commit_and_push, write_checksums_file
from pipeline.scraper import BASE_URL, SPACE_ID, fetch_all_posts, validate_cookie
from shared.tiptap_parser import parse_tiptap_to_chunks

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_REPO_ROOT, "wealthops.db")
CHECKSUMS_PATH = os.path.join(_REPO_ROOT, "checksums.txt")


def main():
    parser = argparse.ArgumentParser(description="WealthOps Pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and parse but do not write to DB or push to git",
    )
    args = parser.parse_args()

    print("WealthOps Pipeline")
    print("==================")

    # Cookie validation loop — repeat until a valid cookie is pasted
    session = requests.Session()
    while True:
        print("\nPaste your Circle.so cookie string (from DevTools > Network > cookie header):")
        cookie = input("> ").strip()
        if not cookie:
            print("No cookie entered. Try again.")
            continue

        # Set as a raw header — session.cookies.set() double-encodes URL-encoded values
        session.headers.update({"cookie": cookie})

        print("\nValidating cookie...")
        if validate_cookie(session, BASE_URL, SPACE_ID):
            print("  ✓ Cookie is valid")
            break
        else:
            print("  ✗ Cookie expired or invalid. Please paste a fresh cookie string.")

    # Scrape all posts
    print("\nScraping Circle.so...")
    try:
        all_posts = fetch_all_posts(session, BASE_URL, SPACE_ID)
    except RuntimeError as e:
        print(f"  Error: {e}")
        sys.exit(1)

    print(f"  {len(all_posts)} total posts found")

    # Incremental check
    print("\nChecking for new posts...")
    existing = get_existing_slugs(DB_PATH)
    new_posts = [p for p in all_posts if p["slug"] not in existing]

    if existing:
        print(f"  {len(existing)} already in database, skipping")

    if not new_posts:
        print("  No new recordings found. Nothing to push.")
        sys.exit(0)

    print(f"  {len(new_posts)} new posts to process:")

    # Parse each post for progress display
    parsed = []
    for post in new_posts:
        title = post.get("name") or post.get("title") or "Untitled"
        tiptap_body = post.get("tiptap_body") or {}
        post_url = post.get("url", "")
        chunks = parse_tiptap_to_chunks(tiptap_body, title, post_url)
        parsed.append((post, chunks))
        print(f"    Parsing: {title}... {len(chunks)} chunks")

    total_chunks = sum(len(chunks) for _, chunks in parsed)

    if args.dry_run:
        print(
            f"\nDRY RUN — parsed {len(new_posts)} new post"
            f"{'s' if len(new_posts) != 1 else ''} ({total_chunks} chunks) "
            "but did not save or push."
        )
        sys.exit(0)

    # Insert into DB
    inserted = insert_new_posts(DB_PATH, new_posts)
    print(f"  {inserted} new chunks inserted")
    print("  FTS5 index rebuilt")

    # Git push
    print("\nPushing to GitHub...")
    db_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    checksum = compute_checksum(DB_PATH)
    print(f"  DB size: {db_size_mb:.1f} MB")
    print(f"  SHA256: {checksum[:16]}...")

    write_checksums_file(DB_PATH, CHECKSUMS_PATH)
    n = len(new_posts)
    git_commit_and_push(f"Update DB: {n} new recording{'s' if n != 1 else ''}")
    print("  Committed and pushed to master")

    print("\nDone! GitHub Action will create the release automatically.")


if __name__ == "__main__":
    main()
