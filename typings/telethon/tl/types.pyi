from collections.abc import Sequence

class User:
    bot: bool

class Chat: ...

class Channel:
    megagroup: bool
    def __init__(self, **kwargs: object) -> None: ...

class PeerUser:
    def __init__(self, *, user_id: int) -> None: ...

class ChatPhotoEmpty:
    def __init__(self) -> None: ...

class MessageMediaPhoto: ...
class MessageMediaEmpty:
    def __init__(self) -> None: ...
class MessageMediaWebPage: ...
class MessageMediaGeo: ...
class MessageMediaContact: ...
class MessageMediaPoll: ...

class MessageMediaDocument:
    document: object | None

class DocumentAttributeAudio:
    voice: bool

class DocumentAttributeVideo: ...
class DocumentAttributeSticker: ...

class InputMediaUploadedPhoto:
    file: object
    def __init__(self, *, file: object) -> None: ...

class InputPrivacyValueAllowAll:
    def __init__(self) -> None: ...

class InputPrivacyValueAllowContacts:
    def __init__(self) -> None: ...

class InputPrivacyValueAllowCloseFriends:
    def __init__(self) -> None: ...

class UpdateStoryID:
    id: int
    random_id: int
    def __init__(self, *, id: int, random_id: int) -> None: ...

class JsonString:
    value: str
    def __init__(self, value: str) -> None: ...

class JsonNumber:
    value: float
    def __init__(self, value: float) -> None: ...

class JsonBool:
    value: bool
    def __init__(self, value: bool) -> None: ...

class JsonNull:
    def __init__(self) -> None: ...

class JsonArray:
    value: Sequence[object]
    def __init__(self, value: Sequence[object]) -> None: ...

class JsonObjectValue:
    key: str
    value: object
    def __init__(self, key: str, value: object) -> None: ...

class JsonObject:
    value: Sequence[JsonObjectValue]
    def __init__(self, value: Sequence[JsonObjectValue]) -> None: ...

class StoryItem:
    def __init__(self, **kwargs: object) -> None: ...

class PeerStories:
    def __init__(self, **kwargs: object) -> None: ...

class _StoriesModule:
    class PeerStories:
        def __init__(self, **kwargs: object) -> None: ...

    class Stories:
        def __init__(self, **kwargs: object) -> None: ...

stories: _StoriesModule
