"""英特尔 (Intel) 解码器，支持 29F 料号和 Flash ID 解码。"""
from . import register, BaseDecoder, decode_die_cell_level
from ..utils import format_density

# ── 前缀/封装表 ────────────────────────────────────────────────────

_INTEL_PACKAGE: dict[str, str] = {
    "JS": "TSOP48", "BK": "LGA", "PF": "BGA", "CU": "LSOP",
}

# ── 位宽表 ─────────────────────────────────────────────────────────

_INTEL_WIDTH: dict[str, int] = {
    "08": 8, "16": 16, "2A": 8, "4A": 8, "A8": 8,
}

# ── 分类表 ─────────────────────────────────────────────────────────

_INTEL_DIE: dict[str, int] = {
    "A": 1, "B": 2, "C": 2, "D": 2, "E": 2,
    "F": 4, "G": 4, "H": 8, "J": 4, "K": 8,
    "L": 1, "M": 2, "N": 4, "O": 8, "P": 8,
    "Q": 8, "S": 16, "W": 16, "Y": 16,
}

_INTEL_CE: dict[str, int] = {
    "A": 1, "B": 1, "C": 2, "D": 2, "E": 2,
    "F": 2, "G": 2, "H": 4, "J": 4, "K": 4,
    "L": 1, "M": 2, "N": 4, "O": 8, "P": 8,
    "Q": 2, "S": 4, "W": 8, "Y": 4,
}

_INTEL_CH: dict[str, int] = {"4A": 4, "2A": 2}

# ── 电压表 ─────────────────────────────────────────────────────────

_INTEL_VOLTAGE: dict[str, str] = {
    "A": "3.3V (2.70V-3.60V)",
    "B": "1.8V (1.70V-1.95V)",
    "C": "Vcc: 3.3V, VccQ: 1.8V/1.2V",
}

# ── 制程表 ─────────────────────────────────────────────────────────

_INTEL_PROCESS: dict[str, str] = {
    "A": "90nm", "B": "72nm", "C": "50nm", "D": "34nm",
    "E": "25nm", "F": "20nm",
    "G": "3D1", "H": "3D2",
    "J": "3D3", "K": "3D4", "L": "3D5",
}

# ── 料号解码 ───────────────────────────────────────────────────────


