import re
import os
import json
from typing import Any
import requests


UNKNOWN = "Unknown"

VENDOR_PATCH: dict[str, str] = {
    "sandisk": "sndk",
    "san disk": "sndk",
    "sndk": "sndk",
    "westerndigital": "sndk",
    "western digital": "sndk",
    "wd": "sndk",
    "toshiba": "kioxia",
    "toshiba-iver": "kioxia",
    "hynix": "skhynix",
    "septeck": "spectek",
    "stm": "st",
}

LANGUAGES = ["chs", "eng"]

CELL_LEVEL_MAP: dict[int, str] = {
    1: "SLC",
    2: "MLC",
    3: "TLC",
    4: "QLC",
}


def normalize_vendor(vendor: str) -> str:
    key = vendor.strip().lower()
    return VENDOR_PATCH.get(key, key)


def normalize_part_number(pn: str) -> str:
    if not pn:
        return ""
    pn = pn.strip().upper()
    pn = re.sub(r"[\s,\.\&\|_\-]", "", pn)
    length = len(pn)
    if length > 20:
        pn = pn[:20]
    return pn


def normalize_flash_id(id_str: str) -> str:
    nid = re.sub(r"\s+", "", id_str).upper()
    if not nid or len(nid) % 2 != 0 or len(nid) < 4 or len(nid) > 16:
        return ""
    if not re.match(r"^[0-9A-F]+$", nid):
        return ""
    return nid


def contains(text: str, query: str) -> bool:
    return query.upper() in text.upper()


def pad_flash_id(id_str: str) -> str:
    """Pad flash ID to 12 characters (24 hex digits) with trailing zeros."""
    return id_str.ljust(12, "0")


def format_density(density: int | float, use_byte: bool = False) -> str:
    """Format density number to human readable string."""
    unit = ["MB", "GB", "TB"] if use_byte else ["Mb", "Gb", "Tb"]
    numeric = density / 8 if use_byte else density
    idx = 0
    while numeric >= 1024 and idx + 1 < len(unit):
        numeric /= 1024
        idx += 1
    return f"{int(numeric)}{unit[idx]}" if numeric == int(numeric) else f"{numeric:.2f}{unit[idx]}"


def translate_string(lang_packs: dict[str, dict[str, str]], fallback_lang: str, key: str, lang: str | None = None) -> str:
    lang = lang or fallback_lang
    pack = lang_packs.get(lang, lang_packs.get(fallback_lang, {}))
    return pack.get(key, key)


def translate_value(
    lang_packs: dict[str, dict[str, str]],
    fallback_lang: str,
    value: Any,
    lang: str | None = None,
    translate_keys: bool = True,
) -> Any:
    """Recursively translate values using language packs."""
    if isinstance(value, str):
        return translate_string(lang_packs, fallback_lang, value, lang)
    elif isinstance(value, dict):
        return {
            translate_string(lang_packs, fallback_lang, k, lang) if translate_keys else k: translate_value(
                lang_packs, fallback_lang, v, lang, translate_keys
            )
            for k, v in value.items()
        }
    elif isinstance(value, list):
        return [translate_value(lang_packs, fallback_lang, item, lang, translate_keys) for item in value]
    return value


def clone_object(obj: Any) -> Any:
    """Deep clone a JSON-serializable object."""
    import json

    return json.loads(json.dumps(obj))


def infer_vendor_from_part_number(pn: str) -> str | None:
    """Infer vendor from part number prefix."""
    if re.search(r"^(MT29|MTFC|MTFD|MT40|MT41|NW[0-9A-Z]{3,})", pn):
        return "micron"
    if re.search(r"^(K9[ABCDEFG]|KLM|KLU|KMD|KMF|KMN|KMV|K3[AL])", pn):
        return "samsung"
    if re.search(r"^(HY27|H27|H25|H26|H2D|H2J|H9T|HYNIX)", pn):
        return "skhynix"
    if re.search(r"^(TC58|TH58)", pn):
        return "kioxia"
    if re.search(r"^(SD|S34|S35|SANDISK|SNDK|DFT|MDT|05[0-9]{3})", pn):
        return "sndk"
    if re.search(r"^(JS29F|I29F|PF29F|PC29F|PD29F)", pn):
        return "intel"
    if re.search(r"^(FBNL|FNNL|FNN|FXXL)", pn):
        return "spectek"
    if re.search(r"^(NAND|M29F)", pn):
        return "st"
    if re.search(r"^(YM|YMN|XT)", pn):
        return "ymtc"
    if re.search(r"^[TIKHDCN][APCOKFTBY][135678ABC][0-9A-Z]{7}$", pn):
        return "phison"
    return None


def get_human_readable_density(density: int, use_byte: bool = False) -> str:
    unit = ["MB", "GB", "TB"] if use_byte else ["Mb", "Gb", "Tb"]
    numeric = density / 8 if use_byte else density
    idx = 0
    while numeric >= 1024 and idx + 1 < len(unit):
        numeric /= 1024
        idx += 1
    return f"{numeric}{unit[idx]}"


