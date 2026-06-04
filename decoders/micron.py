"""镁光 (Micron) 解码器，支持 FBGA 码、MT/29 料号和 Flash ID 解码。"""
from . import register, BaseDecoder, decode_die_cell_level
from ..utils import resolve_micron_fbga

# ── FBGA 解析 ─────────────────────────────────────────────────────────

_MICRON_FBGA_PREFIXES = ("N", "C", "D", "J")



# ── 密度表 (takeLongest) ─────────────────────────────────────────────

def _take_longest_density(s: str) -> tuple[str, str, str]:
    """贪心匹配最长的密度码，返回 (matched, 密度值, 剩余)。

    常规: {n}G → n Gb, {n}T → n Tb
    特殊: 1T2 → 1.125 Tb, 1HT → 1.5 Tb
    """
    special: dict[str, str] = {"1T2": "1.125Tb", "1HT": "1.5Tb"}
    for key in sorted(special, key=len, reverse=True):
        if s.startswith(key):
            return (key, special[key], s[len(key):])
    for i in range(len(s), 0, -1):
        prefix = s[:i]
        if prefix.endswith("G") and prefix[:-1].isdigit():
            val = f"{int(prefix[:-1])}Gb"
            return (prefix, val, s[i:])
        if prefix.endswith("T") and prefix[:-1].isdigit():
            val = f"{int(prefix[:-1])}Tb"
            return (prefix, val, s[i:])
    return ("", "Unknown", s)


# ── 其他映射表 ───────────────────────────────────────────────────────

_CELL_MAP = {
    "A": "SLC", "C": "MLC", "E": "TLC", "G": "QLC",
}

_CLASS_MAP: dict[str, dict[str, int]] = {
    "1": {"ce": 2, "ch": 1, "die": 16}, "2": {"ce": 8, "ch": 2, "die": 64},
    "3": {"ce": 4, "ch": 2, "die": 8}, "4": {"ce": 4, "ch": 1, "die": 4},
    "A": {"ce": 0, "ch": 1, "die": 1}, "B": {"ce": 1, "ch": 1, "die": 1},
    "D": {"ce": 1, "ch": 1, "die": 2}, "E": {"ce": 2, "ch": 2, "die": 2},
    "F": {"ce": 2, "ch": 1, "die": 2}, "G": {"ce": 3, "ch": 3, "die": 3},
    "J": {"ce": 2, "ch": 1, "die": 4}, "K": {"ce": 2, "ch": 2, "die": 4},
    "L": {"ce": 4, "ch": 4, "die": 4}, "M": {"ce": 4, "ch": 2, "die": 4},
    "Q": {"ce": 4, "ch": 4, "die": 8}, "R": {"ce": 2, "ch": 2, "die": 8},
    "T": {"ce": 8, "ch": 2, "die": 16}, "U": {"ce": 4, "ch": 2, "die": 8},
    "V": {"ce": 8, "ch": 4, "die": 16}, "C": {"ce": 3, "ch": 2, "die": 3},
    "H": {"ce": 1, "ch": 1, "die": 4}, "N": {"ce": 6, "ch": 3, "die": 6},
    "P": {"ce": 8, "ch": 2, "die": 8}, "W": {"ce": 4, "ch": 2, "die": 16},
    "X": {"ce": 4, "ch": 2, "die": 4}, "Y": {"ce": 7, "ch": 4, "die": 11},
    "S": {"ce": 4, "ch": 4, "die": 16},
}

_VOLTAGE_MAP = {
    "A": "Vcc: 3.3V (2.70–3.60V), VccQ: 3.3V (2.70–3.60V)",
    "B": "1.8V (1.70–1.95V)",
    "C": "Vcc: 3.3V (2.70–3.60V), VccQ: 1.8V (1.70–1.95V)",
    "D": "Vcc: 3.3V (2.70–3.60V), VccQ: 1.8V (1.70–1.95V)",
    "E": "Vcc: 3.3V (2.70–3.60V), VccQ: 3.3V or 1.8V",
    "F": "Vcc: 3.3V (2.50–3.60V), VccQ: 1.2V (1.14–1.26V)",
    "G": "Vcc: 3.3V (2.60–3.60V), VccQ: 1.8V (1.70–1.95V)",
    "H": "Vcc: 3.3V (2.50–3.60V), VccQ: 1.2V or 1.8V",
    "J": "Vcc: 3.3V (2.50–3.60V), VccQ: 1.8V (1.70–1.95V)",
    "K": "Vcc: 3.3V (2.60–3.60V), VccQ: 3.3V (2.60–3.60V)",
    "L": "Vcc: 2.5V/3.3V, VccQ: 1.2V", "S": "Vcc: 3.3V, VccQ: 3.3V",
    "T": "Vcc: 3.3V, VccQ: 1.2V/1.8V",
}

