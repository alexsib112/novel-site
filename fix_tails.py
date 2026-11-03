# -*- coding: utf-8 -*-
"""Починка хвостов глав: английские абзацы в конце, служебные строки, потерянная концовка.

  python fix_tails.py 145 215 931
"""
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import novelfull_pipeline as P

BASE = os.path.dirname(os.path.abspath(__file__))
SLUG = "battle-through-the-heavens"

SYS = (
    "Ты литературный переводчик китайских сянься-романов. Переведи абзац с английского "
    "на русский, литературно и точно. Выдай ТОЛЬКО перевод, без пояснений и кавычек.\n\n"
    "Глоссарий (EN — RU):\n" + P.GLOSSARY
)


def paras(t):
    return [p.strip() for p in re.split(r"\n\s*\n", (t or "").strip()) if p.strip()]


def latin_ratio(s):
    return len(re.findall(r"[A-Za-z]", s)) / max(1, len(s))


def translate_para(en):
    key = P.get_api_key()
    for attempt in range(6):
        try:
            r = requests.post(P.QWEN_URL,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": P.MODEL, "temperature": 0.3, "max_tokens": 800,
                      "messages": [{"role": "system", "content": SYS},
                                   {"role": "user", "content": en}]},
                timeout=180)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            time.sleep(10 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return ""


def main():
    nums = [int(x) for x in sys.argv[1:] if x.isdigit()]
    if not nums:
        print("укажите номера глав")
        return
    conn = P.db()
    for num in nums:
        en, ru = conn.execute(
            "SELECT content_en, content_ru FROM chapters WHERE slug=? AND num=?", (SLUG, num)).fetchone()
        pe, pr = paras(en), paras(ru)
        changed = False
        # 1. служебные строки в конце
        while pr and re.fullmatch(r"(глава|chapter)\s*\d+[.:!]?", pr[-1].strip(), re.I):
            pr.pop()
            changed = True
        # 2. английские абзацы в конце
        removed_en = False
        while len(pr) > 1 and len(pr[-1]) > 60 and latin_ratio(pr[-1]) > 0.5:
            pr.pop()
            removed_en = True
            changed = True
        # 3. если выкинули выдуманный английский хвост — возвращаем настоящую концовку
        if removed_en and pe:
            add = translate_para(pe[-1])
            if add:
                pr.append(add)
                print(f"  глава {num}: дописан финальный абзац")
        if changed:
            conn.execute("UPDATE chapters SET content_ru=? WHERE slug=? AND num=?",
                         ("\n\n".join(pr), SLUG, num))
            conn.commit()
            print(f"глава {num}: исправлена ({len(pr)} абзацев)")
        else:
            print(f"глава {num}: без изменений")
    conn.close()


if __name__ == "__main__":
    main()
