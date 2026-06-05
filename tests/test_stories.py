import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch
from telethon.tl import functions, types

from tgcli.cli import build_parser
from tgcli.config import RuntimeConfig
from tgcli.errors import CliError
from tgcli.telegram import (
    post_story_photo,
    story_config_from_app_config,
    story_history,
    story_limits,
    story_period_seconds,
    story_privacy_rules,
    story_targets,
    story_wait_seconds,
)


class FakeStoryClient:
    def __init__(self, *, can_post: bool = True) -> None:
        self.can_post = can_post
        self.requests: list[object] = []
        self.uploads: list[str] = []

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def is_user_authorized(self) -> bool:
        return True

    async def get_input_entity(self, value: object) -> str:
        return f"input:{value}"

    async def upload_file(self, path: str) -> str:
        self.uploads.append(path)
        return "uploaded-file"

    async def __call__(self, request: object) -> object:
        self.requests.append(request)
        for request_type, handler in self.request_handlers():
            if isinstance(request, request_type):
                return handler(request)
        raise AssertionError(f"Unexpected request: {request!r}")

    def request_handlers(self) -> list[tuple[type[object], Callable[[object], object]]]:
        return [
            (functions.help.GetAppConfigRequest, self.app_config),
            (functions.stories.GetPeerStoriesRequest, self.peer_stories),
            (functions.stories.GetStoriesArchiveRequest, self.stories_archive),
            (functions.stories.GetChatsToSendRequest, self.chats_to_send),
            (functions.stories.CanSendStoryRequest, self.can_send_story),
            (functions.stories.SendStoryRequest, self.send_story),
        ]

    def app_config(self, request: object) -> object:
        return SimpleNamespace(config=types.JsonObject(story_config_values()))

    def peer_stories(self, request: object) -> object:
        return types.stories.PeerStories(
            stories=types.PeerStories(
                peer=types.PeerUser(user_id=42),
                stories=[story_item(5, "active story", contacts=True)],
            ),
            chats=[],
            users=[],
        )

    def stories_archive(self, request: object) -> object:
        return types.stories.Stories(
            count=1,
            stories=[story_item(4, "archived story", public=True)],
            chats=[],
            users=[],
        )

    def chats_to_send(self, request: object) -> object:
        return SimpleNamespace(chats=[story_channel()])

    def can_send_story(self, request: object) -> object:
        if self.can_post:
            return SimpleNamespace(count_remains=3)
        raise FakeStoryRpcError("PREMIUM_ACCOUNT_REQUIRED")

    def send_story(self, request: object) -> object:
        return SimpleNamespace(updates=[types.UpdateStoryID(id=321, random_id=request.random_id)])


def story_config_values() -> list[object]:
    return [
        types.JsonObjectValue("stories_posting", types.JsonString("enabled")),
        types.JsonObjectValue("story_expiring_limit_default", types.JsonNumber(1)),
        types.JsonObjectValue("story_expiring_limit_premium", types.JsonNumber(100)),
        types.JsonObjectValue("stories_sent_weekly_limit_default", types.JsonNumber(3)),
        types.JsonObjectValue("stories_sent_monthly_limit_default", types.JsonNumber(10)),
        types.JsonObjectValue("story_caption_length_limit_default", types.JsonNumber(200)),
        types.JsonObjectValue("story_expire_period", types.JsonNumber(86400)),
        types.JsonObjectValue("unrelated", types.JsonString("ignored")),
    ]


def story_item(identifier: int, caption: str, *, contacts: bool = False, public: bool = False) -> object:
    return types.StoryItem(
        id=identifier,
        date=None,
        expire_date=None,
        media=types.MessageMediaEmpty(),
        caption=caption,
        out=True,
        contacts=contacts,
        public=public,
    )


