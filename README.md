# SE Shipyard

A small self-hosted web app for administering multiple Space Engineers dedicated
server instances (running as `devidian/spaceengineers` Docker containers on
TrueNAS) from one dashboard.

## Features

- **Home:** card view of every server (status, CPU, memory, mods, restart-needed flag).
- **Servers:** expandable per-server settings, mods, live log and backups; add a
  server from the UI.
- **Default settings:** a template (game mode, PCU, players, backup saves/interval,
  admins/banned/reserved, password) you can apply to any server.
- **Mods:** your mod list with Workshop names/descriptions, which servers use each,
  and Workshop search by name (needs a free Steam Web API key, set in
  *UI settings*, or via the `STEAM_API_KEY` env var).
- **World analyzer:** scans a saved world's files (the server can be offline) and
  shows grid/block statistics, physics-heavy block counts, moving vs static
  grids, a sortable per-grid table, the mod list with "may be heavy" flags, host
  resources, and rule-of-thumb tuning tips. The scan runs in a separate
  low-priority process. Tips are heuristics, not measurements.
- **UI settings:** light/dark/system theme, and an optional faint background
  slideshow (opacity and interval adjustable). Images come from your own uploads
  and/or the official Space Engineers Steam store screenshots, fetched on demand
  to the data volume (`backgrounds/`) -- no images are bundled in this repo.

Data kept on the data volume: `instances.yaml`, `defaults.yaml`, `library.yaml`,
`pending.yaml`, `mod_cache.json`, and `steam_key` (mode 0600, never sent back to
the browser). The default password, if set, is stored in `defaults.yaml` in
plaintext (it is never returned by the API).

## Why this exists

Keen's own "Space Engineers Dedicated Server" GUI tool cannot run reliably
under Proton on Linux: it crashes under Wine-Mono (`NotImplementedException`
on the "add new instance" dialog), and the real-.NET workaround
(`protontricks <appid> dotnet48`) fails reproducibly with a Wine
cabinet-extraction error. SE Shipyard replaces it for day-to-day admin tasks.

It also does **not** use the dedicated server's built-in Remote API
(`RemoteApiEnabled`/`RemoteApiPort` in `SpaceEngineers-Dedicated.cfg`) — that
API was tested directly (signed requests, raw unauthenticated requests, and a
request from a container on the same Docker network hitting the instance's
internal IP with zero NAT involved) and found to be completely
non-responsive: TCP connections are accepted but the server never completes
an HTTP response, for any endpoint. Root cause: the dedicated server binary
itself runs under Wine inside the `devidian/spaceengineers` image, and the
Remote API is almost certainly built on `System.Net.HttpListener`, which has
known gaps under Wine. So SE Shipyard works entirely by:

