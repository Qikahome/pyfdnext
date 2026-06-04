"""海力士 (SK hynix) 解码器，支持 H2/HY27/H25 料号和 Flash ID 解码。"""
from . import register, BaseDecoder, decode_die_cell_level, DENSITY_TOGGLE
from ..utils import format_density, total_density

# ── 密度表 ─────────────────────────────────────────────────────────

_HYNIX_DENSITY: dict[str, int] = {
    "64": 64, "25": 256, "12": 128, "51": 512,
    "1G": 1024, "2G": 2048, "4G": 4096, "8G": 8192,
    "AG": 16384, "BG": 32768, "CG": 65536, "DG": 131072,
    "EG": 262144, "FG": 524288,
    "PG": 196608, "RG": 393216, "VG": 786432,
    "1T": 1048576, "2T": 2097152, "4T": 4194304,
}

# ── 电压表 ─────────────────────────────────────────────────────────

_HYNIX_VOLTAGE: dict[str, str] = {
    "U": "Vcc: 3.3V, VccQ: 3.3V",
    "L": "2.7V",
    "S": "1.8V",
    "J": "2.7V~3.6V/1.2V",
    "Q": "Vcc: 2.7V~3.6V, VccQ: 1.7V~1.95V/2.7V~3.6V",
    "T": "Vcc: 3.3V, VccQ: 1.8V/3.3V",
}

# ── 位宽表 ─────────────────────────────────────────────────────────

_HYNIX_WIDTH: dict[str, int] = {"8": 8, "6": 16, "L": 8, "I": 8, "D": 8, "08": 8, "16": 16, "32": 32}

# ── 单元/分类表 ───────────────────────────────────────────────────

_HYNIX_CELL: dict[str, str] = {
    "S": "SLC", "A": "SLC", "B": "SLC", "F": "SLC", "G": "SLC",
    "H": "SLC", "J": "SLC", "K": "SLC",
    "T": "MLC", "U": "MLC", "V": "MLC", "W": "MLC", "Y": "MLC",
    "R": "MLC", "Z": "MLC", "C": "MLC", "2": "MLC", "4": "MLC",
    "3": "MLC", "5": "MLC", "D": "MLC",
    "M": "TLC", "N": "TLC", "P": "TLC", "Q": "TLC", "L": "TLC",
}

_HYNIX_DIE: dict[str, int] = {
    "S": 1, "A": 2, "B": 4, "F": 1, "G": 2, "H": 4, "J": 8, "K": 2,
    "T": 1, "U": 2, "V": 4, "W": 2, "Y": 8, "R": 6, "Z": 12, "C": 16,
    "M": 1, "N": 2, "P": 4, "Q": 8, "2": 1, "4": 2, "3": 4, "5": 8,
    "D": 1, "L": 16,
}

_HYNIX_CE: dict[str, int] = {
    "1": 1, "2": 1, "4": 2, "5": 2, "D": 2, "F": 4,
    "T": 5, "U": 6, "V": 8, "M": 4, "G": 4, "W": 6, "H": 8,
    "E": 4, "Q": 4, "A": 4,
}

_HYNIX_CH: dict[str, int] = {
    "1": 1, "2": 1, "4": 1, "5": 1, "D": 2, "F": 2,
    "T": 1, "U": 1, "V": 1, "M": 2, "G": 2, "W": 2, "H": 2,
    "E": 4, "Q": 4, "A": 2,
}

_HYNIX_GEN: dict[str, int] = {
    "M": 1, "A": 2, "B": 3, "C": 4, "D": 5, "E": 6,
    "F": 7, "G": 8, "H": 9, "Y": 25, "Z": 26,
}

_HYNIX_PACKAGE: dict[str, str] = {
    "T": "TSOP1", "V": "WSOP", "S": "USOP", "N": "LSOP1",
    "F": "FBGA", "X": "LGA", "M": "WLGA", "Y": "VLGA",
    "U": "ULGA", "W": "Wafer",
    "I": "VFBGA-100", "J": "LFBGA-100",
    "8": "FBGA-152", "9": "FBGA-152",
    "2": "FBGA-316", "3": "FBGA-316",
    "6": "BGA-132", "0": "BGA-132", "5": "BGA-132", "L": "BGA-132",
    "4": "BGA-132",
}

# ── AD Flash ID ProcessNode 映射 ───────────────────────────────

_HYNIX_ID_PROCESS_NODE: dict[str, str] = {
    "C4": "20nm",
    "25": "16nm", "50": "14nm",
    "60": "3DV1", "70": "3DV2", "80": "3DV3",
    "90": "3DV4", "A0": "3DV5",
    "B0": "3DV6", "C0": "3DV7", "D0": "3DV8",
}

# ── AD Flash ID 2D ProcessNode（byte 6 低 nibble, fdnext 补充） ──

_HYNIX_ID_PROCESS_2D: dict[str, str] = {
    "0": "48nm", "1": "41nm", "2": "32nm", "3": "26nm",
    "4": "20nm", "5": "16nm", "6": "16nm", "7": "16nm",
    "9": "16nm", "A": "16nm",
}


