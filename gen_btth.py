# -*- coding: utf-8 -*-
"""
Генерация данных сайта для «Повелителя Небес» из novelfull.db.

Пишет:
  site/data/bth/index.json         — список переведённых глав [{n, title}]
  site/data/bth/chunk-XXXX.json    — контент главами по CHUNK_SIZE [{n, title, content:[]}]

Запуск:  python gen_btth.py
"""
import json
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "novelfull.db")
OUT = os.path.join(BASE, "site", "data", "bth")
SLUG = "battle-through-the-heavens"
CHUNK_SIZE = 25


def paras(text):
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return parts


def clean_title(t):
    t = (t or "").strip().strip('"«»“”').strip()
    t = re.sub(r'^(глава|chapter)\s*\d+[\s:.:–—-]*', '', t, flags=re.I)
    return t.strip(' .:–—-')


def main():
    os.makedirs(OUT, exist_ok=True)
    # чистим старые чанки, чтобы не осталось устаревших файлов
    for name in os.listdir(OUT):
        if name.startswith("chunk-") or name == "index.json":
            os.remove(os.path.join(OUT, name))
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT num, title, title_ru, content_ru FROM chapters "
        "WHERE slug=? AND content_ru IS NOT NULL AND content_ru != '' AND status='translated' "
        "ORDER BY num", (SLUG,)).fetchall()
    conn.close()

    index = []
    chunks = {}
    for num, title, title_ru, ru in rows:
        head = title_ru or clean_title(title)
        label = f"Глава {num}. {head}" if head else f"Глава {num}"
        index.append({"n": num, "title": label})
        chunk_no = (num - 1) // CHUNK_SIZE + 1
        chunks.setdefault(chunk_no, []).append({
            "n": num,
            "title": label,
            "content": paras(ru),
        })

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"chapters": index}, f, ensure_ascii=False, separators=(",", ":"))

    for chunk_no, items in chunks.items():
        name = f"chunk-{chunk_no:04d}.json"
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump({"chapters": items}, f, ensure_ascii=False, separators=(",", ":"))

    total = sum(len(v) for v in chunks.values())
    print(f"глав: {total}, чанков: {len(chunks)}, index: {len(index)}")


if __name__ == "__main__":
    main()
