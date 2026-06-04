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
from pyfdnext.translate import translate_output, _load_lang

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


# ── field labels ─────────────────────────────────────────────

# key mapping: camelCase (decoder output) → snake_case (fdnext key)
_FIELD_KEY: dict[str, str] = {
    "cellLevel": "cell_level",
    "deviceWidth": "device_width",
    "dieCode": "die_codename",
    "processNode": "process_node",
    "pageSize": "page_size",
    "die": "die_count",
    "plane": "plane_count",
    "ce": "ce_count",
    "ch": "channel_count",
    "rb": "rb_count",
    "partNumber": "part_number",
}
_FIELD_LABELS_ENG: dict[str, str] = {
    "density": "Density",
    "cell_level": "Cell Level",
    "device_width": "Device Width",
    "voltage": "Voltage",
    "package": "Package",
    "die_codename": "Process",
    "process_node": "Process",
    "page_size": "Page size",
    "die_count": "Die Count",
    "plane_count": "Plane Count",
    "ce_count": "CE Count",
    "channel_count": "Channel Count",
    "controller": "Controller",
    "type": "Type",
    "generation": "Generation",
}
_FIELD_LABELS_CHS: dict[str, str] = {
    "density": "容量",
    "cell_level": "单元类型",
    "device_width": "器件位宽",
    "voltage": "电压",
    "package": "封装",
    "die_codename": "制程",
    "process_node": "制程",
    "die_count": "Die 数",
    "plane_count": "Plane 数",
    "ce_count": "CE 数",
    "channel_count": "Channel 数",
    "controller": "控制器",
    "type": "类型",
    "generation": "代",
    "page_size": "页大小",
}
_BLOCK_LABEL: dict[str, dict[str, str]] = {
    "storage": {"eng": "Storage", "chs": "存储"},
    "geometry": {"eng": "Geometry", "chs": "几何信息"},
    "interface": {"eng": "Interface", "chs": "接口"},
    "package": {"eng": "Package", "chs": "封装"},
    "controllers": {"eng": "Controllers", "chs": "控制器"},
}
_REL_LABEL: dict[str, dict[str, str]] = {
    "identifier.decode": {"eng": "Decode NAND Flash ID", "chs": "解析 NAND Flash ID"},
    "part.decode": {"eng": "Decode Part", "chs": "解析料号"},
}

_VENDOR_REVERSE: dict[str, str] | None = None

def _get_vendor_reverse() -> dict[str, str]:
    global _VENDOR_REVERSE
    if _VENDOR_REVERSE is None:
        _VENDOR_REVERSE = {}
        # Load from chs.json
        chs = _load_lang("chs")
        for eng, chs_val in chs.items():
            if eng and chs_val:
                _VENDOR_REVERSE[chs_val] = eng
                _VENDOR_REVERSE[chs_val.lower()] = eng
        # Also add raw aliases
        raw: dict[str, str] = {
            "micron": "micron", "intel": "intel", "samsung": "samsung",
            "skhynix": "skhynix", "kioxia": "kioxia", "ymtc": "ymtc",
            "spectek": "spectek", "phison": "phison", "sandisk": "sandisk",
        }
        _VENDOR_REVERSE.update(raw)
    return _VENDOR_REVERSE

def _eng_vendor_id(name: str) -> str:
    """Get English vendor key from possibly-translated vendor name."""
    rev = _get_vendor_reverse()
    if name in rev:
        return rev[name].lower()
    low = name.lower().replace(" ", "_")
    if low in rev:
        return rev[low].lower()
    return low


def _resolve_chip_kind(decoded: dict[str, Any]) -> str:
    t = (decoded.get("type") or "").lower()
    if "dram" in t or "ddr" in t or "lpddr" in t:
        return "dram"
    if "emmc" in t or "ufs" in t:
        return "managed_nand"
    return "raw_nand"


