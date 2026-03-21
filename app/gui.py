"""tkinter GUI for WealthOps Assistant.

Contains no business logic — all backend calls go through the imported
app.* modules.  All GUI updates happen on the main thread; background
threads push updates via root.after().
"""

from __future__ import annotations

import os
import platform
import sys
import threading
import webbrowser
import tkinter as tk
from datetime import datetime, timedelta, timezone
from tkinter import messagebox, ttk

from app import chat_store, config as cfg, llm, retriever

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

EXAMPLE_QUESTIONS = [
    "What tax strategies have been discussed?",
    "How should I set up bookkeeping for the holding company?",
    "What did Christopher say about options trading?",
    "What tools were recommended for tracking investments?",
]

NO_RESULTS_MSG = (
    "I couldn't find anything about that in the call recordings. "
    "Try rephrasing your question or using different words."
)

_PLACEHOLDER_INPUT = "Ask about the call recordings..."
_PLACEHOLDER_HELP = "Type a message to Travis..."


def asset_path(relative_path: str) -> str:
    """Return path to a bundled asset, works both frozen (PyInstaller) and dev."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)


def _font(size: int = 13, weight: str = "normal") -> tuple:
    if platform.system() == "Windows":
        return ("Segoe UI", size, weight)
    return ("TkDefaultFont", size, weight)


# ---------------------------------------------------------------------------
# API-key entry screen (shown before main GUI on first launch)
# ---------------------------------------------------------------------------

def show_api_key_screen(root: tk.Tk, on_valid_key: callable) -> None:
    """Replace root contents with an API-key entry form.

    ``on_valid_key(key)`` is called with the validated key so the caller can
    proceed to the next startup step.  The form performs a live 1-token
    validation call before invoking the callback.
    """
    for w in root.winfo_children():
        w.destroy()

    root.title("WealthOps Assistant — Setup")
    root.geometry("480x320")
    root.resizable(False, False)

    outer = tk.Frame(root, bg="#f5f5f5")
    outer.pack(expand=True, fill="both")

    tk.Label(
        outer,
        text="Welcome to WealthOps Assistant",
        bg="#f5f5f5",
        fg="#2c3e50",
        font=_font(16, "bold"),
    ).pack(pady=(40, 8))

    tk.Label(
        outer,
        text="To get started, please enter your Claude API key below.",
        bg="#f5f5f5",
        fg="#555555",
        font=_font(12),
        wraplength=400,
        justify="center",
    ).pack(pady=(0, 20))

    key_var = tk.StringVar()
    entry = tk.Entry(
        outer,
        textvariable=key_var,
        font=_font(12),
        show="*",
        relief="solid",
        bd=1,
        width=40,
    )
    entry.pack(pady=4, ipady=6)
    entry.focus_set()

    status_var = tk.StringVar()
    status_lbl = tk.Label(
        outer, textvariable=status_var, fg="#c0392b", bg="#f5f5f5", font=_font(11)
    )
    status_lbl.pack(pady=4)

    save_btn = tk.Button(
        outer,
        text="Save & Continue",
        bg="#2c3e50",
        fg="white",
        relief="flat",
        font=_font(12, "bold"),
        padx=16,
        pady=8,
        cursor="hand2",
    )
    save_btn.pack(pady=8)

    def _validate():
        key = key_var.get().strip()
        if not key:
            status_var.set("Please enter an API key.")
            return
        save_btn.config(state="disabled", text="Validating…")
        status_var.set("")
        root.update_idletasks()

        def worker():
            valid = _check_api_key(key)
            root.after(0, _on_result, key, valid)

        threading.Thread(target=worker, daemon=True).start()

    def _on_result(key: str, valid: bool):
        if valid:
            on_valid_key(key)
        else:
            save_btn.config(state="normal", text="Save & Continue")
            status_var.set(
                "That key doesn't seem to work. Double-check it and try again, "
                "or ask Travis for help."
            )

    save_btn.config(command=_validate)
    entry.bind("<Return>", lambda _e: _validate())


def _check_api_key(key: str) -> bool:
    """Return True if the API key works (1-token validation call)."""
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    try:
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "Hi"}],
        )
        return True
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        return False
    except Exception:
        # Network error etc. — assume key might be valid; let the user proceed
        return True


# ---------------------------------------------------------------------------
# Download screen (shown when no local DB on first launch)
# ---------------------------------------------------------------------------

def show_download_screen(root: tk.Tk, on_done: callable, on_failed: callable) -> None:
    """Show a 'Downloading database…' screen in root while the DB downloads."""
    for w in root.winfo_children():
        w.destroy()

    root.title("WealthOps Assistant — Setup")

    outer = tk.Frame(root, bg="#f5f5f5")
    outer.pack(expand=True, fill="both")

    gif_label: tk.Label | None = None
    frames: list[tk.PhotoImage] = []
    try:
        path = asset_path(os.path.join("assets", "dollar.gif"))
        idx = 0
        while True:
            try:
                frames.append(tk.PhotoImage(file=path, format=f"gif -index {idx}"))
                idx += 1
            except tk.TclError:
                break
    except Exception:
        pass

    if frames:
        gif_label = tk.Label(outer, image=frames[0], bg="#f5f5f5")
        gif_label.pack(pady=(60, 8))
        _animate(root, gif_label, frames, [0])

    status_var = tk.StringVar(value="Downloading call recording database…")
    tk.Label(
        outer,
        textvariable=status_var,
        bg="#f5f5f5",
        fg="#555555",
        font=_font(13),
    ).pack(pady=8)

    def worker():
        from app import updater

        config = cfg.load_config()
        repo = config.get("github_repo", cfg.GITHUB_REPO)
        result = updater.check_and_update(repo, cfg.KNOWLEDGE_DB_PATH)
        if result in ("downloaded", "updated", "up_to_date"):
            root.after(0, on_done)
        else:
            root.after(
                0,
                lambda: status_var.set(
                    "Couldn't download the database. "
                    "Check your internet and restart, or ask Travis for help."
                ),
            )
            root.after(3000, on_failed)

    threading.Thread(target=worker, daemon=True).start()


def _animate(
    root: tk.Tk,
    label: tk.Label,
    frames: list[tk.PhotoImage],
    idx_ref: list[int],
) -> None:
    if not frames or not label.winfo_exists():
        return
    idx_ref[0] = (idx_ref[0] + 1) % len(frames)
    try:
        label.config(image=frames[idx_ref[0]])
        root.after(100, _animate, root, label, frames, idx_ref)
    except tk.TclError:
        pass


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class WealthOpsApp:
    """Main chat application widget.  Packed to fill ``root``."""

    def __init__(
        self,
        root: tk.Tk,
        api_key: str,
        db_path: str,
        chats_db_path: str,
        session_id: int,
    ) -> None:
        self.root = root
        self.api_key = api_key
        self.db_path = db_path
        self.chats_db_path = chats_db_path
        self.session_id = session_id

        self.conversation_history: list[dict] = []
        self._current_chunks: list[dict] = []
        self.current_chunk_ids: set[int] = set()
        self.stop_event = threading.Event()
        self._streaming = False
        self._has_messages = False

        # GIF animation state
        self._gif_frames: list[tk.PhotoImage] = []
        self._gif_idx_ref: list[int] = [0]
        self._gif_label: tk.Label | None = None
        self._loading_text_var: tk.StringVar | None = None

        # IRC state
        self._irc_client = None

        self._build_ui()
        self._load_gif()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root.title("WealthOps Assistant")
        self.root.configure(bg="#f5f5f5")
        self.root.minsize(700, 500)

        self._build_topbar()

        self._content = tk.Frame(self.root, bg="#f5f5f5")
        self._content.pack(fill="both", expand=True)

        self._build_chat_view()
        self._build_history_view()
        self._build_help_view()

        self._show_view("chat")

    def _build_topbar(self) -> None:
        bar = tk.Frame(self.root, bg="#2c3e50", height=50)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        tk.Label(
            bar,
            text="WealthOps Assistant",
            bg="#2c3e50",
            fg="white",
            font=_font(14, "bold"),
        ).pack(side="left", padx=16, pady=10)

        right = tk.Frame(bar, bg="#2c3e50")
        right.pack(side="right", padx=8)

        tk.Button(
            right,
            text="⚙",
            bg="#2c3e50",
            fg="white",
            relief="flat",
            font=_font(14),
            command=self.show_settings_dialog,
            cursor="hand2",
            activebackground="#3d5166",
            activeforeground="white",
        ).pack(side="right", padx=4)

        for label, cmd in [
            ("Help", self.show_help_view),
            ("History", self.show_history_view),
            ("Clear Chat", self._on_clear_chat),
        ]:
            tk.Button(
                right,
                text=label,
                bg="#3d5166",
                fg="white",
                relief="flat",
                font=_font(12),
                padx=10,
                pady=4,
                command=cmd,
                cursor="hand2",
                activebackground="#4a6580",
                activeforeground="white",
            ).pack(side="right", padx=3)

    def _build_chat_view(self) -> None:
        self._chat_frame = tk.Frame(self._content, bg="#f5f5f5")

        # ---- input area (pack first so it anchors to bottom) ----
        input_outer = tk.Frame(self._chat_frame, bg="#e0e0e0", pady=8, padx=10)
        input_outer.pack(fill="x", side="bottom")

        # ---- chat display (expands to fill remaining space above input) ----
        self._display_outer = tk.Frame(self._chat_frame, bg="#f5f5f5")
        self._display_outer.pack(fill="both", expand=True)

        self._chat_text = tk.Text(
            self._display_outer,
            bg="#f5f5f5",
            fg="#333333",
            font=_font(13),
            relief="flat",
            wrap="word",
            state="disabled",
            padx=20,
            pady=10,
            spacing1=4,
            spacing3=4,
            cursor="arrow",
        )
        self._chat_text.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(self._display_outer, command=self._chat_text.yview)
        scroll.pack(side="right", fill="y")
        self._chat_text.config(yscrollcommand=scroll.set)

        self._chat_text.tag_configure(
            "sender_you", font=_font(11, "bold"), foreground="#666666"
        )
        self._chat_text.tag_configure(
            "sender_asst", font=_font(11, "bold"), foreground="#2c3e50"
        )
        self._chat_text.tag_configure(
            "msg_you",
            font=_font(13),
            foreground="#1a1a1a",
            background="#dff0fa",
            lmargin1=20,
            lmargin2=20,
            rmargin=20,
        )
        self._chat_text.tag_configure(
            "msg_asst",
            font=_font(13),
            foreground="#1a1a1a",
            lmargin1=20,
            lmargin2=20,
            rmargin=20,
        )
        self._chat_text.tag_configure(
            "error_suffix",
            font=_font(11),
            foreground="#c0392b",
            lmargin1=20,
            lmargin2=20,
            rmargin=20,
        )
        self._chat_text.tag_configure("spacer", font=_font(5))

        # ---- loading frame ----
        self._loading_frame = tk.Frame(self._chat_frame, bg="#f5f5f5")

        # ---- welcome overlay (covers display area only, not input) ----
        self._welcome_frame = tk.Frame(self._display_outer, bg="#f5f5f5")
        self._build_welcome_content()

        self._input_text = tk.Text(
            input_outer,
            height=3,
            font=_font(13),
            relief="solid",
            bd=1,
            wrap="word",
            padx=8,
            pady=6,
        )
        self._input_text.pack(side="left", fill="both", expand=True, pady=2)
        self._input_text.insert("1.0", _PLACEHOLDER_INPUT)
        self._input_text.config(fg="#aaaaaa")
        self._input_placeholder = True
        self._input_text.bind("<Return>", self._on_enter_key)
        self._input_text.bind("<Shift-Return>", lambda e: None)
        self._input_text.bind("<FocusIn>", self._on_input_focus_in)
        self._input_text.bind("<FocusOut>", self._on_input_focus_out)
        self._input_text.bind("<Key>", self._on_input_key)

        btn_col = tk.Frame(input_outer, bg="#e0e0e0")
        btn_col.pack(side="right", padx=(8, 0))

        self._send_btn = tk.Button(
            btn_col,
            text="Send",
            bg="#2c3e50",
            fg="white",
            font=_font(12, "bold"),
            relief="flat",
            padx=14,
            pady=8,
            command=self._on_send,
            cursor="hand2",
            activebackground="#3d5166",
            activeforeground="white",
        )
        self._send_btn.pack()

        self._stop_btn = tk.Button(
            btn_col,
            text="Stop",
            bg="#c0392b",
            fg="white",
            font=_font(12, "bold"),
            relief="flat",
            padx=14,
            pady=8,
            command=self._on_stop,
            cursor="hand2",
        )
        # Stop button shown only during streaming

    def _build_welcome_content(self) -> None:
        inner = tk.Frame(self._welcome_frame, bg="#f5f5f5")
        inner.pack(expand=True, pady=30, padx=40)

        tk.Label(
            inner,
            text="Welcome! Ask me anything about your WealthOps call recordings.",
            bg="#f5f5f5",
            fg="#2c3e50",
            font=_font(15, "bold"),
            wraplength=500,
            justify="center",
        ).pack(pady=(0, 4))

        tk.Label(
            inner,
            text="Here are some ideas:",
            bg="#f5f5f5",
            fg="#2c3e50",
            font=_font(13),
            justify="center",
        ).pack(pady=(0, 12))

        for question in EXAMPLE_QUESTIONS:
            card = tk.Frame(inner, bg="#e0ecf4", relief="solid", bd=1, cursor="hand2")
            card.pack(fill="x", pady=3)
            lbl = tk.Label(
                card,
                text=question,
                bg="#e0ecf4",
                fg="#2c3e50",
                font=_font(13),
                anchor="w",
                padx=14,
                pady=9,
                cursor="hand2",
                wraplength=480,
            )
            lbl.pack(fill="x")
            for w in (card, lbl):
                w.bind("<Button-1>", lambda _e, q=question: self._on_example_click(q))

        tk.Label(inner, text="", bg="#f5f5f5").pack(pady=4)

        tips = (
            "Tips:\n"
            "  • Ask follow-up questions — I'll remember our chat\n"
            "  • Click 'Clear Chat' to start on a new topic\n"
            "  • Click 'History' to see your past conversations\n"
            "  • Click 'Help' to message Travis directly"
        )
        tk.Label(
            inner,
            text=tips,
            bg="#f5f5f5",
            fg="#666666",
            font=_font(12),
            justify="left",
            anchor="w",
        ).pack(anchor="w")

    def _build_history_view(self) -> None:
        self._history_frame = tk.Frame(self._content, bg="#f5f5f5")

        # Sub-frames: list and session detail
        self._history_list_frame = tk.Frame(self._history_frame, bg="#f5f5f5")
        self._history_detail_frame = tk.Frame(self._history_frame, bg="#f5f5f5")

        self._build_history_list_header()
        self._build_history_list_body()
        self._build_history_detail_header()
        self._build_history_detail_body()

        # Show list by default
        self._history_list_frame.pack(fill="both", expand=True)

    def _build_history_list_header(self) -> None:
        hdr = tk.Frame(self._history_list_frame, bg="#2c3e50", height=45)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="Chat History", bg="#2c3e50", fg="white", font=_font(13, "bold")
        ).pack(side="left", padx=16, pady=10)
        tk.Button(
            hdr,
            text="← Back",
            bg="#3d5166",
            fg="white",
            relief="flat",
            font=_font(12),
            padx=10,
            pady=4,
            command=lambda: self._show_view("chat"),
            cursor="hand2",
        ).pack(side="right", padx=8, pady=8)

    def _build_history_list_body(self) -> None:
        body = tk.Frame(self._history_list_frame, bg="#f5f5f5")
        body.pack(fill="both", expand=True)

        canvas = tk.Canvas(body, bg="#f5f5f5", highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)

        vbar = ttk.Scrollbar(body, command=canvas.yview)
        vbar.pack(side="right", fill="y")
        canvas.config(yscrollcommand=vbar.set)

        self._history_inner = tk.Frame(canvas, bg="#f5f5f5")
        win = canvas.create_window((0, 0), window=self._history_inner, anchor="nw")

        self._history_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(win, width=e.width),
        )

    def _build_history_detail_header(self) -> None:
        hdr = tk.Frame(self._history_detail_frame, bg="#2c3e50", height=45)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        self._history_detail_title = tk.Label(
            hdr,
            text="Past Conversation",
            bg="#2c3e50",
            fg="white",
            font=_font(13, "bold"),
        )
        self._history_detail_title.pack(side="left", padx=16, pady=10)
        tk.Button(
            hdr,
            text="← Back",
            bg="#3d5166",
            fg="white",
            relief="flat",
            font=_font(12),
            padx=10,
            pady=4,
            command=self._on_history_detail_back,
            cursor="hand2",
        ).pack(side="right", padx=8, pady=8)

    def _build_history_detail_body(self) -> None:
        body = tk.Frame(self._history_detail_frame, bg="#f5f5f5")
        body.pack(fill="both", expand=True)

        self._detail_text = tk.Text(
            body,
            bg="#f5f5f5",
            fg="#333333",
            font=_font(13),
            relief="flat",
            wrap="word",
            state="disabled",
            padx=20,
            pady=10,
            spacing1=4,
            spacing3=4,
            cursor="arrow",
        )
        self._detail_text.pack(side="left", fill="both", expand=True)
        vbar = ttk.Scrollbar(body, command=self._detail_text.yview)
        vbar.pack(side="right", fill="y")
        self._detail_text.config(yscrollcommand=vbar.set)

        self._detail_text.tag_configure(
            "sender_you", font=_font(11, "bold"), foreground="#666666"
        )
        self._detail_text.tag_configure(
            "sender_asst", font=_font(11, "bold"), foreground="#2c3e50"
        )
        self._detail_text.tag_configure(
            "msg_you",
            font=_font(13),
            foreground="#1a1a1a",
            background="#dff0fa",
            lmargin1=20,
            lmargin2=20,
            rmargin=20,
        )
        self._detail_text.tag_configure(
            "msg_asst",
            font=_font(13),
            foreground="#1a1a1a",
            lmargin1=20,
            lmargin2=20,
            rmargin=20,
        )
        self._detail_text.tag_configure("spacer", font=_font(5))

        notice_frame = tk.Frame(self._history_detail_frame, bg="#fff9e6")
        notice_frame.pack(fill="x", side="bottom")
        tk.Label(
            notice_frame,
            text="This is a past conversation (read-only).",
            bg="#fff9e6",
            fg="#555500",
            font=_font(11),
            anchor="w",
            padx=16,
            pady=6,
        ).pack(fill="x")

    def _build_help_view(self) -> None:
        self._help_frame = tk.Frame(self._content, bg="#f5f5f5")

        # Header
        hdr = tk.Frame(self._help_frame, bg="#2c3e50", height=45)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text="Help — Chat with Travis",
            bg="#2c3e50",
            fg="white",
            font=_font(13, "bold"),
        ).pack(side="left", padx=16, pady=10)
        tk.Button(
            hdr,
            text="← Back",
            bg="#3d5166",
            fg="white",
            relief="flat",
            font=_font(12),
            padx=10,
            pady=4,
            command=self._on_help_back,
            cursor="hand2",
        ).pack(side="right", padx=8, pady=8)

        # Notice bar
        self._help_notice = tk.Frame(self._help_frame, bg="#fff9e6")
        self._help_notice.pack(fill="x")
        self._help_notice_lbl = tk.Label(
            self._help_notice,
            text=(
                "Travis may not see your message right away. "
                "He'll respond when he's available."
            ),
            bg="#fff9e6",
            fg="#555500",
            font=_font(11),
            wraplength=600,
            justify="left",
            anchor="w",
            padx=16,
            pady=8,
        )
        self._help_notice_lbl.pack(fill="x")

        # Input area (pack first so it anchors to bottom)
        inp_outer = tk.Frame(self._help_frame, bg="#e0e0e0", pady=8, padx=10)
        inp_outer.pack(fill="x", side="bottom")

        # Chat display (expands to fill remaining space above input)
        help_body = tk.Frame(self._help_frame, bg="#f5f5f5")
        help_body.pack(fill="both", expand=True)

        self._help_text = tk.Text(
            help_body,
            bg="#f5f5f5",
            fg="#333333",
            font=_font(13),
            relief="flat",
            wrap="word",
            state="disabled",
            padx=20,
            pady=10,
            spacing1=4,
            spacing3=4,
            cursor="arrow",
        )
        self._help_text.pack(side="left", fill="both", expand=True)
        vbar = ttk.Scrollbar(help_body, command=self._help_text.yview)
        vbar.pack(side="right", fill="y")
        self._help_text.config(yscrollcommand=vbar.set)

        self._help_text.tag_configure(
            "sender", font=_font(11, "bold"), foreground="#2c3e50"
        )
        self._help_text.tag_configure(
            "msg", font=_font(13), foreground="#1a1a1a", lmargin1=20, lmargin2=20
        )
        self._help_text.tag_configure("spacer", font=_font(5))

        self._help_input = tk.Text(
            inp_outer,
            height=2,
            font=_font(13),
            relief="solid",
            bd=1,
            wrap="word",
            padx=8,
            pady=6,
        )
        self._help_input.pack(side="left", fill="both", expand=True, pady=2)
        self._help_input.insert("1.0", _PLACEHOLDER_HELP)
        self._help_input.config(fg="#aaaaaa")
        self._help_placeholder = True
        self._help_input.bind("<Return>", self._on_help_enter)
        self._help_input.bind("<Shift-Return>", lambda e: None)
        self._help_input.bind("<FocusIn>", self._on_help_focus_in)
        self._help_input.bind("<FocusOut>", self._on_help_focus_out)
        self._help_input.bind("<Key>", self._on_help_key)

        tk.Button(
            inp_outer,
            text="Send",
            bg="#2c3e50",
            fg="white",
            font=_font(12, "bold"),
            relief="flat",
            padx=14,
            pady=8,
            command=lambda: self._do_help_send(),
            cursor="hand2",
        ).pack(side="right", padx=(8, 0))

    # ------------------------------------------------------------------
    # View management
    # ------------------------------------------------------------------

    def _show_view(self, view: str) -> None:
        self._chat_frame.pack_forget()
        self._history_frame.pack_forget()
        self._help_frame.pack_forget()

        if view == "chat":
            self._chat_frame.pack(fill="both", expand=True)
            if not self._has_messages:
                self._show_welcome()
            else:
                self._hide_welcome()
        elif view == "history":
            self._history_frame.pack(fill="both", expand=True)
            self._history_list_frame.pack(fill="both", expand=True)
            self._history_detail_frame.pack_forget()
            self._refresh_history()
        elif view == "help":
            self._help_frame.pack(fill="both", expand=True)
            self._init_irc()

    def _show_welcome(self) -> None:
        self._welcome_frame.place(in_=self._display_outer, relwidth=1.0, relheight=1.0)
        self._welcome_frame.lift()

    def _hide_welcome(self) -> None:
        self._welcome_frame.place_forget()

    # ------------------------------------------------------------------
    # GIF loading
    # ------------------------------------------------------------------

    def _load_gif(self) -> None:
        try:
            path = asset_path(os.path.join("assets", "dollar.gif"))
            idx = 0
            while True:
                try:
                    frame = tk.PhotoImage(file=path, format=f"gif -index {idx}")
                    self._gif_frames.append(frame)
                    idx += 1
                except tk.TclError:
                    break
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Loading animation
    # ------------------------------------------------------------------

    def _show_loading(self, text: str) -> None:
        for w in self._loading_frame.winfo_children():
            w.destroy()
        self._loading_frame.pack(fill="x", padx=20, pady=8)

        if self._gif_frames:
            self._gif_idx_ref = [0]
            self._gif_label = tk.Label(
                self._loading_frame, image=self._gif_frames[0], bg="#f5f5f5"
            )
            self._gif_label.pack()
            _animate(
                self.root, self._gif_label, self._gif_frames, self._gif_idx_ref
            )

        self._loading_text_var = tk.StringVar(value=text)
        tk.Label(
            self._loading_frame,
            textvariable=self._loading_text_var,
            bg="#f5f5f5",
            fg="#666666",
            font=_font(12),
        ).pack()

    def _update_loading_text(self, text: str) -> None:
        if self._loading_text_var is not None:
            self._loading_text_var.set(text)

    def _hide_loading(self) -> None:
        self._gif_label = None
        self._loading_frame.pack_forget()

    # ------------------------------------------------------------------
    # Chat text helpers
    # ------------------------------------------------------------------

    def _append_bubble(
        self, sender: str, content: str, sender_tag: str, msg_tag: str
    ) -> None:
        self._chat_text.config(state="normal")
        self._chat_text.insert("end", "\n", "spacer")
        self._chat_text.insert("end", f"{sender}\n", sender_tag)
        self._chat_text.insert("end", content + "\n", msg_tag)
        self._chat_text.config(state="disabled")
        self._chat_text.see("end")

    def _start_asst_bubble(self) -> None:
        self._chat_text.config(state="normal")
        self._chat_text.insert("end", "\n", "spacer")
        self._chat_text.insert("end", "Assistant\n", "sender_asst")
        self._chat_text.config(state="disabled")
        self._chat_text.see("end")

    def _append_token(self, token: str) -> None:
        self._chat_text.config(state="normal")
        self._chat_text.insert("end", token, "msg_asst")
        self._chat_text.config(state="disabled")
        self._chat_text.see("end")

    def _append_error_suffix(self, error_text: str) -> None:
        self._chat_text.config(state="normal")
        self._chat_text.insert("end", f"\n\n{error_text}", "error_suffix")
        self._chat_text.config(state="disabled")
        self._chat_text.see("end")

    def _typewriter_words(
        self, full_text: str, words: list[str] | None = None, _idx: int = 0
    ) -> None:
        """Reveal *full_text* word-by-word (~50ms/word, ~20 words/sec)."""
        if words is None:
            words = full_text.split(" ")
        if _idx < len(words):
            word = words[_idx]
            prefix = " " if _idx > 0 else ""
            self._chat_text.config(state="normal")
            self._chat_text.insert("end", prefix + word, "msg_asst")
            self._chat_text.config(state="disabled")
            self._chat_text.see("end")
            self.root.after(50, self._typewriter_words, full_text, words, _idx + 1)
        else:
            # Done — save to history and finalize
            chat_store.add_message(
                self.chats_db_path, self.session_id, "assistant", full_text
            )
            self._finalize_stream()

    # ------------------------------------------------------------------
    # Sending messages
    # ------------------------------------------------------------------

    def _on_enter_key(self, event: tk.Event) -> str:
        self._on_send()
        return "break"

    def _clear_input_placeholder(self) -> None:
        if self._input_placeholder:
            self._input_text.delete("1.0", "end")
            self._input_text.config(fg="#333333")
            self._input_placeholder = False

    def _on_input_focus_in(self, _event: tk.Event) -> None:
        self._clear_input_placeholder()

    def _on_input_focus_out(self, _event: tk.Event) -> None:
        if not self._input_text.get("1.0", "end-1c").strip():
            self._input_text.delete("1.0", "end")
            self._input_text.insert("1.0", _PLACEHOLDER_INPUT)
            self._input_text.config(fg="#aaaaaa")
            self._input_placeholder = True

    def _on_input_key(self, _event: tk.Event) -> None:
        self._clear_input_placeholder()

    def _on_example_click(self, question: str) -> None:
        self._input_text.config(state="normal", fg="#333333")
        self._input_text.delete("1.0", "end")
        self._input_text.insert("1.0", question)
        self._on_send()

    def _on_send(self) -> None:
        if self._streaming:
            return

        raw = self._input_text.get("1.0", "end-1c")
        query = raw.strip()
        if not query or query == _PLACEHOLDER_INPUT:
            return

        self._input_text.delete("1.0", "end")
        self._input_text.config(fg="#333333")

        if not self._has_messages:
            self._hide_welcome()
            self._has_messages = True

        self._append_bubble("You", query, "sender_you", "msg_you")
        chat_store.add_message(self.chats_db_path, self.session_id, "user", query)

        self._input_text.config(state="disabled")
        self._send_btn.pack_forget()
        self._stop_btn.pack()
        self.stop_event.clear()
        self._streaming = True

        threading.Thread(
            target=self._stream_worker, args=(query,), daemon=True
        ).start()

    def _on_stop(self) -> None:
        self.stop_event.set()

    def _stream_worker(self, query: str) -> None:
        self.root.after(0, self._show_loading, "Searching call recordings…")

        chunks = retriever.search_chunks(self.db_path, query)

        if not chunks:
            self.root.after(0, self._hide_loading)
            self.root.after(0, self._start_asst_bubble)
            self.root.after(0, self._typewriter_words, NO_RESULTS_MSG)
            return

        # Context overlap logic
        new_ids = {c["id"] for c in chunks}
        if self.current_chunk_ids and not llm.should_replace_context(
            self.current_chunk_ids, new_ids
        ):
            new_only = [c for c in chunks if c["id"] not in self.current_chunk_ids]
            use_chunks = self._current_chunks + new_only
            self.current_chunk_ids = self.current_chunk_ids | new_ids
        else:
            use_chunks = chunks
            self._current_chunks = chunks
            self.current_chunk_ids = new_ids

        request = llm.build_request(use_chunks, self.conversation_history, query)

        self.root.after(0, self._update_loading_text, "Thinking…")

        partial: list[str] = []
        first_token = True

        for token, is_error in llm.stream_response(self.api_key, request):
            if self.stop_event.is_set():
                break

            if is_error:
                if first_token:
                    # Error before any content was shown
                    self.root.after(0, self._hide_loading)
                    self.root.after(
                        0,
                        self._append_bubble,
                        "Assistant",
                        token,
                        "sender_asst",
                        "msg_asst",
                    )
                else:
                    # Error mid-response: separate line with error styling
                    self.root.after(0, self._append_error_suffix, token)
                break
            else:
                if first_token:
                    first_token = False
                    self.root.after(0, self._hide_loading)
                    self.root.after(0, self._start_asst_bubble)
                self.root.after(0, self._append_token, token)
                partial.append(token)

        full_response = "".join(partial)
        if full_response:
            self.root.after(
                0, self._finish_with_history, query, full_response
            )
        else:
            self.root.after(0, self._finalize_stream)

    def _finish_with_history(self, query: str, response: str) -> None:
        self.conversation_history.append({"role": "user", "content": query})
        self.conversation_history.append({"role": "assistant", "content": response})
        chat_store.add_message(
            self.chats_db_path, self.session_id, "assistant", response
        )
        self._finalize_stream()

    def _finalize_stream(self) -> None:
        self._streaming = False
        self._hide_loading()
        self._stop_btn.pack_forget()
        self._send_btn.pack()
        self._input_text.config(state="normal")
        self._input_text.focus_set()

    # ------------------------------------------------------------------
    # Clear chat
    # ------------------------------------------------------------------

    def _on_clear_chat(self) -> None:
        if self._streaming:
            return
        self.session_id = chat_store.create_session(self.chats_db_path)
        self.conversation_history = []
        self._current_chunks = []
        self.current_chunk_ids = set()
        self._has_messages = False

        self._chat_text.config(state="normal")
        self._chat_text.delete("1.0", "end")
        self._chat_text.config(state="disabled")

        self._input_text.config(state="normal", fg="#333333")
        self._input_text.delete("1.0", "end")
        self._input_text.insert("1.0", _PLACEHOLDER_INPUT)
        self._input_text.config(fg="#aaaaaa")
        self._input_placeholder = True
        self._send_btn.config(state="normal")
        self._stop_btn.pack_forget()
        self._send_btn.pack()

        self._show_view("chat")

    # ------------------------------------------------------------------
    # History view
    # ------------------------------------------------------------------

    def show_history_view(self) -> None:
        self._show_view("history")

    def _refresh_history(self) -> None:
        for w in self._history_inner.winfo_children():
            w.destroy()

        sessions = [
            s for s in chat_store.list_sessions(self.chats_db_path) if s["message_count"] > 0
        ]

        if not sessions:
            tk.Label(
                self._history_inner,
                text="No past conversations yet.",
                bg="#f5f5f5",
                fg="#888888",
                font=_font(13),
                pady=20,
            ).pack()
            return

        now = datetime.now(timezone.utc)
        today = now.date()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)

        groups: dict[str, list] = {
            "Today": [],
            "Yesterday": [],
            "Last week": [],
            "Older": [],
        }
        for s in sessions:
            raw = s.get("last_message_at") or s.get("started_at") or ""
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                d = dt.date()
            except (ValueError, AttributeError):
                d = today

            if d == today:
                groups["Today"].append(s)
            elif d == yesterday:
                groups["Yesterday"].append(s)
            elif d > week_ago:
                groups["Last week"].append(s)
            else:
                groups["Older"].append(s)

        for group_name, group_sessions in groups.items():
            if not group_sessions:
                continue
            tk.Label(
                self._history_inner,
                text=group_name,
                bg="#f5f5f5",
                fg="#888888",
                font=_font(11, "bold"),
                anchor="w",
                padx=16,
                pady=6,
            ).pack(fill="x")

            for s in group_sessions:
                title = s.get("title") or "Untitled session"
                raw = s.get("last_message_at") or s.get("started_at") or ""
                try:
                    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    date_str = dt.strftime("%b %d, %Y")
                except (ValueError, AttributeError):
                    date_str = ""
                count = s.get("message_count", 0)

                card = tk.Frame(
                    self._history_inner,
                    bg="white",
                    relief="solid",
                    bd=1,
                    cursor="hand2",
                )
                card.pack(fill="x", padx=16, pady=3)

                tk.Label(
                    card,
                    text=title,
                    bg="white",
                    fg="#2c3e50",
                    font=_font(13),
                    anchor="w",
                    padx=12,
                    pady=8,
                    wraplength=550,
                ).pack(fill="x")
                tk.Label(
                    card,
                    text=f"{date_str} · {count} messages",
                    bg="white",
                    fg="#888888",
                    font=_font(11),
                    anchor="w",
                    padx=12,
                    pady=(0, 8),
                ).pack(fill="x")

                sid = s["id"]
                for widget in [card] + card.winfo_children():
                    widget.bind(
                        "<Button-1>",
                        lambda _e, s_id=sid: self._open_history_session(s_id),
                    )

    def _open_history_session(self, session_id: int) -> None:
        messages = chat_store.get_session_messages(self.chats_db_path, session_id)

        self._detail_text.config(state="normal")
        self._detail_text.delete("1.0", "end")
        self._detail_text.config(state="disabled")

        for msg in messages:
            if msg["role"] == "user":
                self._detail_text.config(state="normal")
                self._detail_text.insert("end", "\n", "spacer")
                self._detail_text.insert("end", "You\n", "sender_you")
                self._detail_text.insert("end", msg["content"] + "\n", "msg_you")
                self._detail_text.config(state="disabled")
            else:
                self._detail_text.config(state="normal")
                self._detail_text.insert("end", "\n", "spacer")
                self._detail_text.insert("end", "Assistant\n", "sender_asst")
                self._detail_text.insert("end", msg["content"] + "\n", "msg_asst")
                self._detail_text.config(state="disabled")

        self._detail_text.see("1.0")

        self._history_list_frame.pack_forget()
        self._history_detail_frame.pack(fill="both", expand=True)

    def _on_history_detail_back(self) -> None:
        self._history_detail_frame.pack_forget()
        self._history_list_frame.pack(fill="both", expand=True)
        self._refresh_history()

    # ------------------------------------------------------------------
    # Help / IRC view
    # ------------------------------------------------------------------

    def show_help_view(self) -> None:
        self._show_view("help")

    def _init_irc(self) -> None:
        if self._irc_client is not None:
            return

        from app.irc_client import HelpChat

        config = cfg.load_config()
        server = config.get("irc_server", cfg.IRC_DEFAULTS["irc_server"])
        port = config.get("irc_port", cfg.IRC_DEFAULTS["irc_port"])
        channel = config.get("irc_channel", cfg.IRC_DEFAULTS["irc_channel"])
        nick = config.get("irc_nick", cfg.IRC_DEFAULTS["irc_nick"])

        # Show connecting status immediately
        self._help_notice_lbl.config(
            text=f"Connecting to help chat ({server}:{port})...",
            bg="#fff9e6",
            fg="#555500",
        )
        self._help_notice.config(bg="#fff9e6")

        def on_message(sender: str, message: str) -> None:
            self.root.after(0, self._append_help_msg, sender, message)

        client = HelpChat(server, port, channel, nick, on_message)

        def worker() -> None:
            try:
                client.connect()
                self._irc_client = client
                self.root.after(0, self._show_irc_connected)
            except Exception as exc:
                import traceback
                detail = f"{type(exc).__name__}: {exc}"
                print(f"[IRC] Connection failed to {server}:{port} — {detail}")
                traceback.print_exc()
                self.root.after(0, self._show_irc_fallback, detail)

        threading.Thread(target=worker, daemon=True).start()

    def _show_irc_connected(self) -> None:
        self._help_notice_lbl.config(
            text=(
                "Connected to help chat. Travis may not see your message "
                "right away — he'll respond when he's available."
            ),
            bg="#e6f9e6",
            fg="#2d6a2d",
        )
        self._help_notice.config(bg="#e6f9e6")

    def _show_irc_fallback(self, detail: str = "") -> None:
        msg = "Can't connect to help chat right now."
        if detail:
            msg += f"\n({detail})"
        self._help_notice_lbl.config(
            text=msg,
            bg="#fdecea",
            fg="#c0392b",
        )
        self._help_notice.config(bg="#fdecea")

        link = tk.Label(
            self._help_notice,
            text="Email Travis instead",
            bg="#fdecea",
            fg="#2980b9",
            font=_font(11, "bold"),
            cursor="hand2",
            anchor="w",
            padx=16,
            pady=(0, 8),
        )
        link.pack(fill="x")
        link.bind(
            "<Button-1>",
            lambda _e: webbrowser.open("mailto:trout.dev.fwd@gmail.com"),
        )

        self._help_input.config(state="disabled")

    def _on_help_back(self) -> None:
        self._show_view("chat")

    def _on_help_enter(self, event: tk.Event) -> str | None:
        if event.state & 0x1:  # Shift held
            return None
        self._do_help_send()
        return "break"

    def _clear_help_placeholder(self) -> None:
        if self._help_placeholder:
            self._help_input.delete("1.0", "end")
            self._help_input.config(fg="#333333")
            self._help_placeholder = False

    def _on_help_focus_in(self, _event: tk.Event) -> None:
        self._clear_help_placeholder()

    def _on_help_focus_out(self, _event: tk.Event) -> None:
        if not self._help_input.get("1.0", "end-1c").strip():
            self._help_input.delete("1.0", "end")
            self._help_input.insert("1.0", _PLACEHOLDER_HELP)
            self._help_input.config(fg="#aaaaaa")
            self._help_placeholder = True

    def _on_help_key(self, _event: tk.Event) -> None:
        self._clear_help_placeholder()

    def _do_help_send(self) -> None:
        msg = self._help_input.get("1.0", "end-1c").strip()
        if not msg or msg == _PLACEHOLDER_HELP:
            return
        self._help_input.delete("1.0", "end")
        self._append_help_msg("You", msg)
        if self._irc_client is not None:
            self._irc_client.send(msg)

    def _append_help_msg(self, sender: str, message: str) -> None:
        self._help_text.config(state="normal")
        self._help_text.insert("end", "\n", "spacer")
        self._help_text.insert("end", f"{sender}\n", "sender")
        self._help_text.insert("end", message + "\n", "msg")
        self._help_text.config(state="disabled")
        self._help_text.see("end")

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def show_settings_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("400x230")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Settings", font=_font(14, "bold"), pady=16).pack()

        tk.Label(dialog, text="Claude API Key:", font=_font(12), anchor="w").pack(
            fill="x", padx=20
        )

        key_var = tk.StringVar(value=self.api_key or "")
        tk.Entry(
            dialog, textvariable=key_var, font=_font(12), show="*", relief="solid", bd=1
        ).pack(fill="x", padx=20, pady=4, ipady=4)

        status_var = tk.StringVar()
        status_lbl = tk.Label(
            dialog, textvariable=status_var, fg="#c0392b", font=_font(11), wraplength=360
        )
        status_lbl.pack(padx=20)

        save_btn = None  # forward ref for nested closures

        def save() -> None:
            new_key = key_var.get().strip()
            if not new_key:
                status_var.set("Please enter an API key.")
                return
            save_btn.config(state="disabled", text="Validating…")
            status_lbl.config(fg="#c0392b")
            status_var.set("")

            def worker():
                valid = _check_api_key(new_key)
                self.root.after(0, _on_validate_result, new_key, valid)

            threading.Thread(target=worker, daemon=True).start()

        def _on_validate_result(new_key: str, valid: bool) -> None:
            if valid:
                c = cfg.load_config()
                c["api_key"] = new_key
                cfg.save_config(c)
                self.api_key = new_key
                status_lbl.config(fg="#27ae60")
                status_var.set("Saved!")
                dialog.after(1500, dialog.destroy)
            else:
                save_btn.config(state="normal", text="Save")
                status_var.set(
                    "That key doesn't seem to work. Double-check it "
                    "and try again, or ask Travis for help."
                )

        btn_row = tk.Frame(dialog)
        btn_row.pack(pady=10)
        save_btn = tk.Button(
            btn_row,
            text="Save",
            bg="#2c3e50",
            fg="white",
            relief="flat",
            font=_font(12),
            padx=14,
            pady=6,
            command=save,
            cursor="hand2",
        )
        save_btn.pack(side="left", padx=8)
        tk.Button(
            btn_row,
            text="Cancel",
            relief="flat",
            font=_font(12),
            padx=14,
            pady=6,
            command=dialog.destroy,
            cursor="hand2",
        ).pack(side="left")

        tk.Button(
            dialog,
            text="Check for updates",
            relief="flat",
            font=_font(11),
            fg="#2980b9",
            bg="white",
            cursor="hand2",
            command=lambda: self._check_updates_manual(dialog),
        ).pack(pady=4)

    def _check_updates_manual(self, parent: tk.Toplevel) -> None:
        from app import updater

        config = cfg.load_config()
        repo = config.get("github_repo", cfg.GITHUB_REPO)

        def worker() -> None:
            result = updater.check_and_update(repo, self.db_path)
            messages = {
                "updated": "Database updated to the latest version.",
                "up_to_date": "You already have the latest database.",
                "downloaded": "Database downloaded successfully.",
                "failed": "Update check failed. Try again later.",
                "no_internet": "Can't reach the internet. Check your WiFi.",
            }
            msg = messages.get(result, "Update check complete.")
            self.root.after(0, messagebox.showinfo, "Update", msg)

        threading.Thread(target=worker, daemon=True).start()