# ── 3D 密度表（第 8 位：A=64, B=128, D=256, F=512, G=1T GB） ──

_HYNIX_3D_DENSITY_8TH: dict[str, str] = {
    "A": "512Gb", "B": "1Tb", "D": "2Tb", "F": "4Tb", "G": "8Tb",
}

# ── 3D 代数映射 ────────────────────────────────────────────────

_HYNIX_3D_GEN_QFBF: dict[str, str] = {
    "A": "3DV4", "M": "3DV5", "B": "3DV6",
}

_HYNIX_3D_GEN_TXGX: dict[str, str] = {
    "C": "3DV7", "D": "3DV8", "M": "3DV6",
}

# ── 料号解码 ───────────────────────────────────────────────────────


def _decode_h25_density(code: str) -> str:
    """解码 H25 Tx/Gx 系列的密度码 (同 kioxia 格式)。

    G{9} → 2^9 Gb, T{0} → 2^0 Tb, T{1} → 2^1 Tb, 等。
    """
    if len(code) != 2:
        return "Unknown"
    prefix, suffix = code[0], code[1]
    if suffix.isdigit():
        n = int(suffix)
        if prefix == "G":
            return f"{2 ** n}Gb"
        elif prefix == "T":
            return f"{2 ** n}Tb"
    return "Unknown"


def _decode_h2(pn: str) -> dict | None:
    rest = pn
    if not rest.startswith("H2"):
        return None
    rest = rest[2:]

    # 跳过 3 位型号
    rest = rest[3:]

    # 电压 (1 位)
    vc = rest[:1]
    rest = rest[1:]
    voltage = _HYNIX_VOLTAGE.get(vc, "Unknown")

    # 密度 (2 位)
    dc = rest[:2]
    rest = rest[2:]
    density_val = _HYNIX_DENSITY.get(dc)
    if density_val is None:
        return None

    # 位宽 (1 位)
    wc = rest[:1]
    rest = rest[1:]
    width = _HYNIX_WIDTH.get(wc, 8)

    # 分类代码 (1 位)
    cc = rest[:1]
    rest = rest[1:]
    cell = _HYNIX_CELL.get(cc, "Unknown")
    die = _HYNIX_DIE.get(cc, 1)

    # 模式代码 (1 位)
    mc = rest[:1]
    rest = rest[1:]
    ce = _HYNIX_CE.get(mc, 1)
    ch = _HYNIX_CH.get(mc, 1)

    # 代数 (1 位)
    gc = rest[:1]
    rest = rest[1:]
    gen = _HYNIX_GEN.get(gc, -1)

    # 封装 (1 位)
    pkg = _HYNIX_PACKAGE.get(rest[:1], "Unknown")

    density_str = format_density(density_val)

    return {
        "partNumber": pn,
        "vendor": "海力士",
        "type": "NAND",
        "density": density_str,
        "deviceWidth": f"x{width}",
        "cellLevel": cell,
        "voltage": voltage,
        "generation": str(gen) if gen != -1 else "Unknown",
        "package": pkg,
        "classification": {
            "die": die,
            "ce": ce,
            "ch": ch,
        },
    }


def _decode_hy27(pn: str) -> dict | None:
    """解码 HY27 开头的海力士 NAND 料号 (HY27{V}{C}{WW}{DD}{M}{G}{skip}{P}{M}...)。"""
    rest = pn
    if not rest.startswith("HY27"):
        return None
    rest = rest[4:]

    # 电压 (1 位)
    vc = rest[:1]
    rest = rest[1:]
    voltage = _HYNIX_VOLTAGE.get(vc, "Unknown")

    # 分类 (1 位)
    cc = rest[:1]
    rest = rest[1:]
    cell = _HYNIX_CELL.get(cc, "Unknown")
    die = _HYNIX_DIE.get(cc, 1)

    # 位宽 (2 位)
    wc = rest[:2]
    rest = rest[2:]
    width = _HYNIX_WIDTH.get(wc, 8)

    # 密度 (2 位)
    dc = rest[:2]
    rest = rest[2:]
    density_val = _HYNIX_DENSITY.get(dc)
    if density_val is None:
        return None

    # 模式 (1 位)
    mc = rest[:1]
    rest = rest[1:]
    ce = _HYNIX_CE.get(mc, 1)
    ch = _HYNIX_CH.get(mc, 1)

    # 代数 (1 位)
    gc = rest[:1]
    rest = rest[1:]
    gen = _HYNIX_GEN.get(gc, -1)

    # 跳过 1 位
    rest = rest[1:]

    # 封装 (1 位)
    pkg = _HYNIX_PACKAGE.get(rest[:1], "Unknown")

    density_str = format_density(density_val)

    return {
        "partNumber": pn,
        "vendor": "海力士",
        "type": "NAND",
        "density": density_str,
        "deviceWidth": f"x{width}",
        "cellLevel": cell,
        "voltage": voltage,
        "generation": str(gen) if gen != -1 else "Unknown",
        "package": pkg,
        "classification": {
            "die": die,
            "ce": ce,
            "ch": ch,
        },
    }


