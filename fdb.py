"""FDB (Flash Database) 加载与合并。

加载 fdb.json，将 FDB 数据（flash ID、控制器兼容性、制程等）
与解码器结果合并，解码器解析出来的字段优先。
"""

import json
import os
from typing import Any

from .translate import translate_output

_FDB_PATH = os.path.join(os.path.dirname(__file__), "resources", "fdb.json")

_fdb_cache: dict[str, Any] | None = None

# ── 厂商名映射（解码器输出的英文名 → FDB 英文 key） ────────────

_VENDOR_ALIAS: dict[str, str] = {
    "Micron": "micron", "micron": "micron",
    "Samsung": "samsung", "samsung": "samsung",
    "SK hynix": "skhynix", "skhynix": "skhynix",
    "Kioxia": "kioxia", "kioxia": "kioxia",
    "Intel": "intel", "intel": "intel",
    "YMTC": "ymtc", "ymtc": "ymtc",
    "Spectek": "spectek", "spectek": "spectek",
    "Phison": "phison", "phison": "phison",
    "Biwin-Micron": "micron",
    "Biwin-YMTC": "ymtc",
    "Biwin-Samsung": "samsung",
    "Kioxia/Toshiba": "kioxia",
    "SanDisk/WD": "sandisk",
}


def load_fdb() -> dict[str, Any]:
    """加载 fdb.json（带缓存）。"""
    global _fdb_cache
    if _fdb_cache is None:
        with open(_FDB_PATH, "r", encoding="utf-8") as f:
            _fdb_cache = json.load(f)
    return _fdb_cache


def find_part_number(
    fdb: dict[str, Any], vendor: str, part_number: str
) -> dict[str, Any] | None:
    """按 vendor + partNumber 查 FDB 记录。"""
    if not part_number or vendor == "Unknown":
        return None
    # 中文厂商名 → FDB 英文 key
    vendor_key = _VENDOR_ALIAS.get(vendor, vendor).lower()
    vendor_map = fdb.get(vendor_key)
    if not vendor_map:
        return None
    # 精确匹配
    if part_number in vendor_map:
        rec = vendor_map[part_number]
        rec["vendor"] = vendor
        return rec
    # 部分匹配（去后缀 -xxx）
    base = part_number.split("-")[0] if "-" in part_number else ""
    if base and base in vendor_map:
        rec = vendor_map[base]
        rec["vendor"] = vendor
        return rec
    return None


def find_part_number_across_vendors(
    fdb: dict[str, Any], part_number: str
) -> dict[str, Any] | None:
    """跨所有厂商查找料号。"""
    if not part_number:
        return None
    for vendor_key, vendor_map in fdb.items():
        if vendor_key == "info" or not isinstance(vendor_map, dict):
            continue
        if part_number in vendor_map:
            rec = vendor_map[part_number]
            rec["vendor"] = vendor_key
            return rec
        base = part_number.split("-")[0] if "-" in part_number else ""
        if base and base in vendor_map:
            rec = vendor_map[base]
            rec["vendor"] = vendor_key
            return rec
    return None


def merge_fdb(result: dict[str, Any], fdb_rec: dict[str, Any] | None) -> None:
    """将 FDB 记录合并到解码结果中（解码结果优先）。

    合并规则：
    - flashId: FDB 的 `id` 字段
    - controller: FDB 的 `t` 字段
    - processNode: 如果解码结果没有，则用 FDB 的 `l` 字段
    """
    if not fdb_rec:
        return

    # flashId（FDB 的 id 列表）
    flash_ids = fdb_rec.get("id", [])
    if flash_ids:
        result["flashId"] = flash_ids

    # controller 兼容性（FDB 的 t 列表）
    controllers = fdb_rec.get("t", [])
    if controllers:
        result["controller"] = controllers

    # processNode（仅当解码结果未提供时）
    if (result.get("processNode") is None or result.get("processNode") == "Unknown") and fdb_rec.get("l"):
        result["processNode"] = fdb_rec["l"]


def decode_and_merge_pn(
    part_number: str,
    manager: Any,
    lang: str = "eng",
) -> dict[str, Any] | None:
    """解码料号并与 FDB 数据合并。"""
    fdb = load_fdb()

    # 1. 解码器解析
    result = manager.decode_pn(part_number)

    # 2. 查 FDB
    fdb_rec = None
    if result:
        vendor = result.get("vendor", "").lower()
        pn = result.get("partNumber", part_number)
        fdb_rec = find_part_number(fdb, vendor, pn)
        if not fdb_rec:
            fdb_rec = find_part_number_across_vendors(fdb, pn)
    else:
        # 解码没命中，尝试全 FDB 查找
        fdb_rec = find_part_number_across_vendors(fdb, part_number)
        if fdb_rec:
            result = {
                "partNumber": part_number,
                "vendor": fdb_rec["vendor"],
                "type": "NAND",
            }
            del fdb_rec["vendor"]

    # 3. 合并
    if result:
        merge_fdb(result, fdb_rec)

    # 4. 翻译
    return translate_output(result, lang)


def decode_and_merge_id(
    id_str: str,
    manager: Any,
    lang: str = "eng",
) -> dict[str, Any] | None:
    """解码 Flash ID 并与 FDB 数据合并。"""
    fdb = load_fdb()

    # 1. 解码器解析
    result = manager.decode_id(id_str)

    # 2. 查 FDB（按 ID 全表搜索）
    if result:
        pn = result.get("partNumber", "")
        vendor = result.get("vendor", "").lower()
        fdb_rec = find_part_number(fdb, vendor, pn) if pn else None
        if not fdb_rec:
            # 用 ID 搜索
            for vk, vm in fdb.items():
                if vk == "info" or not isinstance(vm, dict):
                    continue
                for _pn, rec in vm.items():
                    ids = rec.get("id", [])
                    if isinstance(ids, list) and any(
                        id_str.startswith(i) for i in ids
                    ):
                        fdb_rec = rec.copy()
                        fdb_rec["vendor"] = vk
                        break
                if fdb_rec:
                    break

    if result:
        merge_fdb(result, fdb_rec)

    # 3. 翻译
    return translate_output(result, lang)


def search_part_number(
    query: str, manager: Any, limit: int = 0, partial_match: bool = True
) -> list[dict[str, Any]]:
    """搜索料号（含 FDB 合并）。"""
    fdb = load_fdb()
    results: list[dict[str, Any]] = []

    # 1. 解码器精确解析
    exact = decode_and_merge_pn(query, manager)
    if exact:
        exact["_match"] = "exact"
        results.append(exact)

    # 2. FDB 模糊搜索
    if partial_match:
        q = query.upper()
        for vendor_key, vendor_map in fdb.items():
            if vendor_key == "info" or not isinstance(vendor_map, dict):
                continue
            for pn in vendor_map:
                if pn == query.upper() or query.upper() in pn:
                    if any(r.get("partNumber") == pn for r in results):
                        continue
                    rec = vendor_map[pn].copy()
                    rec["vendor"] = vendor_key
                    rec["partNumber"] = pn
                    rec["_match"] = "fdb"
                    results.append(rec)
                    if limit > 0 and len(results) >= limit:
                        break
            if limit > 0 and len(results) >= limit:
                break

    return results
