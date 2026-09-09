# Running calories.jp on the Contabo box

Moves the site from Railway onto the Tokyo box beside the other apps, and adds
WordPress for `/column`. Nothing about the application changes — same image,
same database, same routes.

Written against the `novatise-infrastructure` conventions: everything binds
`127.0.0.1`, public exposure is a CloudPanel reverse-proxy site, the compose
file is source of truth in that repository, secrets never are.

Two things get better by being on this box rather than Railway:

- **WordPress needs no public presence at all.** No DNS record, no certificate,
  no password wall, no carefully-drilled hole for one REST path. Nothing outside
  the machine can reach it.
- **The deploy artefact stops being the constraint.** The 34 MB extract exists
  because Railway ships the database inside the image. Here the 624 MB working
  corpus can sit on disk and the pipeline can run where the data is.

---

## 0. Preflight

Every step below is also driven by one script, dry-run by default like the other
fleet scripts. It reads and reports and changes nothing, so run it before
anything else — including before the clone in §1, since checking whether the box
is ready should not require putting anything on it yet.

```bash
git clone https://github.com/dwain-coder/calories.jp.git ~/calories-deploy
sudo ~/calories-deploy/tools/contabo-deploy.sh
```

Run it with `sudo` even for the dry run. `/opt/apps/calories` is `0700 root` —
it holds an API key and a webhook secret — so an unprivileged process cannot see
into it and would report the env file missing when it only means it cannot look.
The dry run still changes nothing; `sudo` only lets it read.

Paths inside the script are absolute, so it does not care where it runs from.
On a box that has not been set up yet it will report §2 and §3 as missing —
that is the checklist, not a fault.

It checks disk and RAM against this box's own floors, that port 8001 is free,
that the compose service exists and binds loopback, that nothing mounts over
`/app/data`, and that `.env` is 0600 with the keys that matter. It exits
non-zero and touches nothing if any of that is wrong.

```bash
sudo ./tools/contabo-deploy.sh --apply    # fetch, build, start, verify
./tools/contabo-deploy.sh --verify        # read-only, any time after
```

`--apply` builds the image **before** it touches the running container, so a
broken build cannot replace a working site, and it will not report success
unless the container answers on all ten routes.

The sections below are what the script does, for when you would rather do it by
hand or need to understand a failure.

## 1. Fetch the application

```bash
sudo install -d -m 755 /opt/apps/calories
sudo git clone https://github.com/dwain-coder/calories.jp.git /opt/apps/calories/src
```

The repository carries `data/metadata/site.db` (34 MB), so the clone is
everything the site needs to serve. The 624 MB working corpus is **not** in the
repository and is only needed to re-run the ingest pipeline — copy it over
separately if you want to rebuild data on the box:

```bash
# from the workstation, optional
rsync -avz --progress data/metadata/dataset_manager.db \
    admin@<server>:/opt/apps/calories/corpus/
```

## 2. Secrets

```bash
sudo install -d -m 700 /opt/apps/calories
sudo touch /opt/apps/calories/.env && sudo chmod 600 /opt/apps/calories/.env
sudo nano /opt/apps/calories/.env
```

```ini
# Site
SITE_DOMAIN_JA=calories.jp
SITE_CACHE_MAX_AGE=3600
SITE_OPERATOR=calories.jp

# AI analyzer
GEMINI_API_KEY=...
HELM_LLM_MODEL=gemini/gemini-3.5-flash

# Blog (§5)
WP_URL=http://127.0.0.1
WP_HOST=wp.calories.internal
WP_WEBHOOK_SECRET=...
BLOG_DB_PATH=/data/blog.db
```

`SITE_CACHE_MAX_AGE` matters here. On Railway the app infers it from
`RAILWAY_ENVIRONMENT`; on this box nothing injects that, so without this line
every page would send `no-cache` and Cloudflare would forward every hit.

## 3. The compose service

Put it in an **override file** rather than editing `docker-compose.yml`. Compose
merges the two automatically, so a bad indent cannot stop postgres or the CMS
from starting, and undoing it is `rm`.

```bash
sudo cp -a /opt/apps/docker-compose.yml /opt/apps/docker-compose.yml.bak-$(date +%F)
sudo cp ~/calories-deploy/docs/calories.override.yml /opt/apps/docker-compose.override.yml
```

Validate before anything runs — this parses and resolves both files and starts
nothing:

```bash
sudo docker compose --project-directory /opt/apps config --services
```

Expect `postgres`, `cms`, `calories`. If it errors, the running containers are
untouched and only the override needs fixing.

