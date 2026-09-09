# Setting up /column — a runbook

WordPress writes the posts. calories.jp renders them. WordPress is never
publicly served.

One design system, one sitemap, one cache policy, one public attack surface —
and a post inherits `base.html`, so it looks like the rest of the site without
anyone maintaining a second theme.

```
column-origin.calories.jp                 calories.jp
┌──────────────────────┐                  ┌──────────────────────────┐
│ WordPress + MariaDB  │                  │ FastAPI in Docker        │
│ HestiaCP vhost       │                  │  /column, /column/{slug} │
│ caloriescolumn user  │                  │  reads blog.db on volume │
└──────────┬───────────┘                  └────────────▲─────────────┘
           │ on publish: POST /internal/sync-posts     │
           │ header X-Webhook-Secret                   │
           └───────────────────────────────────────────┘
                app pulls /wp-json/wp/v2/posts?_embed
```

Both live on the same box. WordPress is **headless**: nothing proxies visitors
to it, and the app is its only reader.

---

## Step 0 — DNS

Cloudflare → calories.jp → DNS → Add record:

| Field | Value |
|---|---|
| Type | `A` |
| Name | `column-origin` |
| IPv4 | the box |
| Proxy | **Proxied** |

Must exist before step 2 — Let's Encrypt validates over HTTP.

## Step 1 — The Hestia site

`calories.jp` is owned by the `calories` user, and Hestia refuses to let a
different user claim a subdomain of it. Turn the check off for the one command
and put it straight back, rather than folding WordPress into the user that owns
the main site:

```bash
H=/usr/local/hestia/bin
PASS=$(openssl rand -base64 18); echo "panel password: $PASS"
sudo $H/v-add-user caloriescolumn "$PASS" you@example.com default caloriescolumn
sudo $H/v-change-sys-config-value ENFORCE_SUBDOMAIN_OWNERSHIP no
sudo $H/v-add-web-domain caloriescolumn column-origin.calories.jp
sudo $H/v-change-sys-config-value ENFORCE_SUBDOMAIN_OWNERSHIP yes
sudo grep -i ownership /usr/local/hestia/conf/hestia.conf
```

That last line is not optional. The setting governs every site on the box, and
leaving it off is a standing invitation to a subdomain takeover.

## Step 2 — Template, PHP, certificate, database

```bash
H=/usr/local/hestia/bin
sudo $H/v-change-web-domain-tpl caloriescolumn column-origin.calories.jp wordpress
sudo $H/v-change-web-domain-backend-tpl caloriescolumn column-origin.calories.jp PHP-8_3
sudo $H/v-add-letsencrypt-domain caloriescolumn column-origin.calories.jp
sudo $H/v-add-database caloriescolumn wp wpu 'A_GENERATED_PASSWORD'
```

Matching `column-origin.pricebest.jp` exactly: same template, same PHP, a real
Let's Encrypt certificate rather than an origin cert. The database comes out as
`caloriescolumn_wp` / `caloriescolumn_wpu`.

## Step 3 — WordPress

`v-quick-install-app apps` throws a PHP fatal on this box and its `install`
subcommand takes undocumented options, so use wp-cli, which is already there:

```bash
D=/home/caloriescolumn/web/column-origin.calories.jp/public_html
ADMINPW=$(openssl rand -base64 18); echo "WP admin password: $ADMINPW"
sudo rm -f $D/index.html
sudo -u caloriescolumn wp core download --locale=ja --path="$D"
sudo -u caloriescolumn wp config create --path="$D" \
  --dbname=caloriescolumn_wp --dbuser=caloriescolumn_wpu --dbpass='THE_DB_PASSWORD' \
  --dbcharset=utf8mb4 --dbcollate=utf8mb4_unicode_ci
sudo -u caloriescolumn wp core install --path="$D" \
  --url=https://column-origin.calories.jp \
  --title='calories.jp コラム' \
  --admin_user=jon --admin_email=jon@novatise.com \
  --admin_password="$ADMINPW"
```

