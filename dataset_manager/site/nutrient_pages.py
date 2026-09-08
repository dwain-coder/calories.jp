"""Which nutrients get a "foods highest in this" page, and what to call it.

The corpus holds 148 components with enough measured values to rank, but almost
nobody searches 「17:0 antヘプタデカン酸が多い食品」. This is the curated subset people
actually look for, with the word they look for it under: MEXT calls vitamin B1
「チアミン」 in places and 「ビタミンB1」 in others, and a reader types the latter.

`search_term` is the noun a person would type; the page title is built from it.
`blurb` states what the figure is and is not, once per page, in the site's own
voice — these pages rank foods against each other, which is a fact about the
corpus, not dietary advice.

Ordering within a group follows the composition tables, so the index reads like
the source rather than like a popularity list.
"""

# code, url slug, search term, one-line note (ja)
NUTRIENTS = (
    # --- 主要成分 -----------------------------------------------------------
    ("PROT-", "protein", "たんぱく質",
     "可食部100gあたりのたんぱく質量。アミノ酸組成によるものではなく、基準窒素量からの換算値です。"),
    ("FIB-", "dietary-fibre", "食物繊維",
     "可食部100gあたりの食物繊維総量（水溶性・不溶性の合計）。"),
    ("FAT-", "fat", "脂質",
     "可食部100gあたりの脂質量。"),
    ("CHOLE", "cholesterol", "コレステロール",
     "可食部100gあたりのコレステロール量。"),
    ("NACL_EQ", "salt", "食塩相当量",
     "可食部100gあたりの食塩相当量。ナトリウム量から換算した値です。"),

    # --- ミネラル -----------------------------------------------------------
    ("K", "potassium", "カリウム", "可食部100gあたりのカリウム量。"),
    ("CA", "calcium", "カルシウム", "可食部100gあたりのカルシウム量。"),
    ("MG", "magnesium", "マグネシウム", "可食部100gあたりのマグネシウム量。"),
    ("P", "phosphorus", "リン", "可食部100gあたりのリン量。"),
    ("FE", "iron", "鉄", "可食部100gあたりの鉄量。"),
    ("ZN", "zinc", "亜鉛", "可食部100gあたりの亜鉛量。"),
    ("CU", "copper", "銅", "可食部100gあたりの銅量。"),
    ("MN", "manganese", "マンガン", "可食部100gあたりのマンガン量。"),
    ("SE", "selenium", "セレン", "可食部100gあたりのセレン量。"),

    # --- ビタミン -----------------------------------------------------------
    ("VITA_RAE", "vitamin-a", "ビタミンA",
     "可食部100gあたりのレチノール活性当量。"),
    ("VITD", "vitamin-d", "ビタミンD", "可食部100gあたりのビタミンD量。"),
    ("TOCPHA", "vitamin-e", "ビタミンE",
     "可食部100gあたりのα-トコフェロール量。"),
    ("VITK", "vitamin-k", "ビタミンK", "可食部100gあたりのビタミンK量。"),
    ("THIA", "vitamin-b1", "ビタミンB1", "可食部100gあたりのビタミンB1量。"),
    ("RIBF", "vitamin-b2", "ビタミンB2", "可食部100gあたりのビタミンB2量。"),
    ("NIA", "niacin", "ナイアシン", "可食部100gあたりのナイアシン量。"),
    ("VITB6A", "vitamin-b6", "ビタミンB6", "可食部100gあたりのビタミンB6量。"),
    ("VITB12", "vitamin-b12", "ビタミンB12", "可食部100gあたりのビタミンB12量。"),
    ("FOL", "folate", "葉酸", "可食部100gあたりの葉酸量。"),
    ("PANTAC", "pantothenic-acid", "パントテン酸",
     "可食部100gあたりのパントテン酸量。"),
    ("BIOT", "biotin", "ビオチン", "可食部100gあたりのビオチン量。"),
    ("VITC", "vitamin-c", "ビタミンC", "可食部100gあたりのビタミンC量。"),

    # --- 脂肪酸 -------------------------------------------------------------
    ("FASAT", "saturated-fat", "飽和脂肪酸",
     "可食部100gあたりの飽和脂肪酸量。脂肪酸成分表編に基づきます。"),
    ("FAMS", "monounsaturated-fat", "一価不飽和脂肪酸",
     "可食部100gあたりの一価不飽和脂肪酸量。"),
    ("FAPU", "polyunsaturated-fat", "多価不飽和脂肪酸",
     "可食部100gあたりの多価不飽和脂肪酸量。"),
    ("FAPUN3", "omega-3", "n-3系脂肪酸",
     "可食部100gあたりのn-3系多価不飽和脂肪酸量。"),
    ("FAPUN6", "omega-6", "n-6系脂肪酸",
     "可食部100gあたりのn-6系多価不飽和脂肪酸量。"),
    ("F22D6N3", "dha", "DHA",
     "可食部100gあたりのドコサヘキサエン酸（DHA）量。脂肪酸成分表編 第1表に基づきます。"),
    ("F20D5N3", "epa", "EPA",
     "可食部100gあたりのイコサペンタエン酸（EPA/IPA）量。"),

    # --- アミノ酸 -----------------------------------------------------------
    ("LYS", "lysine", "リシン", "可食部100gあたりのリシン（リジン）量。"),
    ("TRP", "tryptophan", "トリプトファン",
     "可食部100gあたりのトリプトファン量。"),
    ("LEU", "leucine", "ロイシン", "可食部100gあたりのロイシン量。"),
    ("ILE", "isoleucine", "イソロイシン", "可食部100gあたりのイソロイシン量。"),
    ("VAL", "valine", "バリン", "可食部100gあたりのバリン量。"),
    ("MET", "methionine", "含硫アミノ酸",
     "可食部100gあたりの含硫アミノ酸（メチオニン）量。"),

    # --- 糖類 ---------------------------------------------------------------
    ("STARCH", "starch", "でん粉", "可食部100gあたりのでん粉量。"),
    ("SUCS", "sucrose", "しょ糖", "可食部100gあたりのしょ糖量。"),
)

BY_SLUG = {slug: (code, slug, term, blurb) for code, slug, term, blurb in NUTRIENTS}
BY_CODE = {code: (code, slug, term, blurb) for code, slug, term, blurb in NUTRIENTS}
SLUGS = [slug for _c, slug, _t, _b in NUTRIENTS]


def get(slug):
    """(code, slug, search term, blurb) for a URL slug, or None."""
    return BY_SLUG.get(slug)


def title(term, lang="ja"):
    if lang != "ja":
        return f"Foods highest in {term}"
    return f"{term}が多い食品ランキング"
