# -*- coding: utf-8 -*-
"""Починка артефактов перевода: смешанный алфавит и loop-tail.

Читает qa_report.json, правит content_ru в novelfull.db через Qwen (NeuralDeep).
Возобновляемый: прогресс хранится в repair_state.json.
Запуск: py repair_mixed.py [slug]     (без аргумента — все slug из отчёта)
После починки не забудь: py upload_kv.py (чтобы исправления ушли на сайт).
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("NEURALDEEP_API_KEY", open(os.path.join(HERE, "api_key.txt")).read().strip()
                      if os.path.exists(os.path.join(HERE, "api_key.txt")) else "")

import requests

import nf_pipeline as nf

QWEN_URL = "https://api.neuraldeep.ru/v1/chat/completions"
MODEL = "qwen3.6-unlim-noreason"

MIX_RE = re.compile(r"\b[\w]*[а-яА-Я][A-Za-z][\w]*\b|\b[\w]*[A-Za-z][а-яА-Я][\w]*\b")
STATE_PATH = os.path.join(HERE, "repair_state.json")


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH, encoding="utf-8"))
    return {}


def save_state(st):
    json.dump(st, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False)


def load_glossary(slug):
    path = os.path.join(HERE, "glossary_%s.json" % slug)
    if os.path.exists(path):
        try:
            g = json.load(open(path, encoding="utf-8"))
            return "; ".join("%s = %s" % (k, v) for k, v in list(g.items())[:40])
        except Exception:
            pass
    return ""


def qwen_fix(paragraph, bad_words, glossary):
    words = "\n".join("- «%s»" % w for w in bad_words)
    prompt = (
        "Ты вычитчик русского перевода китайского веб-романа. В приведённом ниже абзаце ровно "
        "%d артефакт(а) машинного перевода — вот они, каждый содержит латинские буквы внутри "
        "русского слова или прилепленное английское слово:\n%s\n"
        "Исправь КАЖДЫЙ из них: восстанови русское слово кириллицей, английскую часть переведи "
        "по смыслу. Пример: «поразитьintruder» → «поразить нарушителя», «Меллисa» → «Меллиса».\n"
        "Термины перевода (словарь): %s\n"
        "Остальной текст абзаца оставь дословно без изменений. Верни ТОЛЬКО исправленный абзац, "
        "без пояснений и кавычек.\n\nАбзац:\n%s" % (len(bad_words), words, glossary or "нет", paragraph)
    )
    for attempt in range(5):
        try:
            r = requests.post(
                QWEN_URL,
                headers={"Authorization": "Bearer " + nf.KEY, "Content-Type": "application/json"},
                json={"model": MODEL, "temperature": 0.1,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 2000},
                timeout=300)
            if r.status_code == 429:
                wait = 20 * (attempt + 1)
                log("429, жду %dс (попытка %d/5)" % (wait, attempt + 1))
                time.sleep(wait)
                continue
            r.raise_for_status()
            out = r.json()["choices"][0]["message"]["content"].strip()
            out = re.sub(r"^[\"'«]+|[\"'»]+$", "", out).strip()
            out = re.sub(r"\n{2,}", " ", out)
            return out
        except Exception as e:
            log("ошибка API: %s" % e)
            time.sleep(15 * (attempt + 1))
    return None


def fix_loop_tail(paras):
    """Убрать повторяющиеся хвостовые абзацы (зацикливание генерации)."""
    removed = 0
    while len(paras) >= 2 and paras[-1].strip() and paras[-1] == paras[-2]:
        paras.pop()
        removed += 1
    return paras, removed


def repair_chapter(slug, num, issue_kinds, glossary):
    c = nf.db()
    row = c.execute("SELECT content_ru FROM chapters WHERE slug=? AND num=?",
                    (slug, num)).fetchone()
    if not row or not row[0]:
        c.close()
        return "empty"
    ru = row[0]
    c.close()

    paras = [p for p in re.split(r"\n\s*\n", ru) if p.strip()]
    fixed_mixed = 0
    failed_mixed = 0
    new_paras = []
    changed = False

    for p in paras:
        bad = sorted(set(MIX_RE.findall(p)))
        if bad:
            out = qwen_fix(p, bad, glossary)
            if out and out.strip() and not MIX_RE.search(out) \
                    and 0.4 * len(p) <= len(out) <= 2.5 * len(p):
                new_paras.append(out)
                fixed_mixed += 1
                changed = True
            else:
                new_paras.append(p)
                failed_mixed += 1
            time.sleep(2)  # не долбим лимит
        else:
            new_paras.append(p)

    removed = 0
    if "loop-tail" in issue_kinds:
        new_paras, removed = fix_loop_tail(new_paras)
        if removed:
            changed = True

    if changed:
        c = nf.db()
        c.execute("UPDATE chapters SET content_ru=? WHERE slug=? AND num=?",
                  ("\n\n".join(new_paras), slug, num))
        c.commit()
        c.close()
    return {"mixed_fixed": fixed_mixed, "mixed_failed": failed_mixed, "tail_removed": removed}


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    qa = json.load(open(os.path.join(HERE, "qa_report.json"), encoding="utf-8-sig"))
    state = load_state()
    for slug, rep in qa.items():
        if only and slug != only:
            continue
        issues = rep.get("issues", {})
        glossary = load_glossary(slug)
        total = len(issues)
        log("%s: %d проблемных глав" % (slug, total))
        for i, (num, kinds) in enumerate(sorted(issues.items(), key=lambda x: int(x[0])), 1):
            key = "%s:%s" % (slug, num)
            if key in state:
                continue
            kinds_flat = [k.split(":")[0] for k in kinds]
            res = repair_chapter(slug, int(num), kinds_flat, glossary)
            state[key] = res
            save_state(state)
            if isinstance(res, dict):
                log("  ch%s (%d/%d): mixed ok=%s fail=%s, tail -%s" %
                    (num, i, total, res["mixed_fixed"], res["mixed_failed"], res["tail_removed"]))
            else:
                log("  ch%s (%d/%d): %s" % (num, i, total, res))
    log("починка завершена; не забудь py upload_kv.py")


if __name__ == "__main__":
    main()
