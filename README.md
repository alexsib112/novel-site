# Novel-site — сайт веб-новелл с ИИ-переводом

Проект: краулинг новелл (JP/CN/KR) → ИИ-извлечение → перевод (Qwen ∞ / Gemini)
→ самопроверка → выгрузка на статический сайт (Cloudflare Pages).

Сайт: https://novellith.pages.dev

## Состав

```
site/             — сам сайт (index.html, css/, js/)
crawler/          — пайплайн: краулинг + извлечение + перевод
deploy.py         — деплой на Cloudflare Pages (Direct Upload API)
generate_data.py  — генерация site/js/data.js из novels.db
fetch_covers.py   — скачивание обложек с источника
novel_pipeline.py — старый одиночный пайплайн перевода (DeepSeek)
glossary.json     — словарь имён/терминов для перевода
novels.db         — база: novels + chapters (переводы, статусы)
output/           — готовые файлы (.fb2)
```

## Как устроен конвейер

```
crawler/   краулер (syosetu/biquge/munpia) → HTML
   ↓
llm_extract  Qwen извлекает JSON (title/author/chapters)
   ↓
db.py      SQLite: novels + chapters (status=pending)
   ↓
translator  перевод Qwen/Gemini + самопроверка → status=done
   ↓
generate_data  → site/js/data.js (с переводами)
   ↓
deploy.py  → Cloudflare Pages
```

## Ключевые файлы crawler/

| Файл | Назначение |
|---|---|
| `config.py` | ключи (env), модели, источники |
| `db.py` | SQLite: novels + chapters (поле translator) |
| `llm_extract.py` | HTML → JSON (Qwen/Gemini, режимы toc/chapter) |
| `crawler.py` | syosetu (narou API), biquge/munpia (HTML+ИИ) |
| `translator.py` | перевод + self-reflection loop, параллелизм ×3 |
| `covers.py` | обложки (скачивание + сжатие) |

## Запуск

```powershell
# env-ключи
$env:NEURALDEEP_API_KEY = "sk-..."     # Qwen ∞ (безлимит)
$env:CF_API_TOKEN = "..."              # Cloudflare Pages

# 1. Краулинг + сохранение в БД
python -m crawler.pipeline syosetu --ncode N1354HZ

# 2. Перевод (с самопроверкой, Qwen)
python -m crawler.translator --novel 1

# 3. Выгрузка на сайт
python generate_data.py
python deploy.py
```

## Модели

- **Перевод** — `qwen3.6-unlim-noreason` (neuraldeep, безлимит) для всех языков.
- **Парсинг** — `qwen3.6-unlim-noreason`.
- Gemini (`gemini-3.8-flash`) — выключен (free tier, 20 req/день), код оставлен в `translator.py`.

## «Расколотая битвой синева небес» (novelfull.com → русский)

Отдельный конвейер для новеллы `battle-through-the-heavens` (斗破苍穹, 1645 глав).

```powershell
# запуск python (важно: `python` в PATH — заглушка MS Store, используем обёртку)
.\py.cmd novelfull_pipeline.py status battle-through-the-heavens

.\py.cmd novelfull_pipeline.py download  battle-through-the-heavens   # качает главы в novelfull.db
.\py.cmd novelfull_pipeline.py translate battle-through-the-heavens 6 # перевод, 6 потоков (resume)
.\py.cmd novelfull_pipeline.py fb2       battle-through-the-heavens   # output/battle-through-the-heavens.fb2

.\py.cmd repair_titles.py        # чинит русские заголовки глав (идемпотентно)
.\py.cmd gen_btth.py             # site/data/bth/: index.json + chunk-XXXX.json
```

Особенности:

- `novelfull.db` — SQLite: `books(slug, title, chapters_total)`, `chapters(slug, num, title, content_en, content_ru, status, title_ru)`.
- Перевод возобновляемый: глава помечается `status='translated'` только после успешного ответа.
- Длинные главы (> 12 000 символов) режутся на части по абзацам (`CHUNK_LIMIT`).
- Глоссарий имён/терминов — `glossary_btth.json` (подставляется в системный промпт).
- Модель отдаёт заголовок главы, затем `===`, затем текст; парсер устойчив к вариантам оформления.
- `progress.txt` — прогресс перевода.

### Сайт

Главы «Повелителя Небес» **не** грузятся вместе с `data.js` (это ~25 МБ текста).
Вместо этого:

- `site/js/novels-extra.js` — карточка новеллы (`lazy: true`, `indexUrl`, `chunkSize: 25`);
- `site/data/bth/index.json` — список переведённых глав;
- `site/data/bth/chunk-000N.json` — текст глав порциями по 25 (~500 КБ на файл).

`app.js` подтягивает индекс при открытии новеллы и нужный чанк при открытии главы,
результат кэшируется в памяти.

### Контроль качества перевода

| Скрипт | Что делает |
|---|---|
| `detect_bad.py` | ищет главы с выдуманными концовками (латиница, коэффициент длины, зацикливание, маркеры «филлера») → `bad_chapters.json` |
| `repair_bad.py` | переводит найденные главы заново строгим промптом с автопроверкой (до 3 попыток) |
| `last_para_check.py` | точная проверка последнего абзаца: английский хвост, служебный заголовок, зацикливание, аномальная длина → `bad_last.json` |
| `fix_tails.py <номера>` | убирает английские/служебные хвосты и дописывает перевод настоящей концовки |
| `repair_tail.py <номера>` | реперевод глав, где концовка не совпала с оригиналом (проверка через LLM) |
| `cjk_fix.py` | заменяет оставшиеся китайские вставки в русском тексте |
| `normalize_terms.py` | приводит к единообразию «Сяо Ян/Янь», «Доу Ци/доуци», «Сюнь Эр/Сюнь'эр», «Цзя Нань/Цзянань` |

Порядок финальной обработки:

```powershell
.\py.cmd detect_bad.py            # + repair_bad.py, если что-то нашлось
.\py.cmd last_para_check.py       # + fix_tails.py <номера>, если что-то нашлось
.\py.cmd cjk_fix.py
.\py.cmd normalize_terms.py
.\py.cmd repair_titles.py
.\py.cmd gen_btth.py
.\py.cmd novelfull_pipeline.py fb2 battle-through-the-heavens
```

## Важный нюанс деплоя

Cloudflare Pages хэширует файлы как `SHA-256(base64(контента) + расширение)[:32]`,
а не как обычный SHA-256 файла. Реализовано в `deploy.py` → `pages_hash()`.

## БД (novels.db)

- `novels` — карточки (source, source_id, title, cover, lang, ...)
- `chapters` — главы (content, translated, translator, status)

Поле `translator` показывает, какая модель перевела главу (`qwen` / `gemini`).
