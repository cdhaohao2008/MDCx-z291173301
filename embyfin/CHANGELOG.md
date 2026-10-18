# Changelog

## 0.10.0 (2026-10-18)

### Breaking

- `playlist_delete` and `collection_delete` take `confirm`, as `item_delete` does: without `confirm=true` they refuse, saying what the list holds, and delete nothing

### Changed

- the help for `--enable-delete` names accounts among what the tools it loads delete
- the eleven audits that named nothing to fix what they find now say what does: `quality_compare` for copies, `item_identify` for a wrong match, the subtitle tools for a missing language, and a scan of the library once a file is replaced on disk
- built on pandorest 0.12.0, which changes only the SDKs' generated tests

### Fixed

- built on golang.org/x/text 0.41.0, which fixes CVE-2026-56851 (a panic in its Nickname text profile); embyfin's code never reaches that profile

## 0.9.0 (2026-10-15)

### Added

- each of the three SDKs has `Operations`, a table of every operation it has: its name, method and path, the group whose client holds it, and whether it changes nothing on the server

### Changed

- built on go-kt 0.9.0 and pandorest 0.11.0. Nothing a tool does changes, and the SDKs change only by the table above
- `embyfin-mcp tools` gives each tool's first sentence whole: it cut two descriptions short at "e.g." and "etc.", and ran two on past the question they open with

## 0.8.1 (2026-10-13)

### Added

- `audit_file_path` takes one more check, `untitled`, run only when `checks` names it: it lists the episode files whose name gives a season and episode number and no title, `Show - 07x08.mkv`, each with the server's title for it in `title_on_server` to rename the file by. A row says when the name has a dash after the number all the same (`Show - 07x08 - .mkv`, a renamer writing the separator for a title it did not have), and when the server holds only a placeholder or no title. Without it such files are counted in `unnamed`, as before

## 0.8.0 (2026-10-12)

### Breaking

