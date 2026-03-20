"""Entry point for WealthOps Assistant.

Startup flow:
  1. Load config
  2. If no API key → show API-key entry screen (blocking)
  3. Check for DB:
       - No local DB → show downloading screen, block until done or fatal error
       - Local DB exists → background update (silent)
  4. Init chat DB + create session
  5. Show main chat GUI
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

# ---------------------------------------------------------------------------
# Bootstrap: make project root importable when run as a script
# ---------------------------------------------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

from app import chat_store, config as cfg, updater
from app.gui import WealthOpsApp, show_api_key_screen, show_download_screen


def main() -> None:
    root = tk.Tk()
    root.title("WealthOps Assistant")
    root.geometry("860x620")
    root.minsize(700, 500)

    config = cfg.load_config()
    api_key: str | None = config.get("api_key")

    # ------------------------------------------------------------------
    # Step 2 — API key screen
    # ------------------------------------------------------------------
    if not api_key:
        key_holder: list[str | None] = [None]
        key_event = threading.Event()

        def on_valid_key(key: str) -> None:
            key_holder[0] = key
            config["api_key"] = key
            cfg.save_config(config)
            key_event.set()
            # Continue startup from the main thread via after()
            root.after(0, _proceed_after_key, root, config, key)

        show_api_key_screen(root, on_valid_key)
        root.mainloop()
        return  # _proceed_after_key launches a new mainloop if needed

    _proceed_after_key(root, config, api_key)
    root.mainloop()


def _proceed_after_key(root: tk.Tk, config: dict, api_key: str) -> None:
    """Called once a valid API key is confirmed."""
    db_path = cfg.KNOWLEDGE_DB_PATH
    github_repo = config.get("github_repo", cfg.GITHUB_REPO)

    if not os.path.exists(db_path):
        # First launch: show downloading screen, block until complete
        show_download_screen(
            root,
            on_done=lambda: _proceed_after_db(root, api_key),
            on_failed=lambda: _on_db_fatal(root),
        )
    else:
        # Background update (silent)
        threading.Thread(
            target=updater.check_and_update,
            args=(github_repo, db_path),
            daemon=True,
        ).start()
        _proceed_after_db(root, api_key)


def _proceed_after_db(root: tk.Tk, api_key: str) -> None:
    """Called once DB is available (first launch download complete, or already exists)."""
    chat_store.init_chat_db(cfg.CHATS_DB_PATH)
    session_id = chat_store.create_session(cfg.CHATS_DB_PATH)

    # Clear any setup screens from root and build the main GUI
    for w in root.winfo_children():
        w.destroy()

    root.title("WealthOps Assistant")
    root.geometry("860x620")
    root.resizable(True, True)

    WealthOpsApp(
        root=root,
        api_key=api_key,
        db_path=cfg.KNOWLEDGE_DB_PATH,
        chats_db_path=cfg.CHATS_DB_PATH,
        session_id=session_id,
    )


def _on_db_fatal(root: tk.Tk) -> None:
    messagebox.showerror(
        "Database unavailable",
        "Couldn't download the database. "
        "Check your internet and restart, or ask Travis for help.",
    )
    root.destroy()


if __name__ == "__main__":
    main()
