# Deployment

MEPIQ ships two container topologies. Pick whichever fits the host.

| | Single container | Compose (two tiers) |
|---|---|---|
| File | `./Dockerfile` | `./docker-compose.yml` |
| Serves | API **and** the React bundle on one port | nginx for the web tier, uvicorn for the API |
| CORS | none needed (same origin) | none needed (nginx proxies `/api`) |
| Best for | Render, Railway, Fly, Cloud Run, App Runner, Heroku | local development, VPS, Kubernetes |

Both use the same engine and the same data directory layout.

---

## Environment

Copy `.env.example` to `.env`. Everything has a working default; nothing is required.

| Variable | Default | Notes |
|---|---|---|
| `MEPIQ_DATA_DIR` | `./data` | Uploads, analysis results, SQLite, symbol library. **Mount a volume here** — it is the only state. |
| `MEPIQ_STATIC_DIR` | *(unset)* | Path to the built React bundle. Set in the single-container image; leave unset when nginx serves the frontend. |
| `MEPIQ_MAX_UPLOAD_MB` | `200` | Per-file upload cap. |
| `MEPIQ_MAX_SHEETS` | `40` | Ceiling on sheets analysed per run. |
| `MEPIQ_WORKERS` | `2` | Concurrent analysis jobs. Each holds a sheet's geometry in memory, so this is bounded by RAM, not CPU. |
| `MEPIQ_CORS_ORIGINS` | `*` | Comma-separated origins. Only relevant if the frontend is on a different host. |
| `OPENAI_API_KEY` | *(unset)* | Optional. Without it the copilot runs its deterministic engine. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Any chat-completions model with tool calling. |
| `OPENAI_BASE_URL` | *(unset)* | For Azure OpenAI or an OpenAI-compatible gateway. |
| `PORT` | `8000` | Honoured by the single-container image, for hosts that assign a port. |

---

## Sizing

The engine is CPU-bound on geometry and holds one sheet at a time in memory.

| Workload | RAM | Notes |
|---|---|---|
| Typical mechanical plan (100k primitives) | 512 MB | Fine on a starter instance |
| Large bid set, several concurrent users | 2 GB | `MEPIQ_WORKERS=2` |
| Very dense sheets (250k+ primitives) | 4 GB | Consider `MEPIQ_MAX_SHEETS` to bound a single run |

Storage: an analysed sheet's JSON is 1–15 MB depending on run count, plus the original PDF.
5 GB comfortably holds a few dozen projects.

---

## Render — the shortest path

1. Push this repository to GitHub.
2. Render dashboard → **New** → **Blueprint** → select the repo. It reads
   [`deploy/render.yaml`](../deploy/render.yaml).
3. Set `OPENAI_API_KEY` in the dashboard if you want the LLM copilot.
4. Deploy.

One service, one URL, a 5 GB persistent disk mounted at `/data`, health checks on
`/api/health`. Auto-deploys on push.

> Render's free tier sleeps after inactivity and has no persistent disk. Use **starter** or
> above so uploads survive a restart.

## Railway

```bash
railway init
railway up
railway volume add --mount-path /data
railway variables set OPENAI_API_KEY=sk-...     # optional
```

[`deploy/railway.json`](../deploy/railway.json) pins the Dockerfile build and the health check.

## Fly.io

```bash
fly launch --no-deploy --copy-config --config deploy/fly.toml
fly volumes create mepiq_data --size 5
fly secrets set OPENAI_API_KEY=sk-...           # optional
fly deploy
```

`min_machines_running = 1` keeps a machine warm — a cold start in the middle of an upload is a
poor first impression.

## Google Cloud Run

```bash
gcloud builds submit --tag gcr.io/PROJECT/mepiq
gcloud run deploy mepiq \
  --image gcr.io/PROJECT/mepiq \
  --memory 2Gi --cpu 2 --timeout 900 \
  --set-env-vars MEPIQ_STATIC_DIR=/app/static \
  --allow-unauthenticated
```

Cloud Run's filesystem is ephemeral. Either mount a Cloud Storage volume at `/data`, or accept
that results are per-instance — fine for a demo, not for production.

## Split deployment: Vercel + a hosted API

Only worth it if you want the frontend on a CDN.

1. Deploy the backend anywhere above.
2. Edit [`deploy/vercel.json`](../deploy/vercel.json), replacing `YOUR-API-HOST` with the API's
   hostname.
3. `vercel --prod`.

The rewrite keeps the browser on one origin, so no CORS configuration is needed. If you instead
point the bundle straight at the API with `VITE_API_BASE`, set `MEPIQ_CORS_ORIGINS` on the API to
the Vercel domain.

## Self-hosted with Compose

```bash
cp .env.example .env
docker compose up -d --build
```

