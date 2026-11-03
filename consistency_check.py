# -*- coding: utf-8 -*-
"""Проверка единообразия имён и терминов по переведённому корпусу."""
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
conn = sqlite3.connect(os.path.join(BASE, "novelfull.db"))
rows = conn.execute(
    "SELECT num, content_ru FROM chapters WHERE slug='battle-through-the-heavens' "
    "AND status='translated'").fetchall()
conn.close()

VARIANTS = {
    "Сяо Янь (верно)": r"Сяо Янь",
    "Сяо Ян (без ь)": r"Сяо Ян(?!ь)",
    "Яо Лао (верно)": r"Яо Лао",
    "Йао Лао": r"Йао Лао",
    "Налань Яньжань": r"Налань Яньжань",
    "Налань Янжань": r"Налань Янжань",
    "доуци": r"\bдоуци\b",
    "Доу Ци": r"Доу Ци",
    "доучжэ": r"\bдоучжэ\b",
    "Дочжэ": r"\bДочжэ\b",
    "Академия Цзянань": r"Академия Цзянань",
    "Академия Цзя Нань": r"Академия Цзя Нань",
    "секта Юньлань": r"секта Юньлань",
    "Юнь Лань": r"Юнь Лань",
    "Небесное Пламя": r"Небесное Пламя",
    "Небесное пламя": r"Небесное пламя",
    "Сюнь'эр": r"Сюнь'эр",
    "Сюнь Эр": r"Сюнь Эр",
    "Я Фэй": r"Я Фэй",
    "Я Фей": r"Я Фей",
}

counts = {}
for label, pat in VARIANTS.items():
    rx = re.compile(pat)
    n = sum(len(rx.findall(ru or "")) for _num, ru in rows)
    counts[label] = n

for k, v in counts.items():
    print(f"{k:26} {v}")
