from tgcli.output import truncate


def test_truncate_preserves_short_values() -> None:
    assert truncate("hello", 10, False) == "hello"


def test_truncate_uses_ellipsis() -> None:
    assert truncate("hello world", 6, False) == "hel..."


def test_truncate_full_output() -> None:
    assert truncate("hello world", 6, True) == "hello world"
