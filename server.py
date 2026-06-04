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


# ── field labels for display ──────────────────────────────────

_FIELD_LABELS: dict[str, str] = {
    "density": "Density",
    "cellLevel": "Cell Level",
    "deviceWidth": "Device Width",
    "voltage": "Voltage",
    "package": "Package",
    "dieCode": "Process",
    "processNode": "Process",
    "classification": "Classification",
    "type": "Type",
    "generation": "Generation",
    "pageSize": "Page size",
    "die": "Die Count",
    "plane": "Plane Count",
    "ce": "CE Count",
    "ch": "Channel Count",
    "controller": "Controller",
    "partNumber": "Part Number",
    "vendor": "Vendor",
    "densityCode": "Density Code",
    "packageCode": "Package Code",
}

_CHIP_KIND: dict[str, str] = {
    "NAND": "raw_nand",
    "nand": "raw_nand",
    "DRAM": "dram",
    "dram": "dram",
    "eMMC": "managed_nand",
    "emmc": "managed_nand",
    "UFS": "managed_nand",
    "ufs": "managed_nand",
}


def _resolve_chip_kind(decoded: dict[str, Any]) -> str:
    t = (decoded.get("type") or "").lower()
    if "dram" in t:
        return "dram"
    if "emmc" in t or "ufs" in t:
        return "managed_nand"
    return "raw_nand"


def _parse_density(val: str) -> tuple[int | None, str | None, str | None]:
    """Parse density string like '16Gb' → (16384, 'Mbit', '2GB')."""
    if not val or not isinstance(val, str):
        return None, None, None
    val = val.strip().upper()
    import re
    m = re.match(r'(\d+)\s*(GB|GIB|MB|MIB|KB|KIB|GBIT|MBIT|KBIT|G|M|K)B?', val)
    if not m:
        # try removing 'b' or 'B' at end
        m = re.match(r'(\d+)\s*(G|M|K)', val)
    if not m:
        # try 'Gb' as gigabit
        m = re.match(r'(\d+)\s*G\s*B?', val)
    if m:
        num = int(m.group(1))
        unit_str = m.group(2).upper()
        # convert to Mbit
        if unit_str.startswith('G') or unit_str.startswith('T'):
            multiplier = 1024 if 'I' in unit_str else 1000
            if 'B' in val.upper() and 'I' not in val.upper() and 'bit' not in val.lower():
                # GByte → Gbit * 8
                value_mbit = num * multiplier * 8
            else:
                value_mbit = num * multiplier
            if value_mbit < 1000000:
                display_unit = "Mbit"
                display_val = value_mbit
            else:
                display_val = value_mbit
                display_unit = "Mbit"
        elif unit_str.startswith('M'):
            value_mbit = num
            display_val = value_mbit
            display_unit = "Mbit"
        elif unit_str.startswith('K'):
            value_mbit = num // 1024 if num >= 1024 else num / 1024
            display_val = value_mbit
            display_unit = "Mbit"
        else:
            return None, None, None

        # build display string
        if display_val >= 1024 and display_val % 1024 == 0:
            display = f"{display_val // 1024}GB"
        elif display_val >= 1024:
            display = f"{display_val / 1024:.1f}GB"
        elif display_val >= 1:
            display = f"{display_val}Mb"
        else:
            display = str(display_val)

        return int(display_val), display_unit, display

    return None, None, None


def _make_field(key: str, value: Any, importance: str = "secondary") -> dict[str, Any]:
    """Build a field dict matching fdnext.result.v1 format."""
    label = _FIELD_LABELS.get(key, key)
    field: dict[str, Any] = {"key": key, "label": label, "value": value, "importance": importance}

    # special handling for known fields
    if key == "density" and isinstance(value, str):
        v, u, d = _parse_density(value)
        if v is not None:
            field["value"] = v
            field["unit"] = u
            field["display"] = d

    if key == "deviceWidth" and isinstance(value, str):
        m = __import__("re").match(r'[xX](\d+)', value)
        if m:
            field["value"] = int(m.group(1))
            field["unit"] = "bit"
            field["display"] = value
        else:
            field["display"] = str(value)

    return field


