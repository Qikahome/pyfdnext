"""三星 (Samsung) 解码器，支持 K9 料号和 Flash ID (EC) 解码。"""
from . import register, BaseDecoder, decode_die_cell_level
from ..utils import format_density


# ── 密度表 ─────────────────────────────────────────────────────────

_SAMSUNG_DENSITY: dict[str, int] = {
    "12": 512, "16": 16, "28": 128, "32": 32,
    "40": 4, "56": 256, "64": 64, "80": 8,
    "1G": 1024, "2G": 2048, "4G": 4096, "8G": 8192,
    "AG": 16384, "BG": 32768, "CG": 65536, "DG": 131072,
    "EG": 262144, "FG": 262144, "GG": 393216, "HG": 524288,
    "LG": 24576, "NG": 98304, "ZG": 49152,
    "PG": 175104, "QG": 349184, "RG": 699392, "SG": 1397760,
    "KG": 1048576, "MG": 2097152, "UG": 4194304, "VG": 8388608,
}


# ── 分类码表 (第1位: cell + die) ───────────────────────────────────

_SAMSUNG_CELL: dict[str, str] = {
    "F": "SLC", "K": "SLC", "N": "SLC", "Q": "SLC", "T": "SLC",
    "V": "SLC", "W": "SLC",
    "G": "MLC", "H": "MLC", "L": "MLC", "M": "MLC", "P": "MLC",
    "R": "MLC", "S": "MLC", "U": "MLC",
    "A": "TLC", "B": "TLC", "C": "TLC", "D": "TLC", "O": "TLC",
    "3": "TLC",
    "9": "QLC", "X": "QLC",
}

_SAMSUNG_DIE: dict[str, int] = {
    "F": 1, "G": 1, "K": 2, "N": 2, "M": 2, "L": 2,
    "H": 4, "C": 4, "W": 4, "P": 8, "O": 8, "Q": 8,
    "A": 1, "B": 2, "D": 16, "R": 12, "S": 6, "T": 1,
    "U": 16, "V": 16, "3": 1, "9": 8, "X": -1,
}


# ── Toggle 版本 ───────────────────────────────────────────────────

_SAMSUNG_TOGGLE: dict[str, str] = {
    "D": "1.0", "Y": "2.0", "B": "3.0",
}


# ── 位宽 ──────────────────────────────────────────────────────────

_SAMSUNG_WIDTH: dict[str, int] = {"0": 0, "8": 8, "6": 16}


# ── 电压 ──────────────────────────────────────────────────────────

_SAMSUNG_VOLTAGE: dict[str, str] = {
    "A": "1.65V~3.6V",
    "B": "2.7V (2.5V~2.9V)",
    "C": "5.0V (4.5V~5.5V)",
    "D": "2.65V (2.4V~2.9V)",
    "E": "2.3V~3.6V",
    "R": "1.8V (1.65V~1.95V)",
    "Q": "1.8V (1.7V~1.95V)",
    "T": "2.4V~3.0V",
    "S": "Vcc: 3.3V (3V~3.6V), VccQ: 1.8V (1.65V~1.95V)",
    "U": "2.7V~3.6V",
    "V": "3.3V (3.0V~3.6V)",
    "W": "2.7V~5.5V, 3.0V~5.5V",
    "H": "Vcc: 3.3V, VccQ: 1.8V (UNOFFICIAL)",
}


# ── CE / RB ───────────────────────────────────────────────────────

_SAMSUNG_CE: dict[str, int] = {
    "0": 1, "1": 2, "3": 3, "4": 4, "5": 4,
    "6": 6, "7": 8, "8": 8, "C": 16, "J": 16,
}

_SAMSUNG_RB: dict[str, int] = {
    "0": 1, "1": 2, "3": 3, "4": 1, "5": 4,
    "6": 2, "7": 4, "8": 2, "C": 2, "J": 4,
}


# ── 代数 ──────────────────────────────────────────────────────────