Not `admin` as the username, whatever the neighbouring site does — it is the
first thing every WordPress bot tries.

## Step 4 — Lock it down

```bash
D=/home/caloriescolumn/web/column-origin.calories.jp/public_html
C=/home/caloriescolumn/conf/web/column-origin.calories.jp
sudo -u caloriescolumn wp config set DISALLOW_FILE_EDIT true --raw --path="$D"
printf 'User-agent: *\nDisallow: /\n' | sudo tee $D/robots.txt >/dev/null
sudo chown caloriescolumn:caloriescolumn $D/robots.txt
echo 'location = /xmlrpc.php { deny all; access_log off; log_not_found off; return 403; }' \
  | sudo tee $C/nginx.conf_xmlrpc >/dev/null
sudo cp $C/nginx.conf_xmlrpc $C/nginx.ssl.conf_xmlrpc
sudo nginx -t && sudo systemctl reload nginx
```

Three separate reasons:

- **`robots.txt`** — the same posts exist at `calories.jp/column/…`, and the
  origin must not be indexed as a duplicate of them.
- **`DISALLOW_FILE_EDIT`** — closes the theme editor, the usual path from a
  stolen password to running code.
- **`xmlrpc.php`** — pingback amplification and brute-force. The Hestia
  `wordpress` template does not block it; a bare install answers `POST` with
  `200`.

Verify, and do not skip the POST:

```bash
curl -s -o /dev/null -w 'home        %{http_code}\n' https://column-origin.calories.jp/
curl -s -o /dev/null -w 'xmlrpc POST %{http_code}\n' -X POST https://column-origin.calories.jp/xmlrpc.php
curl -s https://column-origin.calories.jp/wp-json/wp/v2/posts | head -c 80
```

200, **403**, JSON. A `GET` to `xmlrpc.php` returns `405` from WordPress itself
even when unprotected, so it proves nothing.

nginx reloads gracefully; a request issued in the same breath can still be
served by the old worker. If the POST says 200, wait a second and repeat before
believing it.

## Step 5 — Wire the app

```bash
D=/home/caloriescolumn/web/column-origin.calories.jp/public_html
sudo cp -a /opt/apps/calories/.env /opt/apps/calories/.env.bak-$(date +%F)
S=$(openssl rand -hex 32)
sudo tee -a /opt/apps/calories/.env >/dev/null <<ENV
WP_URL=https://column-origin.calories.jp
WP_WEBHOOK_SECRET=$S
BLOG_DB_PATH=/data/blog.db
ENV
sudo chmod 600 /opt/apps/calories/.env
sudo -u caloriescolumn wp config set CALORIES_JP_WEBHOOK_SECRET "$S" --path="$D"
sudo docker compose --project-directory /opt/apps up -d calories
sudo grep -n "^[A-Z]" /opt/apps/calories/.env | cut -d= -f1
```

Both sides are set from one generated value, so they cannot disagree. That
heredoc is deliberately unquoted so `$S` expands.

**No `WP_HOST`.** It exists for reaching a vhost that does not resolve; this one
does, over HTTPS by name. Setting it sends a `Host` header nginx cannot match
and every fetch fails.

The final list should be exactly the site keys, the Gemini key, and these three
— nothing repeated. Appending twice is easy and leaves duplicates that resolve
last-wins, which hides the mistake.

## Step 6 — Publish automatically

A must-use plugin, not the theme's `functions.php`: a WordPress update
overwrites a bundled theme, and `DISALLOW_FILE_EDIT` means you could not repair
it from the admin.

Create `wp-content/mu-plugins/calories-sync.php`, owned by `caloriescolumn`:

```php
<?php
/**
 * Plugin Name: calories.jp sync
 */
add_action('transition_post_status', function ($new, $old, $post) {
    if ($post->post_type !== 'post') return;
    if ($new !== 'publish' && $old !== 'publish') return;
    if (!defined('CALORIES_JP_WEBHOOK_SECRET')) return;
    wp_remote_post('https://calories.jp/internal/sync-posts', [
        'timeout'  => 30,
        'blocking' => false,
        'headers'  => ['X-Webhook-Secret' => CALORIES_JP_WEBHOOK_SECRET],
    ]);
}, 10, 3);
```

