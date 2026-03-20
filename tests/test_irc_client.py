"""Tests for app/irc_client.py.

All tests mock the irc.client and irc.connection modules so no live IRC
server is required.
"""

from __future__ import annotations

import ssl
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from app.irc_client import HelpChat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chat(on_message=None):
    if on_message is None:
        on_message = MagicMock()
    return HelpChat(
        server="irc.example.com",
        port=6697,
        channel="#test",
        nickname="TestBot",
        on_message=on_message,
    )


def _fake_event(nick: str, args: list[str]) -> MagicMock:
    event = MagicMock()
    event.source.nick = nick
    event.arguments = args
    return event


# ---------------------------------------------------------------------------
# __init__ — handlers registered once
# ---------------------------------------------------------------------------

def test_handlers_registered_on_init():
    with patch("irc.client.Reactor") as MockReactor:
        reactor = MagicMock()
        MockReactor.return_value = reactor
        _make_chat()
        assert reactor.add_global_handler.call_count == 4
        names = {c.args[0] for c in reactor.add_global_handler.call_args_list}
        assert names == {"welcome", "pubmsg", "privmsg", "disconnect"}


# ---------------------------------------------------------------------------
# connect() — success path
# ---------------------------------------------------------------------------

def test_connect_success():
    """connect() returns without raising when welcome fires in time."""
    with (
        patch("irc.client.Reactor") as MockReactor,
        patch("irc.connection.Factory"),
        patch("ssl.SSLContext"),
    ):
        reactor = MagicMock()
        MockReactor.return_value = reactor

        chat = _make_chat()

        def fake_connect(*args, **kwargs):
            # Simulate welcome event firing after connect
            threading.Timer(
                0.05,
                lambda: chat._on_welcome(MagicMock(), MagicMock()),
            ).start()

        reactor.server.return_value.connect.side_effect = fake_connect

        # Should not raise
        chat.connect()

        assert chat._connected.is_set()
        assert chat._connect_error is None


def test_connect_starts_reactor_thread():
    """The reactor process_forever loop is started in a daemon thread."""
    with (
        patch("irc.client.Reactor") as MockReactor,
        patch("irc.connection.Factory"),
        patch("ssl.SSLContext"),
    ):
        reactor = MagicMock()
        reactor.process_forever = MagicMock()
        MockReactor.return_value = reactor

        chat = _make_chat()

        def fake_connect(*args, **kwargs):
            threading.Timer(
                0.05,
                lambda: chat._on_welcome(MagicMock(), MagicMock()),
            ).start()

        reactor.server.return_value.connect.side_effect = fake_connect
        chat.connect()

        # Give thread a moment to start
        time.sleep(0.1)
        assert chat._thread is not None
        assert chat._thread.daemon is True


# ---------------------------------------------------------------------------
# connect() — failure paths
# ---------------------------------------------------------------------------

def test_connect_raises_on_network_error():
    """connect() raises ConnectionError when irc.connect() throws."""
    with (
        patch("irc.client.Reactor") as MockReactor,
        patch("irc.connection.Factory"),
        patch("ssl.SSLContext"),
    ):
        reactor = MagicMock()
        MockReactor.return_value = reactor
        reactor.server.return_value.connect.side_effect = OSError("refused")

        chat = _make_chat()
        with pytest.raises(ConnectionError):
            chat.connect()


def test_connect_raises_on_timeout():
    """connect() raises ConnectionError when welcome never arrives (timeout=0 for test)."""
    with (
        patch("irc.client.Reactor") as MockReactor,
        patch("irc.connection.Factory"),
        patch("ssl.SSLContext"),
    ):
        reactor = MagicMock()
        MockReactor.return_value = reactor
        # connect() does nothing — welcome never fires
        reactor.server.return_value.connect.return_value = None

        chat = _make_chat()
        # Patch timeout to 0 so the test doesn't wait 15 seconds
        chat._connected = threading.Event()  # never set
        original_wait = chat._connected.wait

        def fast_wait(timeout=None):
            return original_wait(timeout=0.05)

        chat._connected.wait = fast_wait

        with pytest.raises(ConnectionError, match="timed out"):
            chat.connect()


# ---------------------------------------------------------------------------
# send()
# ---------------------------------------------------------------------------

def test_send_calls_privmsg_when_connected():
    chat = _make_chat()
    conn = MagicMock()
    conn.is_connected.return_value = True
    chat._conn = conn

    chat.send("Hello world")

    conn.privmsg.assert_called_once_with("#test", "Hello world")


def test_send_is_noop_when_not_connected():
    chat = _make_chat()
    chat._conn = None  # no connection

    # Should not raise
    chat.send("Hello world")


def test_send_is_noop_when_connection_object_says_disconnected():
    chat = _make_chat()
    conn = MagicMock()
    conn.is_connected.return_value = False
    chat._conn = conn

    chat.send("Hello world")

    conn.privmsg.assert_not_called()


