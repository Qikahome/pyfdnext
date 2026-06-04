"""铠侠/东芝 (Kioxia/Toshiba) 解码器，同时处理闪迪/西数 Flash ID。"""
from . import register, BaseDecoder, decode_die_cell_level, DENSITY_TOGGLE

# ── 料号解码 ─────────────────────────────────────────────────────────


def _pn_density(code: str) -> str:
    """按规则解析密度码。

    数字后缀 Mn/Gn/Tn: 2^n Xb
    字母后缀 G{A..F}: 24 * 2^(int(n,36)-10) Gb
    Bn: 4/3 * 2^n Tb
    """
    if len(code) != 2 or code[0] not in "MGTB":
        return "Unknown"
    prefix, suffix = code[0], code[1]
    if prefix == "B":
        n = int(suffix, 36) if suffix.isalpha() else int(suffix)
        return f"{4 / 3 * 2 ** n:.2f}Tb"
    if suffix.isdigit():
        n = int(suffix)
        if prefix == "M":
            return f"{2 ** n}Mb"
        elif prefix == "G":
            return f"{2 ** n}Gb"
        elif prefix == "T":
            return f"{2 ** n}Tb"
    else:
        n = int(suffix, 36)
        val = 24 * 2 ** (n - 10)
        if prefix == "M":
            return f"{val}Mb"
        elif prefix == "G":
            return f"{val}Gb"
        elif prefix == "T":
            return f"{val}Tb"
    return "Unknown"


_CELL_MAP = {
    "S": "SLC", "H": "SLC", "D": "MLC", "E": "MLC",
    "J": "MLC", "C": "MLC", "T": "TLC", "U": "TLC",
    "V": "TLC", "X": "TLC", "W": "TLC", "F": "QLC",
}

_WIDTH_MAP: dict[str, int] = {
    "0": 8, "1": 8, "2": 8, "3": 8, "4": 8,
    "A": 8, "B": 8, "C": 8, "D": 8, "F": 8,
    "5": 16, "6": 16, "7": 16, "8": 16, "9": 16,
}

_PROCESS_MAP = {
    "A": "130nm", "B": "90nm", "C": "70nm", "D": "56nm",
    "E": "43nm", "F": "32nm", "G": "24nm A-type", "H": "24nm B-type",
    "J": "19nm/1x", "K": "A19nm/1y", "L": "15nm/1z",
    "M": "BiCS4.5",
}
# 数字后缀 = BiCS{n}
for _n in range(10):
    _PROCESS_MAP[str(_n)] = f"BiCS{_n}"

_CE_MAP: dict[str, int] = {
    "0": 1, "I": 1, "2": 2, "K": 2, "4": 2, "M": 2,
    "7": 4, "R": 4, "8": 4, "S": 4, "A": 6, "U": 6,
    "B": 8, "V": 8, "D": 4, "E": 8, "W": 3, "9": 4,
}

# rest[10] → (detail_pkg编号, die/ce 倍率)
_DETAIL_PKG: dict[str, tuple[int, int]] = {
    "G": (272, 2),  "J": (152, 2),
    "E": (272, 1),  "F": (272, 1),  "D": (272, 2),
    "C": (132, 1),  "H": (132, 1),  "P": (132, 4),  "9": (132, 1),
    "K": (152, 1),  "N": (152, 4),
}

# detail_pkg → ch
_CH_MAP: dict[int, int] = {132: 2, 152: 2, 272: 4}


# ── 注册解码器 ───────────────────────────────────────────────────────


