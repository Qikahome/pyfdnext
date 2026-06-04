"""pyfdnext HTTP API Server

Compatible with fdnext 3.0 API (new paths) + old paths for FlashDetail.

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
from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

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
from pyfdnext.decoders import BaseDecoder
from pyfdnext.translate import translate_output

app = FastAPI(title="pyfdnext API", version="1.0.0")

# CORS: allow all origins (required for web frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
_manager = get_manager()
SERVER_NAME = "pyfdnext"


# ── custom 404 for unmapped paths ────────────────────────────────

@app.exception_handler(404)
def not_found_handler(request: Request, exc):
    return Response(
        content=json.dumps({"status": "not_found", "name": SERVER_NAME}),
        media_type="application/json; charset=utf-8",
        status_code=404,
    )


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def html_json(payload: dict[str, Any]) -> Response:
    """Wrap JSON in HTML <p> tag (old FlashDetail compat)."""
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    return Response(
        content=f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head><body><p>{raw}</p></body></html>",
        media_type="text/html; charset=utf-8",
    )

def old_ok(data: Any = None) -> Response:
    if data is None:
        data = {}
    return html_json({"result": True, "data": data})

def old_fail(msg: str = "Not found") -> Response:
    return html_json({"result": False, "message": msg})


# ── new result builder (fdnext.result.v1) ────────────────────────

def new_decode_result(
    operation: str,
    query: str,
    decoded: dict[str, Any] | None,
    lang: str,
) -> dict[str, Any]:
    """Build fdnext.result.v1 for decode operations."""
    result: dict[str, Any] = {
        "schemaVersion": "fdnext.result.v1",
        "operation": operation,
        "status": "ok" if decoded else "not_found",
        "input": {"query": query},
        "relations": [],
        "links": [],
        "warnings": [],
        "candidates": [],
    }

    if decoded:
        vendor_id = (decoded.get("vendor") or "").lower()
        result["device"] = {
            "vendor": {"id": vendor_id, "display": decoded.get("vendor", "?")},
            "chipKind": _chip_kind(decoded),
            "productType": decoded.get("type", "?"),
            "partNumber": decoded.get("partNumber", query),
            "identifier": decoded.get("flashId", ""),
        }
        result["subtitle"] = f"{decoded.get('vendor','?')} {decoded.get('partNumber','')}"

        # blocks
        blocks: list[dict[str, Any]] = []
        field_order = [
            "vendor", "partNumber", "type", "density", "deviceWidth",
            "cellLevel", "voltage", "generation", "processNode",
            "die", "plane", "pageSize", "package",
        ]
        fields: list[dict[str, Any]] = []
        for k in field_order:
            v = decoded.get(k)
            if v and v not in ("?", "Unknown", "未知", ""):
                fields.append({"key": k, "value": str(v), "display": str(v)})
        if fields:
            blocks.append({"title": "Details", "fields": fields})

        # extra fields not in field_order
        extra_fields: list[dict[str, Any]] = []
        for k, v in decoded.items():
            if k in ("flashId", "_match", "_mode", "_info") or k.startswith("_"):
                continue
            if k in field_order:
                continue
            if v and v not in ("?", "Unknown", "未知", ""):
                extra_fields.append({"key": k, "value": str(v), "display": str(v)})
        if extra_fields:
            blocks.append({"title": "Extra", "fields": extra_fields})

        result["blocks"] = blocks
    else:
        result["device"] = None
        result["subtitle"] = None
        result["blocks"] = []

    return result


def new_search_result(
    operation: str,
    query: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build fdnext.result.v1 for search operations."""
    result: dict[str, Any] = {
        "schemaVersion": "fdnext.result.v1",
        "operation": operation,
        "status": "ok" if items else "not_found",
        "input": {"query": query},
        "device": None,
        "subtitle": None,
        "blocks": [],
        "items": [],
        "relations": [],
        "links": [],
        "warnings": [],
        "candidates": [],
    }

    for item in items:
        fields: list[dict[str, Any]] = []
        for k in ("vendor", "partNumber", "type", "density", "cellLevel"):
            v = item.get(k)
            if v and v not in ("?", "Unknown", "未知", ""):
                fields.append({"key": k, "value": str(v), "display": str(v)})
        result["items"].append({
            "fields": fields,
            "links": [],
        })

    return result


def _chip_kind(decoded: dict[str, Any]) -> str:
    t = (decoded.get("type") or "").lower()
    if "dram" in t:
        return "dram"
    if "nand" in t:
        return "raw_nand"
    return "unknown"


# ═══════════════════════════════════════════════════════════════════
#  NEW API (fdnext 3.0 paths)
#  Pure JSON, fdnext.result.v1 / fdnext.capabilities.v2 format
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
def index():
    return {"status": "ok", "name": SERVER_NAME, "version": "1.0.0"}


@app.get("/parts/decode")
def parts_decode(
    query: str = Query("", description="Part number"),
    lang: str = Query("eng", description="Language"),
):
    if not query:
        return {"status": "invalid_input", "name": SERVER_NAME, "message": "Missing query"}
    decoded = decode_and_merge_pn(query, _manager, lang=lang)
    return new_decode_result("part.decode", query, decoded, lang)