def _parse_density(val: str, is_dram: bool = False) -> tuple[int | None, str | None, str | None]:
    """Parse density string like '16Gb' → (16384, 'Mbit', '2GB')."""
    if not val or not isinstance(val, str):
        return None, None, None
    import re
    v = val.strip()
    m = re.match(r'(\d+)\s*([GTMK])[_\s]?(?:b|bit|ib|byte)?\s*$', v, re.IGNORECASE)
    if not m:
        m = re.match(r'(\d+)\s*(GIB|MIB|KIB|GB|MB|KB)\s*$', v, re.IGNORECASE)
    if not m:
        return None, None, None
    num = int(m.group(1))
    raw_unit = m.group(2).upper()
    has_byte_suffix = bool(re.search(r'[GTMK]B$', v))
    multiplier = {"G": 1024, "T": 1024 * 1024, "M": 1, "K": 1 / 1024}.get(raw_unit, 1)
    value_mbit = int(num * multiplier)
    if has_byte_suffix:
        value_mbit *= 8
    # display：统一用 8bit 字节单位（GB/TB/MB）
    if value_mbit >= 8192 and value_mbit % 8192 == 0:
        display = f"{value_mbit // 8192}GB"
    elif value_mbit >= 8192:
        display = f"{value_mbit / 8192:.1f}GB"
    elif value_mbit >= 8:
        display = f"{value_mbit // 8}MB"
    else:
        display = str(value_mbit)
    return value_mbit, "Mbit", display


def _label(key: str, lang: str) -> str:
    """Get label for a field key in the given language."""
    labels = _FIELD_LABELS_CHS if lang and lang != "eng" else _FIELD_LABELS_ENG
    return labels.get(key, key)


def _block_label(block_id: str, lang: str) -> str:
    m = _BLOCK_LABEL.get(block_id, {})
    return m.get(lang, m.get("eng", block_id))


def _rel_label(action_name: str, lang: str) -> str:
    m = _REL_LABEL.get(action_name, {})
    return m.get(lang, m.get("eng", action_name))


