"""Host-header language routing — retired.

The site served /ja/… while a second locale was planned, and this rewrote a
bare path to the language prefix for whichever domain the request arrived on.
The pages now live at the root, so there is nothing to rewrite; /ja/… is
handled by a 301 in the router instead.

Kept as a file rather than deleted because bringing back a second language
means bringing this back with it, and the shape of the answer is here.
"""


def add_host_lang_middleware(app):     # pragma: no cover - retired
    return app
