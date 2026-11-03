# -*- coding: utf-8 -*-
"""
Оркестратор: краулинг → извлечение → сохранение в БД → очередь на перевод.

Примеры:

  # Собрать топ-10 новелл с syosetu и положить в БД
  python -m crawler.pipeline syosetu --catalog 10

  # Собрать одну конкретную новеллу
  python -m crawler.pipeline syosetu --ncode N1354HZ

  # Собрать новеллу с biquge / munpia по URL (через ИИ-извлечение)
  python -m crawler.pipeline biquge --url https://www.biquge.example/book/123/

  # Показать очередь глав на перевод
  python -m crawler.pipeline queue
"""

import argparse

from . import config
from . import crawler
from . import covers
from .db import DB


def save_novel(db: DB, novel: dict) -> int:
    """Сохраняет новеллу и её главы, возвращает id новеллы."""
    chapters = novel.pop("chapters", [])
    cover_url = novel.get("cover", "")

    # скачать обложку ДО сохранения, чтобы записать путь в БД
    cover_path = ""
    if cover_url:
        cover_name = f"{novel['source']}_{novel['source_id']}".lower()
        cover_path = covers.download_cover(cover_url, cover_name)
    if cover_path:
        novel["cover"] = cover_path

    novel_id = db.upsert_novel(novel)
    for ch in chapters:
        db.upsert_chapter(
            novel_id, ch["index"], ch.get("title", ""), ch.get("content", "")
        )
    print(f"  [OK] {novel['title'] or novel['source_id']}: {len(chapters)} глав"
          + (f", обложка {cover_path}" if cover_path else ""))
    return novel_id


def cmd_catalog(db: DB, source: str, limit: int):
    print(f"[каталог] {source}, топ-{limit}")
    if source == "syosetu":
        novels = crawler.syosetu_catalog(limit=limit)
    else:
        print(f"  для {source} каталога через API нет — задай --url конкретной книги")
        return
    for n in novels:
        # каталог даёт метаданные; главы скачаем отдельно по запросу
        db.upsert_novel(n)
        print(f"  [OK] {n['title']} ({n['chapters_count']} глав)")
    print(f"Итого в каталоге: {len(novels)}")


def cmd_novel(db: DB, source: str, ncode: str = None, url: str = None, gemini: bool = False):
    print(f"[новелла] {source}: {ncode or url}")
    if source == "syosetu" and ncode:
        novel = crawler.syosetu_novel(ncode)
    elif url:
        novel = crawler.html_novel(url, source, use_gemini=gemini)
    else:
        print("  укажи --ncode (для syosetu) или --url (для biquge/munpia)")
        return
    save_novel(db, novel)


def cmd_queue(db: DB, limit: int = 100):
    rows = db.pending_chapters(limit)
    print(f"Глав в очереди на перевод: {len(rows)}")
    for r in rows[:20]:
        print(f"  #{r['id']} гл.{r['idx']} «{r['title'][:30]}» ({r['status']})")


def main():
    p = argparse.ArgumentParser(description="Краулер + ИИ-извлечение новелл")
    p.add_argument("command", choices=["syosetu", "biquge", "munpia", "queue"])
    p.add_argument("--catalog", type=int, default=0, help="собрать топ-N из каталога")
    p.add_argument("--ncode", help="код новеллы syosetu (напр. N1354HZ)")
    p.add_argument("--url", help="URL книги (biquge/munpia)")
    p.add_argument("--gemini", action="store_true", help="извлекать через Gemini (vision)")
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args()

    db = DB()

    if args.command == "queue":
        cmd_queue(db, args.limit)
    elif args.command == "syosetu":
        if args.catalog:
            cmd_catalog(db, "syosetu", args.catalog)
        elif args.ncode:
            cmd_novel(db, "syosetu", ncode=args.ncode)
        else:
            print("укажи --catalog N или --ncode X")
    elif args.command in ("biquge", "munpia"):
        cmd_novel(db, args.command, url=args.url, gemini=args.gemini)

    db.close()


if __name__ == "__main__":
    main()