Fold the service into `docker-compose.yml` in the infrastructure repository once
it has proven itself — that file is the source of truth, and the override is a
way of getting there without risking it on the first attempt.

## 4. Public hostname

CloudPanel → **Add Site** → *Create a Reverse Proxy*:

| Field | Value |
|---|---|
| Domain | `calories.jp` |
| Reverse proxy URL | `http://127.0.0.1:8001` |

Then issue the certificate (Let's Encrypt) from the site's SSL tab, and point
Cloudflare's `calories.jp` A record at this box, **proxied**, with SSL/TLS mode
**Full (strict)**.

The app already sends its own security headers — HSTS, nosniff, `DENY` framing,
a CSP — and lifts framing only for `/embed`. Do not add duplicates in the
CloudPanel vhost; two `X-Frame-Options` headers is worse than one.

## 5. WordPress for /column

CloudPanel → **Add Site** → *WordPress*:

| Field | Value |
|---|---|
| Domain | `wp.calories.internal` |
| Site user | `wpcalories` |

**Create no DNS record for that name.** It exists only in the box's nginx. That
one decision removes the certificate, the basic-auth wall and the public REST
hole that a split deployment needs — there is no route to this WordPress from
outside the machine.

The app reaches it by asking nginx on loopback for that vhost by name:

```ini
WP_URL=http://127.0.0.1
WP_HOST=wp.calories.internal
```

Give the container a route to the host's loopback, in the compose service:

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

and use `WP_URL=http://host.docker.internal` instead of `127.0.0.1` — inside a
container, `127.0.0.1` is the container itself. (The CMS service already uses
`extra_hosts` for the same reason.)

In `wp-config.php`, above `/* That's all, stop editing! */`:

```php
define('DISALLOW_FILE_EDIT', true);
define('CALORIES_JP_WEBHOOK_SECRET', 'the same value as WP_WEBHOOK_SECRET');
```

In the active theme's `functions.php`:

```php
add_action('transition_post_status', function ($new, $old, $post) {
    if ($post->post_type !== 'post') return;
    if ($new !== 'publish' && $old !== 'publish') return;   // publish, edit, unpublish
    wp_remote_post('https://calories.jp/internal/sync-posts', [
        'timeout'  => 30,
        'blocking' => false,
        'headers'  => ['X-Webhook-Secret' => CALORIES_JP_WEBHOOK_SECRET],
    ]);
}, 10, 3);
```

Publish one post, then:

```bash
curl -X POST https://calories.jp/internal/sync-posts -H "X-Webhook-Secret: $WP_WEBHOOK_SECRET"
```

Expect `{"fetched":1,"stored":1,"removed":0}`.

## 6. Verify

```bash
for p in / /menu /nutrients /cooking-yield /api /embed /column /foods /analyzer /sitemap.xml; do
  printf '%-16s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' https://calories.jp$p)"
done
curl -s -o /dev/null -w 'old /blog  %{http_code}\n' https://calories.jp/blog          # 301
curl -s -D - -o /dev/null https://calories.jp/ | grep -i cache-control                 # max-age=3600
curl -s -o /dev/null -w 'wp private %{http_code}\n' https://wp.calories.internal/      # must not resolve
```

Ten 200s, a 301, a cache header, and a WordPress that does not answer from
outside.

## 7. Updating

```bash
sudo git -C /opt/apps/calories/src pull
sudo docker compose --project-directory /opt/apps up -d --build calories
```

A data change is the same two commands, because `site.db` is committed: rebuild
the extract on the workstation, commit, push, pull here. To rebuild on the box
instead, point `DATABASE_PATH` at the corpus copied in step 1 and run the
pipeline there.

## 8. Going back

Railway is unchanged by any of this — the same repository still builds there,
and the app still reads `RAILWAY_ENVIRONMENT` for its cache policy. Rolling back
is a Cloudflare DNS change: point `calories.jp` at Railway again.

Keep that in mind before deleting the Railway service.

## What to watch

- **The volume is `/data`, never `/app/data`.** The composition database ships
  inside the image at `data/metadata/site.db`; a volume mounted over `/app/data`
  hides it and every route returns 502.
- **Never publish container ports.** `127.0.0.1:8001:8000`, as the apps README
  requires, so the only way in is through nginx.
- **The compose file lives in the infrastructure repository.** The last one that
  lived only on the server was nearly lost in the panel migration.
- **RAM is this box's ceiling, not disk.** calories.jp adds roughly 2 GB of disk
  and 200–400 MB of RAM, which `scripts/capacity-check.sh` will barely register.