def _intel_process_suffix(cell_level: str, pc: str, density_mb: int, die: int) -> str:
    """生成 processNode 的 (ABC) 后缀。

    A=cellLevel: SLC→M, MLC→L, TLC→B, QLC→N
    B=process: 34nm→6, 25nm→7, 20nm→8, 3Dn→n-1
    C=die density: 按 die_size(GB) 查表
    """
    a = {"SLC": "M", "MLC": "L", "TLC": "B", "QLC": "N"}.get(cell_level, "x")
    # 3D 制程: G=3D1→0, H=3D2→1, J=3D3→2, K=3D4→3, L=3D5→4
    _3d_map = {"G": "0", "H": "1", "J": "2", "K": "3", "L": "4"}
    b = _3d_map.get(pc) or {"D": "6", "E": "7", "F": "8"}.get(pc, "x")

    die_size_gb = (density_mb // 8 // die) / 1024  # Mb → MB → GB per die
    # 按 die_size 值查 C 码
    c_map: dict[int, str] = {
        2: "2", 4: "3", 8: "4", 16: "5",
        32: "6", 48: "K", 64: "7", 128: "8",
        204: "P",
    }
    c = c_map.get(int(die_size_gb), "x")
    return f"({a}{b}{c})"


def _decode_29f(pn: str) -> dict | None:
    """解码 29F 开头的 Intel NAND 料号。

    格式: 29F{density}{width}{classification}{voltage}{cell}{process}{gen}
    例: 29F64G08ACDB → 64Gb, x8, CE=1, 3.3V, MLC, 72nm
    """
    rest = pn
    # 跳过后缀（如 -xxx 版本号）
    if "-" in rest:
        rest = rest.split("-")[0]

    # 跳过 29F
    if rest.startswith("29F"):
        rest = rest[3:]
    elif rest.startswith("29"):
        rest = rest[2:]
    elif rest.startswith("I29F"):
        rest = rest[4:]
    else:
        return None

    if not rest:
        return None

    # 密度: 固定 3 位，xxG=Gb, xxB=GB(×8→Gb), xxT=Tb
    d3 = rest[:3]
    rest = rest[3:]
    d_num_str = d3[:2]
    d_unit = d3[2]

    if not d_num_str.isdigit():
        return None
    d_num = int(d_num_str)

    if d_unit == "B":  # GB → Gb
        density_val = d_num * 8 * 1024  # MB
    elif d_unit == "G":  # Gb
        density_val = d_num * 1024  # MB
    elif d_unit == "T":  # Tb
        density_val = d_num * 1024 * 1024  # MB
    else:
        return None

    # 位宽: 2 位
    wc = rest[:2]
    rest = rest[2:]
    width = _INTEL_WIDTH.get(wc, 8)
    ch = _INTEL_CH.get(wc, 1)

    # 分类代码: 1 位 → die / ce
    cc = rest[:1]
    rest = rest[1:]

    # 电压: 1 位
    vc = rest[:1]
    rest = rest[1:]
    voltage = _INTEL_VOLTAGE.get(vc, vc)

    # 单元类型: 1 位
    cell_code = rest[:1]
    rest = rest[1:]
    cell_map = {"N": "SLC", "M": "MLC", "T": "TLC", "Q": "QLC"}
    cell_level = cell_map.get(cell_code, "Unknown")

    # 分类 → die/ce（制程后缀需要 die 算 die_size）
    die = _INTEL_DIE.get(cc, 1)
    ce = _INTEL_CE.get(cc, 1)

    # 制程: 1 位
    pc = rest[:1]
    rest = rest[1:]
    process = _INTEL_PROCESS.get(pc, "Unknown")
    process += _intel_process_suffix(cell_level, pc, density_val, die)

    # 代数: 1 位（可选）
    gen = rest[:1] if rest else None

    density_str = format_density(density_val)

    return {
        "partNumber": pn.split("-")[0],
        "vendor": "英特尔",
        "type": "NAND",
        "density": density_str,
        "deviceWidth": f"x{width}",
        "cellLevel": cell_level,
        "voltage": voltage,
        "processNode": process,
        "generation": gen,
        "package": "BGA",
        "classification": {
            "die": die,
            "ce": ce,
            "ch": ch,
        },
    }


# ── 注册解码器 ───────────────────────────────────────────────────────


@register
class IntelDecoder(BaseDecoder):
    """英特尔 NAND 解码器。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        if not pn:
            return False
        return pn.startswith(("29F", "29", "I29", "PF29", "BK29", "JS29", "CU29"))

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn:
            return None

        # PF/BK/JS/CU + 29F → 统一去掉封装前缀再解码
        for prefix in ("PF29", "BK29", "JS29", "CU29"):
            if pn.startswith(prefix):
                pkg = _INTEL_PACKAGE.get(prefix[:2], "BGA")
                result = _decode_29f(pn[2:])  # 去掉 PF/BK/JS/CU，保留 29F
                if result:
                    result["package"] = pkg
                    result["partNumber"] = pn.split("-")[0]
                return result

        # 29F / 29 / I29 开头 → NAND 解码
        if pn.startswith(("29F", "29", "I29")):
            return _decode_29f(pn)

        return None

    # ── Flash ID 解码 ─────────────────────────────────────────────

    def check_id(self, id_str: str) -> bool:
        return id_str.strip().upper().startswith("89")

    def decode_id(self, id_str: str) -> dict | None:
        # Intel (89) ID 与 Micron (2C) 共用 ONFI 逻辑
        # micron.py 的 _decode_micron_id 也处理了 89
        from .micron import _decode_micron_id
        id_str = id_str.strip().upper()
        if not id_str.startswith("89"):
            return None
        return _decode_micron_id(id_str, "英特尔")
