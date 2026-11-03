#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пайплайн: syosetu (narou) → скачивание → перевод DeepSeek → сборка .fb2

Полный цикл одной командой:
    python novel_pipeline.py N1354HZ --lang ru

Что делает:
  1. Берёт метаданные новеллы через официальный narou API.
  2. Скачивает оглавление и текст всех глав с ncode.syosetu.com.
  3. Переводит каждую главу через DeepSeek API (глоссарий + контекст).
  4. Кэширует переводы (повторный запуск не переводит заново).
  5. Собирает валидный .fb2 (FictionBook 2.0).

Зависимости: requests (pip install requests)
API-ключ:   переменная окружения DEEPSEEK_API_KEY
"""

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import requests

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek-V3
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

USER_AGENT = "Mozilla/5.0 (compatible; NovelPipeline/1.0)"
NAROU_API = "https://api.syosetu.com/novelapi/api/"
NCODE_BASE = "https://ncode.syosetu.com/{ncode}/"

# Глава длиннее этой длины (в символах) будет разбита на куски для перевода.
CHUNK_SIZE = 4000

# Пауза между запросами к DeepSeek (снижает риск rate-limit).
REQUEST_DELAY = 0.5

# ---------------------------------------------------------------------------
# 1. Метаданные (narou API)
# ---------------------------------------------------------------------------


def fetch_metadata(ncode: str) -> dict:
    """Тянет метаданные новеллы из narou API."""
    url = f"{NAROU_API}?out=json&ncode={ncode}"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if len(data) < 2:
        raise RuntimeError(f"Новелла {ncode} не найдена в narou API")
    return data[1]


# ---------------------------------------------------------------------------
# 2. Оглавление и текст глав
# ---------------------------------------------------------------------------

def fetch_toc(ncode: str) -> list[dict]:
    """Возвращает список {index, subtitle} из страницы оглавления."""
    ncode_lower = ncode.lower()
    url = NCODE_BASE.format(ncode=ncode_lower)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    text = resp.text

    # Ссылки на главы вида /n1354hz/12/
    pattern = re.compile(
        rf'href="/{re.escape(ncode_lower)}/(\d+)/"[^>]*>(.*?)</a>', re.S
    )
    items = []
    for m in pattern.finditer(text):
        idx = int(m.group(1))
        subtitle = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        items.append({"index": idx, "subtitle": subtitle})
    # Убираем дубликаты, сортируем по номеру.
    seen = set()
    uniq = []
    for it in items:
        if it["index"] not in seen:
            seen.add(it["index"])
            uniq.append(it)
    uniq.sort(key=lambda x: x["index"])
    return uniq


def fetch_chapter(ncode: str, index: int) -> str:
    """Скачивает текст одной главы и возвращает его очищенным."""
    ncode_lower = ncode.lower()
    url = NCODE_BASE.format(ncode=ncode_lower) + f"{index}/"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    text = resp.text

    m = re.search(
        r'class="js-novel-text p-novel__text"[^>]*>(.*?)</div>', text, re.S
    )
    if not m:
        # Запасной вариант — общий контейнер.
        m = re.search(r'id="novel_honbun"[^>]*>(.*?)</div>', text, re.S)
    if not m:
        raise RuntimeError(f"Не найден текст главы {index} для {ncode}")

    body = m.group(1)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(r"</p>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", "", body)
    body = html_lib.unescape(body)
    body = body.replace("\u3000", " ")
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


# ---------------------------------------------------------------------------
# 3. Глоссарий
# ---------------------------------------------------------------------------

GLOSSARY_FILE = "glossary.json"


def load_glossary() -> dict:
    """Глоссарий имён/терминов: {оригинал: перевод}."""
    if os.path.exists(GLOSSARY_FILE):
        with open(GLOSSARY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def glossary_block(glossary: dict) -> str:
    if not glossary:
        return ""
    lines = ["СЛОВАРЬ (используй строго эти переводы имён и терминов):"]
    for src, dst in glossary.items():
        lines.append(f"- {src} → {dst}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Перевод (DeepSeek API)
# ---------------------------------------------------------------------------


def split_into_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Разбивает текст по абзацам на куски не длиннее size."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) + 1 > size and current:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n{p}" if current else p
    if current:
        chunks.append(current)
    return chunks


def translate_text(text: str, target_lang: str, glossary: dict,
                   title: str = "") -> str:
    """Переводит текст через DeepSeek. Тяжёлые главы режутся на куски."""
    gl = glossary_block(glossary)
    chunks = split_into_chunks(text)
    translated = []

    for i, chunk in enumerate(chunks):
        system = (
            "Ты — профессиональный литературный переводчик "
            "японских веб-новелл. Переводи на русский язык (или язык, "
            "указанный в задании) литературно, сохраняя стиль, тон, "
            "разбивку на абзацы и эмоции персонажей. Ничего не сокращай "
            "и не добавляй отсебятину. Имена и термины переводи строго "
            "по словарю, если он задан."
        )
        user_parts = [f"Название произведения: {title}"] if title else []
        if gl:
            user_parts.append(gl)
        user_parts.append(
            f"Переведи следующий текст на язык '{target_lang}'. "
            f"Выдай только перевод, без пояснений:\n\n{chunk}"
        )
        user = "\n\n".join(user_parts)

        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        for attempt in range(5):
            try:
                r = requests.post(
                    DEEPSEEK_API_URL, json=payload, headers=headers, timeout=120
                )
                if r.status_code == 429:
                    wait = 2 ** attempt * 5
                    print(f"    rate-limit, ждём {wait}s…")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                out = r.json()["choices"][0]["message"]["content"].strip()
                translated.append(out)
                break
            except Exception as e:
                if attempt == 4:
                    raise
                print(f"    ошибка: {e}, повтор…")
                time.sleep(3)
        time.sleep(REQUEST_DELAY)

    return "\n\n".join(translated)


# ---------------------------------------------------------------------------
# 5. Кэш переводов
# ---------------------------------------------------------------------------


def cache_path(ncode: str, target_lang: str) -> Path:
    return Path(f"cache_{ncode.lower()}_{target_lang}.json")


def load_cache(ncode: str, target_lang: str) -> dict:
    p = cache_path(ncode, target_lang)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(ncode: str, target_lang: str, cache: dict) -> None:
    with open(cache_path(ncode, target_lang), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 6. Сборка .fb2
# ---------------------------------------------------------------------------


def build_fb2(meta: dict, chapters: list[dict], target_lang: str,
              ncode: str, glossary: dict) -> str:
    title = meta.get("title", ncode)
    writer = meta.get("writer", "")
    story = meta.get("story", "")

    parts = []
    parts.append('<?xml version="1.0" encoding="utf-8"?>')
    parts.append(
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
        'xmlns:l="http://www.w3.org/1999/xlink">'
    )
    parts.append("<description><title-info>")
    parts.append("<genre>fiction</genre>")
    parts.append(
        f"<author><first-name>{escape(writer)}</first-name>"
        f"<last-name></last-name></author>"
    )
    parts.append(f"<book-title>{escape(title)}</book-title>")
    if story:
        parts.append(f"<annotation><p>{escape(story)}</p></annotation>")
    parts.append(f"<lang>{escape(target_lang)}</lang>")
    parts.append("<src-lang>ja</src-lang>")
    parts.append("</title-info><document-info>")
    parts.append(
        f"<program-used>AI translation (DeepSeek)</program-used>"
    )
    parts.append(f"<src-url>{escape(NCODE_BASE.format(ncode=ncode.lower()))}</src-url>")
    parts.append("</document-info></description>")
    parts.append("<body>")
    parts.append(f"<title><p>{escape(title)}</p></title>")

    for ch in chapters:
        parts.append("<section>")
        sub = ch.get("subtitle") or f"Глава {ch['index']}"
        parts.append(f"<title><p>{escape(sub)}</p></title>")
        for para in re.split(r"\n\s*\n", ch["translated"].strip()):
            para = para.strip()
            if para:
                parts.append(f"<p>{escape(para)}</p>")
        parts.append("</section>")

    parts.append("</body></FictionBook>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="syosetu → DeepSeek → fb2")
    parser.add_argument("ncode", help="Код новеллы, напр. N1354HZ")
    parser.add_argument("--lang", default="ru", help="Целевой язык (по умолч. ru)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Перевести только первые N глав (0 = все)")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Не качать заново, взять из кэша")
    args = parser.parse_args()

    if not DEEPSEEK_API_KEY:
        print("Ошибка: задайте DEEPSEEK_API_KEY в переменных окружения.")
        sys.exit(1)

    ncode = args.ncode.upper()
    glossary = load_glossary()

    print(f"[1/4] Метаданные {ncode}…")
    meta = fetch_metadata(ncode)
    title = meta.get("title", ncode)
    total = meta.get("general_all_no", 0)
    print(f"      «{title}» — {meta.get('writer','')} — глав: {total}, "
          f"символов: {meta.get('length', 0)}")

    print("[2/4] Оглавление…")
    toc = fetch_toc(ncode)
    if not toc:
        # Фолбэк: нумеруем главы от 1 до total.
        toc = [{"index": i, "subtitle": ""} for i in range(1, total + 1)]
    if args.limit:
        toc = toc[: args.limit]
    print(f"      глав к обработке: {len(toc)}")

    print("[3/4] Скачивание и перевод…")
    cache = load_cache(ncode, args.lang)
    chapters = []

    for i, item in enumerate(toc, 1):
        idx = item["index"]
        sub = item.get("subtitle") or f"Глава {idx}"
        key = str(idx)

        if key not in cache or not cache[key].get("translated"):
            raw = fetch_chapter(ncode, idx)
            print(f"  [{i}/{len(toc)}] гл.{idx} «{sub}» "
                  f"({len(raw)} симв.) — перевод…")
            tr = translate_text(raw, args.lang, glossary, title)
            cache[key] = {"subtitle": sub, "raw": raw, "translated": tr}
            save_cache(ncode, args.lang, cache)
        else:
            print(f"  [{i}/{len(toc)}] гл.{idx} «{sub}» — из кэша")

        chapters.append({
            "index": idx,
            "subtitle": sub,
            "translated": cache[key]["translated"],
        })

    print("[4/4] Сборка .fb2…")
    fb2 = build_fb2(meta, chapters, args.lang, ncode, glossary)
    out_name = f"{ncode.lower()}_{args.lang}.fb2"
    with open(out_name, "w", encoding="utf-8") as f:
        f.write(fb2)
    size = os.path.getsize(out_name)
    print(f"Готово: {out_name} ({size} байт)")


if __name__ == "__main__":
    main()
