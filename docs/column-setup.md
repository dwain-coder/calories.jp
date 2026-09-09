# Setting up /column

WordPress writes the posts. calories.jp renders them. WordPress is never
publicly served.

That gives one design system, one sitemap, one cache policy and one public
attack surface — and a post inherits `base.html`, so it looks like the rest of
the site without anyone maintaining a second theme.

```
Contabo                                   Railway
┌──────────────────────┐                  ┌──────────────────────────┐
│ WordPress + MySQL    │                  │ FastAPI                  │
│ wp-origin.calories.jp│                  │  /column, /column/{slug} │
│ locked down          │                  │  reads blog.db on volume │
└──────────┬───────────┘                  └────────────▲─────────────┘
           │ on publish: POST /internal/sync-posts     │
           │ header X-Webhook-Secret                   │
           └───────────────────────────────────────────┘
                app pulls /wp-json/wp/v2/posts?_embed
```

---

## Step 1 — DNS

In Cloudflare, add an A record:

| Name | Content | Proxy |
|---|---|---|
| `wp-origin` | your Contabo IP | **Proxied** (orange cloud) |

Proxied matters: it keeps the box's real IP off public DNS, and puts
Cloudflare's WAF in front of WordPress.

Nothing on calories.jp links to this hostname and it is in no sitemap, so it
will not be indexed. Send `X-Robots-Tag: noindex` from nginx anyway.

## Step 2 — Install WordPress on Contabo

Install it normally (nginx + PHP-FPM + MySQL, or whatever you prefer). Point the
vhost at `wp-origin.calories.jp` and get a certificate for it.

In `wp-config.php`, define the secret the webhook will use:

```php
define('CALORIES_JP_WEBHOOK_SECRET', 'the-long-random-string-from-step-4');
```

## Step 3 — Lock WordPress down

This is the step that earns the whole architecture. WordPress is the most
attacked software on the web; here it is on your domain's DNS and shares
nothing else with the site.

Block everything except the one endpoint Railway needs. In nginx:

```nginx
# The only path Railway calls. Everything else is private.
location = /wp-json/wp/v2/posts {
    try_files $uri /index.php?$args;
}

location / {
    auth_basic "closed";
    auth_basic_user_file /etc/nginx/.htpasswd;
    try_files $uri $uri/ /index.php?$args;
}

add_header X-Robots-Tag "noindex, nofollow" always;
```

Better, if you use Cloudflare Access: put the whole hostname behind it with a
bypass policy for the posts path. Then the admin needs your identity rather
than a password someone can brute-force.

Also worth doing: disable XML-RPC, set `define('DISALLOW_FILE_EDIT', true);`,
and leave auto-updates on.

## Step 4 — Railway

**Add a volume.** This is the one piece of new infrastructure. Posts must
survive a deploy, and the 34 MB corpus baked into the image is not writable.

- Railway → your service → **Variables → Volumes → New Volume**
- Mount path: `/data`

**Then set three variables:**

| Variable | Value |
|---|---|
| `WP_URL` | `https://wp-origin.calories.jp` |
| `WP_WEBHOOK_SECRET` | a long random string — `openssl rand -hex 32` |
| `BLOG_DB_PATH` | `/data/blog.db` |

`WP_WEBHOOK_SECRET` unset means `/internal/sync-posts` returns 404. A webhook
that authenticates against an empty string is a door, not an endpoint.

If nginx does basic auth and you did not bypass the posts path, put the
credentials in `WP_URL`: `https://user:pass@wp-origin.calories.jp`.

## Step 5 — The publish hook

Any "call a URL on publish" plugin works. Or add this to the active theme's
`functions.php`:

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

That condition covers all three cases that should update the site: publishing,
editing something already published, and unpublishing.

The payload is ignored — the app re-reads the REST API itself. A forged body
cannot put content on the site; the worst a leaked secret buys an attacker is
making us fetch our own WordPress.

## Step 6 — First sync

Publish one post in WordPress, then:

```bash
curl -X POST https://calories.jp/internal/sync-posts -H "X-Webhook-Secret: $WP_WEBHOOK_SECRET"
```

Expect `{"fetched":1,"stored":1,"removed":0}`.

Locally, the same code path runs as:

```bash
uv run python main.py sync-posts
```

## Step 7 — Verify

| Check | Expected |
|---|---|
| `https://calories.jp/column` | the post is listed |
| `https://calories.jp/column/{slug}` | it renders in the site's design |
| `https://calories.jp/blog` | 301 to `/column` |
| `https://calories.jp/sitemap-column-ja.xml` | contains the post URL |
| `https://wp-origin.calories.jp/` | your lock — 401, or Cloudflare Access |

---

## How it behaves

- **Publishing is live in seconds.** No redeploy.
- **Unpublishing in WordPress unpublishes here.** A post the sync no longer sees
  is deleted, so a removed post cannot outlive your ability to edit it.
- **Editing replaces.** Posts are keyed on the WordPress id, not the slug, so
  renaming a post moves its URL instead of leaving a second copy behind.
- **WordPress being down is not this site's emergency.** The sync returns 502
  and the last good copy of every post keeps being served.
- **A missing volume is not an emergency either.** `/column` renders empty
  rather than erroring.

## What is enforced on the content

Post HTML is sanitised against an allowlist before it is stored
(`dataset_manager/blog/sync.py`). Headings, lists, tables, figures, images and
links survive. `<script>`, `<style>`, `<iframe>`, event handlers and
`javascript:` URLs do not.

This is not about distrusting the writer. It is that a compromised WordPress
must not be able to run code on calories.jp — which is the entire reason it is
kept off the domain.

An embed you actually want (a video, a chart) has to be added to `TAGS`/`ATTRS`
deliberately, not pasted into a post and hoped for.

## Images

Featured images are served from `wp-origin.calories.jp`, which is proxied
through Cloudflare (step 1), so posts do not load assets from an unproxied
origin IP. Uploading to WordPress is fine — those files are served from
Contabo, not from the Railway container.

## Writing notes

The site's editorial rule applies to posts too: **no health claims.** 薬機法
prohibits stating that a food prevents, treats or improves a condition.
Nutrient content is fine, mechanism is fine, "this helps with X" is not.

A post's title becomes the `<h1>` and the page `<title>`; the WordPress excerpt
becomes the meta description. Both are worth writing rather than letting
WordPress generate them.

## If something goes wrong

| Symptom | Cause |
|---|---|
| `404` from `/internal/sync-posts` | `WP_WEBHOOK_SECRET` is not set on Railway |
| `403` | the header does not match the variable |
| `502` | Railway cannot reach `WP_URL` — check the lock from step 3 |
| Sync says `stored: 0` | no posts with status `publish` |
| Posts vanish after a deploy | `BLOG_DB_PATH` is not on the mounted volume |