def _make_field(key: str, value: Any, lang: str, importance: str = "secondary",
                 decoded: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a field dict matching fdnext.result.v1 format."""
    out_key = _FIELD_KEY.get(key, key)
    label = _label(out_key, lang)
    field: dict[str, Any] = {"key": out_key, "label": label, "value": value, "importance": importance}

    if out_key == "density" and isinstance(value, str):
        # 判断是否是 DRAM（影响单位：DRAM 用 Gb，NAND 用 GB）
        is_dram = False
        if decoded:
            t = (decoded.get("type") or "").lower()
            is_dram = "dram" in t or "ddr" in t or "lpddr" in t
        v, u, d = _parse_density(value, is_dram=is_dram)
        if v is not None:
            field["value"] = v
            field["unit"] = u
            field["display"] = d

    if out_key == "device_width" and isinstance(value, str):
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
    vendor_id = _eng_vendor_id(vendor_name)
    d: dict[str, Any] = {
        "domain": "memory",
        "chipKind": _resolve_chip_kind(decoded),
        "vendor": {"id": vendor_id, "name": vendor_name},
    }
    if decoded.get("partNumber"):
        d["partNumber"] = decoded["partNumber"]
    ids = decoded.get("id") or decoded.get("flashId")
    if ids:
        if isinstance(ids, list) and ids:
            d["identifier"] = ids[0]
        elif isinstance(ids, str):
            d["identifier"] = ids
    return d


def _build_blocks(decoded: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    """Build blocks array from decoded data."""
    blocks: list[dict[str, Any]] = []

    def _field(key: str, imp: str = "secondary") -> dict[str, Any] | None:
        v = decoded.get(key)
        if v and v not in ("?", "Unknown", "未知", ""):
            return _make_field(key, v, lang, imp, decoded=decoded)
        return None

    # storage block (primary)
    storage_fields = list(filter(None, [_field("density", "primary"), _field("cellLevel", "primary"),
                                         _field("dieCode", "secondary"), _field("processNode", "secondary"),
                                         _field("generation", "secondary")]))
    if storage_fields:
        blocks.append({"id": "storage", "label": _block_label("storage", lang),
                        "importance": "primary", "fields": storage_fields})

    # geometry block (secondary)
    geo_fields: list[dict[str, Any]] = []
    cls = decoded.get("classification")
    if isinstance(cls, dict):
        for k, imp in [("die", "secondary"), ("ce", "secondary"), ("ch", "secondary")]:
            v = cls.get(k)
            if v and v not in ("?", "Unknown", "?"):
                geo_fields.append(_make_field(k, v, lang, imp, decoded=decoded))
    for k in ("plane", "pageSize"):
        f = _field(k)
        if f:
            geo_fields.append(f)
    if geo_fields:
        blocks.append({"id": "geometry", "label": _block_label("geometry", lang),
                        "importance": "secondary", "fields": geo_fields})

    # interface block (secondary)
    iface_fields = list(filter(None, [_field("deviceWidth", "secondary"), _field("voltage", "secondary")]))
    if iface_fields:
        blocks.append({"id": "interface", "label": _block_label("interface", lang),
                        "importance": "secondary", "fields": iface_fields})

    # package block (detail)
    pkg_fields = list(filter(None, [_field("package", "secondary")]))
    if pkg_fields:
        blocks.append({"id": "package", "label": _block_label("package", lang),
                        "importance": "detail", "fields": pkg_fields})

    # controllers block (detail)
    ctrl = decoded.get("controller") or decoded.get("t")
    if ctrl:
        if isinstance(ctrl, str):
            ctrl = [ctrl]
        blocks.append({"id": "controllers", "label": _block_label("controllers", lang),
                        "importance": "detail",
                        "fields": [_make_field("controller", ctrl, lang, "secondary", decoded=decoded)]})

    return blocks


def _build_relations_for_pn(decoded: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    ids = decoded.get("id") or decoded.get("flashId")
    if isinstance(ids, str):
        ids = [ids]
    if isinstance(ids, list):
        for fid in ids:
            if fid and isinstance(fid, str):
                relations.append({
                    "kind": "identifier_for",
                    "target": {"identifier": fid, "idScheme": "nand.flash_id"},
                    "action": {
                        "name": "identifier.decode",
                        "label": _rel_label("identifier.decode", lang),
                        "operation": "identifier.decode",
                        "input": {"query": fid, "constraints": {"idScheme": "nand.flash_id"}},
                    },
                })
    return relations


def _build_relations_for_id(decoded: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    fid = decoded.get("id") or decoded.get("flashId")
    if isinstance(fid, list):
        fid = fid[0] if fid else None
    source_id = fid or ""
    if not source_id:
        return relations
    fdb = load_fdb()
    vendor_name = decoded.get("vendor", "")
    vendor_key = _eng_vendor_id(vendor_name)
    related_pns: list[tuple[str, str]] = []
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
                "label": _rel_label("part.decode", lang),
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
    result: dict[str, Any] = {
        "schemaVersion": "fdnext.result.v1",
        "operation": operation,
        "status": "ok" if decoded else "not_found",
        "input": {"query": query, "normalized": query.upper(), "lang": lang, "constraints": {}},
        "relations": [], "links": [], "warnings": [], "candidates": [],
    }
    if decoded:
        result["device"] = _make_device(decoded, query)
        vendor_name = decoded.get("vendor", "?")
        pn = decoded.get("partNumber", query)
        density = decoded.get("density", "")
        cell = decoded.get("cellLevel", "")
        parts = [vendor_name, pn]
        if density:
            parts.insert(1, density)
        if cell:
            parts.append(cell)
        result["subtitle"] = " · ".join(parts)
        result["blocks"] = _build_blocks(decoded, lang)
        if operation == "part.decode":
            result["relations"] = _build_relations_for_pn(decoded, lang)
        elif operation == "identifier.decode":
            result["relations"] = _build_relations_for_id(decoded, lang)
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
    result: dict[str, Any] = {
        "schemaVersion": "fdnext.result.v1",
        "operation": operation,
        "status": "ok" if items else "not_found",
        "input": {"query": query, "normalized": query.upper(), "lang": lang, "constraints": {}},
        "device": None, "subtitle": None, "blocks": [], "items": [],
        "relations": [], "links": [], "warnings": [], "candidates": [],
    }
    for item in items:
        vendor_name = item.get("vendor", "?")
        vendor_id = _eng_vendor_id(vendor_name)
        pn = item.get("partNumber", "")
        device: dict[str, Any] = {
            "domain": "memory", "chipKind": "raw_nand",
            "vendor": {"id": vendor_id, "name": vendor_name},
        }
        if pn:
            device["partNumber"] = pn
        badges = [vendor_name.title() if vendor_name else ""]
        if item.get("type"):
            badges.append(item["type"])
        fields = list(filter(None, [_make_field(k, item.get(k), lang, "primary",
                                                   decoded=item)
                                      for k in ("density", "cellLevel")
                                      if item.get(k) and item[k] not in ("?", "Unknown", "未知", "")]))
        result["items"].append({
            "label": pn, "device": device,
            "badges": [b for b in badges if b],
            "fields": fields, "links": [],
        })
        marking = item.get("markingCode") or item.get("m")
        if marking and pn:
            result["relations"].append({
                "kind": "marking_for",
                "source": {"markingCode": marking},
                "target": {
                    "partNumber": pn,
                    "device": {
                        "domain": "memory", "chipKind": "raw_nand",
                        "partNumber": pn,
                        "vendor": {"id": vendor_id, "name": vendor_name},
                    },
                },
                "action": {
                    "name": "part.decode",
                    "label": _rel_label("part.decode", lang),
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