def story_channel() -> object:
    return types.Channel(
        id=777,
        title="Story Channel",
        photo=types.ChatPhotoEmpty(),
        date=None,
        creator=True,
        left=False,
        broadcast=True,
        megagroup=False,
        restricted=False,
        signatures=False,
        min=False,
        scam=False,
        has_link=False,
        has_geo=False,
        slowmode_enabled=False,
        call_active=False,
        call_not_empty=False,
        fake=False,
        gigagroup=False,
        noforwards=False,
        join_to_send=False,
        join_request=False,
        forum=False,
        stories_hidden=False,
        stories_hidden_min=False,
        stories_unavailable=False,
        access_hash=123,
    )


class FakeStoryRpcError(Exception):
    pass


def runtime_for(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        store_dir=tmp_path,
        account="default",
        account_dir=tmp_path,
        json_output=False,
        full_output=False,
        read_only=False,
    )


def test_stories_post_parser_defaults() -> None:
    args = build_parser().parse_args(["stories", "post", "--file", "photo.jpg"])

    assert args.command == "stories"
    assert args.stories_command == "post"
    assert args.as_peer == "me"
    assert args.privacy == "contacts"
    assert args.period_hours == 24
    assert not args.pinned
    assert not args.no_forwards


def test_stories_targets_parser() -> None:
    args = build_parser().parse_args(["stories", "targets"])

    assert args.command == "stories"
    assert args.stories_command == "targets"


def test_stories_history_parser() -> None:
    args = build_parser().parse_args(["stories", "history", "--limit", "5"])

    assert args.command == "stories"
    assert args.stories_command == "history"
    assert args.as_peer == "me"
    assert args.limit == 5


def test_story_privacy_rules() -> None:
    assert isinstance(story_privacy_rules("public")[0], types.InputPrivacyValueAllowAll)
    assert isinstance(story_privacy_rules("contacts")[0], types.InputPrivacyValueAllowContacts)
    assert isinstance(story_privacy_rules("close-friends")[0], types.InputPrivacyValueAllowCloseFriends)


def test_story_period_seconds() -> None:
    assert story_period_seconds(6) == 21600
    assert story_period_seconds(24) == 86400


def test_story_wait_seconds() -> None:
    assert story_wait_seconds("STORY_SEND_FLOOD_WEEKLY_12345") == 12345
    assert story_wait_seconds("STORY_SEND_FLOOD_MONTHLY_99") == 99
    assert story_wait_seconds("PREMIUM_ACCOUNT_REQUIRED") is None


def test_story_config_from_app_config_filters_story_keys() -> None:
    app_config = SimpleNamespace(
        config=types.JsonObject(
            [
                types.JsonObjectValue("stories_posting", types.JsonString("enabled")),
                types.JsonObjectValue("story_expiring_limit_default", types.JsonNumber(1)),
                types.JsonObjectValue("unrelated", types.JsonString("ignored")),
            ]
        )
    )

    assert story_config_from_app_config(app_config) == {
        "stories_posting": "enabled",
        "story_expiring_limit_default": 1,
    }


