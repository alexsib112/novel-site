# -*- coding: utf-8 -*-
"""Нормализация имён и терминов в переведённом корпусе.

Правит content_ru и title_ru. Идемпотентно. Запускать после перевода,
до gen_btth.py / fb2.

  python normalize_terms.py --dry   # только посчитать
"""
import os
import re
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "novelfull.db")
SLUG = "battle-through-the-heavens"
DRY = "--dry" in sys.argv

RULES = [
    # падежи «Сяо Ян» → «Сяо Янь»
    ("Сяо Яна", "Сяо Яня"),
    ("Сяо Яну", "Сяо Яню"),
    ("Сяо Яном", "Сяо Янем"),
    # именительный «Сяо Ян» (не «Янь» и не падежная форма)
    (r"Сяо Ян(?![а-яА-ЯёЁь])", "Сяо Янь"),
    # доуци
    ("Доу Ци", "Доуци"),
    ("доу Ци", "доуци"),
    # Сюнь'эр
    ("Сюнь Эр", "Сюнь'эр"),
    (r"Сюньэр", "Сюнь'эр"),
    # Академия Цзянань
    ("Цзя Нань", "Цзянань"),
]


def apply_rules(text):
    total = 0
    for pat, repl in RULES:
        if pat.startswith("Сяо Ян(") or pat.startswith("Сюньэр"):
            text, n = re.subn(pat, repl, text)
        else:
            n = text.count(pat)
            text = text.replace(pat, repl)
        total += n
    return text, total


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT num, content_ru, title_ru FROM chapters WHERE slug=? AND status='translated'",
        (SLUG,)).fetchall()

    changed = []
    for num, ru, tru in rows:
        new_ru, n1 = apply_rules(ru or "")
        new_tru, n2 = apply_rules(tru or "")
        if n1 or n2:
            changed.append((num, n1 + n2))
            if not DRY:
                conn.execute(
                    "UPDATE chapters SET content_ru=?, title_ru=? WHERE slug=? AND num=?",
                    (new_ru, new_tru, SLUG, num))

    if not DRY:
        conn.commit()
    conn.close()

    total = sum(n for _num, n in changed)
    print(f"глав изменено: {len(changed)}, замен: {total}")
    for num, n in changed[:10]:
        print(f"  глава {num}: {n}")
    if DRY:
        print("(dry-run: ничего не записано)")


if __name__ == "__main__":
    main()
