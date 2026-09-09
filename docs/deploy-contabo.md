# Running calories.jp on the Contabo box

Moves the site from Railway onto the Tokyo box beside the other apps, and adds
WordPress for `/column`. Nothing about the application changes — same image,
same database, same routes.

Written against the `novatise-infrastructure` conventions: everything binds
`127.0.0.1`, public exposure is a HestiaCP web domain with a proxy template,
the compose file is source of truth in that repository, secrets never are.

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
WP_URL=http://5.104.81.60
WP_HOST=column-origin.calories.jp
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

The box runs **HestiaCP 1.9.7**. A site is a Hestia user plus a web domain plus
an nginx proxy template; the template is the file that matters, because
`v-rebuild-web-domains` regenerates the vhost from it and discards hand edits.

Templates live in `/usr/local/hestia/data/templates/web/nginx/php-fpm/` as a
`.tpl` (HTTP) and `.stpl` (HTTPS) pair. Start from `pricebest`, the closest
analogue — a proxied app on this same box — rather than writing one:

```bash
T=/usr/local/hestia/data/templates/web/nginx/php-fpm
sudo cp -n $T/pricebest.tpl  $T/calories.tpl
sudo cp -n $T/pricebest.stpl $T/calories.stpl
sudo sed -i -E 's#proxy_pass http://(localhost|127\.0\.0\.1):[0-9]+;#proxy_pass http://localhost:8001;#' \
    $T/calories.tpl $T/calories.stpl
```

Then strip what is pricebest's and not ours. Three things:

- **`location ^~ /column`** proxies to pricebest's WordPress vhost. Delete it.
  Here `/column` is rendered by the app itself out of `blog.db` (§5), so the
  passthrough would hijack every post. `location /` already covers the path.
- **The `www` redirect** names `pricebest.jp`.
- **`location = /api/snapshot`** is pricebest's cron route, inert here.

```bash
sudo sed -i \
  -e '/# WordPress blog\./,/^[[:space:]]*}$/d' \
  -e '/# The snapshot job is expensive/,/^[[:space:]]*}$/d' \
  -e 's/pricebest\.jp/calories.jp/g' \
  $T/calories.tpl $T/calories.stpl
grep -n "add_header\|proxy_pass\|location" $T/calories.tpl $T/calories.stpl
```

That grep is the check that matters. Expect **no `add_header` at all**: the app
sends its own HSTS, nosniff, `DENY` framing and CSP, and lifts framing only for
`/embed`. A template-level `X-Frame-Options` would double up and break the
analyzer embed on every blog it is dropped into. pricebest's only `add_header`
lines were inside the `/column` block that was just deleted.

Then the user and the domain — additive, nothing public moves yet:

```bash
PASS=$(openssl rand -base64 18); echo "calories password: $PASS"
sudo /usr/local/hestia/bin/v-add-user calories "$PASS" you@example.com default calories.jp
sudo /usr/local/hestia/bin/v-add-web-domain calories calories.jp
sudo /usr/local/hestia/bin/v-change-web-domain-tpl calories calories.jp calories
sudo /usr/local/hestia/bin/v-add-web-domain-ssl-force calories calories.jp
```

Use full `/usr/local/hestia/bin/` paths. `sudo` does not inherit an exported
PATH, and the bare command names will not resolve.

`v-change-web-domain-tpl` reloads nginx and fails there if the template is
malformed, leaving the previous config running — so the other sites on the box
are not at risk from a bad template.

**Certificate.** Not Let's Encrypt: a Cloudflare Origin certificate, issued and
installed by the infrastructure repo's own script, which also writes the `.ca`
file Hestia refuses the cert without.

```bash
cd /home/admin/novatise-infrastructure
sudo ./scripts/cloudflare-origin-cert.sh issue calories calories.jp            # dry run
sudo ./scripts/cloudflare-origin-cert.sh issue calories calories.jp --apply
```

It sets the zone's SSL mode to `full`. Finish in the dashboard on **Full
(strict)** — Cloudflare trusts its own Origin CA, so strict works both before
and after the DNS move.

**Test before the DNS move.** `--resolve` sends one request to the box while
public DNS still points at Railway, so the live site is never in play:

```bash
for p in / /menu /nutrients /cooking-yield /api /embed /column /foods /analyzer /sitemap.xml; do
  printf '%-16s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' \
      -k --resolve calories.jp:443:5.104.81.60 https://calories.jp$p)"
done
```

`5.104.81.60`, not `127.0.0.1` — nginx on this box binds the public IP only.
`-k` because the origin cert is signed by Cloudflare's Origin CA, which curl
does not trust; that is the design.

Ten 200s, then move Cloudflare's `calories.jp` record to an **A** record at the
box, proxied. Keep the `_railway-verify` TXT record: it is what lets you point
back without re-verifying.

**Finally, a Cache Rule.** Cloudflare does not cache HTML without one, so every
page reaches the container however good the `Cache-Control` is. Rules → Caching
Rules → *URI Path does not start with `/internal`* → **Eligible for cache**,
edge and browser TTL both **use cache-control header from origin**.

## 5. WordPress for /column

A second Hestia site on the same box, following the convention already in use
(`column-origin.pricebest.jp` feeds pricebest's columns):

| Field | Value |
|---|---|
| Domain | `column-origin.calories.jp` |
| Hestia user | `caloriescolumn` |
| Template | `wordpress` |

WordPress is **headless**. It is never proxied to visitors: the app fetches
`/wp-json/wp/v2/posts?_embed`, sanitises the HTML against an allowlist, stores
it in `blog.db`, and renders `/column` through `base.html`. One design system,
one sitemap, one cache policy, and a compromised WordPress cannot run code on
calories.jp.

The app reaches it over the public IP with an explicit `Host` header:

```ini
WP_URL=http://5.104.81.60
WP_HOST=column-origin.calories.jp
```

**Not** `127.0.0.1` or `host.docker.internal`. nginx on this box binds the
public IP only, so a loopback request is refused — pricebest's template says so
in a comment, having learned it the hard way. `WP_HOST` exists in
`dataset_manager/blog/sync.py` for exactly this.

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
