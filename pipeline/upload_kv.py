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
    with urllib.request.urlopen(req, timeout=60) as resp:
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("success"):
            raise RuntimeError("KV bulk write failed: %s" % body.get("errors"))
        print("  bulk uploaded %d keys (total %d/%d)" % (len(chunk), min(i + 1000, len(entries)), len(entries)))
        time.sleep(1)


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


def upload_catalog(creds):
    catalog = json.load(open(os.path.join(DATA, "catalog.json"), encoding="utf-8"))
    for novel in catalog.get("novels", []):
        novel.setdefault("access", "free")  # free | exclusive — решается на API, не в клиентах
    api_put(creds, "catalog", json.dumps(catalog, ensure_ascii=False))
    print("catalog: %d novels" % len(catalog.get("novels", [])))


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    creds = load_creds()
    upload_catalog(creds)
    for name in sorted(os.listdir(DATA)):
        if only and name != only:
            continue
        if os.path.isdir(os.path.join(DATA, name)):
            upload_novel(creds, name)
    print("done")


if __name__ == "__main__":
    main()