Web on `:8080`, API on `:8000`, named volume `mepiq-data`. Put a TLS terminator (Caddy, Traefik,
nginx) in front for anything public.

---

## Serving on a LAN

Useful for a demo: run it on one machine, let everyone in the room open it.

```powershell
.\run-lan.ps1                          # Windows — prints the URL to share
.\run-lan.ps1 -OpenFirewall -NoBuild   # once, from an admin prompt
```

```bash
./run-lan.sh                           # macOS / Linux
./run-lan.sh stop
```

### Why no rebuild is needed

The frontend is built with `VITE_API_BASE=""`, so every API call in the bundle is **relative** —
`/api/documents/...`, not `http://localhost:8000/api/...`. The browser resolves those against
whatever origin it loaded the page from, and nginx proxies `/api` to the API container over the
internal Docker network.

The practical consequence: `http://localhost:8080`, `http://192.168.1.42:8080` and
`http://my-laptop.local:8080` all work from the same image. There is no host baked in anywhere,
and no CORS configuration to get wrong, because the browser only ever talks to one origin.

### Binding

`MEPIQ_BIND` in `.env` controls which interface the published ports attach to:

| Value | Effect |
|---|---|
| `0.0.0.0` (default) | Every interface — reachable from the network |
| `127.0.0.1` | This machine only |
| A specific IP | Just that interface, for multi-homed machines |

You do not normally need to put your own IP anywhere. `0.0.0.0` covers every interface, and
`run-lan.ps1` only *reads* your IP so it can print a URL worth sharing.

### When a colleague cannot connect

Work down this list — it is almost always the first item.

1. **Windows Firewall.** Inbound TCP 8080 must be allowed on the *private* profile. Run
   `.\run-lan.ps1 -OpenFirewall -NoBuild` from an admin prompt, or add the rule by hand:
   ```powershell
   New-NetFirewallRule -DisplayName "MEPIQ 8080" -Direction Inbound -Action Allow `
       -Protocol TCP -LocalPort 8080 -Profile Private
   ```
2. **Network profile is Public.** Windows blocks most inbound traffic on public networks. Check
   with `Get-NetConnectionProfile`; switch to Private with
   `Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private`.
3. **Client isolation.** Guest Wi-Fi and many corporate SSIDs block device-to-device traffic
   entirely. Nothing on the host can fix that — use a wired network or a phone hotspot.
4. **Wrong IP.** `ipconfig` lists Docker, WSL and Hyper-V virtual adapters too. You want the
   Wi-Fi or Ethernet address, usually `192.168.x.x` or `10.x.x.x`. `run-lan.ps1` filters the
   virtual ones out for you.
5. **Confirm the port is listening.** `docker compose ps` should show `0.0.0.0:8080->80/tcp`.
   If it shows `127.0.0.1:8080->80/tcp`, `MEPIQ_BIND` is set to loopback in `.env`.

Quick check from the other machine:

```bash
curl http://192.168.1.42:8080/api/health
```

If that returns JSON but the page looks broken, it is a browser cache issue, not the network —
hard-reload with Ctrl+Shift+R.

### Before you expose it more widely

The app has **no authentication**. On a trusted LAN for a demo that is fine; anywhere else it is
not. Anyone who can reach the port can upload drawings, read every project, and spend your
OpenAI quota through the copilot. Put it behind a reverse proxy with auth, or an SSO tunnel
(Cloudflare Access, Tailscale), before it leaves a network you control.

---

## Verifying a deployment

```bash
curl -fsS https://YOUR-HOST/api/health
# {"status":"ok","version":"1.0.0","llm_enabled":true,...}

curl -fsS https://YOUR-HOST/api/catalogue | head -c 200
curl -sS -o /dev/null -w '%{http_code}\n' https://YOUR-HOST/     # 200 = frontend served
```

`llm_enabled` tells you whether the API key was picked up. The CI workflow runs this same smoke
test against the built image on every push.

---

## Operational notes

- **State is one directory.** Back up `MEPIQ_DATA_DIR` and you have backed up everything —
  uploads, results, review decisions and the learned symbol library.
- **Long requests.** Analysis is a background job, but progress is streamed over SSE. Any proxy
  in front must disable buffering and allow long reads; the bundled
  [`nginx.conf`](../frontend/nginx.conf) already does.
- **Upload size.** Raise both `MEPIQ_MAX_UPLOAD_MB` and the proxy's body limit
  (`client_max_body_size`) — they must agree, or large sets fail at the proxy with a confusing
  error.
- **The LLM is optional and hot-swappable.** Adding or removing `OPENAI_API_KEY` changes copilot
  behaviour on restart with no code change, and the UI reflects which mode is live.
- **No GPU, no model download, no training step.** The image is a slim Python base plus
  PyMuPDF and NumPy, and it starts in seconds.
