# -*- coding: utf-8 -*-
"""
Деплой сайта на Cloudflare Pages (Direct Upload API) — на Python (requests).

Проблема PowerShell-версии: --form-string ломал JSON manifest (экранирование).
Здесь всё формируется корректно через requests.

Использование:
  python deploy.py
"""
import base64
import hashlib
import json
import os
import sys

import requests

TOKEN = os.environ.get("CF_API_TOKEN", "")  # задать через env: CF_API_TOKEN
ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "48233e46d743a2fc3b81fda6b5153fc2")
PROJECT = os.environ.get("CF_PROJECT", "novellith")
BASE = "https://api.cloudflare.com/client/v4"
SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")

FILES = None  # формируется автоматически обходом site/ (см. collect_files)

CONTENT_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".txt": "text/plain",
    ".woff2": "font/woff2",
}


def collect_files():
    """Все файлы site/ → [(относительный путь, /remote, content-type)]."""
    out = []
    for root, _dirs, names in os.walk(SITE):
        for name in sorted(names):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, SITE).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            out.append((rel, "/" + rel, CONTENT_TYPES.get(ext, "application/octet-stream")))
    return out

H = {"Authorization": f"Bearer {TOKEN}"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def pages_hash(path):
    """Точный хэш Cloudflare Pages: SHA-256(base64(контента) + расширение)[:32]."""
    with open(path, "rb") as f:
        content = f.read()
    b64 = base64.b64encode(content).decode()
    ext = os.path.splitext(path)[1].lstrip(".")  # "html", "css", "js", "" для _headers
    return hashlib.sha256((b64 + ext).encode()).hexdigest()[:32]


def main():
    # 1. upload-token (JWT)
    print("[1/3] upload-token…")
    jwt = requests.get(
        f"{BASE}/accounts/{ACCOUNT}/pages/projects/{PROJECT}/upload-token",
        headers=H, timeout=30,
    ).json()["result"]["jwt"]

    # 2. upload files
    print("[2/3] загрузка файлов…")
    files = collect_files()
    print(f"      всего файлов: {len(files)}")
    payload = []
    manifest = {}
    for local, remote, ctype in files:
        path = os.path.join(SITE, local.replace("/", os.sep))
        with open(path, "rb") as f:
            content = f.read()
        h = pages_hash(path)
        payload.append({
            "key": h,
            "value": base64.b64encode(content).decode(),
            "metadata": {"contentType": ctype},
            "base64": True,
        })
        manifest[remote] = h
        print(f"      {remote} -> {h[:12]}… ({len(content)} байт)")

    up = requests.post(
        f"{BASE}/pages/assets/upload",
        headers={**H, "Authorization": f"Bearer {jwt}",
                 "Content-Type": "application/json"},
        json=payload, timeout=120,
    ).json()
    print(f"      upload: {up.get('result', {}).get('successful_key_count')} файлов, "
          f"success={up.get('success')}")

    # 3. create deployment
    print("[3/3] deployment…")
    dep = requests.post(
        f"{BASE}/accounts/{ACCOUNT}/pages/projects/{PROJECT}/deployments",
        headers=H,
        files={"manifest": (None, json.dumps(manifest))},  # multipart/form-data
        timeout=60,
    ).json()

    if dep.get("success"):
        print(f"\nГОТОВО: {dep['result']['url']}")
        print(f"ПРОДАКШН: https://{PROJECT}.pages.dev")
    else:
        print(f"\nОШИБКА: {json.dumps(dep, ensure_ascii=False)[:500]}")


if __name__ == "__main__":
    main()
