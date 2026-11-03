# -*- coding: utf-8 -*-
"""Поиск глав с дефектами перевода: выдуманные концовки, английские остатки, зацикливание."""
import json
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
conn = sqlite3.connect(os.path.join(BASE, "novelfull.db"))
rows = conn.execute(
    "SELECT num, content_en, content_ru FROM chapters "
    "WHERE slug='battle-through-the-heavens' AND status='translated' ORDER BY num").fetchall()
conn.close()

MARKERS = [
    "он и не подозревал", "мало кто знал", "это было только начало",
    "только время покажет", "судьба готовила", "впереди его ждали",
    "важным шагом на пути", "путь к его цели", "новые испытания",
    "его путь только начинался", "и он знал, что эта победа",
    "он был готов ко всему", "будущее готовило", "это было лишь начало",
]


def paras(t):
    return [p.strip() for p in re.split(r"\n\s*\n", (t or "").strip()) if p.strip()]


reasons = {}
for num, en, ru in rows:
    en, ru = en or "", ru or ""
    if not ru:
        reasons[num] = ["пусто"]
        continue
    r = []
    latin = len(re.findall(r"[A-Za-z]", ru))
    if latin > 0.10 * len(ru):
        r.append(f"латиница {latin / len(ru):.0%}")
    ratio = len(ru) / max(1, len(en))
    if ratio > 1.22:
        r.append(f"длина x{ratio:.2f}")
    pr = paras(ru)
    counts = {}
    for p in pr:
        if len(p) >= 40:
            counts[p] = counts.get(p, 0) + 1
    if counts and max(counts.values()) >= 3:
        r.append("зацикливание")
    tail = ru[-900:].lower()
    hits = [m for m in MARKERS if m in tail]
    if hits:
        r.append("филлер: " + hits[0])
    if r:
        reasons[num] = r

with open(os.path.join(BASE, "bad_chapters.json"), "w", encoding="utf-8") as f:
    json.dump(reasons, f, ensure_ascii=False, indent=2)
print(f"глав с дефектами: {len(reasons)}")
for k, v in list(reasons.items())[:15]:
    print(k, v)
