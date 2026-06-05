class help:
    class GetAppConfigRequest:
        def __init__(self, *, hash: int) -> None: ...

class stories:
    class CanSendStoryRequest:
        def __init__(self, *, peer: object) -> None: ...
    class SendStoryRequest:
        random_id: int
        def __init__(
            self,
            *,
            peer: object,
            media: object,
            privacy_rules: list[object],
            caption: str | None,
            random_id: int,
            period: int,
            pinned: bool | None,
            noforwards: bool | None,
        ) -> None: ...
    class GetChatsToSendRequest:
        def __init__(self) -> None: ...
    class GetPeerStoriesRequest:
        def __init__(self, *, peer: object) -> None: ...
    class GetStoriesArchiveRequest:
        def __init__(self, *, peer: object, offset_id: int, limit: int) -> None: ...

class contacts:
    class GetContactsRequest:
        def __init__(self, *, hash: int) -> None: ...