def _make_device(decoded: dict[str, Any], query: str) -> dict[str, Any]:
    """Build device object."""
    vendor_name = decoded.get("vendor", "?")
    vendor_id = vendor_name.lower().replace(" ", "_") if vendor_name and vendor_name != "?" else "unknown"
    d: dict[str, Any] = {
        "domain": "memory",
        "chipKind": _resolve_chip_kind(decoded),
        "vendor": {"id": vendor_id, "name": vendor_name},
    }
    if decoded.get("partNumber"):
        d["partNumber"] = decoded["partNumber"]
    if decoded.get("flashId"):
        d["identifier"] = decoded["flashId"] if isinstance(decoded["flashId"], str) else decoded["flashId"][0]
    if decoded.get("id"):
        ids = decoded["id"]
        if isinstance(ids, list) and ids:
            d["identifier"] = ids[0]
    return d


def _build_blocks(decoded: dict[str, Any]) -> list[dict[str, Any]]:
    """Build blocks array from decoded data."""
    blocks: list[dict[str, Any]] = []

    # ── storage block (primary) ──
    storage_fields: list[dict[str, Any]] = []
    for k in ("density", "cellLevel"):
        v = decoded.get(k)
        if v and v not in ("?", "Unknown", "未知", ""):
            storage_fields.append(_make_field(k, v, "primary"))
    # process/dieCode
    for k in ("dieCode", "processNode", "generation"):
        v = decoded.get(k)
        if v and v not in ("?", "Unknown", "未知", ""):
            storage_fields.append(_make_field(k, v, "secondary"))
    if storage_fields:
        blocks.append({
            "id": "storage",
            "label": "Storage",
            "importance": "primary",
            "fields": storage_fields,
        })

    # ── geometry block (secondary) ──
    geo_fields: list[dict[str, Any]] = []
    classification = decoded.get("classification")
    if isinstance(classification, dict):
        die = classification.get("die")
        if die and die not in ("?", "Unknown", "?"):
            geo_fields.append(_make_field("die", die, "secondary"))
        ce = classification.get("ce")
        if ce and ce not in ("?", "Unknown", "?"):
            geo_fields.append(_make_field("ce", ce, "secondary"))
        ch = classification.get("ch")
        if ch and ch not in ("?", "Unknown", "?"):
            geo_fields.append(_make_field("ch", ch, "secondary"))
    # plane from decoded top level
    for k in ("die", "plane", "pageSize"):
        v = decoded.get(k)
        if v and v not in ("?", "Unknown", "未知", ""):
            geo_fields.append(_make_field(k, v, "secondary"))
    if geo_fields:
        blocks.append({
            "id": "geometry",
            "label": "Geometry",
            "importance": "secondary",
            "fields": geo_fields,
        })

    # ── interface block (secondary) ──
    iface_fields: list[dict[str, Any]] = []
    for k in ("deviceWidth", "voltage"):
        v = decoded.get(k)
        if v and v not in ("?", "Unknown", "未知", ""):
            iface_fields.append(_make_field(k, v, "secondary"))
    if iface_fields:
        blocks.append({
            "id": "interface",
            "label": "Interface",
            "importance": "secondary",
            "fields": iface_fields,
        })

    # ── package block (detail) ──
    pkg_fields: list[dict[str, Any]] = []
    for k in ("package",):
        v = decoded.get(k)
        if v and v not in ("?", "Unknown", "未知", ""):
            pkg_fields.append(_make_field(k, v, "secondary"))
    if pkg_fields:
        blocks.append({
            "id": "package",
            "label": "Package",
            "importance": "detail",
            "fields": pkg_fields,
        })

    # ── controllers block (detail) ──
    ctrl = decoded.get("controller") or decoded.get("t")
    if ctrl:
        if isinstance(ctrl, str):
            ctrl = [ctrl]
        blocks.append({
            "id": "controllers",
            "label": "Controllers",
            "importance": "detail",
            "fields": [
                _make_field("controller", ctrl, "secondary")
            ],
        })

    return blocks