def total_density(density: str, die_count: str) -> str:
    """根据单die大小和die数量计算总大小。"""
    try:
        original = density
        density = str(density).strip()
        die_count = float(die_count.strip())
        bytes_val = 0.0

        if density.endswith("Tb"):
            num = float(density[:-2])
            bytes_val = num * 1024 * 1024 / 8
        elif density.endswith("Gb"):
            num = float(density[:-2])
            bytes_val = num * 1024 / 8
        elif density.endswith("Mb"):
            num = float(density[:-2])
            bytes_val = num / 8
        elif density.endswith("GB"):
            num = float(density[:-2])
            bytes_val = num * 1024
        elif density.endswith("MB"):
            num = float(density[:-2])
            bytes_val = num
        elif density.endswith("G"):
            num = float(density[:-1])
            bytes_val = num * 1024
        elif density.endswith("M"):
            num = float(density[:-1])
            bytes_val = num
        else:
            num = float(density)
            bytes_val = num / 8

        total_bytes = bytes_val * die_count

        if total_bytes >= 1024 * 1024:
            tb = total_bytes / (1024 * 1024)
            return f"{int(tb)}TB" if tb.is_integer() else f"{tb:.2f}TB"
        elif total_bytes >= 1024:
            gb = total_bytes / 1024
            return f"{int(gb)}GB" if gb.is_integer() else f"{gb:.2f}GB"
        else:
            return f"{int(total_bytes)}MB" if total_bytes.is_integer() else f"{total_bytes:.2f}MB"
    except Exception:
        return str(original)


# ── Micron FBGA 解析 ──────────────────────────────────────────────────

_MICRON_API = "https://www.micron.com/content/micron/us/en/sales-support/design-tools/fbga-parts-decoder/_jcr_content.products.json/getpartbyfbgacode/-/-/-/en_US/-/-/"


def _mdb_path():
    return os.path.join(os.path.dirname(__file__), "resources", "mdb.json")


def _save_to_mdb(fbga: str, part_number: str):
    path = _mdb_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        else:
            raw = {}
        if "micron" not in raw:
            raw["micron"] = {}
        raw["micron"][fbga] = part_number
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_mdb() -> dict[str, str]:
    path = _mdb_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get("micron", {})


_mdb_cache: dict[str, str] | None = None


def _get_mdb() -> dict[str, str]:
    global _mdb_cache
    if _mdb_cache is None:
        _mdb_cache = _load_mdb()
    return _mdb_cache


def query_micron_fbga_api(fbga: str) -> str | None:
    """实时查询 Micron API 获取 FBGA 对应的料号。"""
    try:
        resp = requests.get(f"{_MICRON_API}{fbga}", timeout=10, verify=False)
        resp.raise_for_status()
        data = resp.json()
        details = data.get("details", [{}])
        if details and details[0]:
            return details[0].get("part-number") or details[0].get("partNumber")
    except Exception:
        return None
    return None


def resolve_micron_fbga(fbga: str) -> str | None:
    """查缓存 → 查 API → 写缓存，返回完整料号。"""
    mdb = _get_mdb()
    resolved = mdb.get(fbga)
    if not resolved:
        resolved = query_micron_fbga_api(fbga)
        if resolved:
            _save_to_mdb(fbga, resolved)
    return resolved


# ── Spectek Mark Code 解码 ────────────────────────────────────────────

import urllib3
import ssl
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _TLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        return super(_TLSAdapter, self).init_poolmanager(*args, **kwargs)


def resolve_spectek_mark(mark_code: str) -> str | None:
    """在线解码 Spectek Mark Code，返回完整料号（查缓存 → 查 API → 写缓存）。"""
    # 查缓存
    path = _mdb_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cached = raw.get("spectek", {}).get(mark_code.upper())
            if cached:
                return cached
    except Exception:
        pass

    # 查 API
    resolved = _query_spectek_api(mark_code)
    if resolved:
        # 写缓存
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            else:
                raw = {}
            raw.setdefault("spectek", {})[mark_code.upper()] = resolved
            with open(path, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return resolved


def _query_spectek_api(mark_code: str) -> str | None:
    """实时查询 Spectek 官网 API。"""
    url = "https://www.spectek.com/menus/mark_code.aspx"
    session = requests.Session()
    session.mount('https://', _TLSAdapter())
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.spectek.com/menus/mark_code.aspx",
    })
    try:
        resp = session.get(url, verify=False, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        viewstate = soup.find('input', {'id': '__VIEWSTATE'})['value']
        viewstate_gen = soup.find('input', {'id': '__VIEWSTATEGENERATOR'})['value']
        ev = soup.find('input', {'id': '__EVENTVALIDATION'})
        event_validation = ev['value'] if ev else ""
        payload = {
            '__VIEWSTATE': viewstate,
            '__VIEWSTATEGENERATOR': viewstate_gen,
            '__EVENTVALIDATION': event_validation,
            'ctl00$MainCPH$MarkCodeTextBox': mark_code,
            'ctl00$MainCPH$MarkCodeButton.x': '10',
            'ctl00$MainCPH$MarkCodeButton.y': '10',
        }
        resp = session.post(url, data=payload, verify=False, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', {'id': 'MainCPH_MarkCodeGridView'})
        if not table:
            return None
        rows = table.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if cols and len(cols) >= 2:
                return cols[1].text.strip()
        return None
    except Exception:
        return None
