# Deploying to Fly

Nothing here needs a token pasted anywhere but your own terminal. `flyctl`
authenticates on your machine and stays there.

## Once

```bash
brew install flyctl          # or: curl -L https://fly.io/install.sh | sh
fly auth login
```

## First deploy

```bash
cd ~/Documents/Claude/Projects/Film\ Stock\ Exchange

# 1. Pick a name. It has to be unique across all of fly.io, so edit the
#    `app = ` line in fly.toml first, then:
fly launch --no-deploy --copy-config --name YOUR-APP-NAME

# 2. The database volume. 1GB is far more than this needs.
fly volumes create market_data --size 1 --region iad

# 3. Secrets. These never enter the repo or this chat.
fly secrets set SESSION_SECRET=$(openssl rand -hex 32)
fly secrets set FSX_ENV=production
fly secrets set TMDB_READ_ACCESS_TOKEN=... OMDB_API_KEY=...

# 4. Ship it.
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
fly ssh console -C "python -m app.jobs seed --months 24"
```

Then check it:

```bash
fly open                     # the market
curl https://YOUR-APP-NAME.fly.dev/healthz
```

## Sign-in

OAuth apps need the deployed hostname, which does not exist until after the
first deploy — so do this last.

- **GitHub** → Settings → Developer settings → OAuth Apps → New.
  Callback: `https://YOUR-APP-NAME.fly.dev/auth/github/callback`
- **Google** → Cloud Console → Credentials → OAuth client ID (Web).
  Redirect URI: `https://YOUR-APP-NAME.fly.dev/auth/google/callback`

```bash
fly secrets set GITHUB_CLIENT_ID=... GITHUB_CLIENT_SECRET=...
fly secrets set GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
```

Either pair is enough; the sign-in page only offers the buttons that are
configured. Until one is set, the market and leaderboards are public and
read-only and nobody can sign in.

## The nightly job

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
fly ssh console -C "python -m app.jobs mark"      # force a repricing
```

A boot loop with `SESSION_SECRET is not set` is the app refusing to run with
forgeable sessions. Set the secret and redeploy — that error is deliberate.
