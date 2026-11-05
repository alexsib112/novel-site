# -*- coding: utf-8 -*-
"""
Очередной запускатор: novels_queue.json → скачивание → перевод → QA → чанки.

Возобновляемый: каждый шаг смотрит в БД и продолжает с места остановки.
Лог: queue.log. Прогресс: progress.txt. QA-отчёты: qa_report.json.
Запуск: python3 queue_runner.py [start_index]
"""
import sys, os, re, time, json, sqlite3, threading, subprocess, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if os.path.exists(os.path.join(HERE, "api_keys.txt")):
    os.environ.setdefault("NEURALDEEP_API_KEYS", ",".join(
        l.strip() for l in open(os.path.join(HERE, "api_keys.txt"), encoding="utf-8")
        if l.strip() and not l.startswith("#")))
else:
    os.environ.setdefault("NEURALDEEP_API_KEY", open(os.path.join(HERE, "api_key.txt")).read().strip()
                          if os.path.exists(os.path.join(HERE, "api_key.txt")) else "")

import nf_pipeline as nf

QUEUE = json.load(open(os.path.join(HERE, "novels_queue.json"), encoding="utf-8"))
DL_WORKERS = 3
TR_WORKERS = 8  # лимит аккаунта 9 параллельных (Qwen ∞), 1 про запас на служебные вызовы
TR_BATCH = 300          # переводим партиями, чтобы чанки пересобирались инкрементально

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(HERE, "queue.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

def download_novel(slug):
    """Скачать недостающие главы (3 потока, вежливая пауза)."""
    toc = nf.collect_toc(slug)
    if not toc:
        log(f"{slug}: оглавление пусто!")
        return
    total = max(toc)
    c = nf.db()
    have = {r[0] for r in c.execute(
        "SELECT num FROM chapters WHERE slug=? AND content_en != ''", (slug,)).fetchall()}
    c.close()
    missing = sorted(set(toc) - have)
    if not missing:
        log(f"{slug}: скачивание не нужно ({total} глав в базе)")
        return
    log(f"{slug}: скачиваем {len(missing)} глав (всего {total})")
    lock = threading.Lock()
    done = [0]
    def work(num):
        for attempt in range(5):
            try:
                r = nf.get(nf.BASE + toc[num])
                title, content = nf.extract_chapter(r, slug)
                with lock:
                    c2 = nf.db()
                    if content:
                        c2.execute("INSERT OR REPLACE INTO chapters(slug,num,title,content_en,content_ru,status) "
                                   "VALUES(?,?,?,?,?,'downloaded')", (slug, num, title, content, None))
                    else:
                        c2.execute("INSERT OR REPLACE INTO chapters(slug,num,title,content_en,content_ru,status) "
                                   "VALUES(?,?,?,?,'','empty')", (slug, num, title))
                    c2.commit(); c2.close()
                    done[0] += 1
                    if done[0] % 100 == 0:
                        log(f"{slug}: скачано {done[0]}/{len(missing)}")
                time.sleep(0.35)
                return
            except Exception as e:
                time.sleep(3 * (attempt + 1))
        log(f"{slug}: НЕ СКАЧАЛАСЬ глава {num}")
    with ThreadPoolExecutor(max_workers=DL_WORKERS) as ex:
        list(ex.map(work, missing))
    log(f"{slug}: скачивание завершено, всего в базе {len(have) + done[0]}")

def translate_novel(slug):
    """Перевод партиями до полного покрытия."""
    while True:
        c = nf.db()
        total = c.execute("SELECT count(*) FROM chapters WHERE slug=? AND content_en != ''", (slug,)).fetchone()[0]
        left = c.execute("SELECT count(*) FROM chapters WHERE slug=? AND content_en != '' AND "
                         "(content_ru IS NULL OR content_ru='')", (slug,)).fetchone()[0]
        c.close()
        if left == 0:
            log(f"{slug}: перевод завершён ({total}/{total})")
            return
        log(f"{slug}: к переводу {left} (всего {total})")
        subprocess.run([sys.executable, os.path.join(HERE, "nf_pipeline.py"), "translate",
                        slug, str(TR_WORKERS), str(TR_BATCH)],
                       env=os.environ, cwd=HERE)
        # если партия не сдвинулась (все ошибки) — пауза и ещё раз
        c = nf.db()
        left2 = c.execute("SELECT count(*) FROM chapters WHERE slug=? AND content_en != '' AND "
                          "(content_ru IS NULL OR content_ru='')", (slug,)).fetchone()[0]
        c.close()
        if left2 == left:
            log(f"{slug}: партия не сдвинулась ({left2} осталось), пауза 120с")
            time.sleep(120)

MIX_RE = re.compile(r"\b[\w]*[а-яА-Я][A-Za-z][\w]*\b|\b[\w]*[A-Za-z][а-яА-Я][\w]*\b")

def qa_and_fix_titles(slug):
    """Заголовки-заглушки 'Глава N' → перевести название; собрать QA-отчёт."""
    c = nf.db()
    bad = c.execute("SELECT num, title FROM chapters WHERE slug=? AND title_ru IS NOT NULL AND "
                    "title_ru LIKE 'Глава %'", (slug,)).fetchall()
    fixed = 0
    for num, en_title in bad:
        for attempt in range(5):
            try:
                r = nf.qwen_translate_title(en_title)
                if r:
                    c.execute("UPDATE chapters SET title_ru=? WHERE slug=? AND num=?", (r, slug, num))
                    fixed += 1
                break
            except Exception as e:
                if "429" in str(e) and attempt < 4:
                    wait = 20 * (attempt + 1)
                    log(f"{slug}: ch{num} лимит 429, ждём {wait}с (попытка {attempt+1}/5)")
                    time.sleep(wait)
                    continue
                log(f"{slug}: ch{num} заголовок не исправлен: {e}")
                break
        time.sleep(2)  # пауза между вызовами — не долбим лимит провайдера
    c.commit()
    # QA-отчёт
    report = {}
    for num, en, ru in c.execute("SELECT num, content_en, content_ru FROM chapters WHERE slug=? "
                                 "AND content_ru IS NOT NULL AND content_ru != ''", (slug,)):
        issues = []
        if MIX_RE.search(ru):
            issues.append("mixed-alphabet: " + ", ".join(sorted(set(MIX_RE.findall(ru)))[:5]))
        if len(ru) < 0.5 * len(en):
            issues.append(f"short: {len(ru)}/{len(en)}")
        paras = [p for p in re.split(r"\n\s*\n", ru) if p.strip()]
        if len(paras) >= 3 and (paras[-1] == paras[-2] or paras[-1] == paras[-3]):
            issues.append("loop-tail")
        if issues:
            report[num] = issues
    c.close()
    if report or fixed:
        path = os.path.join(HERE, "qa_report.json")
        try:
            all_rep = json.load(open(path, encoding="utf-8"))
        except Exception:
            all_rep = {}
        all_rep[slug] = {"fixed_titles": fixed, "issues": report}
        json.dump(all_rep, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log(f"{slug}: QA — исправлено заголовков {fixed}, проблемных глав {len(report)}")

def build_site_package(slug, meta):
    """Чанки + novels-extra.js + zip."""
    out_site = os.path.join(HERE, "site")
    outdir = os.path.join(out_site, "data", meta["id"])
    nf.cmd_chunks(slug, outdir, 25)
    # novels-extra.js из очереди
    cards = []
    for m in QUEUE:
        c = nf.db()
        tr = c.execute("SELECT count(*) FROM chapters WHERE slug=? AND content_ru IS NOT NULL AND content_ru != ''",
                       (m["slug"],)).fetchone()[0]
        c.close()
        if tr == 0:
            continue
        ct = m.get("chapters_total")
        if not ct:
            c2 = nf.db()
            row = c2.execute("SELECT chapters_total FROM books WHERE slug=?", (m["slug"],)).fetchone()
            c2.close()
            ct = (row[0] if row and row[0] else tr)
        cards.append({
            "id": m["id"], "title": m["ru"], "orig": m["orig"], "author": m["author"],
            "genres": m["genres"], "status": m["status"], "rating": m["rating"], "likes": m["likes"],
            "chapters": ct, "synopsis": m["synopsis"],
            "gradient": m["gradient"], "letter": m["letter"], "lang": m["lang"],
            "translated": True, "lazy": True,
            "indexUrl": f'data/{m["id"]}/index.json', "chunkSize": 25,
        })
    js = "// Дополнительные новеллы NovelVerse (подключается после data.js).\n// Контент глав подгружается лениво из site/data/<id>/ (см. app.js).\n\n"
    js += "\n\n".join("NOVELS.push(" + json.dumps(c_, ensure_ascii=False, indent=2) + ");" for c_ in cards)
    pkg = os.path.join(HERE, "site_pkg")
    os.makedirs(os.path.join(pkg, "site", "js"), exist_ok=True)
    with open(os.path.join(pkg, "site", "js", "novels-extra.js"), "w", encoding="utf-8") as f:
        f.write(js)
    # catalog.json для мобильного/десктопного приложения (статика + очередь с живыми счётчиками)
    try:
        cat = json.load(open(os.path.join(HERE, "catalog_static.json"), encoding="utf-8"))
        cat["novels"] = cat["novels"] + cards
        json.dump(cat, open(os.path.join(out_site, "data", "catalog.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception as e:
        log(f"catalog.json не обновлён: {e}")
    # копируем data (rsync-lite)
    import shutil
    src_data = os.path.join(out_site, "data")
    dst_data = os.path.join(pkg, "site", "data")
    if os.path.exists(dst_data):
        shutil.rmtree(dst_data)
    shutil.copytree(src_data, dst_data)
    # zip
    import zipfile
    zpath = os.path.join(HERE, "site-update.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(pkg):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, pkg))
    log(f"{slug}: пакет обновлён (карточек: {len(cards)}) → {zpath}")

def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    for i, meta in enumerate(QUEUE):
        if i < start:
            continue
        slug = meta["slug"]
        log(f"=== [{i+1}/{len(QUEUE)}] {slug} ({meta['ru']}) ===")
        try:
            download_novel(slug)
            # сохранить chapters_total в мету (для карточек)
            c = nf.db()
            t = c.execute("SELECT chapters_total FROM books WHERE slug=?", (slug,)).fetchone()
            c.close()
            meta["chapters_total"] = t[0] if t else 0
            translate_novel(slug)
            qa_and_fix_titles(slug)
            build_site_package(slug, meta)
            # сохраняем обновлённую очередь (chapters_total)
            json.dump(QUEUE, open(os.path.join(HERE, "novels_queue.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        except Exception:
            log(f"{slug}: ИСКЛЮЧЕНИЕ:\n{traceback.format_exc()}")
            log("пауза 300с и продолжаем очередь")
            time.sleep(300)
    log("ОЧЕРЕДЬ ВЫПОЛНЕНА ПОЛНОСТЬЮ")

if __name__ == "__main__":
    main()
