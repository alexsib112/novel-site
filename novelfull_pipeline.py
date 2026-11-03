# -*- coding: utf-8 -*-
"""
Novelfull → Qwen (EN→RU) → fb2

Команды:
  python novelfull_pipeline.py download <slug>      # качает все главы в SQLite
  python novelfull_pipeline.py translate <slug>     # переводит Qwen (resume, параллельно)
  python novelfull_pipeline.py fb2 <slug>           # собирает .fb2
  python novelfull_pipeline.py status <slug>        # статус
  python novelfull_pipeline.py preview <slug> <n>   # показать перевод главы

Пример: python novelfull_pipeline.py download battle-through-the-heavens
"""
import sys, os, re, time, json, sqlite3, html, threading
import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8')

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE = "https://www.novelfull.com"

# --- read API key from file ---
_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "neuraldeep_api_key.txt")
def get_api_key():
    try:
        return open(_KEY_PATH).read().strip()
    except Exception:
        return os.environ.get("NEURALDEEP_API_KEY", "")

KEY = get_api_key()
QWEN_URL = "https://api.neuraldeep.ru/v1/chat/completions"
MODEL = "qwen3.6-unlim-noreason"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "novelfull.db")

def db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS books(
        slug TEXT PRIMARY KEY, title TEXT, chapters_total INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS chapters(
        slug TEXT, num INTEGER, title TEXT, content_en TEXT,
        content_ru TEXT, status TEXT DEFAULT 'downloaded',
        PRIMARY KEY(slug, num))""")
    # миграция: русский заголовок главы
    cols = [r[1] for r in c.execute("PRAGMA table_info(chapters)")]
    if "title_ru" not in cols:
        c.execute("ALTER TABLE chapters ADD COLUMN title_ru TEXT")
        c.commit()
    return c

def get(url, retries=4):
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    for i in range(retries):
        try:
            r = s.get(url, timeout=25)
            if r.status_code == 200:
                r.encoding = 'utf-8'
                return r
        except Exception:
            pass
        time.sleep(2 + i * 2)
    raise RuntimeError(f"failed {url}")

# ---------- DOWNLOAD ----------
def collect_toc(slug):
    """Все главы {num: href}, упорядоченные 1..N (дедуп по номеру)."""
    links = {}
    page = 1
    while page <= 300:
        url = f"{BASE}/{slug}.html" if page == 1 else f"{BASE}/{slug}.html?page={page}"
        try:
            r = get(url)
        except RuntimeError:
            break  # кончились страницы
        found = re.findall(r'href="(/' + slug + r'/chapter-(\d+)-[^"]+\.html)"', r.text)
        if not found:
            break
        new = 0
        for href, num in found:
            n = int(num)
            if n not in links:
                links[n] = href
                new += 1
        if new == 0:
            break
        page += 1
    return links

def extract_chapter(r):
    soup = BeautifulSoup(r.text, "html.parser")
    cont = soup.find(id="chapter-content") or soup.find("div", class_=re.compile("chapter-content|reading-content"))
    if not cont:
        return ("", "")
    paras = [p.get_text(strip=True) for p in cont.find_all("p") if p.get_text(strip=True)]
    if not paras:
        return ("", "")
    title = paras[0]                       # первая строка — "Chapter N <название>"
    content = "\n\n".join(paras[1:])
    return (title, content)

def cmd_download(slug):
    c = db()
    toc = collect_toc(slug)
    if not toc:
        print("не нашли главы"); return
    total = max(toc)
    print(f"глав в оглавлении: {total}")
    # title книги
    try:
        r = get(f"{BASE}/{slug}.html")
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', r.text)
        title = m.group(1).strip() if m else slug
    except Exception:
        title = slug
    c.execute("INSERT OR REPLACE INTO books VALUES(?,?,?)", (slug, title, total))
    done = 0
    for num in sorted(toc):
        row = c.execute("SELECT status FROM chapters WHERE slug=? AND num=?", (slug, num)).fetchone()
        if row and row[0] not in ('downloaded', 'empty'):
            continue
        if row and row[0] == 'downloaded':
            existing = c.execute("SELECT content_en FROM chapters WHERE slug=? AND num=?", (slug, num)).fetchone()
            if existing and existing[0]:
                # already fully downloaded
                done += 1
                continue
        href = toc[num]
        try:
            r = get(BASE + href)
            chtitle, content = extract_chapter(r)
            if content:
                c.execute("INSERT OR REPLACE INTO chapters VALUES(?,?,?,?,?, 'downloaded')",
                          (slug, num, chtitle, content, None))
                done += 1
            else:
                c.execute("INSERT OR REPLACE INTO chapters VALUES(?,?,?,?,?, 'empty')",
                          (slug, num, chtitle, '', None))
        except Exception as e:
            print(f"  err ch{num}: {e}")
        c.commit()
        if num % 50 == 0:
            print(f"  ... {num}/{total} скачано")
        time.sleep(0.4)
    c.commit(); c.close()
    print(f"готово, скачано {done} новых глав")

# ---------- TRANSLATE ----------
_GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary_btth.json")

def load_glossary():
    try:
        with open(_GLOSSARY_PATH, encoding="utf-8") as f:
            g = json.load(f)
        return "\n".join(f"{k} — {v}" for k, v in g.items())
    except Exception:
        return ""

GLOSSARY = load_glossary()

CHUNK_LIMIT = 12000

TRANSLATE_SYS = (
    "Ты профессиональный литературный переводчик китайских сянься-романов. "
    "Переводишь с английского на русский.\n\n"
    "Правила:\n"
    "— Литературный, живой русский язык. Сохраняй стиль, темп и все детали оригинала; "
    "ничего не сокращай и не добавляй от себя.\n"
    "— Переводи ТОЛЬКО предоставленный текст. Не дописывай продолжение, не придумывай финал, "
    "не добавляй итоговых/обобщающих абзацев. Остановись ровно там, где заканчивается исходный текст.\n"
    "— Никогда не повторяй один и тот же абзац или фразу несколько раз.\n"
    "— Имена и термины передавай строго по глоссарию ниже, единообразно во всех главах.\n"
    "— Прямая речь — с тире (—), мысли персонажей — в круглых скобках.\n"
    "— Никаких пояснений, примечаний, вводных фраз и английских слов в тексте.\n\n"
    "Формат ответа (строго):\n"
    "1) Первая строка — перевод названия главы: только подзаголовок, без слова «Глава» и без номера.\n"
    "2) Отдельная строка-разделитель: ===\n"
    "3) Полный перевод текста главы; абзацы разделяй пустой строкой.\n"
    + ("\nГлоссарий (EN — RU):\n" + GLOSSARY if GLOSSARY else "")
)

def clean_title(t):
    t = (t or "").strip().strip('"«»“”').strip()
    t = re.sub(r'^(глава|chapter)\s*\d+[\s:.:–—-]*', '', t, flags=re.I)
    return t.strip(' .:–—-')

def looks_like_title(p):
    """Похожа ли строка на заголовок главы (а не на абзац прозы)."""
    p = (p or "").strip()
    if not p or len(p) > 90 or "\n" in p:
        return False
    if p[0] in "—-–«(«\"'":
        return False
    if re.fullmatch(r"[\W_]+", p):          # только символы (◇◇◇, ***)
        return False
    if p.endswith((".", "!", "…", ";", ",", ":")):
        return False
    return True


def parse_reply(text, num):
    """Ответ модели → (title_ru, body_ru).

    Модель не всегда оформляет ответ строго: разделитель «===» может стоять
    в одной строке с заголовком или отсутствовать вовсе. Поэтому пробуем
    несколько стратегий.
    """
    text = (text or "").strip()
    title = ""
    body = text

    m = re.search(r"={3,}", text)
    if m:
        title = clean_title(text[:m.start()])
        body = text[m.end():].strip()
    else:
        lines = text.splitlines()
        if (len(lines) >= 2 and lines[0].strip()
                and re.fullmatch(r"[-–—*=]{3,}", lines[1].strip() or "")):
            title = clean_title(lines[0])
            body = "\n".join(lines[2:]).strip()
        else:
            parts = re.split(r"\n\s*\n", text, 1)
            if len(parts) > 1 and looks_like_title(parts[0]):
                title = clean_title(parts[0])
                body = parts[1].strip()

    if not title:
        title = f"Глава {num}"
    return title, body

def qwen_translate(en_text, title=None, num=0):
    key = get_api_key()
    if not key:
        raise RuntimeError("NEURALDEEP_API_KEY не задан (ни файл, ни env)")
    user = (f"Название главы: {title}\n\nТекст:\n{en_text}" if title else en_text)
    last = None
    for attempt in range(8):
        try:
            r = requests.post(QWEN_URL,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": MODEL, "temperature": 0.4,
                      "messages": [
                          {"role": "system", "content": TRANSLATE_SYS},
                          {"role": "user", "content": user}
                      ],
                      "max_tokens": 8000},
                timeout=600)
            if r.status_code == 200:
                return parse_reply(r.json()["choices"][0]["message"]["content"], num)
            last = f"http {r.status_code}: {r.text[:200]}"
            if r.status_code == 429:
                time.sleep(min(90, 10 * (attempt + 1)))
            else:
                time.sleep(5 * (attempt + 1))
        except Exception as e:
            last = str(e)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(last or "unknown error")

def split_text(text, limit):
    """Разбить текст на куски <= limit символов по границам абзацев."""
    paras = re.split(r"\n\s*\n", text)
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > limit:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur.strip():
        chunks.append(cur)
    return chunks


def translate_chapter(num, title, en):
    """Перевод главы с автоматическим дроблением длинных текстов."""
    if len(en) <= CHUNK_LIMIT:
        t, body = qwen_translate(en, title, num)
        if len(body) >= 0.55 * len(en):
            return t, body
    parts = split_text(en, CHUNK_LIMIT)
    bodies, title_ru = [], None
    for i, part in enumerate(parts):
        t, b = qwen_translate(part, title if i == 0 else None, num)
        if i == 0:
            title_ru = t
        if b:
            bodies.append(b)
    return title_ru or f"Глава {num}", "\n\n".join(bodies)


def cmd_translate(slug, workers=4, limit=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    key = get_api_key()
    if not key:
        print("ОШИБКА: NEURALDEEP_API_KEY не найден"); return

    c = db()
    q = ("SELECT num, title, content_en FROM chapters "
         "WHERE slug=? AND content_en != '' AND (content_ru IS NULL OR content_ru='')")
    if limit:
        q += f" ORDER BY num LIMIT {int(limit)}"
    else:
        q += " ORDER BY num"
    chapters = {r[0]: (r[1], r[2]) for r in c.execute(q, (slug,)).fetchall()}
    total_all, done_all = c.execute(
        "SELECT COUNT(*), SUM(CASE WHEN content_ru IS NOT NULL AND content_ru != '' THEN 1 ELSE 0 END) "
        "FROM chapters WHERE slug=? AND content_en != ''", (slug,)).fetchone()
    c.close()

    total = len(chapters)
    done0 = int(done_all or 0)
    print(f"к переводу: {total} (уже переведено {done0}/{total_all})")
    if not total:
        return

    lock = threading.Lock()
    success = errors = 0
    started = time.time()

    def work(num):
        chtitle, en = chapters[num]
        try:
            t_ru, body = translate_chapter(num, chtitle, en)
            if not body or len(body) < 50:
                raise RuntimeError("пустой ответ")
            with lock:
                c3 = db()
                c3.execute(
                    "UPDATE chapters SET content_ru=?, title_ru=?, status='translated' "
                    "WHERE slug=? AND num=?", (body, t_ru, slug, num))
                c3.commit(); c3.close()
            return (num, True)
        except Exception as e:
            print(f"  err ch{num}: {e}", file=sys.stderr)
            return (num, False)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, n): n for n in chapters}
        for f in as_completed(futs):
            try:
                num, ok = f.result()
            except Exception:
                ok = False
            if ok:
                success += 1
            else:
                errors += 1
            n = success + errors
            if n % 10 == 0 or n == total:
                el = time.time() - started
                rate = n / el * 60 if el else 0
                eta = (total - n) / (n / el) / 60 if el and n else 0
                msg = (f"  ... {n}/{total} (ok {success}, err {errors}) "
                       f"{rate:.1f} гл/мин, осталось ~{eta:.0f} мин")
                print(msg)
                try:
                    with open("progress.txt", "w", encoding="utf-8") as pf:
                        pf.write(msg + "\n")
                        pf.write(f"всего переведено в БД: {done0 + success}/{total_all}\n")
                except Exception:
                    pass
    print(f"перевод завершён: {success} ok, {errors} errors из {total}")

# ---------- FB2 ----------
FB2_META = {
    "battle-through-the-heavens": {
        "title": "Расколотая битвой синева небес",
        "author": "Тянь Цань Ту Доу",
        "annotation": (
            "Сяо Янь был вундеркиндом клана Сяо — а в двенадцать лет разом лишился силы. "
            "Три года насмешек, изгнание из семьи, разорванная помолвка… Но в старом кольце "
            "на его пальце дремлет душа великого алхимика Яо Лао. Отныне «мусор» клана "
            "начинает восхождение к вершинам мира."
        ),
        "genres": ["фэнтези", "приключения", "сянься"],
        "sequence": "Повелитель Небес",
    },
}


def cmd_fb2(slug):
    c = db()
    b = c.execute("SELECT title, chapters_total FROM books WHERE slug=?", (slug,)).fetchone()
    if not b:
        print("книга не найдена"); return
    title, total = b
    meta = FB2_META.get(slug, {})
    title = meta.get("title", title)
    rows = c.execute(
        "SELECT num, title, title_ru, content_ru FROM chapters "
        "WHERE slug=? AND content_ru IS NOT NULL AND content_ru != '' ORDER BY num",
        (slug,)).fetchall()
    c.close()
    if not rows:
        print("нет переведённых глав"); return
    body = []
    for num, chtitle, title_ru, ru in rows:
        head = title_ru or clean_title(chtitle)
        title_line = f"Глава {num}. {head}" if head else f"Глава {num}"
        parts = [f"<p>{html.escape(p)}</p>" for p in re.split(r"\n\s*\n", ru) if p.strip()]
        body.append(
            f'<section id="ch{num}"><title><p>{html.escape(title_line)}</p></title>'
            f'{"".join(parts)}</section>')

    genres = "".join(f"<genre>{html.escape(g)}</genre>" for g in meta.get("genres", []))
    annotation = meta.get("annotation", "")
    annotation_xml = (f"<annotation><p>{html.escape(annotation)}</p></annotation>"
                      if annotation else "")
    author = meta.get("author", "")
    author_xml = ""
    if author:
        parts_a = author.split()
        author_xml = (f"<author><first-name>{html.escape(' '.join(parts_a[:-1]))}</first-name>"
                      f"<last-name>{html.escape(parts_a[-1])}</last-name></author>")
    seq = meta.get("sequence", "")
    seq_xml = f'<sequence name="{html.escape(seq)}" number="{len(rows)}"/>' if seq else ""

    fb2 = f'''<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
<description>
<title-info>
{genres}
{author_xml}
<book-title>{html.escape(title)}</book-title>
{annotation_xml}
<lang>ru</lang>
{seq_xml}
</title-info>
<document-info>
<author><nickname>NovelVerse</nickname></author>
<program-used>novelfull_pipeline.py (Qwen)</program-used>
<date value="2026-01-01">2026</date>
<id>{slug}</id>
<version>1.0</version>
</document-info>
</description>
<body>
<title><p>{html.escape(title)}</p></title>
{''.join(body)}
</body>
</FictionBook>'''
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", f"{slug}.fb2")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(fb2)
    print(f"fb2 собран: {out}  (глав: {len(rows)}, {os.path.getsize(out) // 1024} КБ)")

def cmd_status(slug):
    c = db()
    b = c.execute("SELECT title, chapters_total FROM books WHERE slug=?", (slug,)).fetchone()
    if not b:
        print("книга не скачана"); return
    total = b[1]
    dl = c.execute("SELECT count(*) FROM chapters WHERE slug=? AND content_en != ''", (slug,)).fetchone()[0]
    tr = c.execute("SELECT count(*) FROM chapters WHERE slug=? AND content_ru IS NOT NULL", (slug,)).fetchone()[0]
    c.close()
    print(f"{slug}: скачано {dl}/{total}, переведено {tr}/{total}")

def cmd_preview(slug, num):
    c = db()
    r = c.execute(
        "SELECT num, title, content_en, content_ru FROM chapters WHERE slug=? AND num=?",
        (slug, num)
    ).fetchone()
    c.close()
    if not r:
        print(f"глава {num} не найдена")
        return
    print(f"=== Глава {num}: {r[1]} ===\n")
    if r[2]:
        print("--- ORIGINAL (EN) ---\n")
        print(r[2][:800].replace('\n', '\n  '))
        if len(r[2]) > 800:
            print("  ...")
    if r[3]:
        print(f"\n--- ПЕРЕВОД (RU) ---\n")
        print(r[3][:800].replace('\n', '\n  '))
        if len(r[3]) > 800:
            print("  ...")
    if not r[3]:
        print("  (нет перевода)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(0)
    cmd, slug = sys.argv[1], sys.argv[2]
    if cmd == "download":
        cmd_download(slug)
    elif cmd == "translate":
        workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
        limit = int(sys.argv[4]) if len(sys.argv) > 4 else None
        cmd_translate(slug, workers=workers, limit=limit)
    elif cmd == "fb2":
        cmd_fb2(slug)
    elif cmd == "status":
        cmd_status(slug)
    elif cmd == "preview":
        num = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        cmd_preview(slug, num)
    else:
        print(f"unknown command: {cmd}")
