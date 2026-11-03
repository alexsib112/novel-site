# -*- coding: utf-8 -*-
"""
Слой хранения: SQLite (по умолчанию) или PostgreSQL.

Таблицы:
  novels   — карточка новеллы (нормализованная структура).
  chapters — главы (сырой текст на языке оригинала + перевод).
"""

import sqlite3
import os

from . import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS novels (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,           -- syosetu / biquge / munpia
    source_id      TEXT NOT NULL,           -- ncode или URL-идентификатор
    title          TEXT,
    title_orig     TEXT,
    author         TEXT,
    synopsis       TEXT,
    lang           TEXT,                    -- jp / cn / kr
    status         TEXT,                    -- ongoing / completed
    url            TEXT,
    cover          TEXT,                    -- относительный путь обложки (covers/xxx.jpg)
    chapters_count INTEGER DEFAULT 0,
    created_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS chapters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id   INTEGER NOT NULL,
    idx        INTEGER NOT NULL,            -- номер главы
    title      TEXT,
    content    TEXT,                        -- сырой текст (оригинал)
    translated TEXT,                        -- перевод (заполняет конвейер перевода)
    translator TEXT,                        -- какая модель перевела (qwen/gemini/...)
    status     TEXT DEFAULT 'pending',      -- pending / translating / done / failed
    UNIQUE(novel_id, idx),
    FOREIGN KEY(novel_id) REFERENCES novels(id)
);

CREATE INDEX IF NOT EXISTS idx_chapters_status ON chapters(status);
"""


class DB:
    def __init__(self, path=None):
        self.path = path or config.DB_PATH
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # миграция: добавить колонку translator, если её ещё нет
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(chapters)")]
        if "translator" not in cols:
            self.conn.execute("ALTER TABLE chapters ADD COLUMN translator TEXT")
        # миграция: добавить колонку cover, если её ещё нет
        ncols = [r[1] for r in self.conn.execute("PRAGMA table_info(novels)")]
        if "cover" not in ncols:
            self.conn.execute("ALTER TABLE novels ADD COLUMN cover TEXT")
        self.conn.commit()

    # --- novels ---
    def upsert_novel(self, n: dict) -> int:
        """Вставляет/обновляет новеллу, возвращает её id."""
        cur = self.conn.execute(
            """INSERT INTO novels
               (source, source_id, title, title_orig, author, synopsis,
                lang, status, url, cover, chapters_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source, source_id) DO UPDATE SET
                 title=excluded.title,
                 title_orig=excluded.title_orig,
                 author=excluded.author,
                 synopsis=excluded.synopsis,
                 lang=excluded.lang,
                 status=excluded.status,
                 url=excluded.url,
                 cover=excluded.cover,
                 chapters_count=excluded.chapters_count""",
            (
                n["source"], n["source_id"], n.get("title"), n.get("title_orig"),
                n.get("author"), n.get("synopsis"), n.get("lang"),
                n.get("status"), n.get("url"), n.get("cover"),
                n.get("chapters_count", 0),
            ),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT id FROM novels WHERE source=? AND source_id=?",
            (n["source"], n["source_id"]),
        ).fetchone()["id"]

    def get_novel(self, source, source_id):
        return self.conn.execute(
            "SELECT * FROM novels WHERE source=? AND source_id=?",
            (source, source_id),
        ).fetchone()

    # --- chapters ---
    def upsert_chapter(self, novel_id: int, idx: int, title: str, content: str):
        self.conn.execute(
            """INSERT INTO chapters (novel_id, idx, title, content, status)
               VALUES (?,?,?,?, 'pending')
               ON CONFLICT(novel_id, idx) DO UPDATE SET
                 title=excluded.title, content=excluded.content""",
            (novel_id, idx, title, content),
        )
        self.conn.commit()

    def pending_chapters(self, limit=100):
        """Главы, ожидающие перевода (для конвейера перевода)."""
        return self.conn.execute(
            "SELECT * FROM chapters WHERE status='pending' ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()

    def set_chapter_status(self, chapter_id: int, status: str):
        self.conn.execute(
            "UPDATE chapters SET status=? WHERE id=?", (status, chapter_id)
        )
        self.conn.commit()

    def set_chapter_translated(self, chapter_id: int, text: str, translator: str = None):
        self.conn.execute(
            "UPDATE chapters SET translated=?, translator=?, status='done' WHERE id=?",
            (text, translator, chapter_id),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
