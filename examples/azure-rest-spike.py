#!/usr/bin/env python3
"""CCCP v2 — Phase 0 de-risking spike.

Exercises all 6 Azure Blob REST operations CCCP v2 needs, using ONLY the Python
standard library (urllib + xml.etree) against a real container via a SAS token.
Proves the "homebrew" stdlib+SAS approach works before the real transport is built.

Reads CCCP_ACCOUNT / CCCP_CONTAINER / CCCP_SAS from the environment, falling back
to ~/.config/cccp/config (the file infra/azure/apply.sh writes).

Run:  python3 examples/azure-rest-spike.py
Exit: 0 if every operation passed, 1 otherwise.
"""

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

API_VERSION = "2023-11-03"
PREFIX = "__spike__"


# ---------- config ----------

def load_config():
    cfg = {}
    config_file = Path.home() / ".config" / "cccp" / "config"
    if config_file.exists():
        for line in config_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    # Environment wins over the file.
    for k in ("CCCP_ACCOUNT", "CCCP_CONTAINER", "CCCP_SAS"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    missing = [k for k in ("CCCP_ACCOUNT", "CCCP_CONTAINER", "CCCP_SAS") if not cfg.get(k)]
    if missing:
        sys.exit(f"error: missing config {missing}; run infra/azure/apply.sh or set env vars")
    return cfg["CCCP_ACCOUNT"], cfg["CCCP_CONTAINER"], cfg["CCCP_SAS"].lstrip("?")


ACCOUNT, CONTAINER, SAS = load_config()


# ---------- REST helper ----------

def _url(path, query=""):
    base = f"https://{ACCOUNT}.blob.core.windows.net/{CONTAINER}"
    u = f"{base}/{path}" if path else base
    return u + "?" + "&".join(p for p in (query, SAS) if p)


def req(method, path, query="", data=None, headers=None):
    """Make one Blob REST call. Returns (status, headers_dict, body_bytes).

    HTTPError (4xx/5xx) is caught and returned like a normal response so callers
    can assert on expected failures (e.g. the 409 from a conditional create).
    """
    h = {"x-ms-version": API_VERSION}
    if headers:
        h.update(headers)
    request = urllib.request.Request(_url(path, query), data=data, method=method, headers=h)
    try:
        resp = urllib.request.urlopen(request, timeout=30)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


# ---------- test harness ----------

results = []


def check(name, ok, detail=""):
    results.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


# ---------- the 6 operations ----------

def test_put_block_blob():
    st, _, _ = req("PUT", f"{PREFIX}/hello.txt", data=b"hello cccp",
                   headers={"x-ms-blob-type": "BlockBlob"})
    check("PUT block blob", st == 201, f"status {st}")


def test_get():
    st, _, body = req("GET", f"{PREFIX}/hello.txt")
    check("GET blob", st == 200 and body == b"hello cccp", f"status {st}, body {body!r}")


def test_list():
    st, _, body = req("GET", "",
                      query=f"restype=container&comp=list&prefix={urllib.parse.quote(PREFIX)}/")
    if not check("LIST blobs", st == 200, f"status {st}"):
        return
    root = ET.fromstring(body)
    blobs = {b.findtext("Name"): b.findtext("Properties/Last-Modified")
             for b in root.findall(".//Blob")}
    hit = f"{PREFIX}/hello.txt"
    check("LIST returns blob + Last-Modified",
          bool(hit in blobs and blobs.get(hit)), f"found: {sorted(blobs)}")


def test_conditional_put():
    h = {"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}
    st1, _, _ = req("PUT", f"{PREFIX}/claim", data=b"alice@hostA", headers=h)
    check("conditional PUT — first claim", st1 == 201, f"status {st1}")
    st2, _, _ = req("PUT", f"{PREFIX}/claim", data=b"alice@hostA", headers=h)
    check("conditional PUT — second claim rejected", st2 == 409, f"status {st2} (want 409)")


def test_append_blob():
    st, _, _ = req("PUT", f"{PREFIX}/log", data=b"",
                   headers={"x-ms-blob-type": "AppendBlob"})
    if not check("create append blob", st == 201, f"status {st}"):
        return
    s1, _, _ = req("PUT", f"{PREFIX}/log", query="comp=appendblock", data=b"line1\n")
    s2, _, _ = req("PUT", f"{PREFIX}/log", query="comp=appendblock", data=b"line2\n")
    check("append blocks", s1 == 201 and s2 == 201, f"statuses {s1}, {s2}")
    st, _, body = req("GET", f"{PREFIX}/log")
    check("append blob concatenated", body == b"line1\nline2\n", f"body {body!r}")


def test_delete():
    statuses = []
    for name in ("hello.txt", "claim", "log"):
        st, _, _ = req("DELETE", f"{PREFIX}/{name}")
        statuses.append(st)
    check("DELETE blobs", all(s == 202 for s in statuses), f"statuses {statuses}")
    st, _, _ = req("GET", f"{PREFIX}/hello.txt")
    check("deleted blob is gone", st == 404, f"status {st} (want 404)")


# ---------- run ----------

def main():
    print(f"CCCP v2 spike — {ACCOUNT}/{CONTAINER}, prefix {PREFIX}/")
    for test in (test_put_block_blob, test_get, test_list,
                 test_conditional_put, test_append_blob, test_delete):
        try:
            test()
        except Exception as e:
            check(test.__name__, False, f"exception: {e!r}")
    passed, total = sum(results), len(results)
    print(f"\n{'PASS' if passed == total else 'FAIL'}: {passed}/{total} checks")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