def test_post_story_photo_builds_send_story_request(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    runtime = runtime_for(tmp_path)
    photo = tmp_path / "story.jpg"
    photo.write_bytes(b"fake-jpeg")
    fake_client = FakeStoryClient()

    monkeypatch.setattr("tgcli.telegram_client.api_credentials", lambda _runtime: (123, "hash"))
    monkeypatch.setattr("tgcli.telegram_client.make_client", lambda *_args, **_kwargs: fake_client)

    result = asyncio.run(
        post_story_photo(
            runtime,
            as_peer="me",
            file_path=photo,
            caption="sent by tgcli",
            privacy="contacts",
            period_hours=24,
            pinned=True,
            noforwards=True,
        )
    )

    assert result["story_id"] == 321
    assert result["caption"] == "sent by tgcli"
    assert result["privacy"] == "contacts"
    assert fake_client.uploads == [str(photo)]
    assert isinstance(fake_client.requests[0], functions.stories.CanSendStoryRequest)
    request = fake_client.requests[1]
    assert isinstance(request, functions.stories.SendStoryRequest)
    assert request.peer == "input:me"
    assert isinstance(request.media, types.InputMediaUploadedPhoto)
    assert request.media.file == "uploaded-file"
    assert request.caption == "sent by tgcli"
    assert request.period == 86400
    assert request.pinned is True
    assert request.noforwards is True
    assert isinstance(request.privacy_rules[0], types.InputPrivacyValueAllowContacts)


def test_post_story_photo_preflights_before_upload(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    runtime = runtime_for(tmp_path)
    photo = tmp_path / "story.jpg"
    photo.write_bytes(b"fake-jpeg")
    fake_client = FakeStoryClient(can_post=False)

    monkeypatch.setattr("tgcli.telegram_stories.RPCError", FakeStoryRpcError)
    monkeypatch.setattr("tgcli.telegram_client.api_credentials", lambda _runtime: (123, "hash"))
    monkeypatch.setattr("tgcli.telegram_client.make_client", lambda *_args, **_kwargs: fake_client)

    try:
        asyncio.run(
            post_story_photo(
                runtime,
                as_peer="me",
                file_path=photo,
                caption="sent by tgcli",
                privacy="contacts",
                period_hours=24,
                pinned=False,
                noforwards=False,
            )
        )
    except CliError as exc:
        assert "will not allow posting a story" in str(exc)
    else:
        raise AssertionError("Expected blocked story posting to raise CliError")

    assert len(fake_client.requests) == 1
    assert isinstance(fake_client.requests[0], functions.stories.CanSendStoryRequest)
    assert fake_client.uploads == []


def test_story_targets(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    runtime = runtime_for(tmp_path)
    fake_client = FakeStoryClient()

    monkeypatch.setattr("tgcli.telegram_client.api_credentials", lambda _runtime: (123, "hash"))
    monkeypatch.setattr("tgcli.telegram_client.make_client", lambda *_args, **_kwargs: fake_client)

    result = asyncio.run(story_targets(runtime))

    assert result == [
        {
            "chat_id": -1000000000777,
            "title": "Story Channel",
            "kind": "channel",
            "username": None,
            "phone": None,
        }
    ]
    assert isinstance(fake_client.requests[0], functions.stories.GetChatsToSendRequest)


def test_story_limits(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    runtime = runtime_for(tmp_path)
    fake_client = FakeStoryClient()

    monkeypatch.setattr("tgcli.telegram_client.api_credentials", lambda _runtime: (123, "hash"))
    monkeypatch.setattr("tgcli.telegram_client.make_client", lambda *_args, **_kwargs: fake_client)

    result = asyncio.run(story_limits(runtime, as_peer="me"))

    assert result["eligibility"]["can_post"] is True
    assert result["eligibility"]["remaining_active_slots"] == 3
    assert result["posting_mode"] == "enabled"
    assert result["free"]["active_limit"] == 1
    assert result["free"]["weekly_send_limit"] == 3
    assert result["free"]["monthly_send_limit"] == 10
    assert result["free"]["expiry_seconds"] == 86400
    assert "unrelated" not in result["raw_config"]
    assert isinstance(fake_client.requests[0], functions.help.GetAppConfigRequest)
    assert isinstance(fake_client.requests[1], functions.stories.CanSendStoryRequest)


def test_story_history(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    runtime = runtime_for(tmp_path)
    fake_client = FakeStoryClient()

    monkeypatch.setattr("tgcli.telegram_client.api_credentials", lambda _runtime: (123, "hash"))
    monkeypatch.setattr("tgcli.telegram_client.make_client", lambda *_args, **_kwargs: fake_client)

    result = asyncio.run(story_history(runtime, as_peer="me", limit=5))

    assert result["active_count"] == 1
    assert result["archive_count"] == 1
    assert result["active"][0]["caption"] == "active story"
    assert result["active"][0]["contacts"] is True
    assert result["archive"][0]["caption"] == "archived story"
    assert result["archive"][0]["public"] is True
    assert isinstance(fake_client.requests[0], functions.stories.GetPeerStoriesRequest)
    assert isinstance(fake_client.requests[1], functions.stories.GetStoriesArchiveRequest)
