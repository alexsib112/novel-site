#!/usr/bin/env python3
"""Upload site content (catalog, indexes, chapters) to Cloudflare KV.

Reads data from site/data/ (catalog.json + <novel>/ dirs with index.json and chunk-*.json).
Uses Global API Key auth (scoped token lacks KV permissions).

Config: file cf_credentials.json next to this script, or env vars:
  CF_EMAIL, CF_GLOBAL_KEY, CF_ACCOUNT_ID, CF_KV_NAMESPACE_ID

Usage: python3 upload_kv.py            # upload everything
       python3 upload_kv.py lotm       # upload one novel dir (plus catalog)
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "site", "data")


def load_creds():
    path = os.path.join(HERE, "cf_credentials.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {
        "email": os.environ["CF_EMAIL"],
        "global_key": os.environ["CF_GLOBAL_KEY"],
        "account_id": os.environ["CF_ACCOUNT_ID"],
        "kv_namespace_id": os.environ["CF_KV_NAMESPACE_ID"],
    }


def _open_with_retry(req, attempts=6):
    """urllib с ретраями: 429/5xx пережидаем с экспоненциальной паузой."""
    last = None
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                wait = 20 * (attempt + 1)
                print("  HTTP %d, жду %dс (попытка %d/%d)" % (e.code, wait, attempt + 1, attempts))
                time.sleep(wait)
                continue
            raise
    raise last


def api_put(creds, key, value):
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + creds["account_id"]
        + "/storage/kv/namespaces/"
        + creds["kv_namespace_id"]
        + "/values/"
        + urllib.request.quote(key, safe="")
    )
    req = urllib.request.Request(url, data=value.encode("utf-8"), method="PUT")
    req.add_header("X-Auth-Email", creds["email"])
    req.add_header("X-Auth-Key", creds["global_key"])
    req.add_header("Content-Type", "application/json; charset=utf-8")
    with _open_with_retry(req) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError("KV write failed for %s: %s" % (key, body.get("errors")))


def api_bulk(creds, entries):
    """entries: list of (key, value). Uses bulk endpoint, 1000 per call."""
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + creds["account_id"]
        + "/storage/kv/namespaces/"
        + creds["kv_namespace_id"]
        + "/bulk"
    )
    for i in range(0, len(entries), 1000):
        chunk = entries[i : i + 1000]
        payload = json.dumps([{"key": k, "value": v} for k, v in chunk]).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="PUT")
        req.add_header("X-Auth-Email", creds["email"])
        req.add_header("X-Auth-Key", creds["global_key"])
        req.add_header("Content-Type", "application/json")
        with _open_with_retry(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("success"):
            raise RuntimeError("KV bulk write failed: %s" % body.get("errors"))
        print("  bulk uploaded %d keys (total %d/%d)" % (len(chunk), min(i + 1000, len(entries)), len(entries)))
        time.sleep(3)


def upload_novel(creds, novel_id):
    ndir = os.path.join(DATA, novel_id)
    if not os.path.isdir(ndir):
        print("skip %s: no dir" % novel_id)
        return
    index = json.load(open(os.path.join(ndir, "index.json"), encoding="utf-8"))
    api_put(creds, "novels/%s/index" % novel_id, json.dumps(index, ensure_ascii=False))
    print("%s: index (%d chapters)" % (novel_id, len(index["chapters"])))

    entries = []
    for fname in sorted(os.listdir(ndir)):
        if not fname.startswith("chunk-") or not fname.endswith(".json"):
            continue
        chunk = json.load(open(os.path.join(ndir, fname), encoding="utf-8"))
        for ch in chunk["chapters"]:
            entries.append((
                "novels/%s/chapters/%d" % (novel_id, ch["n"]),
                json.dumps({"n": ch["n"], "title": ch["title"], "content": ch["content"]}, ensure_ascii=False),
            ))
    if entries:
        api_bulk(creds, entries)
        print("%s: %d chapters" % (novel_id, len(entries)))


def synthesize_catalog():
    """Если site/data/catalog.json ещё не собран очередью — собрать из novels_queue.json + index.json."""
    qpath = os.path.join(HERE, "novels_queue.json")
    catalog = {"base": "https://novellith-18k.pages.dev", "novels": []}
    if not os.path.exists(qpath):
        return catalog
    for m in json.load(open(qpath, encoding="utf-8")):
        ndir = os.path.join(DATA, m["id"])
        ipath = os.path.join(ndir, "index.json")
        if not os.path.exists(ipath):
            continue
        idx = json.load(open(ipath, encoding="utf-8"))
        if not idx.get("chapters"):
            continue
        catalog["novels"].append({
            "id": m["id"], "title": m["ru"], "orig": m["orig"], "author": m["author"],
            "genres": m["genres"], "status": m["status"], "rating": m["rating"], "likes": m["likes"],
            "chapters": len(idx["chapters"]), "synopsis": m["synopsis"],
            "gradient": m["gradient"], "letter": m["letter"], "lang": m["lang"],
            "translated": True, "lazy": True,
            "indexUrl": "data/%s/index.json" % m["id"], "chunkSize": 25,
        })
    return catalog


def upload_catalog(creds):
    path = os.path.join(DATA, "catalog.json")
    if os.path.exists(path):
        catalog = json.load(open(path, encoding="utf-8"))
    else:
        print("catalog.json не найден (%s) — собираю из novels_queue.json + index.json" % path)
        catalog = synthesize_catalog()
    for novel in catalog.get("novels", []):
        novel.setdefault("access", "free")  # free | exclusive — решается на API, не в клиентах
    api_put(creds, "catalog", json.dumps(catalog, ensure_ascii=False))
    print("catalog: %d novels" % len(catalog.get("novels", [])))


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    creds = load_creds()
    try:
        upload_catalog(creds)
    except Exception as e:
        print("ОШИБКА заливки каталога: %s (продолжаю с новеллами)" % e)
    for name in sorted(os.listdir(DATA)):
        if only and name != only:
            continue
        if os.path.isdir(os.path.join(DATA, name)):
            try:
                upload_novel(creds, name)
            except Exception as e:
                print("ОШИБКА заливки %s: %s" % (name, e))
    print("done")


if __name__ == "__main__":
    main()