_SAMSUNG_GEN: dict[str, int] = {
    "M": 1, "A": 2, "B": 3, "C": 4, "D": 5, "E": 6,
    "F": 7, "G": 8, "H": 9, "Y": 25, "Z": 26,
}


# ── 封装 ──────────────────────────────────────────────────────────

_SAMSUNG_PACKAGE: dict[str, str] = {
    "8": "TSOP1", "9": "56-TSOP1", "A": "COB",
    "B": "FBGA", "C": "BGA316", "D": "TBGA63 or 316",
    "E": "ISM", "F": "WSOP", "G": "FBGA",
    "H": "BGA132 or 136", "I": "ULGA (12*17)", "J": "FBGA",
    "K": "ULGA (12*17)", "L": "ULGA (14*18)", "M": "ULGA52 (13*18)",
    "P": "TSOP1", "Q": "TSOP2", "R": "56-TSOP1",
    "S": "TSOP1", "T": "WSOP", "U": "COB (MMC)",
    "V": "WSOP", "W": "Wafer", "Y": "TSOP1",
    "Z": "WELP", "X": "BGA108", "1": "BGA108",
}


# ── 工作温度 ──────────────────────────────────────────────────────

_SAMSUNG_TEMP: dict[str, str] = {
    "C": "0~70°C", "S": "-25~85°C",
    "B": "0~85°C", "I": "-40~85°C",
}


# ── Flash ID 密度表 (id_str[3], 第4位 hex 查表) ──────────────────

_SAMSUNG_ID_DENSITY: dict[str, str] = {
    "A": "16GB", "C": "32GB", "E": "64GB",
    "F": "128GB", "1": "256GB", "2": "512GB",
}


# ── Flash ID ProcessNode (EC byte 6 low nibble, hex 查表) ────────

_SAMSUNG_ID_PROCESS: dict[str, str] = {
    "0": "50nm", "1": "40nm", "2": "30nm", "3": "27nm",
    "4": "21nm", "5": "19nm", "6": "16nm",
    "7": "24L 3DV1", "8": "32L 3DV2", "9": "48L 3DV3",
    "A": "14nm", "B": "64L 3DV4", "C": "92L 3DV5", "D": "128L 3DV6",
}


# ── 料号解码 ───────────────────────────────────────────────────────


def _decode_k9(pn: str) -> dict | None:
    """解码 K9 开头的三星 NAND 料号。

    格式: K9{cell}{density:2}{tech}{width}{voltage}{mode}{gen}[-]{pkg}{temp}{badblock}
    """
    rest = pn
    if not rest.startswith("K9"):
        return None
    rest = rest[2:]

    pos = 0

    # 1. 分类码 (1位) → cell + die
    cc = rest[pos] if pos < len(rest) else ""
    pos += 1
    cell = _SAMSUNG_CELL.get(cc, "Unknown")
    die = _SAMSUNG_DIE.get(cc, 1)

    # 2. 密度 (2位)
    dc = rest[pos:pos + 2] if pos + 1 < len(rest) else ""
    pos += 2
    density_mb = _SAMSUNG_DENSITY.get(dc)
    density_str = format_density(density_mb) if density_mb else "Unknown"

    # 3. Technology/Interface (1位)
    tc = rest[pos] if pos < len(rest) else ""
    pos += 1
    toggle_ver = _SAMSUNG_TOGGLE.get(tc, "Unknown")
    toggle_flag = tc in _SAMSUNG_TOGGLE

    # 4. 位宽 (1位)
    wc = rest[pos] if pos < len(rest) else ""
    pos += 1
    width_val = _SAMSUNG_WIDTH.get(wc, 8)
    width = f"x{width_val}" if width_val else "Unknown"

    # 5. 电压 (1位)
    vc = rest[pos] if pos < len(rest) else ""
    pos += 1
    voltage = _SAMSUNG_VOLTAGE.get(vc, "Unknown")

    # 6. Mode (1位) → ce + rb
    mc = rest[pos] if pos < len(rest) else ""
    pos += 1
    ce = _SAMSUNG_CE.get(mc, 1)
    rb = _SAMSUNG_RB.get(mc, 1)

    # 7. 代数 (1位)
    gc = rest[pos] if pos < len(rest) else ""
    pos += 1
    gen = _SAMSUNG_GEN.get(gc, -1)

    # 8. 可选 "-" 分隔符
    if pos < len(rest) and rest[pos] == "-":
        pos += 1

    # 9. 封装 (1位)
    pc = rest[pos] if pos < len(rest) else ""
    pos += 1
    pkg = _SAMSUNG_PACKAGE.get(pc, "Unknown")

    # 10. 温度 (1位)
    tc2 = rest[pos] if pos < len(rest) else ""
    pos += 1
    op_temp = _SAMSUNG_TEMP.get(tc2, "Unknown")

    # 11. 坏块 (1位, 可选)
    bc = rest[pos] if pos < len(rest) else ""

    result = {
        "partNumber": pn,
        "vendor": "Samsung",
        "type": "NAND",
        "density": density_str,
        "deviceWidth": width,
        "cellLevel": cell,
        "voltage": voltage,
        "generation": str(gen) if gen != -1 else "Unknown",
        "package": pkg,
        "classification": {
            "die": die,
            "ce": ce,
            "rb": rb,
        },
        "interface": {"toggle": toggle_flag},
    }

    extra = {}
    if toggle_ver != "Unknown":
        extra["toggleVersion"] = toggle_ver
    if op_temp != "Unknown":
        extra["operatingTemperature"] = op_temp
    if bc:
        extra["badBlock"] = bc
    if extra:
        result["extraInfo"] = extra

    return result


