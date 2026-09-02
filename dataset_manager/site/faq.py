"""Deterministic FAQ blocks for food pages.

Every answer is a sentence assembled from database values — no LLM, no
invented facts. Rendered as visible Q&A and as FAQPage structured data,
so the same text a reader sees is what search engines index.
"""

_R1 = lambda v: f"{round(v, 1):g}"


def food_faq(lang, name, nutrition, salt_g=None, portions=None, preps=None,
             source=None, serving=None):
    if not nutrition or nutrition.get("energy_kcal") is None:
        return []
    kcal = nutrition["energy_kcal"]
    p, f, c = (nutrition.get(k) for k in ("protein_g", "fat_g", "carbohydrate_g"))
    qa = []

    if lang == "ja":
        qa.append((
            f"{name}のカロリーは？",
            f"{name}は100gあたり{round(kcal)}kcalです。"
            # A real portion where one is known beats three arbitrary weights:
            # 「茶碗1杯（150g）で234kcal」 is what was being asked.
            + (f"{serving['label']}（{round(serving['grams'])}g）では"
               f"{round(kcal * serving['grams'] / 100)}kcalです。" if serving and kcal
               else (f"1食分の目安は、100gで{round(kcal)}kcal、150gで{round(kcal * 1.5)}kcal、"
                     f"200gで{round(kcal * 2)}kcalになります。" if kcal else ""))
            + (f"出典は{source}。" if source else ""),
        ))
        if p is not None:
            qa.append((
                f"{name}のたんぱく質はどのくらい？",
                f"100gあたり{_R1(p)}gのたんぱく質を含みます。"
                + (f"脂質は{_R1(f)}g、炭水化物は{_R1(c)}gです。"
                   if f is not None and c is not None else ""),
            ))
        if c is not None:
            qa.append((
                f"{name}は糖質制限に向いていますか？",
                f"100gあたりの炭水化物は{_R1(c)}gです。"
                + ("炭水化物が非常に少ないため、糖質を控えたい場合に選びやすい食品です。" if c < 5
                   else "炭水化物が中程度のため、量を調整すれば取り入れられます。" if c < 20
                   else "炭水化物が多めなので、糖質を控える場合は分量に注意してください。"),
            ))
        if salt_g is not None:
            qa.append((
                f"{name}の食塩相当量は？",
                f"100gあたり{_R1(salt_g)}gです。1日の目標量（男性7.5g未満・女性6.5g未満、"
                f"日本人の食事摂取基準2020年版）に対して約{round(salt_g / 7.0 * 100)}%にあたります。",
            ))
        if preps:
            hi = max(preps, key=lambda x: x["energy_kcal"] or 0)
            lo = min(preps, key=lambda x: x["energy_kcal"] or 1e9)
            if hi["energy_kcal"] and lo["energy_kcal"] and hi is not lo:
                qa.append((
                    "調理法でカロリーは変わりますか？",
                    f"変わります。同じ食品でも「{lo['prep']}」は100gあたり{round(lo['energy_kcal'])}kcal、"
                    f"「{hi['prep']}」は{round(hi['energy_kcal'])}kcalで、"
                    f"約{round(hi['energy_kcal'] / lo['energy_kcal'], 1)}倍の差があります。"
                    "水分量や吸油量が変わるためです。",
                ))
        if portions:
            pt = portions[0]
            qa.append((
                f"{name}1食分は何kcal？",
                f"「{pt['description']}」は{_R1(pt['gram_weight'])}gで、"
                f"約{round(kcal * pt['gram_weight'] / 100)}kcalです。",
            ))
    else:
        qa.append((
            f"How many calories are in {name}?",
            f"{name} has {round(kcal)} kcal per 100 g. "
            f"That works out to {round(kcal * 1.5)} kcal for 150 g and "
            f"{round(kcal * 2)} kcal for 200 g."
            + (f" Source: {source}." if source else ""),
        ))
        if p is not None:
            qa.append((
                f"How much protein is in {name}?",
                f"{name} contains {_R1(p)} g of protein per 100 g"
                + (f", along with {_R1(f)} g of fat and {_R1(c)} g of carbohydrates."
                   if f is not None and c is not None else "."),
            ))
        if c is not None:
            qa.append((
                f"Is {name} low in carbohydrates?",
                f"It has {_R1(c)} g of carbohydrates per 100 g. "
                + ("That is very low, so it fits easily into a low-carb pattern." if c < 5
                   else "That is moderate, so portion size decides whether it fits a low-carb pattern."
                   if c < 20 else
                   "That is high, so watch the portion size on a low-carb pattern."),
            ))
        if salt_g is not None:
            qa.append((
                f"How much salt is in {name}?",
                f"{_R1(salt_g)} g of salt equivalent per 100 g — about "
                f"{round(salt_g / 5.8 * 100)}% of the 5.8 g daily reference value.",
            ))
        if preps:
            hi = max(preps, key=lambda x: x["energy_kcal"] or 0)
            lo = min(preps, key=lambda x: x["energy_kcal"] or 1e9)
            if hi["energy_kcal"] and lo["energy_kcal"] and hi is not lo:
                qa.append((
                    "Does cooking change the calories?",
                    f"Yes. Measured per 100 g, {lo['prep'].lower()} is "
                    f"{round(lo['energy_kcal'])} kcal while {hi['prep'].lower()} is "
                    f"{round(hi['energy_kcal'])} kcal — about "
                    f"{round(hi['energy_kcal'] / lo['energy_kcal'], 1)}× the difference, "
                    "driven by water loss and absorbed cooking fat.",
                ))
        if portions:
            pt = portions[0]
            qa.append((
                f"How many calories in one serving of {name}?",
                f"One {pt['description']} weighs {_R1(pt['gram_weight'])} g, "
                f"which is about {round(kcal * pt['gram_weight'] / 100)} kcal.",
            ))
    return qa
