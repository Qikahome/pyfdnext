"""长江存储 (YMTC) 解码器，支持 YM 料号和 Flash ID 解码。"""
import math
from . import register, BaseDecoder, decode_die_cell_level
from ..utils import format_density, total_density

# ── 系统/品牌表 ─────────────────────────────────────────────────────

_YMTC_SYSTEM: dict[str, str] = {
    "YM": "YMTC", "KR": "KRYSTOR",
    "BP": "YMTC Business Partner", "BR": "KRYSTOR Business Partner",
    "BW": "BIWIN Label",
}

# ── Die 密度表 ─────────────────────────────────────────────────────

_YMTC_DIE_SIZE: dict[str, int] = {
    "6": 65536, "7": 131072, "8": 262144, "9": 524288,
    "A": 1048576, "W": 1394606,
}

# ── 关联编码表 ────────────────────────────────────────────────────

_YMTC_CELL: dict[str, str] = {
    "S": "SLC", "M": "MLC", "T": "TLC", "Q": "QLC",
}

_YMTC_WIDTH: dict[str, int] = {"1": 8, "2": 16}

_YMTC_PACKAGE: dict[str, str] = {
    "W0": "Wafer", "T1": "TSOP-48", "L1": "LGA-52",
    "B1": "BGA-132", "B2": "BGA-152", "B3": "BGA-272",
    "B4": "BGA-252", "B5": "BGA-154",
}

_YMTC_VOLTAGE: dict[str, str] = {
    "A": "Vcc: 3.30V, VccQ: 3.30V",
    "B": "Vcc: 3.30V, VccQ: 1.80V",
    "C": "Vcc: 3.30V/2.50V, VccQ: 1.20V",
    "D": "Vcc: 3.30V/2.50V, VccQ: 3.30V/1.80V",
    "E": "Vcc: 3.30V/2.50V, VccQ: 1.80V/1.20V",
    "F": "Vcc: 2.50V, VccQ: 1.20V",
}

_YMTC_CLASS_DIE: dict[str, int] = {
    "A": 1, "B": 2, "C": 2, "D": 2, "E": 4,
    "F": 4, "G": 4, "H": 4, "Q": 4, "I": 8,
    "J": 8, "K": 8, "L": 8, "R": 8,
    "M": 16, "N": 16, "O": 16, "P": 16, "S": 16,
    "0": 1,
}

_YMTC_CLASS_CE: dict[str, int] = {
    "A": 1, "B": 1, "C": 2, "D": 2, "E": 2,
    "F": 4, "G": 2, "H": 4, "Q": 4, "I": 2,
    "J": 4, "K": 4, "L": 8, "R": 8,
    "M": 4, "N": 4, "O": 8, "P": 8, "S": 16,
}

_YMTC_CLASS_CH: dict[str, int] = {
    "A": 1, "B": 1, "C": 1, "D": 2, "E": 1,
    "F": 1, "G": 2, "H": 2, "Q": 4, "I": 2,
    "J": 2, "K": 4, "L": 4, "R": 2,
    "M": 2, "N": 4, "O": 2, "P": 4, "S": 4,
}

_YMTC_PRODUCT_CLASS: dict[str, str] = {
    "C": "Client", "P": "Client", "E": "Enterprise",
    "F": "Enterprise", "D": "Downgrade", "U": "Low Speed",
    "M": "Client MLC", "X": "Undefined",
}

_YMTC_SPEED: dict[str, str] = {
    "0": "400MT/s", "1": "533MT/s", "2": "667MT/s",
    "3": "800MT/s", "4": "1200MT/s", "5": "1333MT/s",
    "6": "1600MT/s", "A": "2400MT/s", "B": "3600MT/s",
}

_YMTC_GEN: dict[str, str] = {
    "A": "Gen1", "B": "Gen2 Xtacking 1.0",
    "C": "Gen3 Xtacking 2.0", "D": "Gen4 Xtacking 3.0",
    "E": "Gen5 Xtacking 4.0",
}

