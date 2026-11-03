# -*- coding: utf-8 -*-
"""Репарация глав, где перевод не совпадает по концовке с оригиналом.

  python repair_tail.py 1043 1086
  python repair_tail.py --all      # взять все EXTRA/MISSING из tail_check.json
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import novelfull_pipeline as P
from tail_check import ask, paras

BASE = os.path.dirname(os.path.abspath(__file__))
SLUG = "battle-through-the-heavens"

BASE_SYS = P.TRANSLATE_SYS


def main():
    if "--all" in sys.argv:
        with open(os.path.join(BASE, "tail_check.json"), encoding="utf-8") as f:
            nums = [n for n, v in json.load(f)["bad"]]
    else:
        nums = [int(x) for x in sys.argv[1:] if x.isdigit()]
    if not nums:
        print("укажите номера глав или --all")
        return

    conn = P.db()
    ok, failed = [], []
    for num in nums:
        row = conn.execute("SELECT title, content_en FROM chapters WHERE slug=? AND num=?",
                           (SLUG, num)).fetchone()
        if not row:
            continue
        title, en = row
        pe = paras(en)
        last_en = pe[-1] if pe else ""
        print(f"глава {num} (…{last_en[-60:]})")
        done = False
        for attempt in range(3):
            P.TRANSLATE_SYS = (
                BASE_SYS
                + "\n\nВАЖНО: последний абзац оригинала — «" + last_en + "». "
                "Твой перевод обязан закончиться точным переводом именно этого абзаца. "
                "Не добавляй после него ни одного слова: ни вывода, ни морали, ни описания будущего."
            )
            t_ru, body = P.translate_chapter(num, title, en)
            pb = paras(body)
            verdict = ask(last_en[:700], (pb[-1] if pb else "")[:700])
            if verdict == "MATCH":
                conn.execute(
                    "UPDATE chapters SET content_ru=?, title_ru=?, status='translated' "
                    "WHERE slug=? AND num=?", (body, t_ru, SLUG, num))
                conn.commit()
                print(f"  ok (попытка {attempt + 1})")
                ok.append(num)
                done = True
                break
            print(f"  попытка {attempt + 1}: {verdict}")
        if not done:
            failed.append(num)
        P.TRANSLATE_SYS = BASE_SYS
    conn.close()
    print(f"\nисправлено: {len(ok)}, не удалось: {len(failed)} {failed}")


if __name__ == "__main__":
    main()
