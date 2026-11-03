# -*- coding: utf-8 -*-
"""
Починка русских заголовков глав «Повелителя Небес».

Случаи:
  1) title_ru IS NULL  — старые главы (перевод до появления заголовков):
     переводим английский title через API.
  2) title_ru = 'Глава N' — модель не отделила заголовок разделителем:
     берём первый абзац перевода как заголовок и убираем его из текста.

Скрипт идемпотентен: можно запускать повторно.

  python repair_titles.py            # починить
  python repair_titles.py --dry      # только отчёт
"""
import json
import os
import re
import sqlite3
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from novelfull_pipeline import DB, MODEL, QWEN_URL, get_api_key, looks_like_title, clean_title

SLUG = "battle-through-the-heavens"
DRY = "--dry" in sys.argv

import time

TITLE_SYS = (
    "Ты переводчик китайских сянься-романов. Переведи название главы на русский, "
    "используя термины из глоссария. Убери «Chapter N» и номер. "
    "Выдай только перевод, без кавычек и пояснений.\n\nГлоссарий:\n{glossary}"
)


def translate_title(en_title):
    from novelfull_pipeline import GLOSSARY
    key = get_api_key()
    sys_prompt = TITLE_SYS.format(glossary=GLOSSARY)
    for attempt in range(6):
        try:
            r = requests.post(QWEN_URL,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": MODEL, "temperature": 0.2,
                      "messages": [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": en_title}],
                      "max_tokens": 200},
                timeout=120)
            if r.status_code == 200:
                t = r.json()["choices"][0]["message"]["content"].strip()
                return clean_title(t.splitlines()[0]) if t else None
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            time.sleep(3)
        except Exception:
            time.sleep(5)
    return None


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT num, title, title_ru, content_ru FROM chapters "
        "WHERE slug=? AND status='translated' AND (title_ru IS NULL OR title_ru = 'Глава ' || num) "
        "ORDER BY num", (SLUG,)).fetchall()

    fixed_body, fixed_api, review = [], [], []
    for num, en_title, title_ru, body in rows:
        body = body or ""
        parts = re.split(r"\n\s*\n", body.strip(), 1)
        first = parts[0].strip() if parts else ""

        if title_ru is None:
            # старый перевод: заголовка в тексте нет — переводим английский
            t = translate_title(en_title or f"Chapter {num}")
            if t:
                fixed_api.append((num, t))
                if not DRY:
                    conn.execute("UPDATE chapters SET title_ru=? WHERE slug=? AND num=?", (t, SLUG, num))
                    conn.commit()
            else:
                review.append((num, en_title, "не удалось перевести заголовок"))
            continue

        # title_ru == 'Глава N' → заголовок оказался первым абзацем текста
        if len(parts) > 1 and looks_like_title(first):
            t = clean_title(first)
            new_body = parts[1].strip()
            fixed_body.append((num, t))
            if not DRY:
                conn.execute("UPDATE chapters SET title_ru=?, content_ru=? WHERE slug=? AND num=?",
                             (t, new_body, SLUG, num))
                conn.commit()
        else:
            t = translate_title(en_title or f"Chapter {num}")
            if t:
                fixed_api.append((num, t))
                if not DRY:
                    conn.execute("UPDATE chapters SET title_ru=? WHERE slug=? AND num=?", (t, SLUG, num))
                    conn.commit()
            else:
                review.append((num, en_title, "заголовок не распознан: " + first[:80]))

    conn.close()
    print(f"заголовок взят из текста: {len(fixed_body)}")
    print(f"заголовок переведён через API: {len(fixed_api)}")
    print(f"требуют проверки: {len(review)}")
    with open("repair_report.json", "w", encoding="utf-8") as f:
        json.dump({"from_body": fixed_body, "from_api": fixed_api, "review": review},
                  f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
