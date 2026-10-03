# SE Shipyard

A small self-hosted web app for administering multiple Space Engineers dedicated
server instances (running as `devidian/spaceengineers` Docker containers on
TrueNAS) from one dashboard.

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
- editing each instance's files directly (`SpaceEngineers-Dedicated.cfg` for
  settings/admins/bans, the `<Mods>` block in `Sandbox.sbc` for mods, and the
  backup folder for restores) — the same files you'd otherwise edit by hand.

## Known limitations

- **No live player list, kick, or chat.** There's no working live channel to
  a running instance (see above). The "Recent activity" section on each
  instance page is a best-effort approximation parsed from container logs —
  it recognizes join-attempt and world-load lines, but has not yet observed
  (and so cannot recognize) a disconnect or chat-message log line. Everything
  unrecognized shows as a raw log line rather than being hidden.
- **No setting a new server password.** Keen's password hash algorithm
  (`ServerPasswordHash`/`ServerPasswordSalt`) isn't confirmed, and guessing
  wrong would silently produce a broken password. Clearing an existing
  password (disabling protection) is supported since that's unambiguous.
- Settings and mod changes require a container restart to take effect — the
  UI says so but does not restart automatically, so you can batch several
  changes before restarting.

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
**Install via YAML**, pasting `compose.yaml` — same flow already used for the
`spaceengineers-<worldname>` instances themselves, rather than running compose
over SSH.

Before first deploy:
1. Create an empty `se-shipyard` dataset under `apps_dataset` (same way
   `spaceengineers-plateau` was created) — holds `instances.yaml`.
2. The container runs as **root**, deliberately, matching `port-garden`'s
   working precedent — this is required for clean `/var/run/docker.sock`
   access from inside the container.

## Adding a new instance

Each instance needs two bind-mount lines added to **this app's**
`compose.yaml` (not the instance's own), then a redeploy, then registering it
through the UI:

```yaml
- /mnt/tank/apps/spaceengineers-<worldname>/server:/mnt/instances/<worldname>
- /mnt/tank/backups/spaceengineers-<worldname>:/mnt/backups/<worldname>
```

Then on the dashboard, "Add instance" with:
- **Dataset mount** = `/mnt/instances/<worldname>` (the path above, as seen
  inside this container)
- **Instance dir** = the `INSTANCE_NAME` value from that instance's own
  `compose.yaml` (the subfolder containing its `SpaceEngineers-Dedicated.cfg`)
- **World folder** = the world name under `Saves/` (matches `<WorldName>` in
  its cfg)
- **Backup mount** = `/mnt/backups/<worldname>` (the second path above)
