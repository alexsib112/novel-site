# -*- coding: utf-8 -*-
"""Точная проверка последнего абзаца и зацикливаний.

Ловит:
  * английский хвост (последний абзац в основном латиницей);
  * служебный мусор в конце («Глава N», повтор заголовка, «КОНЕЦ» без причины);
  * зацикливание (абзац повторён >= 3 раз);
  * аномальную длину (ru/en > 1.22 или < 0.7).
"""
import json
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
conn = sqlite3.connect(os.path.join(BASE, "novelfull.db"))
rows = conn.execute(
    "SELECT num, title_ru, content_en, content_ru FROM chapters "
    "WHERE slug='battle-through-the-heavens' AND status='translated' ORDER BY num").fetchall()
conn.close()


def paras(t):
    return [p.strip() for p in re.split(r"\n\s*\n", (t or "").strip()) if p.strip()]


bad = {}
for num, title_ru, en, ru in rows:
    en, ru = en or "", ru or ""
    pr = paras(ru)
    if not pr:
        bad[num] = ["пусто"]
        continue
    reasons = []
    last = pr[-1]

    latin = len(re.findall(r"[A-Za-z]", last))
    if len(last) > 60 and latin > 0.5 * len(last):
        reasons.append("английский хвост")

    if re.fullmatch(r"(глава|chapter)\s*\d+[.:!]?", last.strip(), re.I):
        reasons.append("служебный заголовок в конце")

    if title_ru and last.strip().lower() == title_ru.strip().lower() and len(pr) > 1:
        reasons.append("заголовок повторён в конце")

    counts = {}
    for p in pr:
        if len(p) >= 40:
            counts[p] = counts.get(p, 0) + 1
    if counts and max(counts.values()) >= 3:
        reasons.append("зацикливание")

    ratio = len(ru) / max(1, len(en))
    if ratio > 1.22:
        reasons.append(f"длина x{ratio:.2f}")
    if ratio < 0.7:
        reasons.append(f"коротко x{ratio:.2f}")

    if reasons:
        bad[num] = reasons

with open(os.path.join(BASE, "bad_last.json"), "w", encoding="utf-8") as f:
    json.dump(bad, f, ensure_ascii=False, indent=2)
print("глав с дефектами:", len(bad))
for k, v in list(bad.items())[:20]:
    print(k, v)
