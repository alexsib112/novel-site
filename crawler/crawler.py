# -*- coding: utf-8 -*-
"""
Краулеры источников новелл: syosetu (JP), biquge (CN), munpia (KR).

- syosetu: у него есть официальный narou API — метаданные и текст берём
  напрямую БЕЗ ИИ (быстро и бесплатно). Селекторы известны.
- biquge / munpia: статический HTML без публичного API — скачиваем страницы,
  а структуру из «грязного» HTML извлекает ИИ (см. llm_extract.py).
"""

import re
import time
import html as html_lib

import requests

from . import config
from . import llm_extract


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch(url: str) -> str:
    """GET-запрос с вежливой паузой, возвращает HTML-строку."""
    time.sleep(config.CRAWL_DELAY)
    r = requests.get(
        url,
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _clean_html(html_fragment: str) -> str:
    """Убирает теги из фрагмента HTML, оставляя текст с переносами."""
    text = re.sub(r"<br\s*/?>", "\n", html_fragment, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# SYOSETU (JP) — narou API + прямые селекторы, без ИИ
# ---------------------------------------------------------------------------

NAROU_API = "https://api.syosetu.com/novelapi/api/"
NCODE_BASE = "https://ncode.syosetu.com/{ncode}/"


def syosetu_catalog(limit: int = 20, order: str = "hyoka") -> list[dict]:
    """Список популярных завершённых новелл через narou API."""
    items = []
    for st in range(1, limit + 500, 500):
        if len(items) >= limit:
            break
        url = f"{NAROU_API}?out=json&order={order}&end=1&lim=500&st={st}"
        data = requests.get(
            url, headers={"User-Agent": config.USER_AGENT}, timeout=30
        ).json()
        for it in data[1:]:
            items.append(
                {
                    "source": "syosetu",
                    "source_id": it["ncode"],
                    "title": it.get("title"),
                    "title_orig": it.get("title"),
                    "author": it.get("writer"),
                    "synopsis": it.get("story"),
                    "lang": "jp",
                    "status": "completed" if it.get("end") == 1 else "ongoing",
                    "url": NCODE_BASE.format(ncode=it["ncode"].lower()),
                    "chapters_count": it.get("general_all_no", 0),
                }
            )
            if len(items) >= limit:
                break
    return items


def syosetu_novel(ncode: str) -> dict:
    """Скачивает новеллу целиком: метаданные + все главы (прямой парсинг)."""
    ncode_low = ncode.lower()
    # метаданные
    meta = requests.get(
        f"{NAROU_API}?out=json&ncode={ncode}",
        headers={"User-Agent": config.USER_AGENT},
        timeout=30,
    ).json()[1]

    # список глав
    toc_html = fetch(NCODE_BASE.format(ncode=ncode_low))
    # обложка — og:image на странице новеллы
    cover_url = ""
    m_og = re.search(r'property="og:image" content="([^"]+)"', toc_html)
    if m_og:
        cover_url = m_og.group(1)

    chapters = []
    seen = set()
    for m in re.finditer(
        rf'href="/{re.escape(ncode_low)}/(\d+)/"[^>]*>(.*?)</a>', toc_html, re.S
    ):
        idx = int(m.group(1))
        if idx in seen:
            continue
        seen.add(idx)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        chapters.append({"index": idx, "title": title, "url": f"{NCODE_BASE.format(ncode=ncode_low)}{idx}/"})

    # скачиваем текст каждой главы
    result_chapters = []
    for ch in chapters:
        html = fetch(ch["url"])
        m = re.search(
            r'class="(?:js-novel-text p-novel__text|p-novel__body)"[^>]*>(.*?)</div>',
            html, re.S,
        )
        content = _clean_html(m.group(1)) if m else ""
        result_chapters.append(
            {"index": ch["index"], "title": ch["title"], "content": content}
        )

    return {
        "source": "syosetu",
        "source_id": ncode,
        "title": meta.get("title"),
        "title_orig": meta.get("title"),
        "author": meta.get("writer"),
        "synopsis": meta.get("story"),
        "lang": "jp",
        "status": "completed" if meta.get("end") == 1 else "ongoing",
        "url": NCODE_BASE.format(ncode=ncode_low),
        "cover": cover_url,
        "chapters_count": len(result_chapters),
        "chapters": result_chapters,
    }


# ---------------------------------------------------------------------------
# BIQUGE (CN) / MUNPIA (KR) — HTML + ИИ-извлечение
# ---------------------------------------------------------------------------

def html_novel(url: str, source: str, use_gemini: bool = False) -> dict:
    """
    Универсальный путь для сайтов без API (biquge, munpia):
    скачиваем страницу книги, ИИ извлекает структуру (название, главы, текст).

    Для экономии: сначала ИИ разбирает ОГЛАВЛЕНИЕ (получает список ссылок на
    главы), затем по каждой ссылке ИИ извлекает текст главы.
    """
    name = config.SOURCES[source]["name"]
    toc_html = fetch(url)

    # обложка — og:image или первый <img> обложки
    cover_url = ""
    m_og = re.search(r'property="og:image" content="([^"]+)"', toc_html)
    if m_og:
        cover_url = m_og.group(1)
    else:
        m_img = re.search(r'<img[^>]+src="([^"]+)"[^>]*>', toc_html)
        if m_img:
            cover_url = m_img.group(1)

    # ИИ разбирает оглавление → метаданные + список ссылок на главы
    toc = llm_extract.extract(toc_html, name, mode="toc", use_gemini=use_gemini)

    chapters = []
    for ch in toc.get("chapters", []):
        ch_url = ch.get("url") or ch.get("href")
        if not ch_url:
            continue
        if not ch_url.startswith("http"):
            # относительная ссылка → склеить с базовым URL
            from urllib.parse import urljoin
            ch_url = urljoin(url, ch_url)
        ch_html = fetch(ch_url)
        # ИИ извлекает текст конкретной главы
        full = llm_extract.extract(ch_html, name, mode="chapter", use_gemini=use_gemini)
        chapters.append(
            {
                "index": ch.get("index", len(chapters) + 1),
                "title": full.get("title") or ch.get("title", ""),
                "content": full.get("content", ""),
            }
        )

    return {
        "source": source,
        "source_id": url,
        "title": toc.get("title"),
        "title_orig": toc.get("title_orig") or toc.get("title"),
        "author": toc.get("author"),
        "synopsis": toc.get("synopsis"),
        "lang": config.SOURCES[source]["lang"],
        "status": toc.get("status", ""),
        "url": url,
        "cover": cover_url,
        "chapters_count": len(chapters),
        "chapters": chapters,
    }


def biquge_novel(url: str, use_gemini: bool = False) -> dict:
    return html_novel(url, "biquge", use_gemini=use_gemini)


def munpia_novel(url: str, use_gemini: bool = False) -> dict:
    return html_novel(url, "munpia", use_gemini=use_gemini)