- the three SDKs moved into folders named for the version of the document they were generated from: `sdk/emby/4.10.0.40`, `sdk/jf/12.1.0` and `sdk/tmdb/2026.09.22`, so an import path says exactly which API it is for. Under each, `client` has `New`, the package named for the service (`emby`, `jf`, `tmdb`) holds every type, and each group of operations is a package of its own and a field on the client: `c.GetItems(...)` is `c.Items.GetItems(...)` on Emby and `c.Library.GetItems(...)` on Jellyfin
- an operation's options type is `<Name>Options`, where it was `<Name>OperationOptions`
- what a call answered is `res.Answer`, where it was `res.Model`, and the type of `res` is `<Name>Response`, where it was `<Name>OperationResponse`
- the types the TMDB SDK makes up for an answer TMDB's document does not name end in `Answer`, where they ended in `Response`: `tmdb.FindByIdAnswerMovieResults`
- a true or false in a record the servers only ever answer is a plain `bool`, where it was a pointer: `info.HasPendingRestart`. A record a request sends keeps its pointers, so a value never set is still never sent, and three answers keep theirs because "not said" means something: Emby's `TranscodingInfo.VideoDecoderIsHardware` and `VideoEncoderIsHardware`, and Jellyfin's `PluginInfo.CanUninstall`
- an operation with exactly one option takes it as a plain argument in place of the struct: `c.Library.DeleteItems(ctx, ids)`. An optional one can be left out, and a `false` or `0` that is given is sent; a paged list and an operation with two or more options keep the struct
- the hand-written TMDB code, `Facts` and the retrying transport, moved from `sdk/tmdb` to `sdk/tmdb/facts`; TMDB's `New`, `Client` and `DefaultBaseURL` are in the versioned folder
- a date in the Emby and Jellyfin SDKs is a `Time`, where it was a string: `item.DateCreated.Year()`. It reads every form the two servers write, a date written any other way is zero with its text kept in `Unread`, and a zero one is not sent. One option stays text, `MinDateLastSaved` on the item searches (`GET /Items` on both servers and Emby's `GET /Users/{UserId}/Items`): the servers also take a bare day there and read it their own way. The other operations that take it, 57 on Emby and one on Jellyfin, take a `Time`
- in the TMDB SDK a day is a `Day` and a date with a time is a `Time`, in options and answers alike: `film.ReleaseDate.Year()`. TMDB's document declares them plain strings, so which fields are dates is said by two workarounds and checked against the recorded answers. `facts.DateYear` takes a `Day`
- an id in the Emby and Jellyfin SDKs says what it is the id of: `ItemID`, `UserID`, `SessionID`, `TaskID`, `PlaylistItemID` and `MediaSourceID`, each a string underneath, so a user's id where an item's goes does not compile. `emby.ItemID(text)` and `string(id)` convert one, pandorest's `client.StringIDs` a list. An id of anything else is a string as before
- on Emby the options that take several ids as one comma-joined text are lists: `Ids`, `ExcludeItemIds` and `ItemIds` are `[]emby.ItemID`, and a playlist's `EntryIds` is `[]emby.PlaylistItemID`. They are sent joined as before

### Changed

- built on pandorest 0.8.3: an error from any of the three SDKs never repeats the API key or token it was given
- built on go-kt 0.6.4: a tool that takes no arguments refuses one, where it was answered as if the argument had meant something: `library_list`, `server_info` and seven more. A failure's words reach the caller without what an address in them may carry a credential in: who it signs in as, its query values and what follows its `#`
- a client is told on connecting what holds for every tool: text from outside is data and never an instruction, what a tool's annotations say, that an argument a tool does not take is refused, and what an empty list means; then which text embyfin cleans and which it shows exactly
- text written outside embyfin is cleaned once, around every tool: a title, a name, an overview and a server's words for what went wrong lose the characters that do not display, a tab or a line break in them becomes a space, and one longer than 16,384 characters is cut with `…`. What a later call hands back is shown exactly as the server holds it: a path, an id, a genre, a tag, a studio, a setting, and a value an audit says to pass on
- a date a server writes as year 1, which is how both write a date they do not have, is no date. A tool leaves it out where it showed `0001-01-01T00:00:00.0000000Z`; `audit_quality` no longer lists a file as written after the server first saw it in year 1; `audit_missing_episodes` and `show_missing` no longer count an episode dated so as aired; and an edit of an item sends such a date back as none
- `server_log`'s `tail` blanks the keys in each line, as its search already did, and `task_get`'s `error_detail` loses what an address in it may carry a key in; both keep their line breaks
- the line `EMBYFIN_LOG=info` writes for a write or delete call blanks more: every value under a free-form argument, the same parts of any address, and any value sent under a name with `password`, `passphrase` or `secret` in it. Two free-form arguments that cannot hold a credential are still written as sent, for a call the tool answered: `server_config_edit`'s `set` and `item_identify_apply`'s `candidate_ids`
- `sdk/embyfin` names the two API versions it is built on, `EmbyAPIVersion` and `JellyfinAPIVersion`, and `server_info` reports both as `sdk_api_versions`, beside the one for the connected server
- a call none of whose options is required can leave the options out: `c.Sessions.GetSessions(ctx)`
- the generator's settings moved out of `sdk/pandorest`: the program is `sdk/main.go` (`go run ./sdk`), the list of services is `sdk/zservices`, and each service's workarounds sit beside its SDK in `sdk/<service>/workarounds`
- `scripts/` is `.scripts/`
- every test that runs against a real server is under `acceptance/`: `integration/` is now `acceptance/emby`, `acceptance/jf` and `acceptance/tmdb`, and the tool suite is `acceptance/tools`; the make targets are `testacc-sdk-<server>` and `testacc-tools-<server>`, and the build tag is `acceptance`
- the checks are level with terraform-provider-azurerm's: spelling (`make typos`) and markdown (`make markdownlint`) are checked, and the workflow checker builds from the one tools module
- lint reads every Go file, the acceptance tests included: it is given their build tag, and the rule that tests run in parallel is off for them, since they share one server and run in order
- the live tool suite fails when an answer or a refusal shows one of the credentials the suite was given: the server's key, the test accounts' password, or the token of an account a test signs in

### Added

- `user_create`, `user_edit` and `user_delete`, in the `admin` toolset: make an ordinary account, give it a new password, say which libraries it sees, and remove it. An account always gets a password, since both servers let one without be logged into by its name alone, and the password is blanked in the log of write calls. `user_delete` is a delete tool, wants `confirm`, and never removes the last administrator
- on Jellyfin `user_delete` waits three seconds first, and refuses an account that is playing: Jellyfin 12.2 stops, the whole server, when an account is deleted within half a second of its watch state changing
- on Jellyfin `user_create` clears the new account of the watched marks, favourites, ratings and resume points of an account deleted before it, which Jellyfin 12.2 lists it with until the server is restarted, and says when there were any
- one acceptance journey per server that goes from nothing to audited to fixed and back: it makes an account and a library, fixes every finding `audit_all` reports with the tools, makes a collection and a playlist, and removes all of it again, leaving the server holding what it held before
- 92 tools: 62 read, 24 write, 6 delete
- `acceptance/embyfin`: live tests of the hand-written `sdk/embyfin` layer by itself, each written once and run against both servers (`make testacc-embyfin`)
- `sdk/embyfin`: `Count` says how many items a search matches without fetching any of them, and `ItemCounts` carries the server's artists, books, programs and its own total of everything, which Emby leaves at 0
- the Emby SDK takes a list wherever Emby's document says a text option carries several values joined by commas, 21 options in all: `IncludeItemTypesList`, `FieldsList`, `YearsList` and the rest sit beside the text option of the same name and are sent joined. The text option stays, so no caller has to move

### Fixed

- `server_log` and `server_log_search` no longer show a session's access token: Jellyfin 12.2 writes the token itself into its log when a session signs out, and both tools handed the line on as written; found by the live suite's new credential check
- an item asked for by an id of the wrong shape (a name, say) is answered "no item with id ..." on Emby too, where it was Emby's own HTTP 500; found by the new `acceptance/embyfin` suite
- `user_get` leaves `has_password` out on Jellyfin, which says true for every account, one that logs in with no password included

## 0.7.0 (2026-10-10)

### Breaking

- the Emby SDK's `GetSystemPing` and `GetEnvironmentParentPath` give their text as `Model`, a string, where a caller had to read and close the response body

### Changed

- built on pandorest 0.6.0: a call that answers a file, an image or a stream asks the server for that type, where every call asked for JSON
- eight of the workarounds for Emby's document are pandorest's ready-made ones, which say what the document declares and what the server really answers

## 0.6.0 (2026-10-10)

### Breaking

- `sdk/client` is gone: the three SDKs send through [pandorest](https://github.com/katbyte/pandorest)'s base client, so a Go program that used it imports `github.com/katbyte/pandorest/client`, and each SDK's `New` takes that client's options

### Changed

- the SDKs are generated with pandorest, the generator that began in this repository and is now a library shared with the other MCP servers; `sdk/pandorest` keeps what is embyfin's, the three services and the workarounds for their documents
- `EMBYFIN_LOG=trace` shows each request to the server and its answer, with keys and passwords blanked
- a server url that answers with a web page is told so and to check the url, where it was a JSON error; a server that cannot be reached names the request that failed
- built on go-kt 0.6.1: `EMBYFIN_LOG=info` writes a line for every call of a write or delete tool, with the tool, what the call sent and whether it was refused, failed or answered. A value is blanked only when the name it was sent under reads as a credential's; no tool here takes one
- a call with an argument the tool does not take is told which arguments it does take

### Fixed

- a live suite that failed on Emby left its two test servers running

## 0.5.0 (2026-10-10)

### Breaking

- `--allow-tools` beside `--toolsets` adds the tools it names to the sets: `--toolsets curation --allow-tools task_list` is curation and `task_list` as well. It used to keep only what both held, and refused a name the sets did not hold. On its own it is still only the tools it names. Narrow a set with `--deny-tools`

### Added

- `server_health` says how the server is doing in one call: tasks running and failed, who is playing and how, and what the last stretch of the log shows
- `server_log_search` searches the log between two times or over its last stretch, as entries, counts by message, a histogram, the gaps of a freeze, or the slow answers and requests still waiting
- `task_get`, `task_stop` and `task_edit`; `task_list` gives progress, what starts each task and how its last run went
- `session_list` says how each device plays, as the file is or transcoded and why; `details` adds the file and the whole transcode
- `server_config` reads the server's settings in groups; `server_config_edit` changes the ones that tune Jellyfin's trickplay images and scanning
- `library_options` puts every library's settings side by side, and says which libraries are set differently
- `server_plugins` lists what is installed into the server
- `server_info` says whether a restart is pending or an update is out, and what the log says of the machine
- `--config` (or `EMBYFIN_CONFIG`) names the settings file, so two instances can serve two servers side by side
- 89 tools: 62 read, 22 write, 5 delete

### Changed

- built on go-kt 0.5.1: `audit_whitespace` sees a space before the extension when spaces trail the name too, and counts a no-break space beside an ordinary one as a double space
- test servers and builds take their images from Google's mirror of Docker Hub first

### Fixed

- `audit_spelling` reported an artist's numbered albums, "II" beside "III", as one name typed two ways
- `audit_whitespace` gave an empty suggestion for a name that is nothing but spaces, and said to rename to it

## 0.4.1 (2026-10-09)

### Fixed

- the release build takes its images from Google's mirror of Docker Hub. Docker Hub turned the 0.4.0 build away every time it was tried, so 0.4.0 was tagged and never published: this release is what 0.4.0 was to be

## 0.4.0 (2026-10-09)

### Breaking

- `collection_add` and `collection_remove` are `collection_edit`'s `add_items` and `remove_items`; `playlist_add` and `playlist_remove` are `playlist_edit`'s `add_items` and `remove_entries`
- `library_recent` is `library_items` with `added_since`; `library_genres` is `library_filters`
- `server_logs` is gone: `server_log` lists every log file beside the newest one's tail
- the three missing-metadata audits are one, `audit_missing_metadata`, with `problems` to pick from
- `audit_duplicate_series` is `audit_duplicates`' `folder_groups`
- `item_watch_history` is `server_activity` with `item`
- `audit_runtime` reports only runtimes no film or episode can have: under 2 minutes, or 12 hours or more. `tolerance_percent`, `runtime_multiple` and `season_median_runtime_s` are gone
- `audit_provider` checks episodes too by default
- the SDKs and their generator moved under `sdk/`, so a Go program importing them uses the new paths

### Added

- `audit_previews` finds missing, damaged or wrong-length preview thumbnails, and `item_previews_regenerate` makes them again (Emby only so far)
- `audit_spelling` checks album and artist names
- a file holding a run of episodes is read in every common form, and `run_warning` says when the server will not read it as a run
- `audit_provider` checks each episode's runtime against TMDB's
- `provider_cache_clear` forgets the TMDB answers the tools keep
- `server_activity` takes `item` and `user`, carries `item_id`, and says how far back it could read
- `audit_missing_metadata` on a music library looks at the albums' covers alone
- `audit_anime_ids` says when an older copy of the anime list answered
- 80 tools: 56 read, 19 write, 5 delete

### Changed

- serving, choosing which tools a session gets, the locks that keep two edits of one item apart, the spelling and whitespace checks, and the tests' recording proxy are go-kt's, shared with the other MCP servers
- over HTTP, a session its client left open and stopped using is closed after half an hour

### Fixed

- stopping the HTTP server with a client still connected no longer takes ten seconds and exits with an error
- a date or a number from TMDB, the server or the anime list that can't be read is an error, not a guess
- a failed server read while finding a show or checking a folder is reported instead of dropped
- `audit_missing_episodes` judges a show in two folders named alike as one show, and reads Jellyfin's records of episodes it has no file for
- TMDB titles and searches are kept an hour, not until a restart
- `quality_compare` judges a thinly encoded frame as thin, and says when the server has not read a file yet
- `item_delete` says Jellyfin can keep an item deleted during a scan listed through several more scans
- `audit_file_path` no longer misreads a dotted acronym with a number after it (`Q.R.S.1`), nor says a Jellyfin search misses a lookalike letter
- `audit_runtime` leaves a disc image (`.iso`) unjudged
- `library_edit` says what a rename does to an account given that library alone on Jellyfin 12.2

## 0.3.0 (2026-09-27)

### Breaking

- `playlist_remove` and `playlist_edit` name an entry by entry id and item (`item_ids`, `move_item_id`), need the playlist's `fingerprint` for an item held twice, and refuse when the playlist changed; removing both copies on Jellyfin needs `all_copies`
- `item_identify_apply` needs the candidate's `candidate_ids`
- `library_edit remove_paths` and `task_run` (anything but a scan) need `--enable-delete`
- `item_delete` refuses collections, playlists, libraries, genres, studios, people and artists
- `item_edit`'s `nfo_written` is `nfo_expected`
- `show_episodes` is gone (use `library_episodes`); `user_in_progress` is gone (use `user_next_up`)
- `collection_create` is marked destructive: the first collection starts a scan of every library

### Added

- `audit_whitespace`: double, stray and odd spaces in names, genres, people, folders and files
- `audit_file_path` checks a film is the film its file names, against every title it goes by and, with a TMDB token, TMDB's search and the film's collection
- every whole-library read says in `note` when the library changed while it read
- `item_get` lists every version with its own file facts and warns when one names another film
- `audit_duplicate_episodes` says how sure each group is: near certain only on proof in the files
- write tools read back what they set, say everything they change on the server and on disk, and warn when a running scan may undo it
- `audit_all` keeps every row when one audit fails and says how long each took
- `original_title` on items, task ids, `ids` for `audit_file_path` and `audit_provider`
- reads retry 502/503/504 and cut-off answers, over HTTP/1.1 and HTTP/2
- 88 tools: 61 read, 22 write, 5 delete

### Fixed

- different episodes of a steady-length show no longer read as near-certain copies
- nothing says "not there", "never watched", "missing" or a total from a read cut short; tools that decide a delete refuse instead
- `playlist_remove` no longer removes the wrong entry on Emby 4.11, which renumbers entries after a change
- `collection_create` no longer empties a renamed collection on Jellyfin; collections no longer count a series' episodes as members
- `item_set_state` no longer reports a watched mark or favourite the server dropped
- a failed delete says what already went and whether the item is still listed
- `metadata_rename` no longer answers before Emby's album genres catch up
- film and file names: part 1 and 2 kept apart, a title's own year never read as the release year, Radarr and TRaSH tags not read as titles, "can't tell" instead of a guess
- Emby versions are grouped by the key Emby merges them by, not any shared id
- `library_items` title searches give a true total; a `saved_since` that isn't a date is refused
- a parental limit of 0 shows as a limit
- a series carrying a film's ids no longer reports another show's episodes as missing
- an unknown id no longer reads as "nobody watched this" or "nothing similar"
- sort name edits on Emby are kept; `library_edit` can't rename onto another library's name
- Emby routes the SDK couldn't call now work

## 0.2.0 (2026-09-23)

### New

- Comparing a download folder or vault against a big TV library without a call per series: `library_episodes`, `library_export`, `show_episodes_exist`, `show_resolve`, `plan_check` and `quality_compare`.
- Audits: `audit_file_path`, `audit_provider`, `audit_language`, `audit_duplicate_episodes`, `audit_duplicate_series`, `audit_disc_folders`, `audit_anime_ids` and `audit_orphans` (with `item_orphans_delete`). `audit_all` has a row for every audit.
- `audit_missing_episodes` and `show_missing` can read a series' whole run from TMDB, and say when they cannot tell rather than answering "nothing missing".
- Quality rows carry frame rate, HDR, aspect ratio and display width, which give away upscales and anamorphic rips.
- `user_get` reports playback preferences; `server_info` reports its own version and the SDK's.
- `lib/tmdb` is generated from TMDB's OpenAPI document like the Emby and Jellyfin SDKs, and `make spec-refresh` re-vendors all three.

### Changed

- Tools that did the same thing are merged: `library_items` searches and filters, `item_set_state` sets watched, favourite and position, `item_edit` takes one id or many. 89 tools: 62 read, 22 write, 5 delete.
- `playlist_delete` and `collection_delete` need `--enable-delete`.
- `library_export` only ever writes a new file.
- Breaking: sizes are in bytes and times in seconds everywhere, audio tracks are objects rather than strings, every list pages with `limit` and `offset`, and every audit answers `items_scanned` and `total_findings`.
- The TMDB setting is `--tmdb-token` / `EMBYFIN_TMDB_TOKEN`; `--tmdb-key` still works.

### Fixed

- Emby finding nothing no longer ends the session, and a tool that fails unexpectedly returns an error.
- Answers that were confidently wrong: a path read as free that was taken, a film and a series reported as duplicates, unprobed files counted as having no audio, a name resolved to the wrong show, one user's plays credited to another, a subtitle download reported that never happened.
- Playlists: adding a series or album no longer doubles it, a move keeps repeated items, and a playlist takes only what its user can see.
- Deletes say what they remove: `item_delete` lists every path (a film alone in its folder takes the folder) and previews without `confirm`, and a Jellyfin collection no longer comes back after a delete.
- Identifying an item in a library with its fetchers off only sets its ids; Jellyfin wiped a series' episode numbers.
- Emby's merged versions of a film are versions, not duplicates.
- Names in any script are compared, and the history tools read their whole period.
- An older TMDB key no longer shows in errors, and the Emby key is not sent to another host on a redirect.
- Two-word settings in a `.embyfin-mcp` file (`TMDB_TOKEN`, `READ_ONLY`...) are read.

## 0.1.1 (2026-09-15)

No code changes. 0.1.0 published its binaries and image but not the Homebrew formula, because the tap token was not set; this release runs that path with the token in place.

## 0.1.0 (2026-09-15)

Initial release.

- **81 tools** for Emby and Jellyfin, in toolsets: 12 audits, identify, artwork, subtitles, metadata edits, watch state, playlists, collections, sessions and server admin. `core` (7 read-only tools) is the default; `--toolsets`, `--allow-tools`/`--deny-tools`, `--read-only` and `--enable-delete` decide the rest.
- **CLI**: `serve`, `info`, `tools`, `version`. Flags, `EMBYFIN_*` environment variables or a `.embyfin-mcp` file.
- **Transports**: stdio, or Streamable HTTP with `--listen` (bearer token required). Alpine Docker image at `ghcr.io/katbyte/embyfin-mcp`, plus `docker-compose.yml`.
- **Two generated Go SDKs**, `lib/emby` (Emby 4.10, 499 operations) and `lib/jf` (Jellyfin 12.0, 346), written by `internal/pandorest` from the servers' own OpenAPI documents, over a shared base client. `lib/embyfin` is the thin layer that makes both servers answer alike.
- **Tested against real servers**: unit tests, an SDK suite and a tool suite against Emby and Jellyfin in Docker, with provider calls recorded and replayed. Every registered tool must have a test, every GET is swept, and `make cover` merges the lot into the coverage badge.