# ── Flash ID 解码 ─────────────────────────────────────────────────


def _decode_samsung_id(id_str: str) -> dict | None:
    """解码 EC 开头的三星 Flash ID。"""
    if len(id_str) < 12:
        id_str = id_str.ljust(12, "0")

    data: dict = {"id": id_str, "vendor": "Samsung"}

    # 密度: id_str[3] 第4位 hex 查表
    data["density"] = _SAMSUNG_ID_DENSITY.get(id_str[3].upper(), "Unknown")

    # 第6位 (id_str[5]): die + cellLevel
    die, cell = decode_die_cell_level(id_str[5])
    data["die"] = die
    data["cellLevel"] = cell

    # byte 4 低 nibble (id_str[7] bits 0-1): pageSize
    data["pageSize"] = ["2KB", "4KB", "8KB", "16KB"][int(id_str[7], 16) % 4]

    # byte 5 低 nibble (id_str[9] bits 2-3): 总 plane 数（CE级），需 /die
    _total = [1, 2, 4, 8][(int(id_str[9], 16) >> 2) % 4]
    data["plane"] = str(_total // int(die)) if int(die) else str(_total)

    # byte 6 低 nibble (id_str[11]): processNode
    data["processNode"] = _SAMSUNG_ID_PROCESS.get(id_str[11].upper(), "Unknown")

    return data


# ── 注册解码器 ───────────────────────────────────────────────────────


@register
class SamsungDecoder(BaseDecoder):
    """三星 NAND 解码器。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        if not pn:
            return False
        return pn.startswith(("K9", "KLM", "KLU", "KMD", "KMF", "KMN", "KMV", "K3"))

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn:
            return None

        if pn.startswith("K9"):
            return _decode_k9(pn)

        if pn.startswith(("KLM", "KLU", "KMD", "KMF", "KMN", "KMV", "K3")):
            return {"partNumber": pn, "vendor": "Samsung", "type": "Managed NAND"}

        return None

    # ── Flash ID 解码 ─────────────────────────────────────────────

    def check_id(self, id_str: str) -> bool:
        return id_str.strip().upper().startswith("EC")

    def decode_id(self, id_str: str) -> dict | None:
        id_str = id_str.strip().upper()
        if not id_str.startswith("EC"):
            return None
        return _decode_samsung_id(id_str)
