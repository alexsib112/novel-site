# -*- coding: utf-8 -*-
"""Точечный реперевод глав с дефектами (см. bad_chapters.json).

Для каждой главы: перевести заново строгим промптом, проверить результат
(длина, латиница, зацикливание, филлер). Если проверка не прошла — до 3 попыток.

  python repair_bad.py
"""
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from novelfull_pipeline import db, translate_chapter

SLUG = "battle-through-the-heavens"
BASE = os.path.dirname(os.path.abspath(__file__))

MARKERS = [
    "он и не подозревал", "мало кто знал", "это было только начало",
    "только время покажет", "судьба готовила", "впереди его ждали",
    "важным шагом на пути", "путь к его цели", "новые испытания",
    "его путь только начинался", "и он знал, что эта победа",
    "он был готов ко всему", "будущее готовило", "это было лишь начало",
]


def paras(t):
    return [p.strip() for p in re.split(r"\n\s*\n", (t or "").strip()) if p.strip()]


def validate(body, en):
    if not body or len(body) < 0.6 * len(en):
        return False, "слишком коротко"
    ratio = len(body) / max(1, len(en))
    if ratio > 1.22:
        return False, f"длина x{ratio:.2f}"
    latin = len(re.findall(r"[A-Za-z]", body))
    if latin > 0.10 * len(body):
        return False, f"латиница {latin / len(body):.0%}"
    counts = {}
    for p in paras(body):
        if len(p) >= 40:
            counts[p] = counts.get(p, 0) + 1
    if counts and max(counts.values()) >= 3:
        return False, "зацикливание"
    hits = [m for m in MARKERS if m in body[-900:].lower()]
    if hits:
        return False, "филлер: " + hits[0]
    return True, "ok"


def main():
    path = os.path.join(BASE, "bad_chapters.json")
    if not os.path.exists(path):
        print("нет bad_chapters.json — сначала запусти detect_bad.py")
        return
    with open(path, encoding="utf-8") as f:
        bad = json.load(f)

    conn = db()
    ok, failed = [], []
    for num_s in sorted(bad, key=int):
        num = int(num_s)
        row = conn.execute("SELECT title, content_en FROM chapters WHERE slug=? AND num=?",
                           (SLUG, num)).fetchone()
        if not row:
            continue
        title, en = row
        print(f"глава {num}: {bad[num_s]}")
        done = False
        for attempt in range(3):
            t_ru, body = translate_chapter(num, title, en)
            good, why = validate(body, en)
            if good:
                conn.execute(
                    "UPDATE chapters SET content_ru=?, title_ru=?, status='translated' "
                    "WHERE slug=? AND num=?", (body, t_ru, SLUG, num))
                conn.commit()
                print(f"  ok (попытка {attempt + 1})")
                ok.append(num)
                done = True
                break
            print(f"  попытка {attempt + 1}: {why}")
        if not done:
            failed.append(num)
    conn.close()
    print(f"\nисправлено: {len(ok)}, не удалось: {len(failed)} {failed}")


if __name__ == "__main__":
    main()
