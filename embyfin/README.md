# embyfin-mcp

[![GitHub release](https://img.shields.io/github/v/release/katbyte/embyfin-mcp?color=blueviolet)](https://github.com/katbyte/embyfin-mcp/releases/latest)
[![Go Version](https://img.shields.io/github/go-mod/go-version/katbyte/embyfin-mcp?color=00ADD8)](https://github.com/katbyte/embyfin-mcp/blob/main/go.mod)
[![License](https://img.shields.io/github/license/katbyte/embyfin-mcp?color=blue)](https://github.com/katbyte/embyfin-mcp/blob/main/LICENSE)
![build](https://github.com/katbyte/embyfin-mcp/actions/workflows/build.yaml/badge.svg)
![tests](https://github.com/katbyte/embyfin-mcp/actions/workflows/pr-acceptance.yaml/badge.svg)
![lint](https://github.com/katbyte/embyfin-mcp/actions/workflows/pr-golangci-lint.yaml/badge.svg)
[![coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/katbyte/embyfin-mcp/badges/coverage.json)](https://github.com/katbyte/embyfin-mcp/actions/workflows/coverage.yaml)

An [MCP](https://modelcontextprotocol.io) server that finds what is wrong in an [Emby](https://emby.media) or [Jellyfin](https://jellyfin.org) library and helps fix it, from Claude Code, Claude Desktop or any other MCP client.

**Detection is code, correction is judgment.** The server runs cheap, exact checks over the whole library and returns short worklists. The model reasons only about what they flag.

## Install

```bash
brew install katbyte/tap/embyfin-mcp
# or
go install github.com/katbyte/embyfin-mcp@latest
```

A Docker image is published at `ghcr.io/katbyte/embyfin-mcp`. Tested against Emby 4.10 and Jellyfin 12.2.

## Quick start

Make an API key in the server's dashboard, then put three settings in `~/.embyfin-mcp`:

```env
BACKEND=jellyfin
SERVER=http://nas:8096
TOKEN=...
```

Check that it connects, and register it with Claude Code:

```bash
embyfin-mcp info
claude mcp add embyfin -e EMBYFIN_TOOLSETS=curation -- embyfin-mcp serve
```

That loads the audits and everything that fixes what they find. Without `EMBYFIN_TOOLSETS` it loads six read-only tools.

## The audits

Each audit checks a whole library for one thing that goes wrong. Each name links to its full rules.

| Audit | What it catches |
|---|---|
| [`audit_all`](docs/audits.md#audit_all) | Runs the audits in one call and counts what each found. Start here. |
| [`audit_missing_metadata`](docs/audits.md#audit_missing_metadata) | Items with no match, no poster or no plot. Fix with `item_identify`, `item_artwork_set` or `item_refresh`. |
| [`audit_file_path`](docs/audits.md#audit_file_path) | Files and folders named for another title, year or episode than the server holds. Fix with `item_identify` or `item_edit`, or rename the file. |
| [`audit_duplicates`](docs/audits.md#audit_duplicates) | The same film or show held as two entries. `quality_compare` says which copy is better. |
| [`audit_multiple_versions`](docs/audits.md#audit_multiple_versions) | One entry made of several files, such as a 4K and a 1080p copy. `quality_compare` says which is better. |
| [`audit_runtime`](docs/audits.md#audit_runtime) | Runtimes nothing can have: under 2 minutes, or 12 hours and over. Replace the file, or remove it with `item_delete`. |
| [`audit_quality`](docs/audits.md#audit_quality) | Copies worth replacing: low resolution, an old format or a low bitrate. `quality_compare` weighs two copies. |
| [`audit_missing_episodes`](docs/audits.md#audit_missing_episodes) | Episodes and seasons a series is missing. `show_missing` checks one series. |
| [`audit_duplicate_episodes`](docs/audits.md#audit_duplicate_episodes) | One episode filed under two numbers in a season. `item_delete` removes the copy to go. |
| [`audit_spelling`](docs/audits.md#audit_spelling) | Genres, tags and studios spelled more than one way. Fix with `metadata_rename`. |
| [`audit_whitespace`](docs/audits.md#audit_whitespace) | Stray spaces in names, tags and file names. Fix with `item_edit` or `metadata_rename`. |
| [`audit_language`](docs/audits.md#audit_language) | What has, or lacks, audio or subtitles in a language. `item_subtitle_download` fetches subtitles. |
| [`audit_unwatched`](docs/audits.md#audit_unwatched) | Films or series nobody has watched: what to archive, remove with `item_delete`, or recommend with a playlist or collection. |
| [`audit_disc_folders`](docs/audits.md#audit_disc_folders) | A disc copied in as loose files, which the server reads as many films. Remux the feature to one file, then `library_scan`. |
| [`audit_previews`](docs/audits.md#audit_previews) | Missing or damaged preview thumbnails, on Emby. Fix with `item_previews_regenerate`. |
| [`audit_anime_ids`](docs/audits.md#audit_anime_ids) | Anime whose ids disagree with the community Anime-Lists. Fix a wrong match with `item_identify`. |
| [`audit_provider`](docs/audits.md#audit_provider) | Ids and runtimes that disagree with TMDB. Fix a wrong match with `item_identify`. Needs a TMDB key. |
| [`audit_orphans`](docs/audits.md#audit_orphans) | Items a removed library left behind. Fix with `item_orphans_delete`. |

## The tools

There are 92 tools. Only `core` loads by default, because every tool's description takes room in the client's context. Load what the job needs with `EMBYFIN_TOOLSETS`.

| Toolset | For | Tools |
|---|---|---|
| `core` | Finding libraries and items; always loaded | 6 |
| `curation` | The audits, and everything that fixes what they find | 39 |
| `watching` | Watch history, what is next, marking things watched | 8 |
| `organise` | Playlists and collections | 10 |
| `remote` | What is playing, and controlling it | 4 |
| `admin` | Libraries, scans, tasks, logs, accounts and deleting files | 25 |
| `all` | Everything | 92 |

Three more settings matter early:

- `EMBYFIN_READ_ONLY` loads only the tools that change nothing.
- `EMBYFIN_ENABLE_DELETE` loads the tools that delete. It is off by default, and nothing deleted can be brought back.
- `EMBYFIN_TMDB_TOKEN` adds the checks that compare with TMDB.

## More

- [The audits](docs/audits.md): each audit's full rules, edge cases and options.
- [The tools](docs/tools.md): every tool, by what it acts on, and how deleting works.
- [Choosing which tools load](docs/toolsets.md): toolsets, families, allow and deny lists.
- [Configuration](docs/configuration.md): every setting, the settings file, and two servers at once.
- [Running it as a service](docs/service.md): over HTTP, and in Docker.
- [A typical curation session](docs/curation.md): the audits and their fixes, in order.
- [Cleaning up after a removed library](docs/recovery.md): removing what it left behind.
- [Using the Go clients on their own](docs/go-clients.md): typed clients for the Emby, Jellyfin and TMDB APIs, with no MCP in them.
- [Development](docs/development.md): building, the tests and the fixtures.
- [Contributing](CONTRIBUTING.md): what a change needs, and how releases are cut.

## How this is built

- I set the design, the scope and the audit rules, and I decide what stays.
- Every tool must have a live test against a real Emby and a real Jellyfin in Docker. CI fails if a tool has none.
- The generated Go clients are checked another way. Every operation must have a method, and a sweep calls every read against the live servers. Every write embyfin's own code sends must be reached by a live test, and CI fails if one is not.
- CI lints with golangci-lint, actionlint, yamllint, ShellCheck, typos and markdownlint.
- For security it runs CodeQL, govulncheck, zizmor on the workflows, and a Trivy scan of the built binary.
