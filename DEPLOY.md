# Deploying to Fly

Nothing here needs a token pasted anywhere but your own terminal. `flyctl`
authenticates on your machine and stays there.

## Once

```bash
brew install flyctl
fly auth login
```

No Homebrew? Use Fly's installer instead, on a line of its own:

```bash
curl -L https://fly.io/install.sh | sh
```

## First deploy

Every line below is safe to paste on its own. Nothing here has a trailing
comment: zsh does not strip one from a line you type by hand, so `brew install
flyctl  # or ...` hands brew the rest of the line as arguments and fails on
`-L`.

**1. Pick a name.** It has to be unique across the whole of fly.io. Edit the
`app = ` line in `fly.toml` first, then use the same name here.

```bash
cd ~/Documents/Claude/Projects/Film\ Stock\ Exchange

fly launch --no-deploy --copy-config --name YOUR-APP-NAME
```

**2. The database volume.** 1GB is far more than this needs, and it is what
keeps portfolios alive across deploys.

```bash
fly volumes create market_data --size 1 --region iad
```

**3. Secrets.** These never enter the repo or a chat.

```bash
fly secrets set SESSION_SECRET=$(openssl rand -hex 32)
fly secrets set FSX_ENV=production
fly secrets set TMDB_READ_ACCESS_TOKEN=PASTE_YOURS
fly secrets set OMDB_API_KEY=PASTE_YOURS
```

**4. Ship it.**

```bash
fly deploy
```

`FSX_ENV=production` does two things that matter: the app refuses to boot
without a real `SESSION_SECRET`, rather than running with forgeable cookies,
and the local test player is turned off so nobody can sign in as one.

## Seed the market, once

A fresh volume has an empty database, so the market would render with nothing
in it. Prices are computed from a date, so a new database can be given real
history immediately rather than waiting months to grow one:

```bash
fly ssh console -C "python -m app.jobs seed --resume"
```

Ten years, fortnightly, about two minutes for a roster of 500. It prices the
newest day first and works backwards, and `--resume` keeps whatever is already
there — so if the SSH session drops or the machine restarts partway, run the
same command again and it picks up where it stopped.

That ordering matters. The first version seeded oldest first with no resume,
the run was interrupted, and the deployed market spent months quoting prices
from July 2022 with nothing to say so.

Then check it — the date on the market page should be today:

```bash
fly open
curl https://YOUR-APP-NAME.fly.dev/healthz
```

If it is not today, the nightly job below will also close the gap on its next
run.

## Sign-in

OAuth apps need the deployed hostname, which does not exist until after the
first deploy — so do this last. **This app is deployed at
`https://film-stock-exchange.fly.dev`**, so that is the host in both URLs
below.

Until at least one provider is configured, `/signin` says so and nobody can
sign in: `FSX_ENV=production` turns the local test player off, which is the
point of it. The market, the stock pages and the leaderboards are all public
and work already.

GitHub takes about two minutes. Google needs a consent screen, scopes and a
publishing status, and is worth leaving until you actually want it — one
provider is enough to open the doors.

### GitHub

1. https://github.com/settings/developers → **OAuth Apps** → **New OAuth App**
2. Application name: `Film Stock Exchange`
3. Homepage URL: `https://film-stock-exchange.fly.dev`
4. Authorization callback URL:
   `https://film-stock-exchange.fly.dev/auth/github/callback`
5. **Register application**, then **Generate a new client secret** and copy it
   before leaving the page — GitHub shows it once.

Then, in your own terminal (the secret never goes anywhere else):

```bash
fly secrets set GITHUB_CLIENT_ID=PASTE_THE_CLIENT_ID
```
```bash
fly secrets set GITHUB_CLIENT_SECRET=PASTE_THE_SECRET
```

Setting a secret restarts the app on its own. Give it a few seconds, then load
`https://film-stock-exchange.fly.dev/signin` — "Continue with Github" should be
there.

### If GitHub says the redirect_uri is not associated

