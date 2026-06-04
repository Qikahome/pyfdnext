"""pyfdnext HTTP API Server

Compatible with fdnext TS server format: JSON wrapped in HTML <p> tags.

Usage:
    python -m pyfdnext.server              # 0.0.0.0:8000
    python -m pyfdnext.server --port 8080
"""

import json
import os
import sys
from argparse import ArgumentParser
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Response

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from pyfdnext import (
    decode_and_merge_pn,
    decode_and_merge_id,
    search_part_number,
    get_manager,
    load_fdb,
)
from pyfdnext.translate import translate_output

app = FastAPI(title="pyfdnext API", version="1.0.0")
_manager = get_manager()


# ── helpers ─────────────────────────────────────────────────────

def html_json(payload: dict[str, Any]) -> Response:
    """Wrap JSON in HTML <p> tag, as FlashDetail expects."""
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    return Response(
        content=f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head><body><p>{raw}</p></body></html>",
        media_type="text/html; charset=utf-8",
    )


def ok(data: Any = None) -> Response:
    if data is None:
        data = {}
    return html_json({"result": True, "data": data})


def fail(msg: str = "Not found") -> Response:
    return html_json({"result": False, "message": msg})


# ── index ───────────────────────────────────────────────────────

@app.get("/")
def index():
    return ok({
        "endpoints": ["/", "/info", "/decode", "/decodeId", "/searchPn",
                       "/searchId", "/summary", "/summaryId", "/capabilities"],
    })


@app.get("/info")
def info():
    return ok({
        "ver": "1.0.0",
        "decoderCount": len(_manager._decoders),
    })


# ── decode / decodeId ───────────────────────────────────────────

@app.get("/decode")
def decode_pn(
    pn: str = Query("", description="Part number"),
    lang: str = Query("eng", description="Language"),
):
    if not pn:
        return fail("Missing part number")
    result = decode_and_merge_pn(pn, _manager, lang=lang)
    if result is None:
        return fail("Not found")
    return ok(result)


@app.get("/decodeId")
def decode_id(
    id: str = Query("", description="Flash ID hex string"),
    lang: str = Query("eng", description="Language"),
):
    if not id:
        return fail("Missing Flash Id")
    result = decode_and_merge_id(id, _manager, lang=lang)
    if result is None:
        return fail("Not found")
    return ok(result)


# ── search ──────────────────────────────────────────────────────

@app.get("/searchPn")
def search_pn(
    q: str = Query(None, description="Search query"),
    pn: str = Query(None, description="Alias for q (FlashDetail compat)"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    query = pn or q or ""
    results = search_part_number(query, _manager, limit=limit, lang=lang)
    return ok(results)


@app.get("/searchId")
def search_id(
    id: str = Query("", description="Flash ID to search"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    """Search FDB by flash ID prefix. """
    if not id:
        return fail("Missing Flash Id")
    q = id.strip().upper()
    fdb = load_fdb()
    results: list[dict[str, Any]] = []
    for vk, vm in fdb.items():
        if vk == "info" or not isinstance(vm, dict):
            continue
        for pn, rec in vm.items():
            ids = rec.get("id", [])
            if isinstance(ids, list) and any(i.startswith(q) for i in ids):
                entry = rec.copy()
                entry["vendor"] = vk
                entry["partNumber"] = pn
                results.append(translate_output(entry, lang))
                if limit > 0 and len(results) >= limit:
                    break
        if limit > 0 and len(results) >= limit:
            break
    return ok(results)


# ── summary ─────────────────────────────────────────────────────

@app.get("/summary")
def summary(
    pn: str = Query("", description="Part number"),
    lang: str = Query("eng", description="Language"),
):
    if not pn:
        return fail("Missing part number")
    result = decode_and_merge_pn(pn, _manager, lang=lang)
    if result is None:
        return fail("Not found")
    # Build a concise summary string like TS engine.getSummary()
    parts = [
        f"Vendor: {result.get('vendor','?')}",
        f"Type: {result.get('type','?')}",
        f"Density: {result.get('density','?')}",
        f"Cell: {result.get('cellLevel','?')}",
    ]
    return ok(" | ".join(parts))


@app.get("/summaryId")
def summary_id(
    id: str = Query("", description="Flash ID"),
    lang: str = Query("eng", description="Language"),
):
    if not id:
        return fail("Missing Flash Id")
    result = decode_and_merge_id(id, _manager, lang=lang)
    if result is None:
        return fail("Not found")
    parts = [
        f"Vendor: {result.get('vendor','?')}",
        f"Type: {result.get('type','?')}",
        f"Density: {result.get('density','?')}",
    ]
    return ok(" | ".join(parts))


# ── capabilities ────────────────────────────────────────────────

@app.get("/capabilities")
def capabilities(lang: str = Query("eng", description="Language")):
    """返回纯 JSON（官方 fdnext.capabilities.v2 格式）。"""
    fdb = load_fdb()
    pn_count = sum(len(v) for k, v in fdb.items() if k != "info" and isinstance(v, dict))
    id_count = 0
    for k, v in fdb.items():
        if k == "info" or not isinstance(v, dict):
            continue
        for rec in v.values():
            ids = rec.get("id", [])
            if isinstance(ids, list):
                id_count += len(ids)

    fdb_info = fdb.get("info", {})
    controllers = fdb_info.get("controllers", [])

    # 官方格式：纯 JSON，不包 result/data
    return {
        "schemaVersion": "fdnext.capabilities.v2",
        "server": {
            "name": "pyfdnext",
            "version": "1.0.0",
        },
        "fdb": {
            "name": fdb_info.get("name", "pyfdnext FDB"),
            "version": fdb_info.get("version", "?"),
            "time": fdb_info.get("time", ""),
            "website": fdb_info.get("website", "https://github.com/iTXTech/FlashDetector"),
        },
        "inventory": {
            "metrics": [
                {"id": "part_numbers", "label": "Part Number Records", "count": pn_count},
                {"id": "flash_ids", "label": "NAND Flash IDs", "count": id_count},
                {"id": "controllers", "label": "Controller Models", "count": len(controllers)},
                {"id": "decoders", "label": "PN Decoders", "count": len(_manager._decoders)},
            ],
            "controllers": {
                "count": len(controllers),
                "items": controllers,
            },
        },
    }


# ── main ────────────────────────────────────────────────────────

def main():
    parser = ArgumentParser(description="pyfdnext HTTP API Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("pyfdnext.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