@register
class KioxiaDecoder(BaseDecoder):
    """铠侠/东芝 (Kioxia/Toshiba) 解码器。"""

    # ── 料号解码 ─────────────────────────────────────────────────

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        return pn.startswith(("TC58", "TH58"))

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn.startswith(("TC58", "TH58")):
            return None

        rest = pn[4:]
        data: dict = {"partNumber": pn, "type": "NAND"}

        pos = 0

        # 接口标志 (1位)
        pos += 1

        # 电压 (1位)
        pos += 1

        # 密度 (2位)
        density_code = rest[pos:pos + 2] if pos + 1 < len(rest) else ""
        pos += 2
        data["density"] = _pn_density(density_code)

        # 单元类型 (1位)
        cell_code = rest[pos] if pos < len(rest) else ""
        pos += 1
        data["cellLevel"] = _CELL_MAP.get(cell_code, "Unknown")

        # 位宽 (1位)
        width_code = rest[pos] if pos < len(rest) else ""
        pos += 1
        data["deviceWidth"] = _WIDTH_MAP.get(width_code, "Unknown")
        if isinstance(data["deviceWidth"], int):
            data["deviceWidth"] = f"x{data['deviceWidth']}"

        # 制程 (1位)
        process_code = rest[pos] if pos < len(rest) else ""
        pos += 1
        data["processNode"] = _PROCESS_MAP.get(process_code, "Unknown")

        # 封装: base(1位) + 保留(1位)
        base_code = rest[pos] if pos < len(rest) else ""
        pos += 1
        base_pkg = {"B": "BGA", "T": "TSOP", "L": "LGA"}.get(base_code, "Unknown")
        pos += 1  # rest[8] 保留位

        # CE (1位)
        ce_code = rest[pos] if pos < len(rest) else ""
        pos += 1
        ce = _CE_MAP.get(ce_code, 0)

        # 详细封装 + die 倍率 (1位)
        detail_code = rest[pos] if pos < len(rest) else ""
        pos += 1
        pkg_num, die_ratio = _DETAIL_PKG.get(detail_code, (0, 0))
        die = ce * die_ratio
        ch = _CH_MAP.get(pkg_num, 0) if base_pkg == "BGA" else 1

        data["package"] = f"{base_pkg}{pkg_num}" if pkg_num else base_pkg
        data["classification"] = {"ce": ce, "ch": ch, "die": die}

        data["vendor"] = "Kioxia"
        return data

    # ── Flash ID 解码 ────────────────────────────────────────────
    # 同时支持 98 (铠侠) 和 45 (闪迪/西数)，解码逻辑相同

    def check_id(self, id_str: str) -> bool:
        id_str = id_str.strip().upper()
        return id_str.startswith(("98", "45"))

    def decode_id(self, id_str: str) -> dict | None:
        id_str = id_str.strip().upper()
        if not id_str.startswith(("98", "45")):
            return None

        vendor_name = {"98": "Kioxia/Toshiba", "45": "SanDisk/WD"}.get(id_str[:2], "Unknown")
        return _decode_toggle_id(id_str, vendor_name)


# ── Toggle Flash ID 解码公共逻辑 ─────────────────────────────────────

_PROCESS_TOGGLE: dict[str, str] = {
    "71": "BiCS2",      "72": "BiCS3",
    "63": "BiCS4",      "64": "BiCS5",
    "65": "BiCS6",      "66": "BiCS8",      "67": "BiCS9",
    "51": "15nm(1z)",   "50": "A19nm(1y)",
    "57": "19nm(1x)",   "56": "24nm",
}

_TOTAL_PLANE: dict[str, int] = {
    "6": 2,   "A": 4,   "E": 8,
    "2": 16,  "B": 12,
}


def _decode_toggle_id(id_str: str, vendor_name: str) -> dict | None:
    if len(id_str) < 12:
        id_str = id_str.ljust(12, "0")

    data: dict = {"id": id_str, "vendor": vendor_name}

    # 密度 (bytes 2-3)
    data["density"] = DENSITY_TOGGLE.get(id_str[2:4], "Unknown")

    # Die 和 CellLevel (byte 5)
    data["die"], data["cellLevel"] = decode_die_cell_level(id_str[5])

    # PageSize (byte 7, bit 0-1)
    data["pageSize"] = ["2KB", "4KB", "8KB", "16KB"][int(id_str[7], 16) % 4]

    # Plane (byte 9 → totalPlane → / die)
    total = _TOTAL_PLANE.get(id_str[9], 0)
    try:
        plane = total // int(data["die"])
        while plane >= 16:
            plane //= 16
        data["plane"] = str(plane)
    except (ValueError, ZeroDivisionError):
        data["plane"] = "Unknown"

    # ProcessNode (bytes 10-11, bit 0-2)
    pn1 = int(id_str[10], 16) % 8
    pn2 = int(id_str[11], 16) % 8
    p_n = str(pn1) + str(pn2)

    if p_n == "63" and id_str[8] == "F":
        data["processNode"] = "BiCS4.5"
    else:
        data["processNode"] = _PROCESS_TOGGLE.get(p_n, "Unknown")

    return data