_DIE_CODE_MAP = {
    "A": "A-Die", "B": "B-Die", "C": "C-Die", "D": "D-Die",
    "E": "E-Die", "F": "F-Die", "G": "G-Die",
    "K": "K-Die", "L": "L-Die",
}

_PACKAGE_MAP: dict[str, str] = {
    "C3": "LGA52", "C4": "LGA52", "C5": "LGA52", "C6": "LGA52",
    "C7": "LGA48", "C8": "LGA52", "D1": "LGA52",
    "D4": "BGA154", "D5": "BGA154", "D6": "BGA154", "D7": "BGA154", "D8": "BGA154",
    "G1": "BGA272", "G2": "BGA272", "G4": "BGA252", "G5": "BGA272",
    "G6": "BGA272", "G7": "BGA252", "G8": "BGA252", "G9": "BGA252",
    "H1": "BGA100", "H2": "BGA100", "H3": "BGA100", "H4": "BGA63",
    "H5": "BGA56", "H6": "BGA152", "H7": "BGA152", "H8": "BGA152", "H9": "BGA152",
    "HC": "BGA63",
    "J1": "BGA132", "J2": "BGA132", "J3": "BGA132", "J4": "BGA132",
    "J5": "BGA132", "J6": "BGA132", "J7": "BGA152", "J9": "BGA132",
    "K3": "BGA100", "K4": "BGA100", "K6": "BGA152", "K7": "BGA152",
    "K8": "BGA152", "K9": "BGA132",
    "L4": "BGA160", "L5": "BGA160", "L6": "BGA160", "L7": "BGA160", "L8": "BGA160",
    "M4": "BGA132", "M5": "BGA132", "M6": "BGA132", "M8": "BGA55", "M9": "BGA252",
    "MD": "BGA130", "M8Z": "BGA55",
    "WP": "TSOP48", "WC": "TSOP48",
}

_PACKAGE_KEYS = sorted(_PACKAGE_MAP.keys(), key=len, reverse=True)


def _take_longest_package(s: str) -> tuple[str, str]:
    for key in _PACKAGE_KEYS:
        if s.startswith(key):
            return (key, _PACKAGE_MAP[key])
    return ("", "Unknown")


def _decode_mt29(pn: str) -> dict | None:
    """解码 MT/29 开头的 Micron 料号。"""
    rest = pn
    for prefix in ("MT", "29"):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
    if not rest:
        return None

    data: dict = {"partNumber": pn, "type": "NAND"}
    pos = 0

    # Enterprise flag (1位, 总是消费)
    ent_flag = rest[pos] if pos < len(rest) else ""
    if ent_flag == "E":
        data["enterprise"] = True
    pos += 1

    # Density (takeLongest)
    _, density_str, rest2 = _take_longest_density(rest[pos:])
    consumed = len(rest[pos:]) - len(rest2)
    pos += consumed
    data["density"] = density_str

    # Device width (2位)
    width_code = rest[pos:pos + 2] if pos + 1 < len(rest) else ""
    pos += 2
    try:
        data["deviceWidth"] = f"x{int(width_code)}"
    except ValueError:
        data["deviceWidth"] = "Unknown"

    # Cell level (1位)
    cell_code = rest[pos] if pos < len(rest) else ""
    pos += 1
    data["cellLevel"] = _CELL_MAP.get(cell_code, "Unknown")

    # Classification (1位)
    cls_code = rest[pos] if pos < len(rest) else ""
    pos += 1
    cls = _CLASS_MAP.get(cls_code, {"ce": -1, "ch": -1, "die": -1})
    data["classification"] = {"ce": cls["ce"], "ch": cls["ch"], "die": cls["die"]}

    # Voltage (1位)
    volt_code = rest[pos] if pos < len(rest) else ""
    pos += 1
    data["voltage"] = _VOLTAGE_MAP.get(volt_code, "Unknown")

    # Die code (1位)
    die_code = rest[pos] if pos < len(rest) else ""
    pos += 1
    data["dieCode"] = _DIE_CODE_MAP.get(die_code, "Unknown")

    # Interface (1位)
    pos += 1

    # Package (takeLongest)
    _, data["package"] = _take_longest_package(rest[pos:])

    if data["density"] == "Unknown":
        return None

    data["vendor"] = "Micron"
    return data


