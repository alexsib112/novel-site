# -*- coding: utf-8 -*-
"""
ИИ-извлечение структуры новеллы из «грязного» HTML → чистый JSON.

Использует Qwen (neuraldeep, безлимит) как основной парсер.
Gemini (vision) — опционально, для сложных/динамических страниц.

Два режима:
  mode="toc"     — из ОГЛАВЛЕНИЯ: метаданные + список глав СО ССЫЛКАМИ.
  mode="chapter" — из СТРАНИЦЫ ГЛАВЫ: заголовок + ПОЛНЫЙ текст главы.
"""

import json
import re
import requests

from . import config


TOC_PROMPT = """\
Ты — парсер оглавления веб-новеллы. Тебе дан HTML-код страницы-оглавления \
(списка глав) сайта веб-новелл на японском, китайском или корейском.

Верни СТРОГО один JSON без пояснений и markdown-обёрток:

{"title": "...", "title_orig": "...", "author": "...", "synopsis": "...",
 "status": "ongoing|completed",
 "chapters": [{"index": 1, "title": "...", "url": "полная ссылка на главу"}]}

Правила:
- title — переведённое название (нет перевода — оставь оригинал).
- title_orig — название на языке оригинала.
- chapters — ПОЛНЫЙ список глав с номерами и ссылками.
- url — абсолютная ссылка на страницу главы (если в HTML относительная, \
  дополни её базовым доменом сайта).
- Не включай текст самих глав. Убери рекламу и меню.
- Если поле отсутствует — пустая строка "".
"""

CHAPTER_PROMPT = """\
Ты — парсер главы веб-новеллы. Тебе дан HTML-код страницы одной главы \
сайта веб-новелл на японском, китайском или корейском.

Верни СТРОГО один JSON без пояснений и markdown-обёрток:

{"title": "...", "content": "..."}

Правила:
- title — название главы.
- content — ПОЛНЫЙ текст главы, дословно, ничего не сокращай и не пересказывай.
- Убери рекламу, навигацию, меню, кнопки, счётчики, комментарии, «след./пред. глава».
- Сохрани диалоги и абзацы. Не добавляй ничего от себя.
"""


def _parse_json(text: str) -> dict:
    """Достаёт JSON из ответа модели (убирает ```json ... ``` и мусор)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"В ответе нет JSON: {text[:200]}")
    return json.loads(text[start : end + 1])


def _chat(messages, use_gemini=False) -> str:
    """Один вызов к LLM, возвращает текст ответа."""
    if use_gemini:
        return _chat_gemini(messages)
    return _chat_qwen(messages)


def _chat_qwen(messages) -> str:
    """Qwen через neuraldeep (OpenAI-совместимый)."""
    if not config.NEURALDEEP_API_KEY:
        raise RuntimeError("Не задан NEURALDEEP_API_KEY")
    r = requests.post(
        f"{config.NEURALDEEP_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.NEURALDEEP_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": config.EXTRACT_MODEL, "messages": messages, "temperature": 0.1},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _chat_gemini(messages) -> str:
    """Gemini (нативный generateContent)."""
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
            "temperature": 0.1,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if system.strip():
        body["systemInstruction"] = {"parts": [{"text": system.strip()}]}

    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent",
        headers={
            "x-goog-api-key": config.GEMINI_API_KEY,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def extract(html: str, source_name: str = "", mode: str = "chapter",
            use_gemini: bool = False) -> dict:
    """Единая точка входа. mode: 'toc' | 'chapter'."""
    prompt = TOC_PROMPT if mode == "toc" else CHAPTER_PROMPT
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Источник: {source_name}\n\nHTML:\n{html}"},
    ]
    content = _chat(messages, use_gemini=use_gemini)
    return _parse_json(content)
