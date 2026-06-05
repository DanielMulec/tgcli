# tgcli

`tgcli` is a macOS-first Telegram CLI inspired by [`wacli`](https://wacli.sh/). It logs in as your Telegram user account through MTProto, stores the Telegram session locally, can sync messages into a local SQLite database with FTS5 search, and exposes script-friendly commands for listing, searching, and sending.

This is not a bot-token wrapper. Bot accounts cannot read your personal Telegram chats. `tgcli` uses [Telethon](https://docs.telethon.dev/) and requires Telegram API credentials from [my.telegram.org](https://core.telegram.org/api/obtaining_api_id).

## Install

```bash
cd /Users/danielmulec/Projekte/tgcli
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e .
tgcli version
```

Python 3.11+ should work. The commands above use the already installed `uv` and Python 3.13 on this Mac.

## First Login

Create an API app at <https://my.telegram.org>, then:

```bash
tgcli auth login --api-id 123456 --api-hash YOUR_API_HASH
tgcli auth status
```

`tgcli auth login` prints a QR code in the terminal by default. Open Telegram on your phone, go to Settings > Devices > Link Desktop Device, scan the code, and approve the login. The session is stored locally and reused by future commands.

Phone-code login is still available as a fallback:

```bash
tgcli auth login --api-id 123456 --api-hash YOUR_API_HASH --phone +43123456789
```

The Telegram login code arrives in Telegram, not SMS in most cases. If your account has two-step verification enabled, `tgcli` prompts for the password.

## Common Commands

```bash
# Sync recent chat metadata and messages into ~/.tgcli/tgcli.db
tgcli sync --limit 100 --per-chat 200

# Keep the local store warm with new messages
tgcli sync --follow

# List locally synced chats
tgcli chats list

# Search locally synced messages with SQLite FTS5
tgcli messages search "meeting"

# Search Telegram live instead of the local store
tgcli messages search "meeting" --live --limit 20

# List local messages for a synced chat id
tgcli messages list --chat -1001234567890

# List live messages by username or local chat name
tgcli messages list --live --chat @someusername

# Send text or files
tgcli send text --to @someusername --message "hello from tgcli"
tgcli send file --to @someusername --file ~/Desktop/report.pdf --caption "report"

# Post an image story/status to contacts
tgcli stories can-post
tgcli stories limits
tgcli stories history
tgcli stories targets
tgcli stories post --file ~/Desktop/story.jpg --caption "posted from tgcli"

# Scriptable JSON output
tgcli --json chats list --limit 10
tgcli --json messages search "invoice"

# Refuse commands that intentionally write Telegram or local state
TGCLI_READONLY=1 tgcli messages search "invoice"
```

## Store

Default macOS store:

```text
~/.tgcli/
  config.json
  tgcli.session
  tgcli.db
```

Named accounts use `~/.tgcli/accounts/<name>`:

```bash
tgcli --account work auth login
tgcli --account work sync
```

The session file grants access to your Telegram account. Keep it private. `tgcli` creates account directories with `0700` permissions and config/session/database files with owner-only permissions where possible.

## Diagnostics

```bash
tgcli doctor
tgcli doctor --connect
tgcli store stats
```

`doctor --connect` checks whether the stored Telegram session is authorized.

## Stories / Statuses

Telegram Stories are supported through Telegram's native Stories API. The initial `tgcli` support posts image stories with optional captions:

```bash
tgcli stories can-post
tgcli stories limits
tgcli stories history
tgcli stories targets
tgcli stories post --file ~/Desktop/story.jpg --caption "posted from tgcli"
```

By default, stories are posted as your own user account, visible to contacts, and expire after 24 hours. You can change the audience and expiry:

```bash
tgcli stories post --file story.jpg --caption "public update" --privacy public
tgcli stories post --file story.jpg --privacy close-friends --period-hours 6 --no-forwards
```

Telegram requires story media to be a vertical photo or video up to 30 MB. This version posts photos; video stories and media overlays can be added later.

Telegram may require Premium to post user stories, and channels/supergroups need the right admin permissions and enough boosts. Run `tgcli stories can-post` first to check the active account, `tgcli stories limits` to show Telegram's current story limits and posting mode, `tgcli stories history` to inspect active and archived story metadata, `tgcli stories targets` to list channel/supergroup targets Telegram exposes for this account, or `tgcli stories can-post --as @channelname` before publishing.

## Live Smoke Test

After login, this sends a unique message to Telegram Saved Messages, syncs Saved Messages into SQLite, and searches the local store for the unique token:

```bash
tgcli --json smoke-test
```

It exits with status `0` only if send, sync, and local search all work.

## License

MIT
