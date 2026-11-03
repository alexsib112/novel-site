# -*- coding: utf-8 -*-
"""
Настройки конвейера: краулинг + ИИ-извлечение + очередь на перевод.

Ключи задаются через переменные окружения:
  NEURALDEEP_API_KEY  — ключ neuraldeep (Qwen безлимит / Gemma по токенам)
  GEMINI_API_KEY      — ключ Google AI Studio (Gemini Flash, JP/KR перевод)
"""

import os

# --- neuraldeep (OpenAI-совместимый, оплата в рублях) ---
NEURALDEEP_BASE_URL = os.environ.get(
    "NEURALDEEP_BASE_URL", "https://api.neuraldeep.ru/v1"
)
NEURALDEEP_API_KEY = os.environ.get("NEURALDEEP_API_KEY", "")

# Модель для ИЗВЛЕЧЕНИЯ структуры из HTML (безлимитный Qwen).
# -reason версии без цепочки рассуждений — быстрее и дешевле.
EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "qwen3.6-unlim-noreason")

# Модели для ПЕРЕВОДА (используются конвейером перевода).
# Всё через Qwen ∞ (безлимит) — Gemini временно не используется.
TRANSLATE_MODELS = {
    "cn": os.environ.get("TRANSLATE_CN", "qwen3.6-unlim-noreason"),
    "jp": os.environ.get("TRANSLATE_JP", "qwen3.6-unlim-noreason"),
    "kr": os.environ.get("TRANSLATE_KR", "qwen3.6-unlim-noreason"),
}

# --- Gemini (Google AI Studio) — опционально для vision-парсинга и JP/KR ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

# --- База данных ---
DB_PATH = os.environ.get("NOVEL_DB", "novels.db")

# --- Краулер ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
REQUEST_TIMEOUT = 30
# Пауза между запросами к одному сайту (вежливость, избегание банов).
CRAWL_DELAY = 1.0

# --- Источники ---
# Каждый источник: как найти список новелл и как вытащить главы.
SOURCES = {
    "syosetu": {
        "lang": "jp",
        "name": "小説家になろう (syosetu)",
        "catalog": "narou",   # есть официальный API
    },
    "biquge": {
        "lang": "cn",
        "name": "笔趣阁 (biquge)",
        "catalog": "html",
    },
    "munpia": {
        "lang": "kr",
        "name": "문피아 (munpia)",
        "catalog": "html",
    },
}
