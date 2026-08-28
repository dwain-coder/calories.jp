"""Readable display names for MEXT items.

MEXT food names are taxonomy paths — `こむぎ うどん・そうめん類 うどん ゆで` —
where the middle tokens are group labels, not food identity. Showing the whole
path in headings and tables is what makes a reference site read like a database
dump. This module strips the group labels and, where that would make two foods
look identical, puts back the label that actually carried the distinction.

Structural rules only: no vocabulary of foods, no semantic guessing. The full
name is never discarded — pages show it as the qualified name beneath the
heading, so the exact source row stays visible.
"""

GROUP_SUFFIX = "類"
# Sub-labels that describe table structure rather than the food itself.
STRUCT_PARTS = ("主品目", "副品目")

# Form and process words. These describe what was done to a food, so a name
# starting with one names nothing: "缶詰 水煮 フレーク" could be tuna or clams.
# When shortening would leave one of these in front, the group label goes back.
PROCESS_WORDS = frozenset({
    "加工品", "缶詰", "漬物", "味付け", "水煮", "生", "ゆで", "焼き", "乾",
    "冷凍", "その他", "素干し", "煮干し", "塩辛", "つくだ煮", "フレーク",
    "蒸し", "揚げ", "粉", "塩漬", "塩抜き", "浸出液", "製品", "調味料",
})


def _is_group_label(tok, i, last):
    if i == last:
        return False                       # the final token always carries identity
    if tok.startswith("（") and tok.endswith("）"):
        return True                        # （かんきつ類）, （植物油脂類）
    return tok.endswith(GROUP_SUFFIX)      # うどん・そうめん類, 豆腐・油揚げ類


def _clean_group_label(tok):
    """（いわし類） -> いわし ; うどん・そうめん類 -> うどん・そうめん"""
    t = tok.strip("（）()")
    if t.endswith(GROUP_SUFFIX) and len(t) > 1:
        t = t[:-1]
    return t


def _strip_struct(tok):
    """若どり・主品目 -> 若どり (keeps 若どり/親, drops the structural half)"""
    if "・" in tok:
        parts = [p for p in tok.split("・") if p not in STRUCT_PARTS]
        if parts:
            return "・".join(parts)
    return tok


def shorten_mext_name(name):
    """Return (short_name, [dropped group labels, outermost first])."""
    ts = name.split()
    last = len(ts) - 1
    kept, dropped = [], []
    for i, tok in enumerate(ts):
        if _is_group_label(tok, i, last):
            dropped.append(_clean_group_label(tok))
            continue
        t = _strip_struct(tok)
        if t in STRUCT_PARTS and i < last:
            continue
        kept.append(t)
    if not kept:
        return name, []
    # A name must open with something that names a food, not a process.
    while dropped and kept[0] in PROCESS_WORDS:
        kept.insert(0, dropped.pop())
    return " ".join(kept), dropped


def resolve_display_names(pairs):
    """pairs: [(item_id, full_name)] -> {item_id: display_name}.

    Two items whose shortened names collide get group labels restored — most
    specific first — until they are distinct again, so no two foods on the site
    ever show the same name.
    """
    short, drops = {}, {}
    for item_id, name in pairs:
        s, d = shorten_mext_name(name)
        short[item_id], drops[item_id] = s, d

    by_name = {}
    for item_id, s in short.items():
        by_name.setdefault(s, []).append(item_id)

    for s, ids in list(by_name.items()):
        if len(ids) < 2:
            continue
        for item_id in ids:
            for label in reversed(drops[item_id]):     # innermost label first
                candidate = f"{label} {short[item_id]}"
                if candidate not in by_name or by_name[candidate] == [item_id]:
                    short[item_id] = candidate
                    by_name.setdefault(candidate, []).append(item_id)
                    break

    # Anything still ambiguous keeps its full name — correctness over brevity.
    final_counts = {}
    for item_id, s in short.items():
        final_counts[s] = final_counts.get(s, 0) + 1
    full = dict(pairs)
    return {
        item_id: (s if final_counts[s] == 1 else full[item_id])
        for item_id, s in short.items()
    }
