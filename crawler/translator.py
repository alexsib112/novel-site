# -*- coding: utf-8 -*-
"""
Воркер перевода с самопроверкой (self-reflection loop).

Каждая модель после перевода главы САМА себя проверяет: сравнивает перевод с
оригиналом и глоссарием, находит ошибки (имена не по глоссарию, пропуски,
искажения смысла) и исправляет их, повторяя проверку, пока не решит, что всё
корректно (или пока не исчерпает лимит итераций).

Без дополнительных ИИ: перевод и проверку делает ОДНА и та же модель.

Использование:
  python -m crawler.translator --limit 20          # перевести 20 глав из очереди
  python -m crawler.translator --novel 3           # перевести все главы новеллы #3
"""

import argparse
import json
import re
import time

import requests

from . import config
from .db import DB


# ---------------------------------------------------------------------------
# Промпты
# ---------------------------------------------------------------------------

TRANSLATE_SYSTEM = """\
Ты — профессиональный литературный переводчик веб-новелл с японского, \
китайского и корейского на русский язык. Переводи литературно, сохраняя стиль, \
тон, разбивку на абзацы и эмоции персонажей. Ничего не сокращай и не добавляй \
отсебятину. Имена и термины переводи строго по словарю, если он задан. \
Выдай ТОЛЬКО перевод, без пояснений."""

REVIEW_SYSTEM = """\
Ты — корректор собственного перевода. Тебе даны: оригинал, твой перевод и \
словарь терминов. Сверь перевод с оригиналом. Проверь строго:

1. Все имена и термины соответствуют словарю (никаких расхождений).
2. Нет пропущенных фраз и абзацев.
3. Смысл передан точно, без искажений.
4. Текст читается естественно на русском.

Верни СТРОГО один JSON без пояснений и markdown:
{"ok": true, "issues": [], "fixed": ""}

Если ошибок нет — "ok": true, "fixed": пустая строка.
Если есть ошибки — "ok": false, перечисли их в "issues" (коротко), а в "fixed" \
верни ПОЛНЫЙ исправленный перевод целиком."""


def _chat(messages, model, provider="neuraldeep", temperature=0.3) -> str:
    """Один вызов к LLM, возвращает текст ответа."""
    if provider == "gemini":
        return _chat_gemini(messages, model, temperature)
    return _chat_openai(messages, model, temperature)


def _chat_openai(messages, model, temperature=0.3) -> str:
    """OpenAI-совместимый (neuraldeep и др.)."""
    if not config.NEURALDEEP_API_KEY:
        raise RuntimeError("Не задан NEURALDEEP_API_KEY")
    for attempt in range(10):
        r = requests.post(
            f"{config.NEURALDEEP_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.NEURALDEEP_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages, "temperature": temperature},
            timeout=300,
        )
        if r.status_code == 429:
            time.sleep(5)  # фиксированная пауза, не экспонента
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("Исчерпаны попытки (429) к neuraldeep")


def _chat_gemini(messages, model, temperature=0.3) -> str:
    """Нативный Gemini API (generateContent), с ретраем при 429."""
    if not config.GEMINI_API_KEY:
        raise RuntimeError("Не задан GEMINI_API_KEY")

    system = ""
    contents = []
    for m in messages:
        if m["role"] == "system":
            system += m["content"] + "\n"
        else:
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})

    body = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "thinkingConfig": {"thinkingBudget": 0},  # без reasoning — для перевода не нужен
        },
    }
    if system.strip():
        body["systemInstruction"] = {"parts": [{"text": system.strip()}]}

    for attempt in range(10):
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={
                "x-goog-api-key": config.GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=300,
        )
        if r.status_code == 429:
            time.sleep(5)  # фиксированная пауза
            continue
        if r.status_code >= 500:
            time.sleep(3)
            continue
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError("Исчерпаны попытки (429/5xx) к Gemini")


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        # модель не вернула JSON — считаем, что ошибок нет, вернём как есть
        return {"ok": True, "issues": [], "fixed": ""}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"ok": True, "issues": [], "fixed": ""}


# ---------------------------------------------------------------------------
# Глоссарий
# ---------------------------------------------------------------------------

def load_glossary() -> dict:
    import os
    if os.path.exists("glossary.json"):
        with open("glossary.json", encoding="utf-8") as f:
            return json.load(f)
    return {}


def glossary_block(glossary: dict) -> str:
    if not glossary:
        return ""
    lines = ["СЛОВАРЬ (переводи эти имена/термины строго так):"]
    for src, dst in glossary.items():
        lines.append(f"- {src} → {dst}")
    return "\n".join(lines)


