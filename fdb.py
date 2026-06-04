"""FDB (Flash Database) 加载与合并。

加载 fdb.json，将 FDB 数据（flash ID、控制器兼容性、制程等）
与解码器结果合并，解码器解析出来的字段优先。
"""

import json
import os
import re
from typing import Any

from .translate import translate_output

_FDB_PATH = os.path.join(os.path.dirname(__file__), "resources", "fdb.json")
_MDB_PATH = os.path.join(os.path.dirname(__file__), "resources", "mdb.json")

_fdb_cache: dict[str, Any] | None = None
_mdb_cache: dict[str, Any] | None = None

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


def _load_mdb() -> dict[str, Any]:
    """加载 mdb.json（FBGA → 料号映射）。"""
    global _mdb_cache
    if _mdb_cache is None:
        if os.path.exists(_MDB_PATH):
            with open(_MDB_PATH, "r", encoding="utf-8") as f:
                _mdb_cache = json.load(f)
        else:
            _mdb_cache = {}
    return _mdb_cache


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
    # 前缀匹配（FDB key 是料号的前缀，如 MT29E1HT08EMHBB 匹配 MT29E1HT08EMHBBJ4-3:B）
    for fdb_key in vendor_map:
        if part_number.startswith(fdb_key) or (base and base.startswith(fdb_key)):
            rec = vendor_map[fdb_key]
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
        # 前缀匹配
        for fdb_key in vendor_map:
            if part_number.startswith(fdb_key) or (base and base.startswith(fdb_key)):
                rec = vendor_map[fdb_key]
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
    query: str, manager: Any, limit: int = 0, partial_match: bool = True,
    lang: str = "eng",
) -> list[dict[str, Any]]:
    """搜索料号。

    支持三种模式：
      - 默认：通配符匹配（* 匹配任意字符，? 匹配单个字符）
      - ``regex:`` 前缀：正则匹配
      - 无通配符时：子串包含匹配（同之前行为）。
    """
    fdb = load_fdb()
    results: list[dict[str, Any]] = []

    # 编译搜索模式
    match_mode: str | None = None  # None="in" sub-string, "wildcard", "regex"
    pattern: re.Pattern | None = None

    if query.startswith("regex:"):
        raw = query[6:]
        if raw:
            try:
                pattern = re.compile(raw, re.IGNORECASE)
                match_mode = "regex"
            except re.error:
                pass

    if match_mode is None:
        # 默认通配符模式：query 当作 *query* 匹配
        raw = query.replace("*", ".*").replace("?", ".")
        if not raw.endswith(".*"):
            raw = raw + ".*"
        if not raw.startswith(".*"):
            raw = ".*" + raw
        try:
            pattern = re.compile(raw, re.IGNORECASE)
            match_mode = "wildcard"
        except re.error:
            pass

    # 1. 解码器精确解析（无论何种模式都尝试）
    exact = decode_and_merge_pn(query, manager, lang=lang)
    if exact:
        exact["_match"] = "exact"
        results.append(exact)

    # 2. FDB 搜索
    if partial_match:
        q = query.upper()

        def _matches(pn: str) -> bool:
            if match_mode == "regex" or match_mode == "wildcard":
                return bool(pattern.search(pn))
            if match_mode is None:
                return q in pn or pn in q
            return False

        for vendor_key, vendor_map in fdb.items():
            if vendor_key in ("info", "iddb") or not isinstance(vendor_map, dict):
                continue
            for pn in vendor_map:
                if not _matches(pn):
                    continue
                if any(r.get("partNumber") == pn for r in results):
                    continue
                rec = vendor_map[pn].copy()
                rec["vendor"] = vendor_key
                rec["partNumber"] = pn
                rec["_match"] = match_mode or "substring"
                results.append(translate_output(rec, lang))
                if limit > 0 and len(results) >= limit:
                    break
            if limit > 0 and len(results) >= limit:
                break

    # 3. MDB 查询（FBGA/标记码 → 料号）
    if partial_match:
        mdb = _load_mdb()
        q = query.upper()
        for vendor_key, mapping in mdb.items():
            if not isinstance(mapping, dict):
                continue
            for fbga, pn in mapping.items():
                if q not in fbga.upper() and q not in pn.upper():
                    continue
                if any(r.get("partNumber") == pn for r in results):
                    continue
                # 尝试解码映射到的料号
                decoded = decode_and_merge_pn(pn, manager, lang=lang)
                if decoded:
                    decoded["_match"] = "mdb"
                    results.append(decoded)
                else:
                    results.append({
                        "partNumber": pn,
                        "vendor": vendor_key,
                        "type": "DRAM",
                        "_match": "mdb",
                    })
                if limit > 0 and len(results) >= limit:
                    break
            if limit > 0 and len(results) >= limit:
                break

    return results
