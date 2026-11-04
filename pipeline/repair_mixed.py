# -*- coding: utf-8 -*-
"""Починка артефактов перевода: смешанный алфавит и loop-tail.

Читает qa_report.json, правит content_ru в novelfull.db.
Двухфазная починка смешанного алфавита:
  1. Детерминированно — «поддельная кириллица»: слова, где латинские буквы
     заменяются на похожие кириллические и слово становится полностью русским
     (Городa → Города). Нейросеть не нужна.
  2. Через Qwen — «полукровки»: английский корень + русское окончание
     (exertил, midstе). Промпт отдаёт ТОЛЬКО слово и одиночное исправление.
Главы, где в прошлом прогоне остались mixed_failed > 0, обрабатываются заново.
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

# Латинские буквы с визуально неотличимыми кириллическими аналогами
HOMO = {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у",
        "m": "м", "A": "А", "B": "В", "E": "Е", "H": "Н", "K": "К", "M": "М",
        "O": "О", "P": "Р", "C": "С", "T": "Т", "X": "Х"}
LAT_RE = re.compile(r"[A-Za-z]")
CYR_RE = re.compile(r"[а-яА-ЯёЁ]")


def homoglyph_word(w):
    """Если замена латиницы на кириллические двойники делает слово полностью
    русским — вернуть исправленное слово, иначе None."""
    if not (CYR_RE.search(w) and LAT_RE.search(w)):
        return None
    mapped = "".join(HOMO.get(ch, ch) for ch in w)
    if LAT_RE.search(mapped):
        return None
    return mapped


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


def qwen_fix_word(word, sentence, glossary):
    """Попросить Qwen исправить ОДНО слово-артефакт. Вернуть замену или None."""
    prompt = (
        "Ты вычитчик русского перевода китайского веб-романа. В русском предложении "
        "встретился артефакт машинного перевода — слово, собранное из английских и "
        "русских букв: «%s».\n"
        "Предложение с этим словом: «%s»\n"
        "Замени артефакт одним русским словом или коротким словосочетанием, подходящим "
        "по смыслу. Примеры: «exertил» → «приложил», «midstе» → «середине», "
        "«thrustнуть» → «толкнуть».\n"
        "Термины перевода (словарь): %s\n"
        "Верни ТОЛЬКО исправленное слово, без кавычек и пояснений." %
        (word, sentence, glossary or "нет")
    )
    for attempt in range(5):
        try:
            r = requests.post(
                QWEN_URL,
                headers={"Authorization": "Bearer " + nf.KEY, "Content-Type": "application/json"},
                json={"model": MODEL, "temperature": 0.1,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 100},
                timeout=120)
            if r.status_code == 429:
                wait = 20 * (attempt + 1)
                log("429, жду %dс (попытка %d/5)" % (wait, attempt + 1))
                time.sleep(wait)
                continue
            r.raise_for_status()
            out = r.json()["choices"][0]["message"]["content"].strip()
            out = re.sub(r"^[\"'«]+|[\"'»]+$", "", out).splitlines()[0].strip().rstrip(",.!?")
            if not out or len(out) > 2.5 * len(word) + 6:
                return None
            if MIX_RE.search(out) or out == word:
                return None
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
        # Фаза 1: детерминированная замена «поддельной кириллицы»
        for tok in sorted(set(MIX_RE.findall(p)), key=len, reverse=True):
            hw = homoglyph_word(tok)
            if hw:
                p = p.replace(tok, hw)
                fixed_mixed += 1
                changed = True
        # Фаза 2: «полукровки» — через Qwen, по одному слову
        bad = sorted(set(MIX_RE.findall(p)))
        if bad:
            sents = re.split(r"(?<=[.!?…»])\s+", p)
            for tok in bad:
                sent = next((s for s in sents if tok in s), p)
                repl = qwen_fix_word(tok, sent, glossary)
                if repl:
                    p = p.replace(tok, repl)
                    fixed_mixed += 1
                    changed = True
                else:
                    failed_mixed += 1
                time.sleep(1)  # не долбим лимит
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
            # пропускаем только полностью починенные главы;
            # с остатком mixed_failed прогоняем заново (новые фазы дочинят)
            if key in state and isinstance(state[key], dict) \
                    and state[key].get("mixed_failed", 0) == 0:
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