```bash
sudo -u caloriescolumn wp plugin list --status=must-use \
  --path=/home/caloriescolumn/web/column-origin.calories.jp/public_html
```

mu-plugins load unconditionally and cannot be deactivated from the admin, so a
compromised login cannot quietly switch the sync off.

The payload is ignored — the app re-reads the REST API itself. A forged body
cannot put content on the site; the worst a leaked secret buys is making us
fetch our own WordPress.

## Step 7 — Verify

```bash
curl -X POST https://calories.jp/internal/sync-posts -H "X-Webhook-Secret: THE_SECRET"
curl -s http://127.0.0.1:8001/column | grep -oE 'href="/column/[^"]+"' | head
curl -s https://calories.jp/sitemap-column-ja.xml | grep -c '<loc>'
```

`{"fetched":1,"stored":1,"removed":0}`, a post link, and a sitemap count of at
least 1.

Check the origin on `127.0.0.1:8001`, not the public URL — the edge caches
`/column`, and a stale page will have you debugging a sync that worked.

Grep for the link, not for a heading. The index renders `<h2><a href=…>`, so a
pattern expecting text straight after `<h2>` matches nothing on a page that is
working perfectly.

## Step 8 — The edge cache

`/column` is cached for an hour like every other page, so a new post does not
appear until it expires. Add a Cache Rule **above** the site-wide one, since the
first match wins:

| Field | Value |
|---|---|
| If | `URI Path` starts with `/column` |
| Then | Eligible for cache |
| Edge TTL | Ignore cache-control, **60 seconds** |
| Browser TTL | Respect origin TTL |

The one place overriding the origin header is right: the app cannot know a post
was published between two requests.

---

## How it behaves

- **Publishing is live in about a minute.** No redeploy.
- **Unpublishing in WordPress unpublishes here.** A post the sync no longer sees
  is deleted, so a removed post cannot outlive your ability to edit it.
- **Editing replaces.** Posts are keyed on the WordPress id, not the slug, so
  renaming one moves its URL rather than leaving a second copy.
- **WordPress being down is not this site's emergency.** The sync returns 502
  and the last good copy of every post keeps being served.
- **A missing volume is not either.** `/column` renders empty rather than
  erroring.

## What is enforced on the content

Post HTML is sanitised against an allowlist before storage
(`dataset_manager/blog/sync.py`). Headings, lists, tables, figures, images and
links survive. `<script>`, `<style>`, `<iframe>`, event handlers and
`javascript:` URLs do not.

Not because the writer is untrusted — because a compromised WordPress must not
be able to run code on calories.jp, which is the entire reason it is kept off
the domain. An embed you actually want has to be added to `TAGS`/`ATTRS`
deliberately.

## Writing notes

**No health claims.** 薬機法 prohibits stating that a food prevents, treats or
improves a condition. Nutrient content is fine, mechanism is fine, "this helps
with X" is not.

A post's title becomes the `<h1>` and the `<title>`; the WordPress excerpt
becomes the meta description. Write both rather than letting WordPress generate
them.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `404` from `/internal/sync-posts` | `WP_WEBHOOK_SECRET` not set in `.env` |
| `403` | the header does not match the variable |
| `502` from the sync | the app cannot reach `WP_URL` — check step 4's verify |
| Every fetch fails | `WP_HOST` is set; it must not be |
| `stored: 0` | no posts with status `publish` |
| Post synced but `/column` unchanged | the edge cache — check `127.0.0.1:8001` |
| Posts vanish after a rebuild | `BLOG_DB_PATH` is not under the `/data` volume |
| `xmlrpc POST` returns 200 | the `nginx.*conf_xmlrpc` files are missing, or nginx has not reloaded |
