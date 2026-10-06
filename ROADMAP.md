# SE Shipyard roadmap / ideas

Ideas for later, roughly grouped. Nothing here is committed to; order within a
group is not priority.

## Likely next

- **Player list from logs.** The server log contains a full session:
  `OnConnectedClient <name> attempt` -> `World request received: <name>` ->
  `User left <name>` -> `Disconnected: [id]`. Parse joins and leaves into a
  "currently online" list, last-seen times, session length and join/leave
  history. Inferred from the log, not authoritative (a missed join in the tail,
  or a crash, can leave it wrong).
- **Safe restore.** Snapshot the current world before a restore overwrites it,
  and don't copy files under a server that failed to stop.
- **Remote API root cause.** The server logs "Remote Server Listener started.
  Listening on port 8080" yet never answers HTTP. The "Wine HttpListener gap"
  explanation is unproven. Check inside the container whether anything actually
  holds the port and whether a URL reservation is missing. Cheap to test; may be
  a rabbit hole. If it works, a signed-request client in Python is doable.

## Servers and operations

- **Chat.** `SaveChatToLog` is off by default; turning it on probably writes
  chat to the log. Need real sample lines before writing a parser.
- **Scheduled backups and cleanup.** Backups on a schedule independent of
  autosave, retention rules, size per server.
- **Scheduled restarts / update checks** with an in-game warning message (the
  cfg has manual-action delay/message settings).
- **Notifications.** Alert (ntfy / webhook / Discord) when a server crashes or
  stays unhealthy for several minutes.
- **Config history.** Snapshot the cfg on every save; show a diff and allow
  rollback.
- **World tools.** Rename a server, clone a server's settings to a new one,
  export/import a world.

## Mods

- **Mod update awareness.** The log prints "Up to date mod: ..." lines. Show
  which mods have updates, when each was last updated, and flag mods removed
  from the Workshop.
- **Performance hints for mods** (see "Performance investigation" below).

## Monitoring

- **Trends.** Small history graphs for CPU, memory and disk per server.
- **Dashboard "needs attention" panel.**

## Security and polish

- **Login / access control.** Shipyard has no authentication and holds the
  Docker socket; a simple password (plus CSRF protection) is the main gap.
- Favicon, mobile layout.

## Performance investigation

- Look at what makes a heavy world slow on the server versus a desktop
  (hardware, simulation speed, mods, grid complexity, settings), and surface
  safe tuning options and known-troublesome mods in the UI.
- **World analyzer (done; ideas to extend).** Parse a stopped world's `SANDBOX_0_0_0_.sbs` (iterparse;
  it is ~100 MB of XML) and report: grids ranked by block count, static vs
  dynamic, and counts of physics-heavy blocks (thrusters, gyros, wheels,
  rotors, pistons, turrets, timers, programmable blocks, batteries), plus
  planets/voxel maps/bots and the mod list with "known heavy" flags. Works
  with the server offline.
- Host-side factors to show alongside: free RAM, CPU contention, CPU governor.
  Possible extensions: compare two analyses over time, per-grid owner names,
  real PCU totals, and exporting the report.
