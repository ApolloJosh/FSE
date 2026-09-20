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
fly ssh console -C "python -m app.jobs seed --months 24"
```

Then check it:

```bash
fly open
curl https://YOUR-APP-NAME.fly.dev/healthz
```

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
