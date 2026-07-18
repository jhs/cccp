#!/usr/bin/env python3
"""Upgrade one cccp cell from the v2 blob layout to the v3 layout, in place,
using only server-side Azure Blob operations (Copy Blob) - blob contents never
transit this machine.

Layouts:

    v2   <prefix>/<slug>/<comrade-id>/gazette.jsonl
         <prefix>/<slug>/<comrade-id>/files/<path>
    v3   <prefix>/<slug>/gazettes/<comrade-id>.jsonl
         <prefix>/<slug>/files/<comrade-id>/<path>

Only blob keys move; the JSONL wire content is identical in v2 and v3, so no
data is rewritten. local-fs cells need no script: rename the same paths with mv.

Ordering is copy-everything, verify-everything, then delete-sources, so a crash
mid-run leaves a recoverable mixed state and re-running is idempotent (a copy
overwrites its destination; an already-migrated source is simply gone).

QUIESCE THE CELL FIRST. A v2 comrade appending mid-copy can lose its tail
(Copy Blob takes the source as of copy start), and v2 writers keep writing the
old keys afterward regardless - v2 and v3 clients cannot see each other by
design. Take a backup first if the cell matters (download every blob under
<prefix>/<slug>/).

Usage:

    python3 upgrade-cell-v2-to-v3.py <slug> \
        --account ACCOUNT --container CONTAINER --sas 'SAS' [--prefix PREFIX]
    python3 upgrade-cell-v2-to-v3.py <slug> ... --yes   # actually migrate

Each flag falls back to the matching cccp config variable
(CCCP_AZURE_BLOB_ACCOUNT / _CONTAINER / _SAS / _PREFIX). NOTE: the cccp config
file cannot be shell-sourced - the SAS value contains unquoted '&'. Extract
values line-wise instead, e.g.:

    cfg="$CCCP_PLUGIN_DATA/backend/azure-blob/config"
    getcfg() { grep "^$1=" "$cfg" | cut -d= -f2-; }
    python3 upgrade-cell-v2-to-v3.py <slug> \
        --account "$(getcfg CCCP_AZURE_BLOB_ACCOUNT)" \
        --container "$(getcfg CCCP_AZURE_BLOB_CONTAINER)" \
        --sas "$(getcfg CCCP_AZURE_BLOB_SAS)"

The SAS needs read, write, delete, and list on the container - the same grants
cccp itself uses.
"""
import argparse
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API_VERSION = "2023-11-03"


def request(base, sas, method, path, query="", headers=None):
    """One REST call. Returns (status, headers_dict, body_bytes)."""
    url = f"{base}/{path}" if path else base
    url += "?" + "&".join(p for p in (query, sas) if p)
    h = {"x-ms-version": API_VERSION}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, method=method, headers=h)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def list_blobs(base, sas, prefix):
    """All blob names and sizes under a prefix, following NextMarker pages."""
    out, marker = {}, ""
    while True:
        query = f"restype=container&comp=list&prefix={urllib.parse.quote(prefix)}"
        if marker:
            query += f"&marker={urllib.parse.quote(marker)}"
        st, _, body = request(base, sas, "GET", "", query=query)
        if st != 200:
            sys.exit(f"error: list failed with status {st}: {body[:200]!r}")
        root = ET.fromstring(body)
        for b in root.findall(".//Blob"):
            size = b.find("Properties").findtext("Content-Length")
            out[b.findtext("Name")] = int(size) if size else 0
        marker = root.findtext("NextMarker") or ""
        if not marker:
            return out