# ── Cell → 字符映射 ───────────────────────────────────────────────

_YMTC_CELL_CHAR: dict[str, str] = {"SLC": "M", "MLC": "A", "TLC": "9", "QLC": "6"}

# ── ProcessNode 映射表 (x{gen}-{cell}0{die_log}0 → 名称) ─────────

_YMTC_PROCESS_MAP: dict[str, str] = {
    "x0-A030": "DBS(x0-A030)",
    "x1-9050": "JGS(x1-9050)",
    "x2-9060": "TAS(x2-9060)",
    "x2-6070": "HUS(x2-6070)",
    "x3-9060": "WYS(x3-9060)",
    "x3-9070": "WDS(x3-9070)",
    "x3-6070": "EMS(x3-6070)",
    "x4-9070": "WTS(x4-9070)",
    "x4-6080": "PTS(x4-6080)",
}

_YMTC_PROCESS_ALIAS: dict[str, str] = {
    "X0-A030": "X0-A030", "X1-9050": "X1-9050",
    "X2-9060": "X2-9060", "X2-6070": "X2-6070",
    "X3-9060": "X3-9060", "X3-9070": "X3-9070",
    "X3-6070": "X3-6070",
    "X4-9060": "X4-9060", "X4-9070": "X4-9070", "X4-6080": "X4-6080",
}

# ── Flash ID 密度表（9B 前缀） ─────────────────────────────────────

_YMTC_ID_DENSITY: dict[str, str] = {
    "C2": "16GB", "C3": "32GB", "C4": "64GB",
    "C5": "128GB", "D5": "170GB",
    "C6": "256GB", "C7": "512GB",
}


# ── 料号解码 ───────────────────────────────────────────────────────


def _decode_ym(pn: str) -> dict | None:
    """解码 YM/KR/BP/BR/BW 开头的 YMTC NAND 料号。

    格式: {system}{N/S}{version}{dieSize}{cell}{voltage}{width}{package}{class}{product}{speed}{gen}
    例: YMN0AT1B1AE1A
    """
    rest = pn

    # 系统前缀 (2 位)
    sys_key = rest[:2]
    rest = rest[2:]
    system = _YMTC_SYSTEM.get(sys_key, sys_key)

    # 类型 (1 位, N/S)
    type_code = rest[:1]
    rest = rest[1:]
    if type_code not in ("N", "S"):
        return None

    # 版本 (1 位)
    ver = rest[:1]
    rest = rest[1:]

    # Die 大小 (1 位)
    ds = rest[:1]
    rest = rest[1:]
    die_size_mb = _YMTC_DIE_SIZE.get(ds)
    if die_size_mb is None:
        return None

    # 单元类型 (1 位)
    cc = rest[:1]
    rest = rest[1:]
    cell = _YMTC_CELL.get(cc, "Unknown")

    # 电压 (1 位)
    vc = rest[:1]
    rest = rest[1:]
    voltage = _YMTC_VOLTAGE.get(vc, "Unknown")

    # 位宽 (1 位)
    wc = rest[:1]
    rest = rest[1:]
    width = _YMTC_WIDTH.get(wc, 8)

    # 封装 (贪婪: 先试 2 位)
    pkg = "Unknown"
    for plen in (2, 1):
        pk = rest[:plen]
        if pk in _YMTC_PACKAGE:
            pkg = _YMTC_PACKAGE[pk]
            rest = rest[plen:]
            break
    else:
        # 不匹配的话吃 1 位
        rest = rest[1:]

    # 分类代码 (1 位)
    cl = rest[:1]
    rest = rest[1:]
    die = _YMTC_CLASS_DIE.get(cl, 1)
    ce = _YMTC_CLASS_CE.get(cl, 1)
    ch = _YMTC_CLASS_CH.get(cl, 1)

    # 产品等级 (1 位)
    pc = rest[:1]
    rest = rest[1:]
    product_class = _YMTC_PRODUCT_CLASS.get(pc, "Unknown")

    # 速度 (1 位)
    sc = rest[:1]
    rest = rest[1:]
    speed = _YMTC_SPEED.get(sc, "Unknown")

    # 代数 (1 位)
    gc = rest[:1] if rest else ""
    gen = _YMTC_GEN.get(gc, "Unknown")

    # ProcessNode: x{gen}-{cell_char}0{die_log}0 → process_map 查
    gen_digit = int(gc, 36) - 10 if gc.isalnum() else "x"
    die_size_gb_bytes = die_size_mb // 8 // 1024
    die_log = int(math.log2(die_size_gb_bytes)) if die_size_gb_bytes > 0 else 0
    x_key = f"x{gen_digit}-{_YMTC_CELL_CHAR.get(cell, 'x')}0{die_log}0"
    process = _YMTC_PROCESS_MAP.get(x_key, "Unknown")

    # 总密度 = die_size × die
    total_mb = int(die_size_mb * die)
    density_str = format_density(total_mb)

    return {
        "partNumber": pn,
        "vendor": "YMTC",
        "type": "NAND",
        "density": density_str,
        "deviceWidth": f"x{width}",
        "cellLevel": cell,
        "voltage": voltage,
        "processNode": process,
        "generation": gen,
        "package": pkg,
        "speed": speed,
        "classification": {
            "die": die,
            "ce": ce,
            "ch": ch,
        },
        "extraInfo": {
            "system": system,
            "productClass": product_class,
        },
    }


