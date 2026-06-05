from __future__ import annotations

import secrets
from pathlib import Path
from typing import Protocol

from telethon.errors import RPCError
from telethon.tl import functions, types

from .config import RuntimeConfig
from .dynamic import attribute
from .errors import CliError
from .telegram_client import connected_client
from .telegram_live import close_optional_store, open_optional_store
from .telegram_mapping import entity_to_public
from .telegram_resolve import EntityResolver, resolve_input_peer
from .telegram_story_values import (
    optional_count,
    public_story_list,
    sequence_attr,
    story_config_from_app_config,
    story_id_from_updates,
    story_period_seconds,
    story_privacy_rules,
    story_wait_seconds,
    validate_story_photo,
)
from .types import JsonObject, JsonRows


class StoryClient(EntityResolver, Protocol):
    # Story workflows need a callable Telegram client plus upload and entity resolution.
    async def __call__(self, request: object) -> object: ...

    async def upload_file(self, path: str) -> object: ...


async def can_post_story(runtime: RuntimeConfig, *, as_peer: str) -> JsonObject:
    async with connected_client(runtime) as client:
        store = open_optional_store(runtime)
        try:
            peer = await resolve_input_peer(client, store, as_peer)
            ok, detail = await story_post_eligibility(client, peer)
            return story_can_post_result(ok, as_peer, detail)
        finally:
            close_optional_store(store)


def story_can_post_result(ok: bool, as_peer: str, detail: object) -> JsonObject:
    if not ok:
        return {"can_post": False, "as": as_peer, "error": str(detail)}
    return {"can_post": True, "as": as_peer, "remaining": optional_count(detail)}


async def post_story_photo(
    runtime: RuntimeConfig,
    *,
    as_peer: str,
    file_path: Path,
    caption: str | None,
    privacy: str,
    period_hours: int,
    pinned: bool,
    noforwards: bool,
) -> JsonObject:
    if runtime.read_only:
        raise CliError("Refusing to post a Telegram story in read-only mode.")
    validate_story_photo(file_path)
    async with connected_client(runtime) as client:
        return await post_validated_story(
            client,
            runtime,
            as_peer,
            file_path,
            caption,
            privacy,
            period_hours,
            pinned,
            noforwards,
        )


async def post_validated_story(
    client: StoryClient,
    runtime: RuntimeConfig,
    as_peer: str,
    file_path: Path,
    caption: str | None,
    privacy: str,
    period_hours: int,
    pinned: bool,
    noforwards: bool,
) -> JsonObject:
    random_id = secrets.randbits(63)
    store = open_optional_store(runtime)
    try:
        peer = await resolve_input_peer(client, store, as_peer)
        await require_story_post_allowed(client, peer, as_peer)
        uploaded = await client.upload_file(str(file_path))
        updates = await send_story_request(
            client,
            peer,
            uploaded,
            caption,
            privacy,
            period_hours,
            pinned,
            noforwards,
            random_id,
        )
        return story_post_result(
            updates,
            random_id,
            as_peer,
            file_path,
            caption,
            privacy,
            period_hours,
            pinned,
            noforwards,
        )
    finally:
        close_optional_store(store)


async def require_story_post_allowed(client: StoryClient, peer: object, as_peer: str) -> None:
    ok, detail = await story_post_eligibility(client, peer)
    if not ok:
        raise CliError(f"Telegram will not allow posting a story as `{as_peer}`: {detail}")


async def send_story_request(
    client: StoryClient,
    peer: object,
    uploaded: object,
    caption: str | None,
    privacy: str,
    period_hours: int,
    pinned: bool,
    noforwards: bool,
    random_id: int,
) -> object:
    media = types.InputMediaUploadedPhoto(file=uploaded)
    return await client(
        functions.stories.SendStoryRequest(
            peer=peer,
            media=media,
            privacy_rules=story_privacy_rules(privacy),
            caption=caption,
            random_id=random_id,
            period=story_period_seconds(period_hours),
            pinned=pinned or None,
            noforwards=noforwards or None,
        )
    )


def story_post_result(
    updates: object,
    random_id: int,
    as_peer: str,
    file_path: Path,
    caption: str | None,
    privacy: str,
    period_hours: int,
    pinned: bool,
    noforwards: bool,
) -> JsonObject:
    return {
        "story_id": story_id_from_updates(updates, random_id=random_id),
        "random_id": random_id,
        "as": as_peer,
        "file": str(file_path),
        "caption": caption,
        "privacy": privacy,
        "period_hours": period_hours,
        "pinned": pinned,
        "noforwards": noforwards,
    }