- controlling containers directly via the Docker socket, and
- editing each instance's files directly — the same files you'd otherwise
  edit by hand. This turned out to involve **two** settings files, not one:
  `SpaceEngineers-Dedicated.cfg`'s `<SessionSettings>` is only the *initial
  seed*, read once. From then on, confirmed directly against a live running
  instance (caught with `GameMode=Survival` in the cfg while actually running
  `GameMode=Creative`), the dedicated server treats `Sandbox_config.sbc` as
  the live, continuously-autosaved source of truth for `GameMode`/PCU
  limits/`MaxPlayers`/`MaxBackupSaves` *and* the `<Mods>` list -- its own
  startup log says as much ("Sandbox world configuration file found,
  overriding checkpoint settings"). So SE Shipyard reads those fields from
  `Sandbox_config.sbc` when it exists and writes changes to both files to
  keep them consistent. `ServerName`/`Administrators`/`Banned`/`Reserved`/the
  password are *not* duplicated into `Sandbox_config.sbc`, so the cfg stays
  the sole source for those.

## Known limitations

- **No live player list, kick, or chat.** There's no working live channel to
  a running instance (see above). The "Recent activity" section on each
  server's Log tab is a best-effort approximation parsed from container logs —
  it recognizes join-attempt and world-load lines, but has not yet observed
  (and so cannot recognize) a disconnect or chat-message log line. Everything
  unrecognized shows as a raw log line rather than being hidden.
- **Password setting is implemented but not yet verified against a real
  client connect.** `ServerPasswordHash`/`ServerPasswordSalt` use
  PBKDF2-HMAC-SHA1, 10,000 iterations, 16-byte random salt, 20-byte derived
  key, base64-encoded -- confirmed against two independent sources describing
  the same community password-generator tool for this exact purpose, and
  matches standard .NET `Rfc2898DeriveBytes` defaults. The math checks out
  (byte lengths, encoding) but actually joining with a password set this way
  hasn't been tested yet -- do that once deployed, before relying on it.
- Settings and mod changes require a container restart to take effect — the
  UI shows a "restart needed" banner but does not restart automatically, so you
  can batch several changes first. Editing a *running* server's files can be
  overwritten by the game's own autosave; stop the server first for safety.

## Security warning

SE Shipyard has **no authentication yet** and mounts the host's Docker socket,
which is root-equivalent. Only expose it on a trusted LAN -- never to the
internet -- until login support is added.

## Running locally

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SE_SHIPYARD_DATA_DIR=./data .venv/bin/python -m uvicorn app.main:app --reload --port 8080
```

`SE_SHIPYARD_DATA_DIR` overrides where `instances.yaml` lives (defaults to
`/app/data`, correct inside the container, not useful locally). Local dev
also needs `instances.yaml` entries whose `dataset_mount`/`backup_mount`
paths actually resolve on your machine — e.g. temporarily `sshfs`-mount the
TrueNAS paths, or point them at a local copy of a test instance's files.

## Deploying on TrueNAS

Image is built by `.github/workflows/publish-image.yml` and published to
`ghcr.io/privatesourcetech/se-shipyard`. Deploy through the TrueNAS Apps UI's
**Install via YAML**, pasting your copy of `compose.example.yaml` (saved as `compose.yaml`, which is gitignored) — same flow already used for the
`spaceengineers-<worldname>` instances themselves, rather than running compose
over SSH.

Before first deploy:
1. Create an empty `se-shipyard` dataset under `apps_dataset` (same way
   `spaceengineers-plateau` was created) — holds `instances.yaml`.
2. The container runs as **root**, deliberately, matching `port-garden`'s
   working precedent — this is required for clean `/var/run/docker.sock`
   access from inside the container.

`pull_policy: always` on the service means every future redeploy (Edit →
save in the Apps UI) forces a fresh registry check and pulls a newer
`:latest` automatically. Before this was added, TrueNAS's redeploy just
recreated the container from whatever image was already cached locally --
confirmed directly: a container recreated after two new pushed fixes was
still running the original pre-fix image, requiring a manual
`docker pull ghcr.io/privatesourcetech/se-shipyard:latest` on the host to
actually fetch the new one. That manual step shouldn't be needed anymore.

## Adding a new instance

Each instance needs two bind-mount lines added to **this app's**
`compose.yaml` (not the instance's own), then a redeploy, then registering it
through the UI:

```yaml
- /path/to/apps/spaceengineers-<worldname>/server:/mnt/instances/<worldname>
- /path/to/backups/spaceengineers-<worldname>:/mnt/backups/<worldname>
```

Then on the dashboard, "Add instance" with:
- **Dataset mount** = `/mnt/instances/<worldname>` (the path above, as seen
  inside this container)
- **Instance dir** = the `INSTANCE_NAME` value from that instance's own
  `compose.yaml` (the subfolder containing its `SpaceEngineers-Dedicated.cfg`)
- **World folder** = the world name under `Saves/` (matches `<WorldName>` in
  its cfg)
- **Backup mount** = `/mnt/backups/<worldname>` (the second path above)