# ── Flash ID 解码 ─────────────────────────────────────────────────


def _decode_ymtc_id(id_str: str) -> dict | None:
    """解码 9B 开头的 YMTC Flash ID。"""
    # 补齐到至少 12 位，否则无法解析 processNode
    if len(id_str) < 12:
        id_str = id_str.ljust(12, "0")

    data: dict = {"id": id_str, "vendor": "YMTC"}
    data["pageSize"] = "16"

    if id_str[0:8] == "9B490100":
        data["density"] = "8GB"
        data["die"] = "1"
        data["cellLevel"] = "MLC"
        data["plane"] = "1"
    else:
        data["density"] = _YMTC_ID_DENSITY.get(id_str[2:4], "Unknown")
        data["die"], data["cellLevel"] = decode_die_cell_level(id_str[5])
        data["plane"] = str((int(id_str[6:8], 16) >> 5) * 2)

    data["dieDensity"] = total_density(data["density"], str(1.0 / int(data["die"])))

    cell_c = _YMTC_CELL_CHAR.get(data["cellLevel"], "x")
    log_val = int(math.log2(int(data["dieDensity"][:-2])))
    data["processNode"] = f"x{id_str[8]}-{cell_c}0{log_val}0"

    data["processNode"] = _YMTC_PROCESS_MAP.get(data["processNode"], data["processNode"])

    return data


# ── 注册解码器 ───────────────────────────────────────────────────────


@register
class YmtcDecoder(BaseDecoder):
    """长江存储 NAND 解码器。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        if not pn:
            return False
        return pn.startswith(("YMN", "YMS", "KRN", "BPN", "BRN")) or \
               pn.startswith("X") and "-" in pn

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn:
            return None

        # Process alias: X{gen}-{code}
        if pn.startswith("X") and "-" in pn:
            alias = pn.split("-")[0] + "-" + pn.split("-")[1][:4]
            if alias in _YMTC_PROCESS_ALIAS:
                return {
                    "partNumber": pn,
                    "vendor": "YMTC",
                    "type": "NAND",
                    "processNode": alias,
                }
            return None

        # YM/KR/BP/BR + N/S 开头
        if pn[:3] in ("YMN", "YMS", "KRN", "BPN", "BRN"):
            return _decode_ym(pn)

        return None

    # ── Flash ID 解码 ─────────────────────────────────────────────

    def check_id(self, id_str: str) -> bool:
        return id_str.strip().upper().startswith("9B")

    def decode_id(self, id_str: str) -> dict | None:
        id_str = id_str.strip().upper()
        if not id_str.startswith("9B"):
            return None
        return _decode_ymtc_id(id_str)