def _decode_h25(pn: str) -> dict | None:
    """解码 H25 开头的海力士 3D NAND 料号。

    两种格式:
      - QF/BF 系列: H25{QF/BF}{T}{cell}{density_8th}{gen}{...}
        e.g. H25QFT8A1A (64GB), H25BFT8G5M (1TB)
      - Tx/Gx 系列: H25{Tx/Gx}{cell_code}{...} (4-5位密度, 同kioxia)
        e.g. H25T0TC18C (128GB), H25T1TC18C (256GB), H25G9TC18C (64GB)
    """
    rest = pn
    if not rest.startswith("H25"):
        return None
    rest = rest[3:]

    # 提取 2 位系列码
    series = rest[:2]

    cell_map = {"S": "SLC", "H": "SLC", "D": "MLC", "E": "MLC",
                 "J": "MLC", "C": "MLC", "T": "TLC", "U": "TLC",
                 "V": "TLC", "X": "TLC", "W": "TLC", "F": "QLC",
                 "M": "MLC", "Q": "QLC"}

    # H25 全系列: 单元类型在第 6 位 (rest[2])
    cell_code = rest[2] if len(rest) > 2 else ""
    cell = cell_map.get(cell_code, "Unknown")

    base = {
        "partNumber": pn, "vendor": "海力士", "type": "NAND",
        "deviceWidth": "x8", "cellLevel": cell,
        "voltage": "Vcc: 2.7V~3.6V, VccQ: 1.7V~1.95V/1.14V~1.26V",
        "interface": {"toggle": True},
    }

    # Tx/Gx 系列: 4-5 位本身用 kioxia 密度, gen 在 rest[3]
    if series not in ("QF", "BF", "QE"):
        density_str = _decode_h25_density(series)
        if density_str == "Unknown":
            return None
        base["density"] = density_str
        gen = _HYNIX_3D_GEN_TXGX.get(rest[3]) if len(rest) > 3 else None
        if gen:
            base["generation"] = gen
        return base

    # QF/BF/QE 系列: 密度在第 8 位（跳过系列码后的 rest[2]）
    rest = rest[2:]
    if len(rest) < 3:
        return None
    raw = _HYNIX_3D_DENSITY_8TH.get(rest[2])
    if not raw:
        return None
    # QE 是 MLC, 密度减半
    if series == "QE":
        num = int(raw[:-2])
        unit = raw[-2:]
        base["density"] = f"{num // 2}{unit}"
    else:
        base["density"] = raw
    if series == "QE":
        base["generation"] = "3DV4"
    elif gen := _HYNIX_3D_GEN_QFBF.get(pn[-1]):
        base["generation"] = gen
    return base


def _decode_hynix_id(id_str: str) -> dict | None:
    """解码 AD 开头的海力士 Flash ID（严格匹配 FDQueryMethods.py 逻辑）。"""
    if len(id_str) < 12:
        id_str = id_str.ljust(12, "0")

    data: dict = {"id": id_str, "vendor": "SK hynix"}

    # 密度: 使用 Toggle 通用密度表
    data["density"] = DENSITY_TOGGLE.get(id_str[2:4], "Unknown")

    # die/cellLevel: byte 5
    data["die"], data["cellLevel"] = decode_die_cell_level(id_str[5])

    # pageSize: id_str[7] bit 0-1
    data["pageSize"] = ["2", "4", "8", "16"][int(id_str[7], 16) % 4]

    # plane: id_str[4] bit 0-1
    data["plane"] = ["1", "2", "4", "8"][int(id_str[4], 16) % 4]

    # processNode: 4x 为 2D(byte 6 低 nibble), 其余 id_str[10:12] 查表
    if id_str[10] == "4" or (id_str[10] == "C" and id_str[11] != "0" and id_str[11] != "2"):
        data["processNode"] = _HYNIX_ID_PROCESS_2D.get(id_str[13], "Unknown")
    else:
        pn = id_str[10] + "0" if id_str[11] == "2" else id_str[10:12]
        data["processNode"] = _HYNIX_ID_PROCESS_NODE.get(pn, "Unknown")

    # 3D 时密度 * die 数
    if "3D" in data["processNode"]:
        data["density"] = total_density(data["density"], data["die"])

    return data


# ── 注册解码器 ───────────────────────────────────────────────────────


@register
class SkHynixDecoder(BaseDecoder):
    """海力士 NAND 解码器。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        if not pn:
            return False
        return pn.startswith(("H2", "HY27", "H25"))

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn:
            return None

        if pn.startswith("HY27"):
            return _decode_hy27(pn)
        if pn.startswith("H25"):
            return _decode_h25(pn)
        if pn.startswith("H2"):
            return _decode_h2(pn)

        return None

    # ── Flash ID 解码 ─────────────────────────────────────────────

    def check_id(self, id_str: str) -> bool:
        return id_str.strip().upper().startswith("AD")

    def decode_id(self, id_str: str) -> dict | None:
        id_str = id_str.strip().upper()
        if not id_str.startswith("AD"):
            return None
        return _decode_hynix_id(id_str)
