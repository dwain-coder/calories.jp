# What to build on calories.jp

Six tools, planned against what the corpus actually holds rather than what it
looks like it holds. Every figure below was counted, not estimated.

One correction before the list. The obvious pitch — "you have price and
nutrition on 17,876 chain rows, nobody else does" — is wrong. 17,667 rows carry
a price, but only **365** carry a price beside nutrition from a source worth
publishing: 110 from a chain's own disclosure, 255 from a composition-table
match. The rest rest on `mext_calc`, the tier-3 estimator, which reads one
keyword from a dish name and this week costed a chicken meatball as 150 g of
dried seaweed.

So the first item is not a tool.

---

## 0. Import more chains' published nutrition — the precondition

**Why first.** Twelve chains now have published figures in the corpus, covering
1,567 menu rows — but only 146 of those rows carry macros:

| chain | menu rows joined | with macros |
|---|---|---|
| ジョナサン | 259 | 0 (energy + salt) |
| ガスト | 256 | 0 (energy + salt) |
| 夢庵 | 210 | 0 (energy + salt) |
| はま寿司 | 207 | 0 (energy only) |
| くら寿司 | 136 | 0 (energy only) |
| モスバーガー | 110 | **110** |
| から好し | 105 | 0 (energy + salt) |
| バーミヤン | 93 | 0 (energy + salt) |
| chawan | 88 | 0 (energy + salt) |
| ステーキガスト | 67 | 0 (energy + salt) |
| ビッグボーイ | 19 | **19** |
| リンガーハット | 17 | **17** |

**How the すかいらーく brands arrived.** Their allergen site is behind a JS
agreement gate, which is why they looked unimportable. But each brand's menu
pages are rendered client-side from
`https://www.skylark.co.jp/<brand>/menu/json/menu_detail.json`, and that file is
the disclosure: dish name, energy, 食塩相当量 and the brand's own photograph, per
dish. Seven brands, 1,078 menu rows, one parser. 藍屋, 魚屋路 and しゃぶ葉 publish
the same file with every calorie field blank.

Where a name appears twice with two different figures — バーミヤン prints
ホイコーロウ定食 at 1,087 kcal on the grand menu and 848 at lunch — the dish is
dropped. Our menu rows carry the bare name and there is nothing to join on that
would tell them apart, so a name that states two figures states neither.

**Build.** A per-chain importer, one chain at a time, in the shape of
`extractors/chains.py`. There are now three shapes to copy: a line-based text
parser (`parse_mosburger`, `parse_bigboy`), a real PDF table
(`nutrition_table_parser`), and a JSON menu feed (`parse_skylark`). Budget hours
per chain, not days.

**Still needed, ranked by menu rows** — see `docs/chain-nutrition-urls.csv`:
ココス 283, かっぱ寿司 270, スターバックス 231, 磯丸水産 216, 元気寿司 203,
コメダ珈琲店 203, スシロー 203, すし松 200, ジョイフル 198. 33 chains, 5,612 rows.

Dead ends confirmed: 幸楽苑, スシロー, なか卯 and すき家 publish allergens with no
energy at all.

**Risk.** Low. It is public data, already cited, and it strictly improves
provenance. The tier-3 estimate is discarded wherever a published figure lands.

---

## 1. Price per gram of protein

**What.** 「タンパク質20gが一番安いチェーン店メニュー」 — a ranked, filterable
table across chains, and a per-chain version on each menu page.

**Why it is defensible.** Price is a fact from the menu. Protein is a fact from
the chain's own disclosure. Neither is inferred, so the ranking cannot be wrong
in the way the tsukune was wrong.

**Data today.** 365 usable rows. Enough to ship for モスバーガー alone and prove
the page; not enough for the cross-chain table that makes it interesting.
**Blocked on item 0.**

**Build.** One query — price, protein, kcal, chain — with a computed
`yen_per_10g_protein`. A sortable page at `/value/protein`, and a block on each
menu page. Exclude `mext_calc` rows entirely and say so on the page.

**Effort.** Half a day once the data exists. Extend to 円あたりのカロリー and
円あたりの食物繊維 from the same query.

**Why it earns.** Nothing in Japanese answers this. It is inherently linkable,
it is a comparison rather than a lookup, and it is the kind of page that gets
cited rather than skimmed.

---

## 2. 食塩相当量 tracker

**What.** Salt as a share of the daily reference on every dish, food and tray
total: 「この一杯で1日の62%」.

**Why it is defensible.** 日本人の食事摂取基準（2025年版） sets 7.5 g/day for adult
men and 6.5 g for women. Stating a percentage against a published national
reference is arithmetic with a citation. It is not a health claim, and it needs
no 薬機法 hedging as long as nothing says salt *causes* anything.

**Data today.** Strong on the food side: **2,537 of 2,538** MEXT foods carry
NACL_EQ. Weaker on menus — 362 chain-published, 8,397 from `mext_calc`. Ship it
on food pages and the tray now; extend to menu rows as item 0 lands.

**Build.** A reference table in `site/servings.py` style (two numbers and a
citation), a bar on the food page, a running total in the tray. The tray already
carries `data-salt`.

**Effort.** A day. The tray integration is most of it.

**Why it earns.** Salt is the one number Japanese readers actually track, and it
is under-served — most sites show calories and stop. It also makes the tray a
reason to return rather than a session toy.

---

## 3. Raw ↔ cooked converter

