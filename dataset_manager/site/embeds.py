"""The code other sites paste to show our figures.

Every snippet carries its link back OUTSIDE the iframe. A link inside a frame is
part of our own document — and a noindex one at that — so to a search engine the
host page would link to nothing at all. The <p> under the frame is the citation
that counts, and it names the page the figures came from, not the home page:
a food card links to that food, a ranking to that ranking.

The anchor is the site name plus the page's own title. Google treats
keyword-rich links distributed through widgets as link spam; a visible citation
naming the source is what a writer would have typed by hand.
"""
from html import escape

from . import seo
from .i18n import LANGS, SITE_NAME, t

LANG = LANGS[0]

# The host page resizes the frame when the widget reports its height. Matched
# on the frame's own window, not "the first calories.jp iframe on the page": a
# post with two widgets used to stretch the first one to fit the second.
_LISTENER = """<script>
addEventListener("message", function (e) {{
  if (e.origin !== "{base}" || !e.data || e.data.caloriesJp !== "height") return;
  var fs = document.querySelectorAll('iframe[src^="{base}/embed/"]');
  for (var i = 0; i < fs.length; i++)
    if (fs[i].contentWindow === e.source) fs[i].style.height = e.data.height + "px";
}});
</script>"""

def _credit(url, text=None, extra=""):
    """出典: <a>calories.jp「page title」</a>. The home page gets the bare name:
    one keyword phrase repeated across every site that pastes a search box is
    the widget-link pattern search engines discount, or worse."""
    anchor = escape(SITE_NAME[LANG]) + (f"「{escape(text)}」" if text else "")
    return (f'<p style="margin:4px 0 0;font-size:12px">{escape(t(LANG, "source"))}: '
            f'<a href="{escape(url)}">{anchor}</a>{extra}</p>')


def iframe(path, height, title, link_url, link_text):
    """An iframe of /embed/…, its citation, and the height listener."""
    base = seo.base_url(LANG)
    return (f'<iframe src="{escape(base + path)}" style="width:100%;border:0;height:{height}px"\n'
            f'        loading="lazy" title="{escape(title)}"></iframe>\n'
            f'{_credit(link_url, link_text)}\n'
            f'{_LISTENER.format(base=base)}')


def search_box():
    """A plain form: no frame and no script, so it survives the blogs that
    strip both, and the link under it is ordinary HTML wherever it lands."""
    base = seo.base_url(LANG)
    return (f'<form action="{base}/search" method="get" target="_blank" '
            f'style="display:flex;gap:6px;max-width:28rem">\n'
            f'  <input type="search" name="q" placeholder="{escape(t(LANG, "embed_search_ph"))}"'
            f' aria-label="{escape(t(LANG, "embed_search_title"))}" style="flex:1">\n'
            f'  <button type="submit">{escape(t(LANG, "search"))}</button>\n'
            f'</form>\n'
            f'{_credit(base + "/")}')


# (label key, nutrition field, unit, decimals)
_MACROS = (("energy", "energy_kcal", "kcal", 0), ("protein", "protein_g", "g", 1),
           ("fat", "fat_g", "g", 1), ("carbs", "carbohydrate_g", "g", 1))


def _fmt(value, unit, decimals, estimated):
    if value is None:
        return "—"
    s = f"{round(value)}" if decimals == 0 else f"{value:.{decimals}f}"
    # MEXT prints its own estimates in parentheses; dropping them would turn an
    # estimate into a measurement on someone else's page.
    return f"({s}) {unit}" if estimated else f"{s} {unit}"


def food_rows(d):
    """[(label, per 100 g, per serving or None)], and the serving if known."""
    serving = d.get("serving") if (d.get("serving") or {}).get("nutrition") else None
    quality = d.get("macro_quality") or {}
    rows = []
    for key, field, unit, dec in _MACROS:
        est = quality.get(field)
        rows.append((t(LANG, key), _fmt(d["nutrition"].get(field), unit, dec, est),
                     _fmt(serving["nutrition"].get(field), unit, dec, est) if serving else None))
    if d.get("salt_g") is not None:
        est = quality.get("salt_g")
        rows.append((t(LANG, "salt"), _fmt(d["salt_g"], "g", 1, est),
                     _fmt(serving.get("salt_g"), "g", 1, est) if serving else None))
    return rows, serving


def food_table(d, name, url):
    """The food card as plain HTML — for the blogs that strip iframes, and the
    one form where the figures become part of the writer's own page."""
    rows, serving = food_rows(d)
    head = f"<tr><th></th><th>{escape(t(LANG, 'per_100g'))}</th>"
    if serving:
        head += f"<th>{escape(serving['label'])}（{round(serving['grams'])}g）</th>"
    lines = [f"<table>\n<caption>{escape(name)}</caption>", head + "</tr>"]
    for label, per100, per_serving in rows:
        cells = f"<td>{escape(per100)}</td>" + (f"<td>{escape(per_serving)}</td>" if serving else "")
        lines.append(f"<tr><th>{escape(label)}</th>{cells}</tr>")
    lines.append("</table>")
    note = escape(seo.source_label(d["item"]["source"], LANG))
    if any("(" in c for _l, *vals in rows for c in vals if c):
        note += escape(t(LANG, "embed_paren_note"))
    lines.append(_credit(url, name, f"（{note}）"))
    return "\n".join(lines)
