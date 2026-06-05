from pathlib import Path

from tgcli.store import ChatRecord, MessageRecord, Store, quote_fts_phrase, rows_to_public


def test_store_sync_and_search(tmp_path: Path) -> None:
    db = tmp_path / "tgcli.db"
    with Store(db) as store:
        store.upsert_chat(ChatRecord(chat_id=1, title="Ada", kind="user", username="ada"))
        store.upsert_message(
            MessageRecord(
                chat_id=1,
                message_id=10,
                date="2026-06-05T10:00:00+00:00",
                sender_id=2,
                sender_name="Ada",
                chat_title="Ada",
                text="Meet at the cafe",
            )
        )
        store.commit()
        rows = rows_to_public(store.search_messages("cafe"))

    assert rows[0]["message_id"] == 10
    assert rows[0]["text"] == "Meet at the cafe"


def test_upsert_replaces_fts_content(tmp_path: Path) -> None:
    db = tmp_path / "tgcli.db"
    with Store(db) as store:
        record = MessageRecord(
            chat_id=1,
            message_id=10,
            date=None,
            sender_id=None,
            sender_name=None,
            chat_title="Ada",
            text="old text",
        )
        store.upsert_message(record)
        store.upsert_message(
            MessageRecord(
                chat_id=1,
                message_id=10,
                date=None,
                sender_id=None,
                sender_name=None,
                chat_title="Ada",
                text="new text",
            )
        )
        store.commit()
        assert store.search_messages("new")
        assert not store.search_messages("old")


def test_quote_fts_phrase_escapes_quotes() -> None:
    assert quote_fts_phrase('a "quote"') == '"a ""quote"""'