**What.** Two fields and a result: 「鶏もも肉 皮つき 200g → 焼き 122g」, both
directions, with the calories for each state.

**Why it is defensible.** 497 rates, straight from MEXT's 重量変化率表, already
rendered at `/cooking-yield`. Nothing is computed that is not published.

**Data today.** Complete. **Nothing blocks this.**

**Build.** A page reusing the existing `cooking_yields()` query, a food picker
fed by `/api/search`, and the arithmetic. Cross-link from every food page that
has a rate, and from the column post already published.

**Effort.** Half a day. The cheapest item on this list.

**Why it earns.** It answers a question people type into search boxes and get
nothing useful back for, it feeds the column, and it makes `/cooking-yield` —
currently a table nobody has a reason to visit — into a tool.

---

## 4. Nutrient percentile within food group

**What.** 「鉄分は肉類の上位8%」 on every food page, and a "highest in X" ranking
per nutrient per group.

**Why it is defensible.** A percentile is a fact about the corpus, computed
deterministically, not a judgement about the food. It states its population
explicitly, so it cannot overreach.

**Data today.** Complete: 2,633 foods, 66 categories, 173 nutrient codes,
257,235 values — each already carrying `quality`. **Nothing blocks this.**

**Build.** A `build-ranks` step writing a `nutrient_ranks` table
(item_id, code, category, percentile), precomputed rather than queried per
request. Panels on the food page grouped by
`site/nutrient_groups.py`. Feed the existing `/nutrient/{slug}` pages with a
"highest in this group" list.

Rank measured and estimated values separately, or say which the percentile is
over — a rank that silently mixes them inherits the estimate's uncertainty
without showing it.

**Effort.** Two days including the precompute step and the page work.

**Why it earns.** It turns 2,633 lookup pages into comparison pages, which is
the difference between a bounce and a second click. It also gives the column an
endless supply of factual posts.

---

## 5. The companion books

**What.** Amino acids, fatty acids and carbohydrates — 糖質 split into sugars and
fibre fractions, saturated against unsaturated fat, the essential amino acid
profile.

**Why it is defensible.** Same publisher, same licence, same 食品番号 key as the
main table, and the schema already fits:
`nutrients(item_id, code, name, unit, amount, quality)` needs no change because
each book carries its own 成分識別子 codes.

**Data today.** All ten files are already downloaded and unused:

```
data/raw/mext_amino_2023/   04.xlsx 05.xlsx 06.xlsx 07.xlsx
data/raw/mext_fatty_2023/   09.xlsx 10.xlsx 11.xlsx
data/raw/mext_carb_2023/    13.xlsx 14.xlsx 15.xlsx
```

**Nothing blocks this** except the work.

**Build.** `config/datasets.yaml` entries plus one parameterised transformer,
`transformers/mext_companion.py`, reusing `clean_amount()` and the
header-assertion approach in `mext.py`. Then `build-pages` and the extract.

**Watch the extract size.** ~150 nutrient rows per food against the current 100.
35 MB will grow; if it passes ~80 MB, move the database to a volume rather than
shrinking the data.

**Effort.** Three days — one transformer, ten configs, a review pass per book.

**Why it earns.** It roughly triples what a food page can say, from data already
licensed and downloaded, and 糖質 specifically is what a large search audience is
looking for.

---

## 6. The API as a product

**What.** Keys, quotas, a paid tier.

**Why now.** The API returns provenance per value as of this week — `measured`,
`estimated`, `trace` — plus source and licence. No free Japanese nutrition API
does that, and it is precisely what a paying integrator needs, because it is
what lets *them* make honest claims downstream.

**Data today.** Six GET endpoints, unauthenticated and unthrottled. The Helm
integration is the reference implementation.

**Build, in order.**

1. **A key and a quota.** `api_keys(key_hash, owner, tier, created_at)` and a
   per-key counter. Hash the key; never store it. This is also the fix for the
   current state, where anyone who finds `/api` can hammer it.
2. **Free tier** — 1,000 calls a day, attribution required. Enough for a hobby
   app, and it seeds the funnel.
3. **Paid tier** — bulk endpoints, the full nutrient set, no attribution
   requirement.
4. **A licence page** stating what may be redistributed. MEXT and MAFF terms
   flow through to the customer; that has to be explicit rather than implied.

**Effort.** Three days for keys and quotas. The pricing decision is longer than
the code.

**Why it earns.** It is the only item that bills someone directly, and the
marginal cost of a served request is close to zero.

---

## Sequencing

**Now, unblocked:** 3 (half a day), then 4 (two days), then 5 (three days).
Those need nothing that does not exist and each improves 2,633 food pages.

**In parallel:** 0, one chain at a time. Every chain imported improves 1, 2 and
the credibility of every menu page.

**After 0 has three or four chains:** 1, then 2 on menu rows.

**When there is something worth selling access to:** 6. It is stronger after 5,
because the companion books are what make the API hard to replicate.

## The thing not on this list

`mext_calc` covers 6,115 menu rows and is the weakest thing on the site. It
reads one keyword from a dish name: 「ひじき入り鶏つくね」 resolves entirely to
hijiki and never to chicken. Fixing it means decomposing a dish name into all of
its parts and costing each — which is a real project, and the precondition for
anything that plans meals rather than describes them.

Until then, do not build a tool that consumes those rows. Two of the six above
were tempting for exactly that reason and are scoped to avoid it.
