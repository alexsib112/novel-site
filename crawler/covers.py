# -*- coding: utf-8 -*-
"""
Скачивание и подготовка обложек новелл.

Обложка качается с сайта-источника, сжимается до ~300px по ширине (формат 2:3)
и сохраняется в site/covers/{name}.jpg. Это избавляет от hotlink к чужому CDN.
"""
import os
import io

import requests

from . import config

COVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site", "covers")
MAX_WIDTH = 300
QUALITY = 82


def ensure_dir():
    os.makedirs(COVER_DIR, exist_ok=True)


def download_cover(cover_url: str, name: str) -> str:
    """
    Скачивает обложку, сжимает и сохраняет. Возвращает относительный путь
    ("covers/xxx.jpg") или пустую строку при неудаче.
    """
    if not cover_url:
        return ""
    ensure_dir()
    dest = os.path.join(COVER_DIR, f"{name}.jpg")
    rel = f"covers/{name}.jpg"

    try:
        r = requests.get(cover_url, headers={"User-Agent": config.USER_AGENT},
                         timeout=30)
        r.raise_for_status()
    except Exception:
        return ""

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        # сохранить пропорции 2:3, ограничить ширину
        w, h = img.size
        if w > MAX_WIDTH:
            new_h = int(h * MAX_WIDTH / w)
            img = img.resize((MAX_WIDTH, new_h), Image.LANCZOS)
        img.save(dest, "JPEG", quality=QUALITY, optimize=True)
        return rel
    except Exception:
        # если Pillow не справился — сохранить как есть (байты)
        try:
            with open(dest, "wb") as f:
                f.write(r.content)
            return rel
        except Exception:
            return ""
