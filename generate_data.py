# -*- coding: utf-8 -*-
"""
Генерация js/data.js для сайта из БД (novels.db).

Берёт 2 книги с переведёнными главами и формирует данные для читалки.
"""
import json
import sqlite3

# Ручные метаданные (русские названия/авторы/синопсисы)
META = {
    "N1354HZ": {
        "title": "Я уже привыкла быть одна",
        "author": "Арасэ Яхиро",
        "genres": ["Романтика", "Комедия", "Драма"],
        "status": "Завершено",
        "rating": 9.2, "likes": 55329,
        "gradient": "linear-gradient(150deg, #ff9a9e 0%, #fecfef 55%, #c471f5 100%)",
        "letter": "ニ",
        "synopsis": "Жених Николь всегда находится подле принцессы Каролайн, своей подруги детства. Из-за постоянного пренебрежения Николь решает: «Ведь можно ходить и одной». Перестав чего-либо ждать от жениха, она погружается в уютную жизнь одиночки — и лишь тогда Кейос осознаёт, что теряет её.",
    },
    "N2710DB": {
        "title": "Умелый повар из другого мира",
        "author": "Эгути Рэн",
        "genres": ["Исекай", "Фэнтези", "Кулинария"],
        "status": "Продолжается",
        "rating": 9.6, "likes": 275265,
        "gradient": "linear-gradient(150deg, #f6d365 0%, #fda085 60%, #f6416c 120%)",
        "letter": "と",
        "synopsis": "Обычного японца призывают в другой мир, но вместо боевых навыков ему достаётся лишь «Интернет-супермаркет». Зато питомец, которого он случайно приручил, оказывается сильнейшим существом на свете. История о спокойных странствиях, готовке и о том, как из еды рождается магия.",
    },
}

def split_paras(text):
    """Разбить переведённый текст на абзацы."""
    parts = [p.strip() for p in (text or "").split("\n") if p.strip()]
    # склеить пустые строки: \n\n означает абзац
    return parts

def main():
    conn = sqlite3.connect("novels.db")
    conn.row_factory = sqlite3.Row

    novels = []
    for source_id in ["N1354HZ", "N2710DB"]:
        nrow = conn.execute(
            "SELECT * FROM novels WHERE source_id=?", (source_id,)
        ).fetchone()
        if not nrow:
            continue
        meta = META[source_id]
        chapters = []
        for c in conn.execute(
            "SELECT idx, title, translated, translator FROM chapters WHERE novel_id=? AND status='done' ORDER BY idx",
            (nrow["id"],),
        ):
            paras = split_paras(c["translated"])
            chapters.append({
                "n": c["idx"],
                "title": f"Глава {c['idx']}",
                "content": paras,
                "translator": c["translator"],
            })
        novels.append({
            "id": source_id.lower(),
            "title": meta["title"],
            "orig": nrow["title_orig"] or nrow["title"],
            "author": meta["author"],
            "genres": meta["genres"],
            "status": meta["status"],
            "rating": meta["rating"],
            "likes": meta["likes"],
            "chapters": len(chapters),
            "synopsis": meta["synopsis"],
            "gradient": meta["gradient"],
            "letter": meta["letter"],
            "lang": nrow["lang"] or "jp",
            "translated": True,
            "chaptersData": chapters,
        })
        print(f"{source_id}: {len(chapters)} глав")

    conn.close()

    # Генерация data.js
    lines = []
    lines.append("// Сгенерировано из novels.db (2 книги с реальными переводами).\n")
    lines.append("const LANGS = [")
    for code, label, flag in [
        ("ru", "Русский", "🇷🇺"), ("en", "English", "🇬🇧"),
        ("es", "Español", "🇪🇸"), ("de", "Deutsch", "🇩🇪"),
        ("fr", "Français", "🇫🇷"), ("pt", "Português", "🇵🇹"),
        ("id", "Indonesia", "🇮🇩"),
    ]:
        lines.append(f'  {{ code: "{code}", label: "{label}", flag: "{flag}" }},')
    lines.append("];\n")
    lines.append('const GENRES = ["Все", "Романтика", "Фэнтези", "Исекай", "Комедия", "Драма", "Приключения", "Фантастика", "Детектив", "Кулинария"];\n')
    lines.append("const NOVELS = " + json.dumps(novels, ensure_ascii=False, indent=2) + ";\n")

    with open("site/js/data.js", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Записано site/js/data.js")

if __name__ == "__main__":
    main()
