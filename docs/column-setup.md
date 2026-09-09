# Setting up /column — a runbook

WordPress writes the posts. calories.jp renders them. WordPress is never
publicly served.

One design system, one sitemap, one cache policy, one public attack surface —
and a post inherits `base.html`, so it looks like the rest of the site without
anyone maintaining a second theme.

```
Contabo                                   Railway
┌──────────────────────┐                  ┌──────────────────────────┐
│ WordPress + MariaDB  │                  │ FastAPI                  │
│ wp-origin.calories.jp│                  │  /column, /column/{slug} │
│ behind basic auth    │                  │  reads blog.db on volume │
└──────────┬───────────┘                  └────────────▲─────────────┘
           │ on publish: POST /internal/sync-posts     │
           │ header X-Webhook-Secret                   │
           └───────────────────────────────────────────┘
                app pulls /wp-json/wp/v2/posts?_embed
```

Written for Ubuntu 22.04/24.04, which is the Contabo default. Run everything as
a sudo-capable user, not as root.

---

## Step 0 — Two secrets, generated now

Generate both and put them somewhere you will still have tomorrow. They are
referenced throughout.

```bash
openssl rand -hex 32   # → WEBHOOK_SECRET
openssl rand -base64 24 # → DB_PASSWORD
```

---

## Step 1 — DNS

Cloudflare → calories.jp → DNS → **Add record**:

| Field | Value |
|---|---|
| Type | `A` |
| Name | `wp-origin` |
| IPv4 | your Contabo IP |
| Proxy status | **Proxied** (orange cloud) |
| TTL | Auto |

Proxied keeps the box's real IP off public DNS and puts Cloudflare's WAF in
front of WordPress.

Then Cloudflare → SSL/TLS → Overview → set encryption mode to **Full (strict)**.
The origin certificate in step 3 is what makes strict work.

## Step 2 — Server packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx mariadb-server php8.3-fpm php8.3-mysql php8.3-xml \
    php8.3-curl php8.3-gd php8.3-mbstring php8.3-zip php8.3-intl \
    apache2-utils unzip curl
