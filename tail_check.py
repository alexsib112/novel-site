# -*- coding: utf-8 -*-
"""Проверка: заканчивается ли перевод там же, где оригинал.

Сравнивает последний абзац оригинала и перевода через модель (дёшево, короткий ответ).

  python tail_check.py            # все главы
  python tail_check.py --sample 40
  python tail_check.py --sample 40 --seed 7
"""
import json
import os
import random
import re
import sqlite3
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from novelfull_pipeline import DB, MODEL, QWEN_URL, get_api_key

SLUG = "battle-through-the-heavens"
BASE = os.path.dirname(os.path.abspath(__file__))

SYS = (
    "Ты редактор литературного перевода. Сравни последний абзац оригинала (английский) "
    "и последний абзац перевода (русский). Ответь ОДНИМ словом:\n"
    "MATCH — перевод заканчивается тем же местом, что и оригинал;\n"
    "EXTRA — в переводе после конца оригинала есть лишний текст;\n"
    "MISSING — перевод обрывается раньше конца оригинала.\n"
    "Никаких пояснений."
)


def paras(t):
    return [p.strip() for p in re.split(r"\n\s*\n", (t or "").strip()) if p.strip()]


def ask(en_tail, ru_tail):
    key = get_api_key()
    for attempt in range(4):
        try:
            r = requests.post(QWEN_URL,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": MODEL, "temperature": 0.0, "max_tokens": 8,
                      "messages": [{"role": "system", "content": SYS},
                                   {"role": "user", "content":
                                    f"ОРИГИНАЛ (последний абзац):\n{en_tail}\n\n"
                                    f"ПЕРЕВОД (последний абзац):\n{ru_tail}"}]},
                timeout=120)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip().upper()[:10]
            time.sleep(5 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return "ERROR"


def main():
    sample = None
    seed = 1
    if "--sample" in sys.argv:
        sample = int(sys.argv[sys.argv.index("--sample") + 1])
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])

    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT num, content_en, content_ru FROM chapters WHERE slug=? AND status='translated' "
        "ORDER BY num", (SLUG,)).fetchall()
    conn.close()

    if sample:
        random.seed(seed)
        rows = random.sample(rows, min(sample, len(rows)))

    bad, counts = [], {}
    lock = threading.Lock()

    def work(row):
        num, en, ru = row
        pe, pr = paras(en), paras(ru)
        if not pe or not pr:
            return num, "EMPTY"
        verdict = ask(pe[-1][:700], pr[-1][:700])
        return num, verdict

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(work, r) for r in rows]
        for f in as_completed(futs):
            num, verdict = f.result()
            with lock:
                counts[verdict] = counts.get(verdict, 0) + 1
                if verdict in ("EXTRA", "MISSING", "EMPTY", "ERROR"):
                    bad.append((num, verdict))

    bad.sort()
    with open(os.path.join(BASE, "tail_check.json"), "w", encoding="utf-8") as f:
        json.dump({"checked": len(rows), "counts": counts, "bad": bad}, f,
                  ensure_ascii=False, indent=2)
    print("проверено:", len(rows), counts)
    print("проблемных:", len(bad))
    print(bad[:20])


if __name__ == "__main__":
    main()
