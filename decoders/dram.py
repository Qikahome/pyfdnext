"""DRAM 解码器，通过 flash_extra API 查询并缓存结果到 ddb.json。"""
from . import register, BaseDecoder, get_manager
import requests
import json
import os

# ── 默认 API ─────────────────────────────────────────────────────────

_FLASH_EXTRA_API = "https://fe-backend.barryblueice.cn"


# ── ddb.json 缓存 ────────────────────────────────────────────────────


def _ddb_path():
    return os.path.join(os.path.dirname(__file__), "..", "resources", "ddb.json")


def _save_to_ddb(pn: str, data: dict):
    path = _ddb_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        else:
            raw = {}
        raw[pn] = data
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_ddb() -> dict:
    path = _ddb_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_ddb_cache: dict | None = None


def _get_ddb() -> dict:
    global _ddb_cache
    if _ddb_cache is None:
        _ddb_cache = _load_ddb()
    return _ddb_cache


# ── API 查询 ─────────────────────────────────────────────────────────


def _query_flash_extra(pn: str) -> dict | None:
    """调用 flash_extra API 查询 DRAM 信息。"""
    try:
        resp = requests.get(
            f"{_FLASH_EXTRA_API}/DRAM?param={pn}",
            timeout=15, verify=False,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _normalize_density(raw: str | None, width: int = 8) -> str:
    """统一 DRAM 密度格式，输出保持 Mb/Gb（bit 单位）。

    - M/G（无后缀）= 已是 Mb/Gb → 补 b
    - Mb/Gb → 保持
    - MB/GB → 按位宽转回 Mb/Gb
    """
    if not raw:
        return "Unknown"
    raw = raw.strip().split(",")[0].strip()

    # G（无后缀）= Gigabit → 补 b
    if raw.endswith("G") and not raw.endswith("GB") and not raw.endswith("Gb"):
        return raw + "b"
    # M（无后缀）= Megabit → 补 b
    if raw.endswith("M") and not raw.endswith("MB") and not raw.endswith("Mb"):
        return raw + "b"

    # Gb / Mb → 保持
    if raw.endswith("Gb") or raw.endswith("Mb"):
        return raw

    # GB → 按位宽转回 Gb: GB * width
    if raw.endswith("GB"):
        num = float(raw[:-2])
        gb = num * width
        return f"{gb:.0f}Gb" if gb % 1 == 0 else f"{gb:.2f}Gb"
    # MB → 按位宽转回 Mb: MB * width
    if raw.endswith("MB"):
        num = float(raw[:-2])
        mb = num * width
        return f"{mb:.0f}Mb" if mb % 1 == 0 else f"{mb:.2f}Mb"

    return raw


def _calc_density_from_depth(depth: str, width: int) -> str:
    """从 depth × width 计算密度。

    depth: "256M"（256 Meg 字数）, "1G"（1 Gig 字数）
    width: 位宽
    返回: "4Gb" 等
    """
    if not depth:
        return "Unknown"
    depth = depth.strip().upper()
    num_str = depth.rstrip("MG")
    if not num_str.isdigit():
        return "Unknown"
    num = float(num_str)
    if depth.endswith("G"):
        total = num * width  # Gb
        return f"{total:.0f}Gb" if total % 1 == 0 else f"{total:.2f}Gb"
    else:  # M 或无后缀
        total_mb = num * width  # Mb
        if total_mb >= 1024:
            gb = total_mb / 1024
            return f"{gb:.0f}Gb" if gb % 1 == 0 else f"{gb:.2f}Gb"
        return f"{total_mb:.0f}Mb"


# ── 请求缓存 ───────────────────────────────────────────────────────


@register
class DramDecoder(BaseDecoder):
    """DRAM 解码器。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        if not pn:
            return False
        return pn.startswith(("NT", "H5", "K4", "DRAM"))

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn:
            return None

        full_pn = pn

        # dram 前缀 → 先解前置码，是 DDR 直接返回，否则强制查 API
        if full_pn.startswith("DRAM"):
            stripped = full_pn[4:]
            resolved = get_manager().decode_pn(stripped)
            if resolved and "DDR" in str(resolved.get("type", "")):
                return resolved
            # 不是 DDR（如 Spectek NAND），用解码出的 partNumber 强制查 API
            if resolved:
                pn_from_code = resolved.get("partNumber", "")
                if pn_from_code and pn_from_code != stripped:
                    full_pn = pn_from_code
                else:
                    full_pn = stripped
            else:
                full_pn = stripped

        # CT → MT（Micron 旧标）
        if full_pn.startswith("CT"):
            full_pn = "M" + full_pn[1:]

        # 查 ddb 缓存
        ddb = _get_ddb()
        cached = ddb.get(full_pn)
        if cached:
            if "density" in cached:
                width = int(str(cached.get("width", "8")).lstrip("x"))
                cached["density"] = _normalize_density(cached["density"], width)
            return cached

        # 查 API
        raw = _query_flash_extra(full_pn)
        if not raw or not raw.get("result"):
            return None

        # 自动格式化 — 对齐到统一格式（API 字段首字母大写）
        detail = raw.get("detail", {})
        d = {k.lower(): v for k, v in detail.items()}
        width = int(d.get("width", "8").lstrip("x"))

        # 厂商名归一化
        vendor_raw = raw.get("Vendor", "Unknown")
        vendor_map = {"镁光降级/Spectek": "Spectek", "镁光降级": "Spectek", "镁光/Micron": "Micron"}
        vendor_name = vendor_map.get(vendor_raw, vendor_raw)

        # Die → classification.die，默认为 1
        raw_die = d.get("die", "")
        die_count = 1
        if isinstance(raw_die, str):
            parts = raw_die.split()
            if parts and parts[0].isdigit():
                die_count = int(parts[0])

        data = {
            "partNumber": full_pn,
            "vendor": vendor_name,
            "type": d.get("type", "DRAM"),
            "deviceWidth": f"x{width}",
            "voltage": d.get("voltage", "Unknown"),
            "speed": d.get("speed", "Unknown"),
            "package": d.get("package", "Unknown"),
            "depth": d.get("depth", "Unknown"),
            "generation": d.get("version", "Unknown"),
            "classification": {
                "die": die_count,
            },
        }

        # 密度：优先 API 值，没有则 depth × width 计算
        density_raw = d.get("density")
        if density_raw:
            data["density"] = _normalize_density(density_raw, width)
        else:
            depth_raw = d.get("depth", "")
            data["density"] = _calc_density_from_depth(depth_raw, width)

        # 从 temppower 提取电压（如果 voltage 是 "Unknown" 或含 &）
        if data["voltage"] == "Unknown" or "&" in str(data["voltage"]):
            tp = d.get("temppower", "")
            if isinstance(tp, str) and "&" in tp:
                data["voltage"] = tp.split("&")[-1].strip()

        # 写入缓存
        _save_to_ddb(full_pn, data)
        if full_pn != pn:
            _save_to_ddb(pn, data)

        return data
