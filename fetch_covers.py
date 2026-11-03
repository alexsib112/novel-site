# -*- coding: utf-8 -*-
"""Скачивает обложки для новелл из БД и обновляет поле novels.cover."""
import sqlite3
import re
import requests

from crawler import covers, config
from crawler.db import DB  # DB() выполнит миграцию (добавит колонку cover)

db = DB()
conn = db.conn

for nrow in conn.execute("SELECT * FROM novels WHERE source='syosetu'").fetchall():
    source_id = nrow["source_id"]
    ncode_low = source_id.lower()
    # стандартная обложка syosetu — og:image / sbo.syosetu.com/{ncode}/twitter.png
    cover_url = f"https://sbo.syosetu.com/{ncode_low}/twitter.png"
    name = f"syosetu_{source_id}".lower()
    rel = covers.download_cover(cover_url, name)
    if rel:
        conn.execute("UPDATE novels SET cover=? WHERE id=?", (rel, nrow["id"]))
        print(f"{source_id}: обложка -> {rel}")
    else:
        print(f"{source_id}: обложка НЕ скачана")

conn.commit()
db.close()
