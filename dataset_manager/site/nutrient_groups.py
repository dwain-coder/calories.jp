"""Sort the composition codes into the sections a reader can navigate.

A food now carries up to ~170 measured components, because the amino acid,
fatty acid and carbohydrate books are loaded alongside the main table. As one
list that is worse than the 45 it replaced: nobody scrolls past イソロイシン to
find カルシウム. The groups below are the ones the tables themselves are
organised by, in the order a Japanese nutrition label reads.

Membership is by explicit code where the set is fixed, and by prefix for the
open-ended families — the individual fatty acids are all F<carbons>D<double
bonds> and there are fifty of them.
"""

# (key, 日本語, English, codes, code_prefixes)
GROUPS = (
    ("basics", "主要成分", "Basics",
     ("REFUSE", "ENERC", "ENERC_KCAL", "WATER", "PROT-", "PROTCAA", "FAT-", "FATNLEA",
      "CHOLE", "CHOCDF-", "CHOAVLM", "CHOAVL", "CHOAVLDF-", "FIB-", "POLYL", "ASH",
      "OA", "ALC", "NACL_EQ"), ()),
    ("minerals", "ミネラル", "Minerals",
     ("NA", "K", "CA", "MG", "P", "FE", "ZN", "CU", "MN", "ID", "SE", "CR", "MO"), ()),
    ("vitamins", "ビタミン", "Vitamins",
     ("RETOL", "CARTA", "CARTB", "CRYPXB", "CARTBEQ", "VITA_RAE", "VITD",
      "TOCPHA", "TOCPHB", "TOCPHG", "TOCPHD", "VITK", "THIA", "RIBF", "NIA", "NE",
      "VITB6A", "VITB12", "FOL", "PANTAC", "BIOT", "VITC"), ()),
    ("fats", "脂肪酸", "Fatty acids",
     ("FACID", "FASAT", "FAMS", "FAPU", "FAPUN3", "FAPUN6", "FAUN"), ("F",)),
    ("amino", "アミノ酸", "Amino acids",
     ("ILE", "LEU", "LYS", "MET", "CYS", "AAS", "PHE", "TYR", "AAA", "THR", "TRP",
      "VAL", "HIS", "ARG", "ALA", "ASP", "GLU", "GLY", "PRO", "SER", "HYP",
      "AAT", "AMMON", "AMMONE"), ()),
    ("sugars", "糖類・でん粉", "Sugars and starch",
     ("STARCH", "GLUS", "FRUS", "GALS", "SUCS", "MALS", "LACS", "TRES",
      "SORTL", "MANTL"), ()),
    ("fibre", "食物繊維", "Dietary fibre",
     ("FIBSOL", "FIBINS", "FIBTG", "FIBSDFS", "FIBSDFP", "FIBIDF", "FIBTDF", "FIBAOAC"),
     ("FIB",)),
    ("organic", "有機酸", "Organic acids",
     ("CITAC", "MALAC", "OXALAC", "SUCAC", "ACEAC", "LACAC", "TARAC", "FUMAC",
      "PYRAC", "GLUCAC", "QUINAC", "SALAC", "GLUTARAC", "PROAC", "BUTAC",
      "FORAC", "SHIKAC", "ADIPAC", "ALPHAKETAC", "GLYCEAC", "ISOCITAC", "PHYTAC"),
     ()),
)

_BY_CODE = {}
for _key, _ja, _en, _codes, _prefixes in GROUPS:
    for _code in _codes:
        _BY_CODE.setdefault(_code, _key)

LABELS = {key: {"ja": ja, "en": en} for key, ja, en, _c, _p in GROUPS}
ORDER = [key for key, *_ in GROUPS]


def group_of(code):
    """Which section a component belongs in. Unknown codes fall to 'basics'
    rather than disappearing: a component MEXT adds in a future edition should
    still be shown, just not filed."""
    code = (code or "").strip()
    if code in _BY_CODE:
        return _BY_CODE[code]
    for key, _ja, _en, _codes, prefixes in GROUPS:
        if prefixes and any(code.startswith(p) for p in prefixes):
            # F16D0 is a fatty acid; FE (iron) is not, and is caught above by
            # its explicit membership.
            return key
    return "basics"


def grouped(nutrients, lang="ja"):
    """[(key, label, [rows])] in reading order, skipping empty sections."""
    buckets = {}
    for row in nutrients:
        buckets.setdefault(group_of(row.get("code")), []).append(row)
    out = []
    for key in ORDER:
        rows = buckets.get(key)
        if rows:
            out.append((key, LABELS[key].get(lang, LABELS[key]["ja"]), rows))
    return out
