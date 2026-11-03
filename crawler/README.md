# Краулер + ИИ-извлечение новелл

Обходит японские / китайские / корейские сайты, извлекает структуру новеллы
(название, автор, главы, текст) и складывает в БД готовую к переводу очередь.

## Архитектура

```
Playwright/requests (краулер)  →  HTML страниц
        ↓
Qwen (безлимит) / Gemini (vision)  →  JSON: title, author, chapters, content
        ↓
SQLite (novels.db)  →  таблицы novels + chapters (status=pending)
        ↓
Конвейер перевода (см. novel_pipeline.py)  →  Qwen ∞ (CN) / Gemini (JP/KR)
```

## Кто что делает

| Слой | Файл | Что |
|---|---|---|
| Настройки | `config.py` | ключи, модели, источники |
| БД | `db.py` | SQLite: `novels` + `chapters` |
| ИИ-извлечение | `llm_extract.py` | HTML → JSON через Qwen/Gemini |
| Краулеры | `crawler.py` | syosetu (API), biquge/munpia (HTML+ИИ) |
| Оркестратор | `pipeline.py` | CLI: каталог / новелла / очередь |
| Перевод + самопроверка | `translator.py` | перевод + self-reflection loop |

## Установка

```bash
pip install -r requirements.txt
$env:NEURALDEEP_API_KEY = "sk-..."   # Qwen безлимит (парсинг)
$env:GEMINI_API_KEY = "AIza..."      # опционально, vision + JP/KR перевод
```

## Использование

```bash
# Топ-10 популярных завершённых новелл с syosetu (в каталог, без глав)
python -m crawler.pipeline syosetu --catalog 10

# Конкретная новелла syosetu — скачает все главы напрямую (без ИИ)
python -m crawler.pipeline syosetu --ncode N1354HZ

# Новелла с biquge (CN) / munpia (KR) — ИИ извлечёт структуру из HTML
python -m crawler.pipeline biquge --url https://www.biquge.example/book/123/
python -m crawler.pipeline munpia --url https://munpia.com/.../...

# Сложный сайт (динамический/vision) — через Gemini
python -m crawler.pipeline biquge --url https://... --gemini

# Очередь глав, ожидающих перевода
python -m crawler.pipeline queue

# Перевести главы из очереди (с самопроверкой)
python -m crawler.translator --limit 20
```

## Как это связано с переводом

Краулер наполняет таблицу `chapters` со статусом `pending` и сырым текстом
`content` (на языке оригинала). Дальше воркер перевода:

```bash
python -m crawler.translator --limit 20     # 20 глав из очереди
python -m crawler.translator --novel 3      # все главы новеллы #3
```

Воркер (`translator.py`):
1. Берёт `pending` главы, по `novels.lang` выбирает модель (CN → Qwen ∞, JP/KR → Gemma/Gemini).
2. Переводит с глоссарием имён.
3. **Самопроверка (self-reflection):** та же модель сверяет перевод с оригиналом
   и глоссарием, находит ошибки и исправляет их, повторяя до 3 итераций — пока
   не решит, что всё корректно.
4. Пишет результат в `chapters.translated`, ставит `status='done'`.

## Схема БД

```sql
novels(id, source, source_id, title, title_orig, author, synopsis,
       lang, status, url, chapters_count)
chapters(id, novel_id, idx, title, content, translated, status)
```

## Особенности источников

- **syosetu (JP)** — есть официальный narou API: метаданные и текст берутся
  напрямую, БЕЗ ИИ (быстро и бесплатно). Селекторы: `.p-novel__text`,
  `.p-novel__body`.
- **biquge (CN) / munpia (KR)** — нет API: краулер качает HTML, а Qwen
  извлекает JSON-структуру из «грязной» страницы (убирает рекламу/меню).
  Gemini с vision — для сайтов, рендерящих контент скриптами.

## Замечание

Для biquge/munpia в `crawler.html_novel` используется двухшаговое извлечение:
сначала ИИ разбирает оглавление (список ссылок на главы), затем по каждой
ссылке извлекает текст главы. Это позволяет парсить произвольную структуру
без жёстких селекторов.