@app.get("/parts/search")
def parts_search(
    query: str = Query("", description="Search query"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    if not query:
        return {"status": "invalid_input", "name": SERVER_NAME, "message": "Missing query"}
    results = search_part_number(query, _manager, limit=limit, lang=lang)
    return new_search_result("part.search", query, results)


@app.get("/identifiers/decode")
def identifiers_decode(
    query: str = Query("", description="Flash ID or typed identifier"),
    lang: str = Query("eng", description="Language"),
):
    if not query:
        return {"status": "invalid_input", "name": SERVER_NAME, "message": "Missing query"}
    decoded = decode_and_merge_id(query, _manager, lang=lang)
    return new_decode_result("identifier.decode", query, decoded, lang)


@app.get("/identifiers/search")
def identifiers_search(
    query: str = Query("", description="Flash ID prefix"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    if not query:
        return {"status": "invalid_input", "name": SERVER_NAME, "message": "Missing query"}
    q = query.strip().upper()
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
    return new_search_result("identifier.search", query, results)


# ── capabilities (pure JSON, fdnext.capabilities.v2) ─────────────

@app.get("/capabilities")
def capabilities(lang: str = Query("eng", description="Language")):
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

    pn_decoder_ids: list[str] = []
    id_decoder_ids: list[str] = []
    base_check_pn = BaseDecoder.check_pn
    base_check_id = BaseDecoder.check_id
    for d in _manager._decoders:
        if d.check_pn.__func__ is not base_check_pn:
            pn_decoder_ids.append(d.id)
        if d.check_id.__func__ is not base_check_id:
            id_decoder_ids.append(d.id)

    return {
        "schemaVersion": "fdnext.capabilities.v2",
        "server": {
            "name": SERVER_NAME,
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
                {"id": "pn_decoders", "label": "PN Decoders", "count": len(pn_decoder_ids)},
                {"id": "id_decoders", "label": "Flash ID Decoders", "count": len(id_decoder_ids)},
            ],
            "controllers": {
                "count": len(controllers),
                "items": controllers,
            },
        },
        "decoders": {
            "partNumber": [{"id": did, "priority": 950} for did in pn_decoder_ids],
            "identifier": [{"id": did, "idScheme": "nand.flash_id", "priority": 400} for did in id_decoder_ids],
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  OLD API (FlashDetail backward compat)
#  HTML wrapped, {"result": ..., "data": ...} format
# ═══════════════════════════════════════════════════════════════════

@app.get("/info")
def old_info():
    return old_ok({"ver": "1.0.0", "decoderCount": len(_manager._decoders)})


@app.get("/decode")
def old_decode(
    pn: str = Query("", description="Part number"),
    lang: str = Query("eng", description="Language"),
):
    if not pn:
        return old_fail("Missing part number")
    result = decode_and_merge_pn(pn, _manager, lang=lang)
    if result is None:
        return old_fail("Not found")
    return old_ok(result)


@app.get("/decodeId")
def old_decode_id(
    id: str = Query("", description="Flash ID hex string"),
    lang: str = Query("eng", description="Language"),
):
    if not id:
        return old_fail("Missing Flash Id")
    result = decode_and_merge_id(id, _manager, lang=lang)
    if result is None:
        return old_fail("Not found")
    return old_ok(result)


@app.get("/searchPn")
def old_search_pn(
    q: str = Query(None, description="Search query"),
    pn: str = Query(None, description="Alias for q"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    query = pn or q or ""
    results = search_part_number(query, _manager, limit=limit, lang=lang)
    return old_ok(results)


@app.get("/searchId")
def old_search_id(
    id: str = Query("", description="Flash ID to search"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    if not id:
        return old_fail("Missing Flash Id")
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
    return old_ok(results)


@app.get("/summary")
def old_summary(
    pn: str = Query("", description="Part number"),
    lang: str = Query("eng", description="Language"),
):
    if not pn:
        return old_fail("Missing part number")
    result = decode_and_merge_pn(pn, _manager, lang=lang)
    if result is None:
        return old_fail("Not found")
    parts = [
        f"Vendor: {result.get('vendor','?')}",
        f"Type: {result.get('type','?')}",
        f"Density: {result.get('density','?')}",
        f"Cell: {result.get('cellLevel','?')}",
    ]
    return old_ok(" | ".join(parts))


@app.get("/summaryId")
def old_summary_id(
    id: str = Query("", description="Flash ID"),
    lang: str = Query("eng", description="Language"),
):
    if not id:
        return old_fail("Missing Flash Id")
    result = decode_and_merge_id(id, _manager, lang=lang)
    if result is None:
        return old_fail("Not found")
    parts = [
        f"Vendor: {result.get('vendor','?')}",
        f"Type: {result.get('type','?')}",
        f"Density: {result.get('density','?')}",
    ]
    return old_ok(" | ".join(parts))


# ── health (old) ────────────────────────────────────────────────

@app.get("/health")
def old_health():
    return old_ok({"status": "ok"})


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = ArgumentParser(description="pyfdnext HTTP API Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("pyfdnext.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