# ── Flash ID 解码表 ──────────────────────────────────────────────────

_MICRON_DENSITY: dict[str, str] = {
    "DC": "512MB", "48": "2GB", "68": "4GB",
    "88": "8GB", "64": "8GB",
    "A8": "16GB", "84": "16GB", "A3": "32GB", "A4": "32GB",
    "B4": "48GB", "C3": "64GB", "C4": "64GB",
    "CB": "96GB", "CC": "96GB", "D3": "128GB", "D4": "128GB",
    "09": "153.6GB", "E3": "256GB", "E4": "256GB",
    "F3": "512GB", "F4": "512GB", "03": "1TB", "04": "1TB",
}

# _2d_pn = id_str[6:8] → 区分 2D/3D
_MICRON_2D_PROCESS: dict[str, str] = {
    "46": "32nm", "CB": "25nm", "3C": "20nm",
    "4B": "20nm", "54": "16nm", "34": "IM3D",
}

_MICRON_PAGE_SIZE: dict[str, str] = {
    "6": "4KB", "7": "8KB", "3": "8KB", "2": "16KB", "4": "16KB",
}


def _decode_micron_id(id_str: str, vendor_name: str = "Micron") -> dict | None:
    """解码 2C 开头美光 Flash ID。"""
    if len(id_str) < 12:
        id_str = id_str.ljust(12, "0")

    data: dict = {"id": id_str, "vendor": vendor_name}

    # Density (bytes 2-3 查表)
    data["density"] = _MICRON_DENSITY.get(id_str[2:4], "Unknown")

    # Die & CellLevel (byte 5)
    data["die"], data["cellLevel"] = decode_die_cell_level(id_str[5])

    # PageSize (byte 4, bit 0-2)
    b4 = int(id_str[4], 16) & 0x07
    data["pageSize"] = _MICRON_PAGE_SIZE.get(str(b4), "Unknown")

    # Plane (byte 5, bit 0-1)
    b5 = int(id_str[5], 16) & 0x03
    data["plane"] = str(b5 + 1)

    # ProcessNode
    _2d = id_str[6:8]
    if _2d in _MICRON_2D_PROCESS:
        data["processNode"] = _MICRON_2D_PROCESS[_2d]
        cell = data["cellLevel"]
        die_size = data["density"]
        data["processNode"] += f"({cell[0]}{({'46':'6','CB':'7','3C':'8','54':'9','34':'0'}.get(_2d,'x'))}{({'16GB':'5','8GB':'4','4GB':'3','2GB':'2'}.get(die_size,'x'))})"
    elif _2d in ("32", "42"):
        # 3D — key = id_str[8:10]
        cell = data["cellLevel"]
        _8_10 = id_str[8:10]
        _10_12 = id_str[10:12]
        _4 = id_str[4]

        if _8_10 == "A1":
            data["processNode"] = "3D1 32L(B05)" if id_str[2:4] == "84" else "3D2 64L(B16)"
        elif _8_10 == "AA":
            data["processNode"] = {"MLC": "3D1 32L(L06)", "TLC": "3D1 32L(B0K)", "QLC": "3D2 64L(N18)"}.get(cell, "3D1")
        elif _8_10 == "A6":
            data["processNode"] = {"TLC": "3D2 64L(B17)", "QLC": "3D4 144L(N38A)"}.get(cell, "3D2 64L")
        elif _8_10 == "A2":
            data["processNode"] = "3D3 96L(B27A)"
        elif _8_10 == "C2" and _4 == "2":
            data["processNode"] = {"2": "3D5 176L(N4PA)", "9": "3D4 144L(N38B)", "A": "3D4 144L(N38B)"}.get(_10_12, "3D5")
        elif _8_10 == "C6" and _4 == "1":
            data["processNode"] = {"1": "3D3 96L(N28A)", "9": "3D4 144L(N38A)", "6": "3D3 96L(M26A)",
                                   "A": "3D4 144L(N38A)", "2": "3D4 144L(N38E)"}.get(id_str[9], "3D3")
        elif _8_10 == "E5":
            data["processNode"] = "3D4 144L(B36R)"
        elif _8_10 == "E6":
            data["processNode"] = {"10": "3D4 144L(B37R)", "30": f"3D5 176L({cell[1]}47R)",
                                   "34": "3D5 176L(B47T)"}.get(_10_12, "3D5")
        elif _8_10 == "E8":
            data["processNode"] = {"30": f"3D6 232L({cell[1]}58R)", "33": "3D7 ???L(N69R)"}.get(_10_12, "3D6")
        else:
            data["processNode"] = "Unknown"
    else:
        data["processNode"] = "Unknown"

    # 电压 (byte 2, bit 0-2)
    v = int(id_str[2], 16) & 0x07
    data["voltage"] = {3: "Vcc: 2.5V/3.3V", 4: "Vcc: 3.3V"}.get(v, "Unknown")

    return data