async def story_targets(runtime: RuntimeConfig) -> JsonRows:
    async with connected_client(runtime) as client:
        result = await client(functions.stories.GetChatsToSendRequest())
        return [entity_to_public(chat) for chat in sequence_attr(result, "chats")]


async def story_limits(runtime: RuntimeConfig, *, as_peer: str) -> JsonObject:
    async with connected_client(runtime) as client:
        app_config = await client(functions.help.GetAppConfigRequest(hash=0))
        story_config = story_config_from_app_config(app_config)
        eligibility = await story_eligibility_for_peer(runtime, client, as_peer)
    return story_limit_result(as_peer, story_config, eligibility)


async def story_eligibility_for_peer(runtime: RuntimeConfig, client: StoryClient, as_peer: str) -> tuple[bool, object]:
    store = open_optional_store(runtime)
    try:
        peer = await resolve_input_peer(client, store, as_peer)
        return await story_post_eligibility(client, peer)
    finally:
        close_optional_store(store)


def story_limit_result(as_peer: str, story_config: JsonObject, eligibility: tuple[bool, object]) -> JsonObject:
    return {
        "eligibility": eligibility_result(as_peer, eligibility),
        "posting_mode": story_config.get("stories_posting"),
        "free": story_limit_group(story_config, premium=False),
        "premium": story_limit_group(story_config, premium=True),
        "raw_config": story_config,
    }


def eligibility_result(as_peer: str, eligibility: tuple[bool, object]) -> JsonObject:
    ok, detail = eligibility
    if ok:
        return {"can_post": True, "as": as_peer, "remaining_active_slots": optional_count(detail)}
    result: JsonObject = {"can_post": False, "as": as_peer, "error": str(detail)}
    wait_seconds = story_wait_seconds(str(detail))
    if wait_seconds is not None:
        result["wait_seconds"] = wait_seconds
    return result


def story_limit_group(story_config: JsonObject, *, premium: bool) -> JsonObject:
    suffix = "premium" if premium else "default"
    result: JsonObject = {
        "active_limit": story_config.get(f"story_expiring_limit_{suffix}"),
        "weekly_send_limit": story_config.get(f"stories_sent_weekly_limit_{suffix}"),
        "monthly_send_limit": story_config.get(f"stories_sent_monthly_limit_{suffix}"),
        "caption_length_limit": story_config.get(f"story_caption_length_limit_{suffix}"),
    }
    if not premium:
        result["expiry_seconds"] = story_config.get("story_expire_period")
    return result


async def story_history(runtime: RuntimeConfig, *, as_peer: str, limit: int) -> JsonObject:
    if limit <= 0:
        raise CliError("Story history limit must be greater than zero.")
    async with connected_client(runtime) as client:
        active_result, archive_result = await story_history_results(runtime, client, as_peer, limit)
    return story_history_result(as_peer, active_result, archive_result)


async def story_history_results(
    runtime: RuntimeConfig,
    client: StoryClient,
    as_peer: str,
    limit: int,
) -> tuple[object, object]:
    store = open_optional_store(runtime)
    try:
        peer = await resolve_input_peer(client, store, as_peer)
        active = await client(functions.stories.GetPeerStoriesRequest(peer=peer))
        archive = await client(functions.stories.GetStoriesArchiveRequest(peer=peer, offset_id=0, limit=limit))
        return active, archive
    finally:
        close_optional_store(store)


def story_history_result(as_peer: str, active_result: object, archive_result: object) -> JsonObject:
    active_stories = public_story_list(attribute(attribute(active_result, "stories"), "stories", []))
    archive_stories = public_story_list(attribute(archive_result, "stories", []))
    return {
        "as": as_peer,
        "active_count": len(active_stories),
        "archive_count": archive_count(archive_result, len(archive_stories)),
        "active": active_stories,
        "archive": archive_stories,
    }


def archive_count(archive_result: object, fallback: int) -> int:
    value = attribute(archive_result, "count", fallback)
    return value if isinstance(value, int) else fallback


async def list_contacts(runtime: RuntimeConfig, *, limit: int) -> JsonRows:
    async with connected_client(runtime) as client:
        result = await client(functions.contacts.GetContactsRequest(hash=0))
        return [entity_to_public(contact) for contact in sequence_attr(result, "users")[:limit]]


async def story_post_eligibility(client: StoryClient, peer: object) -> tuple[bool, object]:
    try:
        return True, await client(functions.stories.CanSendStoryRequest(peer=peer))
    except RPCError as exc:
        return False, str(exc)