def v3_key(head, name):
    """The v3 key for a v2 blob name, or None if it is not a v2 key (already
    migrated, or unrecognized). A comrade id always carries '@' and ':', so the
    v3 top-level segments 'gazettes' and 'files' can never look like one."""
    rest = name[len(head):]
    if "/" not in rest:
        return None
    comrade, leaf = rest.split("/", 1)
    if "@" not in comrade or ":" not in comrade:
        return None   # already a v3 segment (gazettes/, files/)
    if leaf == "gazette.jsonl":
        return f"{head}gazettes/{comrade}.jsonl"
    if leaf.startswith("files/"):
        return f"{head}files/{comrade}/{leaf[len('files/'):]}"
    print(f"warning: unrecognized v2 blob left untouched: {name}")
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Upgrade one cccp cell from the v2 to the v3 blob layout.")
    ap.add_argument("slug", help="Cell slug to upgrade.")
    ap.add_argument("--account",
                    default=os.environ.get("CCCP_AZURE_BLOB_ACCOUNT"))
    ap.add_argument("--container",
                    default=os.environ.get("CCCP_AZURE_BLOB_CONTAINER"))
    ap.add_argument("--sas", default=os.environ.get("CCCP_AZURE_BLOB_SAS"))
    ap.add_argument("--prefix",
                    default=os.environ.get("CCCP_AZURE_BLOB_PREFIX",
                                           "__default__"))
    ap.add_argument("--yes", action="store_true",
                    help="Actually migrate; without it, print the plan only.")
    args = ap.parse_args()
    for flag in ("account", "container", "sas"):
        if not getattr(args, flag):
            sys.exit(f"error: --{flag} missing (no CCCP_AZURE_BLOB_"
                     f"{flag.upper()} in the environment either)")

    base = f"https://{args.account}.blob.core.windows.net/{args.container}"
    sas = args.sas.lstrip("?")
    head = f"{args.prefix}/{args.slug}/" if args.prefix else f"{args.slug}/"

    blobs = list_blobs(base, sas, head)
    plan = {name: dst for name in sorted(blobs)
            if (dst := v3_key(head, name))}
    if not plan:
        print(f"Nothing to migrate under {head!r} "
              f"({len(blobs)} blobs, all v3 or empty)")
        return
    for src, dst in plan.items():
        print(f"{src}\n  -> {dst}")
    if not args.yes:
        print(f"Dry run: {len(plan)} blobs would move - pass --yes to migrate")
        return

    # Phase 1: copy. Same-account copies usually report success synchronously;
    # a pending copy is polled until it settles.
    for src, dst in plan.items():
        print(f"Copy blob: {dst}")
        src_url = f"{base}/{urllib.parse.quote(src)}?{sas}"
        st, hdrs, body = request(base, sas, "PUT", urllib.parse.quote(dst),
                                 headers={"x-ms-copy-source": src_url})
        if st != 202:
            sys.exit(f"error: copy of {src} failed with status {st}: "
                     f"{body[:200]!r}")
        while hdrs.get("x-ms-copy-status") == "pending":
            time.sleep(1)
            st, hdrs, _ = request(base, sas, "HEAD", urllib.parse.quote(dst))
        if hdrs.get("x-ms-copy-status") != "success":
            sys.exit(f"error: copy of {src} ended "
                     f"{hdrs.get('x-ms-copy-status')!r}, not 'success'")

    # Phase 2: verify every destination before deleting anything.
    for src, dst in plan.items():
        st, hdrs, _ = request(base, sas, "HEAD", urllib.parse.quote(dst))
        got = int(hdrs.get("Content-Length", -1))
        if st != 200 or got != blobs[src]:
            sys.exit(f"error: verify of {dst} failed: status {st}, "
                     f"{got} bytes vs source {blobs[src]}; nothing deleted")
    print(f"Verified {len(plan)} copies")

    # Phase 3: delete the v2 sources.
    for src in plan:
        st, _, body = request(base, sas, "DELETE", urllib.parse.quote(src))
        if st != 202:
            sys.exit(f"error: delete of {src} failed with status {st}: "
                     f"{body[:200]!r}")
    print(f"Migrated cell {args.slug!r}: {len(plan)} blobs now v3")


if __name__ == "__main__":
    main()
