import asyncio
from pathlib import Path
from types import SimpleNamespace

from telethon.tl import functions, types

from tgcli.cli import build_parser
from tgcli.config import RuntimeConfig
from tgcli.errors import CliError
from tgcli.telegram import post_story_photo, story_period_seconds, story_privacy_rules, story_targets


class FakeStoryClient:
    def __init__(self, *, can_post: bool = True) -> None:
        self.can_post = can_post
        self.requests = []
        self.uploads = []

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def is_user_authorized(self) -> bool:
        return True

    async def get_input_entity(self, value):
        return f"input:{value}"

    async def upload_file(self, path: str):
        self.uploads.append(path)
        return "uploaded-file"

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, functions.stories.GetChatsToSendRequest):
            return SimpleNamespace(
                chats=[
                    types.Channel(
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
                ]
            )
        if isinstance(request, functions.stories.CanSendStoryRequest):
            if self.can_post:
                return SimpleNamespace(count_remains=3)
            raise FakeStoryRpcError("PREMIUM_ACCOUNT_REQUIRED")
        if isinstance(request, functions.stories.SendStoryRequest):
            return SimpleNamespace(
                updates=[
                    types.UpdateStoryID(id=321, random_id=request.random_id),
                ]
            )
        raise AssertionError(f"Unexpected request: {request!r}")


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


def test_story_privacy_rules() -> None:
    assert isinstance(story_privacy_rules("public")[0], types.InputPrivacyValueAllowAll)
    assert isinstance(story_privacy_rules("contacts")[0], types.InputPrivacyValueAllowContacts)
    assert isinstance(story_privacy_rules("close-friends")[0], types.InputPrivacyValueAllowCloseFriends)


def test_story_period_seconds() -> None:
    assert story_period_seconds(6) == 21600
    assert story_period_seconds(24) == 86400


def test_post_story_photo_builds_send_story_request(monkeypatch, tmp_path: Path) -> None:
    runtime = runtime_for(tmp_path)
    photo = tmp_path / "story.jpg"
    photo.write_bytes(b"fake-jpeg")
    fake_client = FakeStoryClient()

    monkeypatch.setattr("tgcli.telegram.api_credentials", lambda _runtime: (123, "hash"))
    monkeypatch.setattr("tgcli.telegram.make_client", lambda *_args, **_kwargs: fake_client)

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


def test_post_story_photo_preflights_before_upload(monkeypatch, tmp_path: Path) -> None:
    runtime = runtime_for(tmp_path)
    photo = tmp_path / "story.jpg"
    photo.write_bytes(b"fake-jpeg")
    fake_client = FakeStoryClient(can_post=False)

    monkeypatch.setattr("tgcli.telegram.RPCError", FakeStoryRpcError)
    monkeypatch.setattr("tgcli.telegram.api_credentials", lambda _runtime: (123, "hash"))
    monkeypatch.setattr("tgcli.telegram.make_client", lambda *_args, **_kwargs: fake_client)

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


def test_story_targets(monkeypatch, tmp_path: Path) -> None:
    runtime = runtime_for(tmp_path)
    fake_client = FakeStoryClient()

    monkeypatch.setattr("tgcli.telegram.api_credentials", lambda _runtime: (123, "hash"))
    monkeypatch.setattr("tgcli.telegram.make_client", lambda *_args, **_kwargs: fake_client)

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