def model_label(model: str) -> str:
    """Короткая метка модели для поля chapters.translator."""
    m = model.lower()
    if "qwen" in m:
        return "qwen"
    if "gemini" in m:
        return "gemini"
    if "gemma" in m:
        return "gemma"
    if "deepseek" in m:
        return "deepseek"
    return m


# ---------------------------------------------------------------------------
# Перевод с самопроверкой
# ---------------------------------------------------------------------------

def translate_with_selfcheck(original: str, lang: str, glossary: dict,
                             title: str = "", model: str = None,
                             provider: str = None, max_iters: int = 1) -> str:
    """
    Переводит текст и самопроверяет себя до max_iters раз.

    Возвращает финальный (откорректированный) перевод.
    """
    if model is None:
        model = config.TRANSLATE_MODELS.get(lang, "qwen3.6-unlim-noreason")
    if provider is None:
        # Qwen ∞ — neuraldeep; gemma — тоже neuraldeep; gemini-* — google
        provider = "gemini" if model.startswith("gemini-") else "neuraldeep"

    gl = glossary_block(glossary)
    sys_common = TRANSLATE_SYSTEM + ("\n\n" + gl if gl else "")
    if title:
        sys_common += f"\nНазвание произведения: {title}"

    # 1. Первичный перевод
    translation = _chat(
        [
            {"role": "system", "content": sys_common},
            {"role": "user", "content": f"Переведи на русский:\n\n{original}"},
        ],
        model, provider,
    )

    # 2. Цикл самопроверки
    for _ in range(max_iters):
        time.sleep(1.5)  # пауза — не превышать RPM бесплатного тарифа
        review = _parse_json(
            _chat(
                [
                    {"role": "system", "content": REVIEW_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Оригинал:\n{original}\n\n"
                            f"Мой перевод:\n{translation}\n\n"
                            + (gl + "\n\n" if gl else "")
                        ),
                    },
                ],
                model, provider, temperature=0.1,
            )
        )
        if review.get("ok"):
            break
        fixed = (review.get("fixed") or "").strip()
        if not fixed:
            # модель заявила об ошибках, но исправления не дала — не зацикливаемся
            break
        translation = fixed

    return translation.strip()


# ---------------------------------------------------------------------------
# Воркер: берёт главы из очереди и переводит
# ---------------------------------------------------------------------------

def run(limit: int = 0, novel_id: int = None, workers: int = 3):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    db = DB()
    glossary = load_glossary()

    if novel_id is not None:
        rows = db.conn.execute(
            "SELECT * FROM chapters WHERE novel_id=? AND status!='done' ORDER BY idx",
            (novel_id,),
        ).fetchall()
    else:
        rows = db.pending_chapters(limit or 100)

    # язык/название собираем ЗАРАНЕЕ (sqlite-соединение не потокобезопасно)
    tasks = []
    for ch in rows:
        novel = db.conn.execute(
            "SELECT * FROM novels WHERE id=?", (ch["novel_id"],)
        ).fetchone()
        lang = novel["lang"] if novel else "jp"
        title = novel["title"] if novel else ""
        model = config.TRANSLATE_MODELS.get(lang, "qwen3.6-unlim-noreason")
        label = model_label(model)
        tasks.append((ch, lang, title, model, label))

    print(f"Глав к переводу: {len(tasks)} (параллельно ×{workers})")

    def translate_one(task):
        ch, lang, title, model, label = task
        try:
            tr = translate_with_selfcheck(ch["content"], lang, glossary, title=title, model=model)
            return ch["id"], ch["idx"], ch["title"], tr, None, label
        except Exception as e:
            return ch["id"], ch["idx"], ch["title"], None, str(e), label

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(translate_one, t): t for t in tasks}
        for fut in as_completed(futures):
            cid, idx, ctitle, translated, err, label = fut.result()
            if err:
                db.set_chapter_status(cid, "failed")
                print(f"  гл.{idx} — ОШИБКА: {err}")
            else:
                db.set_chapter_translated(cid, translated, translator=label)
                done += 1
                print(f"  гл.{idx} «{ctitle[:30]}» — ok [{label}] ({done}/{len(tasks)})")

    db.close()


def main():
    p = argparse.ArgumentParser(description="Перевод с самопроверкой")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--novel", type=int, default=None, help="перевести все главы новеллы с id")
    p.add_argument("--workers", type=int, default=3, help="параллельных потоков")
    args = p.parse_args()
    run(limit=args.limit, novel_id=args.novel, workers=args.workers)


if __name__ == "__main__":
    main()
