---
name: serve-site
description: Launch local HTTP server on docs/pages. If a previous instance is running on the same port, kill it and start fresh.
---

# /serve-site

Serve the pre-built site in `docs/pages` over a local `http.server` (default port 8000). If something already listens on the port, kill it and restart — this keeps re-runs idempotent so the user never ends up with a stale orphaned server.

## Steps

1. Resolve the port: `--port N` if passed, otherwise 8000.
2. Refuse to serve an empty site: check `ls docs/pages/index.html` first. If it is missing, the site has not been built — ask the user to run `momentum site build` instead of starting a server on nothing.
3. Free the port if occupied: find the PID via `lsof -ti tcp:<port>` and `kill -9` it, then wait ~0.3s for the socket to release.
4. Start in the background: `cd docs/pages && python3 -m http.server <port>`. Use the Bash tool with `run_in_background=true` so it keeps running after the turn.
5. Confirm it is up: `curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:<port>/index.html` — expect 200.
6. Print `http://localhost:<port>/` for the user.

## Notes

- The server serves **only the pre-built artifacts** in `docs/pages/` — there is no live rebuild. If the content is stale, the user regenerates it with `momentum site build`.
- On WSL2, `http.server` binds `0.0.0.0` implicitly, so a Windows browser reaches it at the same `localhost:<port>`.