# ---------------------------------------------------------------------------
# on_message callback — pubmsg and privmsg
# ---------------------------------------------------------------------------

def test_on_pubmsg_calls_callback():
    on_msg = MagicMock()
    chat = _make_chat(on_message=on_msg)
    event = _fake_event("travis", ["Hey there"])
    chat._on_pubmsg(MagicMock(), event)
    on_msg.assert_called_once_with("travis", "Hey there")


def test_on_privmsg_calls_callback():
    on_msg = MagicMock()
    chat = _make_chat(on_message=on_msg)
    event = _fake_event("travis", ["Private message"])
    chat._on_privmsg(MagicMock(), event)
    on_msg.assert_called_once_with("travis", "Private message")


# ---------------------------------------------------------------------------
# disconnect()
# ---------------------------------------------------------------------------

def test_disconnect_sets_stop_event():
    chat = _make_chat()
    conn = MagicMock()
    conn.is_connected.return_value = True
    chat._conn = conn

    chat.disconnect()

    assert chat._stop.is_set()


def test_disconnect_calls_irc_disconnect():
    chat = _make_chat()
    conn = MagicMock()
    conn.is_connected.return_value = True
    chat._conn = conn

    chat.disconnect()

    conn.disconnect.assert_called_once_with("Goodbye")


def test_disconnect_tolerates_no_connection():
    chat = _make_chat()
    chat._conn = None
    # Should not raise
    chat.disconnect()


def test_disconnect_tolerates_exception_in_irc_disconnect():
    chat = _make_chat()
    conn = MagicMock()
    conn.disconnect.side_effect = Exception("already gone")
    chat._conn = conn

    # Should not raise
    chat.disconnect()


# ---------------------------------------------------------------------------
# Auto-reconnect logic
# ---------------------------------------------------------------------------

def test_on_disconnect_schedules_reconnect_when_not_stopped():
    chat = _make_chat()
    chat._stop.clear()

    with patch.object(chat, "_reconnect") as mock_reconnect:
        # Use Timer mock to capture the delay
        with patch("threading.Timer") as MockTimer:
            timer_instance = MagicMock()
            MockTimer.return_value = timer_instance
            chat._on_disconnect(MagicMock(), MagicMock())

        MockTimer.assert_called_once()
        args = MockTimer.call_args
        assert args[0][0] == 1  # initial backoff = 1s
        assert args[0][1] == chat._reconnect
        timer_instance.start.assert_called_once()


def test_on_disconnect_does_not_reconnect_when_stopped():
    chat = _make_chat()
    chat._stop.set()

    with patch("threading.Timer") as MockTimer:
        chat._on_disconnect(MagicMock(), MagicMock())
        MockTimer.assert_not_called()


def test_backoff_doubles_on_each_disconnect():
    chat = _make_chat()
    chat._stop.clear()

    delays = []
    with patch("threading.Timer") as MockTimer:
        timer = MagicMock()
        MockTimer.return_value = timer

        for _ in range(4):
            chat._on_disconnect(MagicMock(), MagicMock())
            delays.append(MockTimer.call_args[0][0])

    assert delays == [1, 2, 4, 8]


def test_backoff_capped_at_max():
    chat = _make_chat()
    chat._stop.clear()
    chat._backoff = 16  # one step below max

    with patch("threading.Timer") as MockTimer:
        timer = MagicMock()
        MockTimer.return_value = timer
        chat._on_disconnect(MagicMock(), MagicMock())
        delay = MockTimer.call_args[0][0]

    assert delay == 16
    assert chat._backoff == 30  # capped


def test_backoff_resets_on_welcome():
    chat = _make_chat()
    chat._backoff = 16

    conn = MagicMock()
    chat._on_welcome(conn, MagicMock())

    assert chat._backoff == 1


def test_reconnect_calls_make_connection_when_not_stopped():
    chat = _make_chat()
    chat._stop.clear()
    with patch.object(chat, "_make_connection") as mock_make:
        chat._reconnect()
        mock_make.assert_called_once()


def test_reconnect_does_nothing_when_stopped():
    chat = _make_chat()
    chat._stop.set()
    with patch.object(chat, "_make_connection") as mock_make:
        chat._reconnect()
        mock_make.assert_not_called()


# ---------------------------------------------------------------------------
# _on_welcome — joins channel
# ---------------------------------------------------------------------------

def test_on_welcome_joins_channel():
    chat = _make_chat()
    conn = MagicMock()
    chat._on_welcome(conn, MagicMock())
    conn.join.assert_called_once_with("#test")


def test_on_welcome_sets_connected_event():
    chat = _make_chat()
    chat._on_welcome(MagicMock(), MagicMock())
    assert chat._connected.is_set()


def test_on_welcome_clears_connect_error():
    chat = _make_chat()
    chat._connect_error = Exception("stale error")
    chat._on_welcome(MagicMock(), MagicMock())
    assert chat._connect_error is None
