"""Whether a food meets Japan's own criteria for a 「高い」 or 「含む」 claim.

食品表示基準 別表第十二 fixes, per nutrient, how much a food must contain
before a label may say it is high in that nutrient (高い旨) or contains it
(含む旨). Those thresholds are the law's, not ours, which is exactly why they
are worth using: "this food meets the criterion a Japanese label must meet to
say 高たんぱく質" is checkable, and unlike a phrase such as "rich in protein"
it is not our opinion.

Values transcribed from the statute itself, via the e-Gov API
(https://laws.e-gov.go.jp/api/1/lawdata/427M60000002010), not from memory —
protein's threshold is 17.0 g/100 g, and a plausible-looking 16.2 was what
recollection offered.

The table gives two figures per nutrient: per 100 g for食品 generally, and a
lower one in parentheses for 一般に飲用に供する液状 food, because nobody drinks
100 g of a beverage expecting a meal. MEXT's し好飲料類 group is treated as
liquid. The per-100kcal basis in the same table is not used here.
"""

# code -> (label, 高い threshold, 含む threshold, unit) for solids, and the
# same for drinks. Both straight from 別表第十二.
THRESHOLDS = {
    "PROT-":    ("たんぱく質", 17.0, 8.5, 8.5, 4.3, "g"),
    "FIB-":     ("食物繊維", 6.0, 3.0, 3.0, 1.5, "g"),
    "ZN":       ("亜鉛", 2.55, 1.28, 1.28, 0.64, "mg"),
    "K":        ("カリウム", 840.0, 420.0, 420.0, 210.0, "mg"),
    "CA":       ("カルシウム", 210.0, 105.0, 105.0, 53.0, "mg"),
    "FE":       ("鉄", 1.95, 0.98, 0.98, 0.49, "mg"),
    "CU":       ("銅", 0.24, 0.12, 0.12, 0.06, "mg"),
    "MG":       ("マグネシウム", 96.0, 48.0, 48.0, 24.0, "mg"),
    "NIA":      ("ナイアシン", 3.9, 1.95, 1.95, 0.98, "mg"),
    "PANTAC":   ("パントテン酸", 1.65, 0.83, 0.83, 0.41, "mg"),
    "BIOT":     ("ビオチン", 15.0, 7.5, 7.5, 3.8, "µg"),
    "VITA_RAE": ("ビタミンA", 231.0, 116.0, 116.0, 58.0, "µg"),
    "THIA":     ("ビタミンB1", 0.30, 0.15, 0.15, 0.08, "mg"),
    "RIBF":     ("ビタミンB2", 0.42, 0.21, 0.21, 0.11, "mg"),
    "VITB6A":   ("ビタミンB6", 0.39, 0.20, 0.20, 0.10, "mg"),
    "VITB12":   ("ビタミンB12", 1.20, 0.60, 0.60, 0.30, "µg"),
    "VITC":     ("ビタミンC", 30.0, 15.0, 15.0, 7.5, "mg"),
    "VITD":     ("ビタミンD", 2.70, 1.35, 1.35, 0.68, "µg"),
    "TOCPHA":   ("ビタミンE", 1.95, 0.98, 0.98, 0.49, "mg"),
    "VITK":     ("ビタミンK", 45.0, 22.5, 22.5, 11.3, "µg"),
    "FOL":      ("葉酸", 72.0, 36.0, 36.0, 18.0, "µg"),
}

LIQUID_CATEGORIES = frozenset({"し好飲料類"})


def is_liquid(category):
    return category in LIQUID_CATEGORIES


def claims_for(nutrients, category=None, limit=6):
    """Which claims this food's composition would support, strongest first.

    nutrients: rows with code / amount / quality, per 100 g.

    A value MEXT marks as its own estimate is skipped rather than used to
    assert that a label could be printed: the claim is about what the food
    contains, and an estimate is not a measurement of this food.
    """
    liquid = is_liquid(category)
    out = []
    for row in nutrients or []:
        spec = THRESHOLDS.get((row.get("code") or "").strip())
        amount = row.get("amount")
        if not spec or amount is None or row.get("quality") == "estimated":
            continue
        label, high_s, high_l, some_s, some_l, unit = spec
        high, some = (high_l, some_l) if liquid else (high_s, some_s)
        if amount >= high:
            level = "high"
        elif amount >= some:
            level = "source"
        else:
            continue
        out.append({"code": row["code"], "label": label, "amount": amount,
                    "unit": unit, "level": level,
                    "threshold": high if level == "high" else some,
                    "times": amount / (high if level == "high" else some)})
    out.sort(key=lambda c: (c["level"] != "high", -c["times"]))
    return out[:limit]