The app built an `http://` redirect and GitHub has an `https://` one
registered. Fly terminates TLS at its proxy and forwards plain HTTP, and
uvicorn honours `X-Forwarded-Proto` only from addresses it trusts — loopback by
default, which the proxy is not. The Dockerfile passes `--proxy-headers
--forwarded-allow-ips "*"` to fix it, so if you see this, redeploy:

```bash
fly deploy
```

### Google, when you want it

Cloud Console → Credentials → **Create credentials** → OAuth client ID → Web
application. Authorised redirect URI:
`https://film-stock-exchange.fly.dev/auth/google/callback`. You will also have
to fill in the OAuth consent screen before it will issue credentials.

```bash
fly secrets set GOOGLE_CLIENT_ID=PASTE_THE_CLIENT_ID
```
```bash
fly secrets set GOOGLE_CLIENT_SECRET=PASTE_THE_SECRET
```

Either pair is enough; the sign-in page only offers the buttons that are
configured. Until one is set, the market and leaderboards are public and
read-only and nobody can sign in.

## The nightly job

Prices move because something reprices them. Nothing on Fly does that by
itself, and until this is set up the market is frozen at whatever date it was
seeded on.

It cannot be a scheduled machine: SQLite lives on a volume, a Fly volume
attaches to one machine at a time, and the web app is holding it. It cannot be
an in-process timer either, because the machine suspends when nobody is
browsing. So the web app runs the job when asked over HTTP, and the request
also wakes the machine — which is what `auto_start_machines` is for.

Pick a token, give it to Fly:

```bash
fly secrets set FSX_JOB_TOKEN=$(openssl rand -hex 32)
```

Read it back so you can paste it into GitHub:

```bash
fly ssh console -C "printenv FSX_JOB_TOKEN"
```

Then in the repo: **Settings → Secrets and variables → Actions → New
repository secret**, twice:

| name | value |
| --- | --- |
| `FSX_JOB_TOKEN` | the token you just made |
| `FSX_HOST` | `film-stock-exchange.fly.dev` |

`.github/workflows/mark.yml` fires at 09:40 UTC daily, and can be run by hand
from the Actions tab. It does three things: looks for work that has come out
since the snapshot, ships the new snapshot to the app, and reprices.

Add the API keys as repository secrets too, or the refresh step skips itself
and the run only reprices: `TMDB_READ_ACCESS_TOKEN` and `OMDB_API_KEY`.

The fetch runs in the Action rather than on Fly because that is where the keys
and the fetch cache live, and because an hour-long job has no business inside a
web request. The app receives the finished file at `POST /jobs/snapshot`,
writes it to a temporary file and renames it, so a connection that drops
halfway cannot leave the market reading half a file — and refuses a snapshot
that has lost more than a tenth of the roster, because that is a failed fetch
rather than news.

Everything here is idempotent. A day already marked is never marked twice, so a
retry, a double fire or an impatient second click all do nothing.

To run it once yourself:

```bash
curl -X POST -H "Authorization: Bearer YOUR_TOKEN" https://film-stock-exchange.fly.dev/jobs/mark
```

## The nightly job, by hand

Prices move every night without refetching anything, because decay is driven by
the date. So the nightly job is cheap and offline:

```bash
fly machine run . --schedule daily --command "python -m app.jobs mark"
```

Refetching the roster is separate and occasional — new credits and awards are a
weekly concern at most. Run it from your laptop and redeploy the snapshot:

```bash
python3 -m fsx.cli backfill roster.txt --max-credits 60
git commit -am "refresh roster" && fly deploy
```

## Costs

One shared-cpu-1x machine with 512MB and a 1GB volume sits inside Fly's free
allowance. `auto_stop_machines = "suspend"` means it sleeps when idle and wakes
on the next request, so a quiet week costs nothing.

## If something is wrong

```bash
fly logs
fly status
fly ssh console -C "python -m app.jobs mark"
```

A boot loop with `SESSION_SECRET is not set` is the app refusing to run with
forgeable sessions. Set the secret and redeploy — that error is deliberate.
