"""IRC help client for WealthOps Assistant.

HelpChat connects to an IRC server over TLS and relays channel / private
messages to the caller via an on_message callback.  The reactor loop runs
in a daemon background thread; auto-reconnect uses exponential backoff.
"""

from __future__ import annotations

import logging
import ssl
import threading
import time
from typing import Callable

import irc.client
import irc.connection

log = logging.getLogger("wealthops.irc")
log.setLevel(logging.DEBUG)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[IRC] %(message)s"))
    log.addHandler(_h)


class HelpChat:
    """IRC-backed help chat.

    Usage::

        def on_msg(sender, message):
            print(f"<{sender}> {message}")

        chat = HelpChat("irc.greed.software", 6697, "#wealthops", "Barbara", on_msg)
        chat.connect()   # blocks until welcome or raises ConnectionError
        chat.send("Hello!")
        # ...
        chat.disconnect()
    """

    _MAX_BACKOFF: int = 30

    def __init__(
        self,
        server: str,
        port: int,
        channel: str,
        nickname: str,
        on_message: Callable[[str, str], None],
    ) -> None:
        self.server = server
        self.port = port
        self.channel = channel
        self.nickname = nickname
        self.on_message = on_message

        self._reactor = irc.client.Reactor()
        self._conn: irc.client.ServerConnection | None = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._connect_error: Exception | None = None
        self._backoff: int = 1
        self._thread: threading.Thread | None = None

        # Register handlers once; they apply to every connection this reactor manages.
        self._reactor.add_global_handler("welcome", self._on_welcome)
        self._reactor.add_global_handler("pubmsg", self._on_pubmsg)
        self._reactor.add_global_handler("privmsg", self._on_privmsg)
        self._reactor.add_global_handler("disconnect", self._on_disconnect)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to IRC (TLS) and block until the welcome message arrives.

        Raises ``ConnectionError`` if the connection times out or fails.
        Call this once; the background thread handles subsequent reconnects.
        """
        log.info("connect() called — %s:%d nick=%s", self.server, self.port, self.nickname)
        self._stop.clear()
        self._connected.clear()
        self._connect_error = None
        self._make_connection()

        if not self._connected.wait(timeout=15):
            log.error("connect() timed out after 15s — welcome never arrived")
            raise ConnectionError("IRC connection timed out")
        if self._connect_error is not None:
            log.error("connect() failed: %s", self._connect_error)
            raise ConnectionError(str(self._connect_error)) from self._connect_error
        log.info("connect() succeeded")

    def send(self, message: str) -> None:
        """Send *message* to the channel (no-op if not connected)."""
        connected = self._conn is not None and self._conn.is_connected()
        log.debug("send() called — connected=%s, channel=%s", connected, self.channel)
        if connected:
            self._conn.privmsg(self.channel, message)
        else:
            log.warning("send() skipped — not connected")

    def disconnect(self) -> None:
        """Stop the auto-reconnect loop and disconnect cleanly."""
        self._stop.set()
        conn = self._conn
        if conn is not None:
            try:
                conn.disconnect("Goodbye")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_connection(self) -> None:
        """Attempt one TCP+TLS connect; signal _connected on success or failure."""
        log.info("_make_connection() — attempting TLS to %s:%d", self.server, self.port)
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            factory = irc.connection.Factory(wrapper=ctx.wrap_socket)
            conn = self._reactor.server()
            conn.connect(self.server, self.port, self.nickname, connect_factory=factory)
            self._conn = conn
            log.info("_make_connection() — socket connect initiated (waiting for welcome)")
        except Exception as exc:
            log.error("_make_connection() — socket/TLS failed: %r", exc)
            self._connect_error = exc
            self._connected.set()
            return

        # Start reactor thread if not already running.  process_forever() picks
        # up new connections automatically so a single thread is sufficient.
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._reactor.process_forever, daemon=True
            )
            self._thread.start()

    def _on_welcome(
        self,
        connection: irc.client.ServerConnection,
        event: irc.client.Event,
    ) -> None:
        log.info("_on_welcome fired — server accepted connection")
        log.info("Joining channel %s", self.channel)
        connection.join(self.channel)
        self._backoff = 1  # reset backoff on successful connect
        self._connect_error = None
        self._connected.set()

    def _on_pubmsg(
        self,
        connection: irc.client.ServerConnection,
        event: irc.client.Event,
    ) -> None:
        self.on_message(event.source.nick, event.arguments[0])

    def _on_privmsg(
        self,
        connection: irc.client.ServerConnection,
        event: irc.client.Event,
    ) -> None:
        self.on_message(event.source.nick, event.arguments[0])

    def _on_disconnect(
        self,
        connection: irc.client.ServerConnection,
        event: irc.client.Event,
    ) -> None:
        log.warning("_on_disconnect fired — lost connection")
        self._conn = None
        if not self._stop.is_set():
            log.info("Scheduling reconnect in %ds", self._backoff)
            t = threading.Timer(self._backoff, self._reconnect)
            t.daemon = True
            t.start()
            self._backoff = min(self._backoff * 2, self._MAX_BACKOFF)

    def _reconnect(self) -> None:
        if not self._stop.is_set():
            self._make_connection()
