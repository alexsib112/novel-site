# -*- coding: utf-8 -*-
"""Замена китайских вставок в русском тексте на русские эквиваленты.

Правит только абзацы, содержащие иероглифы: просит модель переписать абзац,
заменив китайские слова русскими, не меняя остальное.

  python cjk_fix.py            # исправить
  python cjk_fix.py --dry      # только посчитать
"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import novelfull_pipeline as P

BASE = os.path.dirname(os.path.abspath(__file__))
SLUG = "battle-through-the-heavens"
DRY = "--dry" in sys.argv

CJK = re.compile(r"[\u4e00-\u9fff]+")

SYS = (
    "Задача: убрать из русского абзаца китайские иероглифы.\n"
    "Правила:\n"
    "1. Иероглифы 炼制 означают «приготовление/плавка пилюль, алхимия». Замени их русским словом "
    "в нужной падежной форме (приготовление, приготовления, приготовлением, плавка и т.п.).\n"
    "2. Иероглифы 面对 означают «перед лицом / сталкиваясь с»; 某种 — «некое, какое-то»; "
    "凭借 — «благодаря, за счёт»; 松散 — «рыхлый, свободный»; 清醒 — «трезвый, ясный»; "
    "底线 — «предел, граница»; 纠缠 — «тянуть, зацикливаться»; 加上 — «вместе с, плюс»; "
    "无奈 — «беспомощно»; 看似 — «казалось бы».\n"
    "3. Другие иероглифы замени точным русским словом по смыслу.\n"
    "4. Остальной текст не меняй: ни одного лишнего слова, ни сокращений, ни перестановок.\n"
    "5. В ответе не должно остаться ни одного иероглифа.\n"
    "Выдай только исправленный абзац."
)


def translate_para(text):
    key = P.get_api_key()
    for attempt in range(5):
        try:
            r = requests.post(P.QWEN_URL,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": P.MODEL, "temperature": 0.2, "max_tokens": 2000,
                      "messages": [{"role": "system", "content": SYS},
                                   {"role": "user", "content": text}]},
                timeout=180)
            if r.status_code == 200:
                out = r.json()["choices"][0]["message"]["content"].strip()
                return out
            time.sleep(8 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def main():
    conn = sqlite3.connect(P.DB)
    rows = conn.execute(
        "SELECT num, content_ru FROM chapters WHERE slug=? AND status='translated'",
        (SLUG,)).fetchall()

    jobs = []
    for num, ru in rows:
        if not CJK.search(ru or ""):
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", ru) if p.strip()]
        for i, p in enumerate(paragraphs):
            if CJK.search(p):
                jobs.append((num, i, p))

    print(f"глав: {sum(1 for n, _ in rows if False) or len({j[0] for j in jobs})}, абзацев: {len(jobs)}")
    if DRY or not jobs:
        return

    lock = threading.Lock()
    results = {}
    done = [0]

    def work(job):
        num, idx, text = job
        out = translate_para(text)
        if out is None:
            return num, idx, None
        out = out.strip().strip('"«»').strip()
        if CJK.search(out) or not (0.6 * len(text) <= len(out) <= 1.6 * len(text)):
            return num, idx, None
        return num, idx, out

    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(work, j) for j in jobs]
        for f in as_completed(futs):
            num, idx, out = f.result()
            with lock:
                done[0] += 1
                if out:
                    results.setdefault(num, {})[idx] = out
                if done[0] % 25 == 0:
                    print(f"  {done[0]}/{len(jobs)}")

    fixed = 0
    for num, replacements in results.items():
        ru = conn.execute("SELECT content_ru FROM chapters WHERE slug=? AND num=?", (SLUG, num)).fetchone()[0]
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", ru) if p.strip()]
        for idx, new_p in replacements.items():
            if idx < len(paragraphs):
                paragraphs[idx] = new_p
        conn.execute("UPDATE chapters SET content_ru=? WHERE slug=? AND num=?",
                     ("\n\n".join(paragraphs), SLUG, num))
        fixed += 1
    conn.commit()
    conn.close()
    print(f"глав исправлено: {fixed}, абзацев заменено: {sum(len(v) for v in results.values())}")
    with open(os.path.join(BASE, "cjk_fix_report.json"), "w", encoding="utf-8") as f:
        json.dump({"jobs": len(jobs), "fixed_chapters": fixed}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
