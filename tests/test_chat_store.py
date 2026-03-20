import pytest

from app.chat_store import (
    add_message,
    create_session,
    get_session_messages,
    init_chat_db,
    list_sessions,
)


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "chats.db")
    init_chat_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------

def test_create_session_returns_int(db):
    sid = create_session(db)
    assert isinstance(sid, int)
    assert sid > 0


def test_create_multiple_sessions(db):
    s1 = create_session(db)
    s2 = create_session(db)
    assert s1 != s2


# ---------------------------------------------------------------------------
# Message insertion
# ---------------------------------------------------------------------------

def test_add_message_and_retrieve(db):
    sid = create_session(db)
    add_message(db, sid, "user", "Hello there")
    msgs = get_session_messages(db, sid)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hello there"


def test_messages_returned_in_order(db):
    sid = create_session(db)
    add_message(db, sid, "user", "First")
    add_message(db, sid, "assistant", "Second")
    add_message(db, sid, "user", "Third")
    msgs = get_session_messages(db, sid)
    assert [m["content"] for m in msgs] == ["First", "Second", "Third"]


def test_get_messages_for_empty_session(db):
    sid = create_session(db)
    assert get_session_messages(db, sid) == []


def test_messages_isolated_between_sessions(db):
    s1 = create_session(db)
    s2 = create_session(db)
    add_message(db, s1, "user", "Session 1 message")
    add_message(db, s2, "user", "Session 2 message")
    assert len(get_session_messages(db, s1)) == 1
    assert len(get_session_messages(db, s2)) == 1
    assert get_session_messages(db, s1)[0]["content"] == "Session 1 message"


# ---------------------------------------------------------------------------
# Title auto-generation
# ---------------------------------------------------------------------------

def test_title_set_from_first_user_message(db):
    sid = create_session(db)
    add_message(db, sid, "user", "What tax strategies have been discussed?")
    sessions = list_sessions(db)
    s = next(x for x in sessions if x["id"] == sid)
    assert s["title"] == "What tax strategies have been discussed?"


def test_title_truncated_at_60_chars(db):
    sid = create_session(db)
    long_msg = "A" * 100
    add_message(db, sid, "user", long_msg)
    sessions = list_sessions(db)
    s = next(x for x in sessions if x["id"] == sid)
    assert s["title"] == "A" * 60


def test_title_not_overwritten_by_second_user_message(db):
    sid = create_session(db)
    add_message(db, sid, "user", "First question")
    add_message(db, sid, "user", "Follow-up question")
    sessions = list_sessions(db)
    s = next(x for x in sessions if x["id"] == sid)
    assert s["title"] == "First question"


def test_title_not_set_from_assistant_message(db):
    sid = create_session(db)
    add_message(db, sid, "assistant", "Hello, how can I help?")
    sessions = list_sessions(db)
    s = next(x for x in sessions if x["id"] == sid)
    assert s["title"] is None


# ---------------------------------------------------------------------------
# last_message_at
# ---------------------------------------------------------------------------

def test_last_message_at_updated(db):
    sid = create_session(db)
    add_message(db, sid, "user", "First")
    t1 = next(x for x in list_sessions(db) if x["id"] == sid)["last_message_at"]
    add_message(db, sid, "assistant", "Second")
    t2 = next(x for x in list_sessions(db) if x["id"] == sid)["last_message_at"]
    assert t2 >= t1


# ---------------------------------------------------------------------------
# list_sessions ordering and message count
# ---------------------------------------------------------------------------

def test_list_sessions_sorted_by_last_message_desc(db):
    import time
    s1 = create_session(db)
    add_message(db, s1, "user", "Older message")
    time.sleep(0.01)
    s2 = create_session(db)
    add_message(db, s2, "user", "Newer message")

    sessions = list_sessions(db)
    ids = [s["id"] for s in sessions]
    assert ids.index(s2) < ids.index(s1)


def test_list_sessions_message_count(db):
    sid = create_session(db)
    add_message(db, sid, "user", "Q1")
    add_message(db, sid, "assistant", "A1")
    add_message(db, sid, "user", "Q2")

    sessions = list_sessions(db)
    s = next(x for x in sessions if x["id"] == sid)
    assert s["message_count"] == 3


def test_list_sessions_empty_session_has_zero_count(db):
    sid = create_session(db)
    sessions = list_sessions(db)
    s = next(x for x in sessions if x["id"] == sid)
    assert s["message_count"] == 0