```

If `php8.3-*` is not found, use `php8.1-*` (22.04) and adjust the socket path in
step 5 to match.

Lock down MariaDB and create the database:

```bash
sudo mysql_secure_installation
```

```bash
sudo mysql -e "CREATE DATABASE wp_calories CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER 'wp_calories'@'localhost' IDENTIFIED BY 'PASTE_DB_PASSWORD';"
sudo mysql -e "GRANT ALL ON wp_calories.* TO 'wp_calories'@'localhost'; FLUSH PRIVILEGES;"
```

## Step 3 — Origin certificate

Cloudflare → SSL/TLS → **Origin Server** → Create Certificate. Accept the
defaults, hostname `wp-origin.calories.jp`, 15 years. You get two blocks.

```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/wp-origin.pem   # paste the CERTIFICATE block
sudo nano /etc/ssl/cloudflare/wp-origin.key   # paste the PRIVATE KEY block
sudo chmod 600 /etc/ssl/cloudflare/wp-origin.key
```

This certificate is only trusted by Cloudflare, which is the point — nothing
reaches the origin except through them.

## Step 4 — WordPress

```bash
cd /tmp && curl -O https://ja.wordpress.org/latest-ja.tar.gz
tar xzf latest-ja.tar.gz
sudo mv wordpress /var/www/wp-calories
sudo chown -R www-data:www-data /var/www/wp-calories
sudo find /var/www/wp-calories -type d -exec chmod 755 {} \;
sudo find /var/www/wp-calories -type f -exec chmod 644 {} \;
```

```bash
sudo -u www-data cp /var/www/wp-calories/wp-config-sample.php /var/www/wp-calories/wp-config.php
sudo -u www-data nano /var/www/wp-calories/wp-config.php
```

Set the database name, user and password, then paste fresh salts from
<https://api.wordpress.org/secret-key/1.1/salt/> over the placeholder block, and
add these lines above `/* That's all, stop editing! */`:

```php
define('DISALLOW_FILE_EDIT', true);
define('CALORIES_JP_WEBHOOK_SECRET', 'PASTE_WEBHOOK_SECRET');
define('FORCE_SSL_ADMIN', true);
// Cloudflare terminates TLS, so PHP sees plain HTTP without this.
if (!empty($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https') {
    $_SERVER['HTTPS'] = 'on';
}
```

## Step 5 — nginx, locked down

This is the step that earns the whole architecture. WordPress is the most
attacked software on the web, and here it is on your domain's DNS.

Create the password file:

```bash
sudo htpasswd -c /etc/nginx/.htpasswd-wp dwain   # it will prompt for a password
```

```bash
sudo nano /etc/nginx/sites-available/wp-origin
```

```nginx
server {
    listen 80;
    server_name wp-origin.calories.jp;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name wp-origin.calories.jp;

    ssl_certificate     /etc/ssl/cloudflare/wp-origin.pem;
    ssl_certificate_key /etc/ssl/cloudflare/wp-origin.key;

    root /var/www/wp-calories;
    index index.php;

    # Nothing here should ever be indexed. Nothing links to it, but say so.
    add_header X-Robots-Tag "noindex, nofollow" always;

    # The ONE path Railway calls. Public, read-only, no password.
    location = /wp-json/wp/v2/posts {
        try_files $uri /index.php?$args;
    }

    # Everything else needs the password, including the rest of the REST API.
    location / {
        auth_basic "closed";
        auth_basic_user_file /etc/nginx/.htpasswd-wp;
        try_files $uri $uri/ /index.php?$args;
    }

    location ~ \.php$ {
        auth_basic "closed";
        auth_basic_user_file /etc/nginx/.htpasswd-wp;
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }

    # index.php is reached through try_files above, so it must not demand a
    # password of its own or the posts endpoint would too.
    location = /index.php {
        auth_basic off;
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
    }

    location = /xmlrpc.php { deny all; }
    location ~* /(?:uploads|files)/.*\.php$ { deny all; }

    client_max_body_size 32M;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/wp-origin /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Finish the WordPress install in a browser at
`https://wp-origin.calories.jp/wp-admin/install.php` — the basic-auth prompt
comes first, then WordPress's own.

**Verify the lock before going further:**

```bash
curl -s -o /dev/null -w "admin        %{http_code}\n" https://wp-origin.calories.jp/wp-admin/
curl -s -o /dev/null -w "posts API    %{http_code}\n" https://wp-origin.calories.jp/wp-json/wp/v2/posts
```

Expect **401** for the admin and **200** for the posts API. If the posts API
also asks for a password, Railway cannot read it.

## Step 6 — Railway

**Add a volume.** This is the one new piece of infrastructure. Posts must
survive a deploy, and the 34 MB corpus baked into the image is not writable.

Railway → your service → **Variables → Volumes → New Volume**, mount path
**`/data`**.

> Mount it at `/data`, not `/app/data`. `/app/data` would shadow the directory
> the composition database ships in and take the whole site down.

Then Railway → Variables:

| Variable | Value |
|---|---|
| `WP_URL` | `https://wp-origin.calories.jp` |
| `WP_WEBHOOK_SECRET` | the hex string from step 0 |
| `BLOG_DB_PATH` | `/data/blog.db` |

`WP_WEBHOOK_SECRET` unset means `/internal/sync-posts` returns 404. A webhook
that authenticates against an empty string is a door, not an endpoint.

## Step 7 — The publish hook

Appearance → Theme File Editor is disabled by `DISALLOW_FILE_EDIT`, so add this
on the server, in the active theme's `functions.php`:

```bash
sudo -u www-data nano /var/www/wp-calories/wp-content/themes/twentytwentyfour/functions.php
```

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

The payload is ignored — the app re-reads the REST API itself. A forged body
cannot put content on the site; the worst a leaked secret buys is making us
fetch our own WordPress.

## Step 8 — First sync

Publish one post in WordPress, then from anywhere:

```bash
curl -X POST https://calories.jp/internal/sync-posts -H "X-Webhook-Secret: PASTE_WEBHOOK_SECRET"
```

Expect `{"fetched":1,"stored":1,"removed":0}`.

## Step 9 — Verify

```bash
curl -s -o /dev/null -w "column index  %{http_code}\n" https://calories.jp/column
curl -s -o /dev/null -w "old /blog     %{http_code}\n" https://calories.jp/blog
curl -s https://calories.jp/sitemap-column-ja.xml | grep -c "<loc>"
```

Expect 200, 301, and a count of at least 1.

---

## How it behaves

- **Publishing is live in seconds.** No redeploy.
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
| `404` from `/internal/sync-posts` | `WP_WEBHOOK_SECRET` not set on Railway |
| `403` | the header does not match the variable |
| `502` from the sync | Railway cannot reach `WP_URL` — check step 5's verify |
| `401` from the posts API | the `location = /wp-json/wp/v2/posts` block is not matching |
| `stored: 0` | no posts with status `publish` |
| Posts vanish after a deploy | `BLOG_DB_PATH` is not on the mounted volume |
| Whole site 502 after adding the volume | it is mounted at `/app/data` — move it to `/data` |