# ── 注册解码器 ───────────────────────────────────────────────────────


@register
class MicronDecoder(BaseDecoder):
    """镁光 (Micron) 解码器。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        if not pn:
            return False
        # 5/10 位 FBGA 码（首位为 K 的 10 位跳过，可能是三星料号）
        if len(pn) in (5, 10):
            if len(pn) == 5 and pn[0] in _MICRON_FBGA_PREFIXES:
                return True
            if len(pn) == 10 and pn[5] in _MICRON_FBGA_PREFIXES and pn[0] != "K":
                return True
        # MT/CT 料号 (CT 是镁光消费级 DRAM)
        return pn.startswith(("MT", "CT"))

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn:
            return None

        # 10 位 FBGA → 提取后 5 位码解析（首位 K 跳过）
        if len(pn) == 10 and pn[5] in _MICRON_FBGA_PREFIXES and pn[0] != "K":
            return self.decode_pn(pn[5:])

        # 5 位 FBGA 码 → 查 API 得到完整料号，路由到对应解码器
        if len(pn) == 5 and pn[0] in _MICRON_FBGA_PREFIXES:
            resolved = resolve_micron_fbga(pn)
            if resolved:
                # DRAM（MT 非 MT29 前缀）→ dram decoder
                if resolved.startswith("MT") and not resolved.startswith("MT29"):
                    from .dram import DramDecoder
                    return DramDecoder().decode_pn(resolved)
                # NAND → micron 自己的解码器
                return self.decode_pn(resolved)
            return {"partNumber": pn, "vendor": "Micron"}

        # MT/CT 前缀
        if pn.startswith(("MT", "CT")):
            # CT → MCT (Micron 标准前缀)，走 dram
            if pn.startswith("CT"):
                from .dram import DramDecoder
                result = DramDecoder().decode_pn("M" + pn[1:])
                if result:
                    result["partNumber"] = pn
                return result
            # DRAM 料号（MT 非 MT29 前缀）
            if pn.startswith("MT") and not pn.startswith("MT29"):
                from .dram import DramDecoder
                return DramDecoder().decode_pn(pn)
            return _decode_mt29(pn)

        return None

    # ── Flash ID 解码 ─────────────────────────────────────────────

    def check_id(self, id_str: str) -> bool:
        return id_str.strip().upper().startswith(("2C", "89", "B5"))

    def decode_id(self, id_str: str) -> dict | None:
        id_str = id_str.strip().upper()
        if not id_str.startswith(("2C", "89", "B5")):
            return None
        vendor = {"2C": "Micron", "89": "Intel", "B5": "Spectek"}.get(id_str[:2], "Unknown")
        return _decode_micron_id(id_str, vendor)
