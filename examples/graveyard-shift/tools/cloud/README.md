# tools/cloud: put the game online

`ship.py` deploys a game with [OpenTofu](https://opentofu.org) the same way on five providers. Two kinds of thing go
online:

- **static**: a web build (index.html and its files) as a website over HTTPS;
- **container**: one container image (a game server, a save-sync or leaderboard backend) behind HTTPS.

```
python tools/dev.py ship --target aws --kind static --check --alert-email you@example.com   # offline: no login
python tools/dev.py ship --target aws --kind static --plan  --alert-email you@example.com   # what it would make
python tools/dev.py ship --target aws --kind static --apply --yes                           # exactly that plan
python tools/dev.py ship --target aws --kind static --destroy --yes                         # everything it made
```
`dev.py ship` forwards to `python tools/cloud/ship.py` and, for a static site, adds the engine's web build folder
(web and web-3d: `dist/`; Godot and RPG Maker MZ: `build/web/`; other engines pass `--site`). `ship.py -h` lists every
option. Install OpenTofu first and log in with the provider's own tool; the kit never stores a credential.

**Not run against a real account yet.** Every module and every deployment `ship.py` writes is validated offline with
OpenTofu 1.13 (`tofu validate`, `tofu fmt`), and the plan / apply / destroy steps are tested with a stand-in. The first
real apply on each provider is still to come (verify), and it costs money: read the plan.

## What each target makes
| Target | static | container | Budget alert | Log in with |
|---|---|---|---|---|
| `aws` | private S3 bucket behind CloudFront (origin access control) | Lightsail container service, nano | AWS Budgets, 80 % of `--budget` | `aws configure` or `AWS_PROFILE` |
| `azure` | storage account static website (TLS 1.2, no public containers) | Container App, 0 to 1 replica, external HTTPS only | consumption budget on the resource group | `az login`, `ARM_SUBSCRIPTION_ID` |
| `gcp` | Cloud Storage bucket, public read, `storage.googleapis.com` | Cloud Run, 0 to 1 instance, public | billing budget filtered to `--project`, emails `--alert-email` | `gcloud auth application-default login` |
| `linode` | Object Storage bucket, public-read objects | Nanode VM: Docker + Caddy (HTTPS for `--domain`), firewall 80/443 only | **none in Linode's API**: set one by hand | `LINODE_TOKEN` |
| `do` | Spaces bucket, public-read objects, Spaces CDN | App Platform, one smallest instance | **none in DigitalOcean's API**: set one by hand | `DIGITALOCEAN_TOKEN` (+ `SPACES_ACCESS_KEY_ID` / `SPACES_SECRET_ACCESS_KEY` for static) |

Default regions: aws us-east-1, azure eastus, gcp us-central1, linode us-east, do nyc3 (`--region` changes it).

## Guardrails
- **Plan, then apply that plan.** `--apply` refuses without a plan, or when the plan file or the site folder changed
  since; a plan is applied once. `--apply` and `--destroy` ask for the game's slug in a terminal and
  need `--yes` anywhere else. Claude Code asks before any `ship` or `tofu` command (the project's ask rules).
- **No credentials in the project.** Each provider's own login; nothing the kit writes holds a key (an exam checks).
- **Nothing secret goes up.** A static site is refused if it holds a secret-type file (`.env`, `*.pem`, ...) or a
  token (the same rules as `tools/publish_check.py`), a symlink, or no `index.html`.
- **HTTPS only, no SSH.** Every endpoint is HTTPS; nothing opens port 22 (the Linode VM's firewall drops it).
- **A budget alert on every deployment** where the provider's API has one (AWS, Azure, GCP); on Linode and
  DigitalOcean `--plan` warns you to set a billing alert in the control panel first.
- **Destroy checks.** `--destroy` removes everything in the state and fails if `tofu state list` is not empty after.
  Every resource that takes tags carries `game-kit=<slug>`, for finding leftovers by hand.
- **The state stays on your machine** in `deploy/<target>-<kind>/` (git-ignored: it can hold generated secrets).
  Back it up; without it `--destroy` cannot know what was made.

## A least-privilege login per target (verify each before use)
Give the deploy its own login with only what the recipe makes, not your owner account:
- **AWS:** an IAM user or role allowed S3 bucket and object actions on `<slug>-site-*`, CloudFront distributions and
  origin access controls, Lightsail container services, and `budgets:ModifyBudget` / `budgets:ViewBudget`.
- **Azure:** a service principal with Contributor on the subscription (the recipes create resource groups) and Cost
  Management Contributor for the budget; narrow it to the two resource groups once they exist.
- **GCP:** a service account with Storage Admin, Cloud Run Admin, Service Account User and Monitoring
  NotificationChannel Editor on the project, and Billing Account Costs Manager on the billing account for the budget.
- **Linode:** a personal access token with Read/Write on Linodes, Firewalls and Object Storage only.
- **DigitalOcean:** a token scoped to App Platform and Spaces (and Spaces keys limited to the one bucket).

## The container
`--image` is a public image that listens on `--port` (HTTP inside; the provider or Caddy adds HTTPS). The kit does not
build it: a game server's image comes with the netcode work (#254). DigitalOcean takes Docker Hub (`user/name:tag`)
and GHCR (`ghcr.io/owner/name:tag`) images. Cloud Run and Container Apps scale to zero when idle; a server that holds
long-lived connections may need another product (verify for your game).
