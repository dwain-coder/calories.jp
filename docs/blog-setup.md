# Blog: WordPress writes, calories.jp renders

WordPress is the editor and nothing else. It is never publicly served, and
`calories.jp/blog` is rendered by this app from a synced copy of the posts.

That keeps one design system, one sitemap, one cache policy and one public
attack surface. It also means the blog inherits the site's templates, so a post
looks like the rest of calories.jp without anyone maintaining a second theme.

```
Contabo                          Railway
┌────────────────────┐           ┌─────────────────────────┐
│ WordPress + MySQL  │           │ FastAPI                 │
│ bound to localhost │           │  /blog, /blog/{slug}    │
│ admin behind auth  │           │  reads blog.db (volume) │
└─────────┬──────────┘           └───────────▲─────────────┘
          │  on publish: POST /internal/sync-posts
          │  with X-Webhook-Secret                │
          └───────────────────────────────────────┘
                    app pulls /wp-json/wp/v2/posts
```

## 1. WordPress on Contabo

Install WordPress normally. Two things matter:

- **Do not point `calories.jp` at it.** Give it its own hostname, e.g.
  `wp-origin.calories.jp`, as a separate DNS record.
- **Lock the whole site down**, not just `/wp-admin`. Cloudflare Access, an IP
  allowlist, or basic auth in nginx. The REST API must stay reachable from
  Railway — allowlist Railway's egress, or leave `/wp-json/wp/v2/posts`
  readable while everything else is closed.

Nothing links to it and it is not in any sitemap, so it will not be indexed.

## 2. Railway

Add a **volume** mounted at `/data` — posts must survive a deploy, and the 34 MB
corpus that ships inside the image cannot be written to at runtime.

Then set:

| Variable | Value |
|---|---|
| `WP_URL` | `https://wp-origin.calories.jp` |
| `WP_WEBHOOK_SECRET` | a long random string |
| `BLOG_DB_PATH` | `/data/blog.db` |

`WP_WEBHOOK_SECRET` unset means `/internal/sync-posts` returns 404. A webhook
that authenticates against an empty string is a door, not an endpoint.

## 3. The webhook

Any "call a URL on publish" plugin will do, or drop this in the theme's
`functions.php`:

```php
add_action('transition_post_status', function ($new, $old, $post) {
    if ($post->post_type !== 'post') return;
    if ($new !== 'publish' && $old !== 'publish') return;   // publish, edit, unpublish
    wp_remote_post('https://calories.jp/internal/sync-posts', [
        'timeout'  => 30,
        'blocking' => false,
        'headers'  => ['X-Webhook-Secret' => getenv('CALORIES_JP_WEBHOOK_SECRET')],
    ]);
}, 10, 3);
```

The payload is ignored. The app re-reads the REST API itself, so a forged body
cannot put content on the site — the worst a leaked secret buys is making the
app fetch its own WordPress.

## 4. Check it

```bash
uv run python main.py sync-posts          # manual pull, same code path
curl -X POST https://calories.jp/internal/sync-posts \
     -H "X-Webhook-Secret: $WP_WEBHOOK_SECRET"
```

## What is enforced

- **Post HTML is sanitised on the way in** (`dataset_manager/blog/sync.py`):
  an allowlist of tags and attributes, no `<script>`, no `<iframe>`, no event
  handlers, no `javascript:` URLs. This is not about distrusting the writer —
  it is that a compromised WordPress must not be able to run code on
  calories.jp.
- **Unpublishing in WordPress unpublishes here.** A post the sync no longer
  sees is deleted, so a removed post cannot stay up on a site the author can no
  longer edit it from.
- **WordPress being down is not this site's emergency.** The sync fails, the
  last good copy of every post keeps being served, and `/blog` renders empty
  rather than erroring if the volume is missing entirely.

## Images

Featured images are served from the WordPress host. Put that host behind
Cloudflare too, so posts do not load assets from an unproxied origin IP.
