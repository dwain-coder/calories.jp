"""Host-header language routing for production domains.

When a request arrives for SITE_DOMAIN_EN / SITE_DOMAIN_JA and its path is not
already language-prefixed or a known API/asset path, rewrite the path to the
domain's language prefix. Dev on localhost is untouched (no domains set)."""
import os

from .i18n import LANGS

PASSTHROUGH_PREFIXES = (
    "/en", "/ja", "/items", "/api", "/export", "/docs",
    "/static", "/openapi.json", "/robots.txt", "/sitemap", "/redoc",
)


def _passthrough(path):
    return any(path == p or path.startswith(p + "/") for p in PASSTHROUGH_PREFIXES) \
        or path.startswith("/sitemap")


def add_host_lang_middleware(app):
    @app.middleware("http")
    async def host_lang_rewrite(request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()
        lang = None
        for candidate in LANGS:
            domain = os.environ.get(f"SITE_DOMAIN_{candidate.upper()}", "").lower()
            if host and host == domain:
                lang = candidate
                break
        if lang:
            path = request.scope["path"]
            if path == "/" or not _passthrough(path):
                request.scope["path"] = f"/{lang}" + (path if path != "/" else "/")
        return await call_next(request)