def _build_relations_for_pn(decoded: dict[str, Any]) -> list[dict[str, Any]]:
    """Build relations for part decode result (link to identifier decode)."""
    relations: list[dict[str, Any]] = []
    ids = decoded.get("id") or decoded.get("flashId")
    if isinstance(ids, str):
        ids = [ids]
    if isinstance(ids, list):
        for fid in ids:
            if fid and isinstance(fid, str):
                relations.append({
                    "kind": "identifier_for",
                    "target": {
                        "identifier": fid,
                        "idScheme": "nand.flash_id",
                    },
                    "action": {
                        "name": "identifier.decode",
                        "label": "Decode NAND Flash ID",
                        "operation": "identifier.decode",
                        "input": {"query": fid, "constraints": {"idScheme": "nand.flash_id"}},
                    },
                })
    return relations


def _build_relations_for_id(decoded: dict[str, Any]) -> list[dict[str, Any]]:
    """Build relations for identifier decode (link to part decode)."""
    relations: list[dict[str, Any]] = []
    fid = decoded.get("id") or decoded.get("flashId")
    if isinstance(fid, list):
        fid = fid[0] if fid else None
    source_id = fid or ""
    # gather related part numbers from fdb
    fdb = load_fdb()
    vendor_name = decoded.get("vendor", "")
    vendor_key = vendor_name.lower().replace(" ", "_") if vendor_name else ""
    # find matching PNs in fdb
    related_pns: list[str] = []
    for vk, vm in fdb.items():
        if vk == "info" or not isinstance(vm, dict):
            continue
        if vendor_key and vk != vendor_key:
            continue
        for pn, rec in vm.items():
            ids = rec.get("id", [])
            if isinstance(ids, list) and source_id in ids:
                related_pns.append((vk, pn))
                if len(related_pns) >= 20:
                    break
        if len(related_pns) >= 20:
            break

    for vk, pn in related_pns:
        relations.append({
            "kind": "identifier_for",
            "source": {"identifier": source_id, "idScheme": "nand.flash_id"},
            "target": {"partNumber": pn},
            "action": {
                "name": "part.decode",
                "label": "Decode Part",
                "operation": "part.decode",
                "input": {"query": pn, "constraints": {"vendor": vk, "chipKind": "raw_nand"}},
            },
        })

    return relations


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
        "input": {"query": query, "normalized": query.upper(), "lang": lang, "constraints": {}},
        "relations": [],
        "links": [],
        "warnings": [],
        "candidates": [],
    }

    if decoded:
        # device
        result["device"] = _make_device(decoded, query)

        # subtitle
        vendor_name = decoded.get("vendor", "?")
        pn = decoded.get("partNumber", query)
        density = decoded.get("density", "")
        cell = decoded.get("cellLevel", "")
        subtitle_parts = [f"{vendor_name}", pn]
        if density:
            subtitle_parts.insert(1, density)
        if cell:
            subtitle_parts.append(cell)
        result["subtitle"] = " · ".join(subtitle_parts)

        # blocks
        result["blocks"] = _build_blocks(decoded)

        # relations
        if operation == "part.decode":
            result["relations"] = _build_relations_for_pn(decoded)
        elif operation == "identifier.decode":
            result["relations"] = _build_relations_for_id(decoded)
    else:
        result["device"] = None
        result["subtitle"] = None
        result["blocks"] = []

    return result


