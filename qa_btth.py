# -*- coding: utf-8 -*-
"""QA перевода «Повелителя Небес»: усечения, английские остатки, заголовки."""
import json
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
conn = sqlite3.connect(os.path.join(BASE, "novelfull.db"))
SLUG = "battle-through-the-heavens"

rows = conn.execute(
    "SELECT num, title, title_ru, content_en, content_ru FROM chapters "
    "WHERE slug=? AND status='translated' ORDER BY num", (SLUG,)).fetchall()
conn.close()

report = {"total": len(rows), "short_ratio": [], "english_left": [], "no_title": [],
          "empty": [], "ratio_stats": {}}

ratios = []
for num, title, title_ru, en, ru in rows:
    en = en or ""
    ru = ru or ""
    if not ru.strip():
        report["empty"].append(num)
        continue
    ratio = len(ru) / max(1, len(en))
    ratios.append(ratio)
    if ratio < 0.75:
        report["short_ratio"].append((num, round(ratio, 2), len(en), len(ru)))
    # доля латиницы (исключая имена/аббревиатуры вроде BTTH)
    latin = len(re.findall(r"[A-Za-z]", ru))
    if latin > 0.12 * len(ru):
        report["english_left"].append((num, round(latin / len(ru), 3)))
    if not title_ru or title_ru == f"Глава {num}":
        report["no_title"].append(num)

ratios.sort()
report["ratio_stats"] = {
    "min": round(ratios[0], 2) if ratios else None,
    "median": round(ratios[len(ratios) // 2], 2) if ratios else None,
    "max": round(ratios[-1], 2) if ratios else None,
}

with open(os.path.join(BASE, "qa_report.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"глав: {report['total']}")
print(f"пустых: {len(report['empty'])}")
print(f"подозрительно коротких (<0.75): {len(report['short_ratio'])}")
print(f"с остатками английского: {len(report['english_left'])}")
print(f"без заголовка: {len(report['no_title'])}")
print("ratio:", report["ratio_stats"])
