"""Food-group identity: colour and glyph per MEXT group.

Colours are drawn from the foods themselves — wheat gold for grains, yolk for
eggs, soy-dark for seasonings — so the palette reads as a pantry rather than a
chart legend. Every value is muted enough to sit on paper stock next to ink.
Order matches the MEXT table order.
"""

# ja group -> (hex, emoji)
GROUPS = {
    "穀類":              ("#C89B3F", "🌾"),
    "いも及びでん粉類":    ("#A8845C", "🥔"),
    "砂糖及び甘味類":      ("#D9A0A8", "🍬"),
    "豆類":              ("#8C6B4F", "🫘"),
    "種実類":            ("#7A5C43", "🌰"),
    "野菜類":            ("#6E8F44", "🥬"),
    "果実類":            ("#D98032", "🍊"),
    "きのこ類":           ("#9A8C7A", "🍄"),
    "藻類":              ("#2F6F66", "🌿"),
    "魚介類":            ("#3D6B8E", "🐟"),
    "肉類":              ("#A8453C", "🥩"),
    "卵類":              ("#E0B03C", "🥚"),
    "乳類":              ("#93A8C4", "🥛"),
    "油脂類":            ("#C9972E", "🫒"),
    "菓子類":            ("#C4708F", "🍡"),
    "し好飲料類":         ("#6F8F66", "🍵"),
    "調味料及び香辛料類":  ("#5C4632", "🧂"),
    "調理済み流通食品類":  ("#7E8578", "🍱"),
}

DEFAULT_COLOR = "#8B938D"


def color(ja_group):
    g = GROUPS.get(ja_group)
    return g[0] if g else DEFAULT_COLOR


def emoji(ja_group):
    g = GROUPS.get(ja_group)
    return g[1] if g else ""


def ordered():
    """[(ja_group, hex, emoji)] in MEXT table order."""
    return [(k, v[0], v[1]) for k, v in GROUPS.items()]