def new_search_result(
    operation: str,
    query: str,
    items: list[dict[str, Any]],
    lang: str = "eng",
) -> dict[str, Any]:
    """Build fdnext.result.v1 for search operations."""
    result: dict[str, Any] = {
        "schemaVersion": "fdnext.result.v1",
        "operation": operation,
        "status": "ok" if items else "not_found",
        "input": {"query": query, "normalized": query.upper(), "lang": lang, "constraints": {}},
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
        vendor_name = item.get("vendor", "?")
        vendor_id = vendor_name.lower().replace(" ", "_") if vendor_name != "?" else "unknown"
        pn = item.get("partNumber", "")

        # device object
        device: dict[str, Any] = {
            "domain": "memory",
            "chipKind": "raw_nand",
            "vendor": {"id": vendor_id, "name": vendor_name},
        }
        if pn:
            device["partNumber"] = pn

        # badges
        badges: list[str] = [vendor_name.title() if vendor_name else ""]
        chip_kind = item.get("type", "")
        if chip_kind:
            badges.append(chip_kind)

        # fields
        fields: list[dict[str, Any]] = []
        for k in ("density", "cellLevel"):
            v = item.get(k)
            if v and v not in ("?", "Unknown", "未知", ""):
                fields.append(_make_field(k, v, "primary"))

        result["items"].append({
            "label": pn,
            "device": device,
            "badges": [b for b in badges if b],
            "fields": fields,
            "links": [],
        })

    # add marking code relations for search results
    for item in items:
        pn = item.get("partNumber", "")
        marking = item.get("markingCode") or item.get("m")
        if marking and pn:
            result["relations"].append({
                "kind": "marking_for",
                "source": {"markingCode": marking},
                "target": {
                    "partNumber": pn,
                    "device": {
                        "domain": "memory",
                        "chipKind": "raw_nand",
                        "partNumber": pn,
                        "vendor": {"id": item.get("vendor", "").lower().replace(" ", "_"), "name": item.get("vendor", "")},
                    },
                },
                "action": {
                    "name": "part.decode",
                    "label": "Decode Part",
                    "operation": "part.decode",
                    "input": {"query": pn},
                },
            })

    return result




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
    try:
        decoded = decode_and_merge_pn(query, _manager, lang=lang)
    except Exception as e:
        return {"status": "error", "name": SERVER_NAME, "message": str(e)}
    return new_decode_result("part.decode", query, decoded, lang)


@app.get("/parts/search")
def parts_search(
    query: str = Query("", description="Search query"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    if not query:
        return {"status": "invalid_input", "name": SERVER_NAME, "message": "Missing query"}
    try:
        results = search_part_number(query, _manager, limit=limit, lang=lang)
    except Exception as e:
        return {"status": "error", "name": SERVER_NAME, "message": str(e)}
    return new_search_result("part.search", query, results, lang)


@app.get("/identifiers/decode")
def identifiers_decode(
    query: str = Query("", description="Flash ID or typed identifier"),
    lang: str = Query("eng", description="Language"),
):
    if not query:
        return {"status": "invalid_input", "name": SERVER_NAME, "message": "Missing query"}
    try:
        decoded = decode_and_merge_id(query, _manager, lang=lang)
    except Exception as e:
        return {"status": "error", "name": SERVER_NAME, "message": str(e)}
    return new_decode_result("identifier.decode", query, decoded, lang)


@app.get("/identifiers/search")
def identifiers_search(
    query: str = Query("", description="Flash ID prefix"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    if not query:
        return {"status": "invalid_input", "name": SERVER_NAME, "message": "Missing query"}
    try:
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
        return new_search_result("identifier.search", query, results, lang)
    except Exception as e:
        return {"status": "error", "name": SERVER_NAME, "message": str(e)}


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
    try:
        result = decode_and_merge_pn(pn, _manager, lang=lang)
    except Exception as e:
        return old_fail(f"Internal error: {e}")
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
    try:
        result = decode_and_merge_id(id, _manager, lang=lang)
    except Exception as e:
        return old_fail(f"Internal error: {e}")
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
    try:
        results = search_part_number(query, _manager, limit=limit, lang=lang)
    except Exception as e:
        return old_fail(f"Internal error: {e}")
    return old_ok(results)


@app.get("/searchId")
def old_search_id(
    id: str = Query("", description="Flash ID to search"),
    lang: str = Query("eng", description="Language"),
    limit: int = Query(10, description="Max results"),
):
    if not id:
        return old_fail("Missing Flash Id")
    try:
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
    except Exception as e:
        return old_fail(f"Internal error: {e}")
    return old_ok(results)


@app.get("/summary")
def old_summary(
    pn: str = Query("", description="Part number"),
    lang: str = Query("eng", description="Language"),
):
    if not pn:
        return old_fail("Missing part number")
    try:
        result = decode_and_merge_pn(pn, _manager, lang=lang)
    except Exception as e:
        return old_fail(f"Internal error: {e}")
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
    try:
        result = decode_and_merge_id(id, _manager, lang=lang)
    except Exception as e:
        return old_fail(f"Internal error: {e}")
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
