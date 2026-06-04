"""Spectek 解码器。

Mark Code（如 PE812）→ 查官网 API → 委托对应解码器。
FN/FB/FT/FX/CB 料号 → 直接按 datasheet 格式解码。

格式: {prefix}{skip}{process}{density}{grade}{config}{voltage}{class}{pfpt}{iface}{pkg}[-]{speed}{prodgrade}
例: FB  M  B58R  1T0  K  L  B  A  H  J4
   FB  M  B2*B  512G6 K  L  B  A  E  J4  -25 AS
"""
from . import register, BaseDecoder, get_manager
from ..utils import resolve_spectek_mark
from .micron import _take_longest_density

# ── 前缀 ─────────────────────────────────────────────────────────

_SPECTEK_PREFIXES = ("FN", "FB", "FT", "FX", "CB")

# ── Cell 技术 ────────────────────────────────────────────────────

_SPECTEK_CELL: dict[str, str] = {
    "M": "SLC",
    "L": "MLC",
    "B": "TLC",
    "N": "QLC",
}

# ── 密度表（复用 Micron 的贪心匹配） ────────────────────────────────

# _take_longest_density 从 micron.py 导入
# 特殊: 1T2=1.125Tb, 1HT=1.5Tb
# 常规: {n}G → {n}Gb, {n}T → {n}Tb

# ── 旧版功能密度值表（单字符） ──────────────────────────────────

# 制程首字在 [6/7/8/9] 时使用此表
_SPECTEK_OLD_DENSITY: dict[str, str] = {
    "0": "1Gib", "1": "2Gib", "2": "4Gib", "3": "8Gib",
    "4": "16Gib", "5": "32Gib", "6": "64Gib", "7": "128Gib",
    "8": "256Gib", "9": "512Gib", "A": "1024Gib", "B": "2048Gib",
    "N": "Unknown",
}

# ── 密度等级（紧跟在密度码后 1 位） ──────────────────────────────

_SPECTEK_DENSITY_GRADE: dict[str, str] = {
    "1": "94-100%", "9": "90-100%",
    "6": "50-90%", "5": "40-60%",
    "0": "BL or S* grade", "A": "see HP, BL, or S* grade",
}

# ── 位宽配置 ────────────────────────────────────────────────────

_SPECTEK_CONFIG: dict[str, str] = {
    "G": "x8 (ECC)", "K": "x8",
    "M": "x8 (half page)", "L": "x16",
    "P": "x16 (ECC)", "H": "x1", "J": "x4",
    "N": "Unknown",
}

# ── 电压 ─────────────────────────────────────────────────────────

_SPECTEK_VOLTAGE: dict[str, str] = {
    "1": "Vcc: 1.8V, VccQ: 1.8V",
    "3": "Vcc: 3.3V, VccQ: 3.3V",
    "D": "Vcc: 3.3V, VccQ: 1.8V",
    "E": "Vcc: 3.3V, VccQ: 1.8V/3.3V",
    "F": "Vcc: 3.3V, VccQ: 1.2V",
    "J": "Vcc: 3.3V, VccQ: 1.8V/3.3V",
    "L": "Vcc: 2.5V, VccQ: 1.2V",
    "S": "Vcc: 3.3V, VccQ: 3.3V",
    "T": "Vcc: 3.3V, VccQ: 1.8V/1.2V",
}

# ── 封装配置类型 → (die, ce, ch) ──────────────────────────────

_SPECTEK_CLASS: dict[str, tuple[int, int, int]] = {
    "A": (1, 0, 1), "B": (1, 1, 1), "C": (3, 3, 2),
    "D": (2, 1, 1), "E": (2, 2, 2), "F": (2, 2, 1),
    "G": (3, 3, 3), "H": (4, 1, 1), "J": (4, 2, 1),
    "K": (4, 2, 2), "L": (4, 4, 4), "M": (4, 4, 2),
    "N": (6, 6, 3), "P": (8, 8, 2), "Q": (8, 4, 4),
    "R": (8, 2, 2), "S": (16, 4, 4), "T": (16, 8, 2),
    "U": (8, 4, 2), "V": (16, 8, 4), "W": (16, 4, 2),
    "X": (4, 4, 2), "Y": (11, 7, 4),
    "1": (16, 2, 1), "2": (64, 8, 2), "3": (8, 4, 2), "4": (4, 4, 1),
}

# ── PFP Type ────────────────────────────────────────────────────

_SPECTEK_PFP: dict[str, str] = {
    "A": "All CE(s) valid",
    "B": "CE1 valid, CE2 not guaranteed",
    "C": "CE2 valid, CE1 not guaranteed",
    "D": "SLC on the fly",
}

# ── 接口 ─────────────────────────────────────────────────────────

_SPECTEK_INTERFACE: dict[str, str] = {
    "A": "Async", "B": "Async/Sync", "C": "Sync",
    "D": "SPI", "E": "NV-DDR3", "F": "Async/NV-DDR2/NV-DDR3",
    "G": "Enterprise Sync", "M": "SIM Flash", "N": "Async/NV-DDR2",
}

# ── 旧版封装类型表（第 1 位） ──────────────────────────────────

_SPECTEK_OLD_PKG_TYPE: dict[str, str] = {
    "B": "BGA-100/170", "C": "ULGA-52", "D": "VFBGA-63/120",
    "G": "VLGA-52", "H": "VBGA-63/120", "J": "SOP/LLGA-48/52",
    "L": "LLGA-52", "P": "TSOP-48 OCPL", "T": "TSOP-48",
    "V": "VLGA-52 (14x18)", "W": "TSOP-48 CPL",
}

# ── 旧版封装功能 → (die, ce) ──────────────────────────────────

_SPECTEK_OLD_PKG_CLASS: dict[str, tuple[int, int]] = {
    "G": (1, 1),
    "1": (2, 1), "2": (2, 2), "3": (2, 1),
    "4": (4, 2), "5": (4, 1), "6": (4, 1),
    "7": (8, 1), "8": (8, 3), "9": (8, 2),
}

# ── 旧版封装功能表（第 2 位） ──────────────────────────────────

_SPECTEK_OLD_PKG_FUNC: dict[str, str] = {
    "G": "Single Die, CE only",
    "1": "Dual Die, CE1 only",
    "2": "Dual Die, CE1+CE2",
    "3": "Dual Die, CE3 only",
    "4": "Quad Die, CE1+CE2",
    "5": "Quad Die, CE1 only",
    "6": "Quad Die, CE2 only",
    "7": "Octal Die, CE3",
    "8": "Octal Die, CE2/CE3/CE4",
    "9": "Octal Die, CE2/CE4",
}

_SPECTEK_PACKAGE: dict[str, str] = {
    "WP": "TSOP-48 CPL", "WC": "TSOP-48 OCPL",
    "C3": "ULGA-52", "C4": "VLGA-52", "C5": "VLGA-52 (14x18)",
    "C6": "LLGA-52", "C7": "LLGA-48", "C8": "WLGA-52",
    "D1": "VLGA-52 (11x14)", "D4": "VFBGA-154/195",
    "D5": "LFBGA-154/195", "D6": "LFBGA-154/195",
    "G1": "VBGA-272/352", "G2": "TBGA-272/352",
    "G4": "LFBGA-252/308", "G5": "LFBGA-272/352",
    "G6": "LBGA-272/352", "G7": "LFBGA-252/308",
    "G8": "LFBGA-252/308", "G9": "LFBGA-252/308",
    "H1": "VBGA-100/170", "H2": "TBGA-100/170",
    "H3": "LBGA-100/170", "H4": "VFBGA-63/120",
    "H5": "VFBGA-56/256", "H6": "VBGA-152/221",
    "H7": "TBGA-152/221", "H8": "LBGA-152/221",
    "HC": "VFBGA-63/120", "J1": "VBGA-132/187",
    "J2": "TBGA-132/187", "J3": "LBGA-132/187",
    "J4": "VBGA-132/187", "J5": "LBGA-132/187",
    "J6": "TBGA-132/187", "J7": "LBGA-152/221",
    "K3": "VLGA-100/170", "K4": "TLGA-100/170",
    "K6": "LBGA-152/221", "K7": "VLGA-152/221",
    "K8": "TLGA-152/221", "K9": "VLGA-132/187",
    "M4": "TBGA-132/187", "M5": "LBGA-132/187",
    "M8Z": "VFBGA-55", "MD": "VFBGA-130",
}

_PACKAGE_KEYS = sorted(_SPECTEK_PACKAGE.keys(), key=len, reverse=True)

# ── 速度等级 ─────────────────────────────────────────────────────

_SPECTEK_SPEED: dict[str, str] = {
    "15": "133MT/s", "12": "166MT/s", "10": "200MT/s",
    "75": "266MT/s", "6": "333MT/s", "37": "533MT/s",
    "3": "666MT/s", "25": "800MT/s", "18": "1066MT/s",
    "16": "1200MT/s",
}

# ── 产品等级 ────────────────────────────────────────────────────

_SPECTEK_GRADE: dict[str, str] = {
    "AS": "Full Spec SSD", "AL": "Full Spec USB/SD",
    "AF": "Full Spec Low-end", "AR": "Relaxed Spec",
    "ES": "Engineering Sample", "MB": "Mixed Bins (35%)",
    "PG": "Partial Good (50%)", "UT": "Untested (80%)",
    "S7": "Est. 75%", "S9": "Est. 90%",
}


def _decode_spectek_pn(pn: str) -> dict | None:
    """解码 FN/FB/FT/FX/CB 格式料号。"""
    prefix = next(p for p in _SPECTEK_PREFIXES if pn.startswith(p))
    rest = pn[len(prefix):]

    data: dict = {
        "partNumber": pn,
        "vendor": "Spectek",
        "type": "NAND",
    }

    pos = 0

    # 1. 跳过 1 位 (internal marker code)
    pos += 1

    # 2. 制程: 扫描找到密度码起始位置
    density_match = None
    density_key = ""
    density_val = "Unknown"
    is_old_format = False
    for try_pos in range(pos, len(rest)):
        # 先试新格式（贪心匹配 {n}G/{n}T，至少 2 位）
        key, val, _ = _take_longest_density(rest[try_pos:])
        if len(key) >= 2:
            density_match = try_pos
            density_key = key
            density_val = val
            break

    if density_match is None:
        # 新格式没命中 → 旧格式：扫描最后一组 (密度值char + 等级char)
        for try_pos in range(pos, len(rest) - 1):
            dc = rest[try_pos]
            gc = rest[try_pos + 1]
            if dc in _SPECTEK_OLD_DENSITY and gc in _SPECTEK_DENSITY_GRADE:
                density_match = try_pos
                density_key = dc
                density_val = _SPECTEK_OLD_DENSITY[dc]
                is_old_format = True

    if density_match is not None:
        process_raw = rest[pos:density_match]
        data["processNode"] = process_raw
        if process_raw:
            data["cellLevel"] = _SPECTEK_CELL.get(process_raw[0], "Unknown")
        pos = density_match
    else:
        data["density"] = "Unknown"
        return data

    # 3. 密度码
    if is_old_format:
        # 旧格式：1 位密度值
        pos += 1
        data["density"] = density_val
        # 旧格式：紧接 1 位密度等级
        if pos < len(rest):
            grd = rest[pos]
            if grd in _SPECTEK_DENSITY_GRADE:
                extra = data.setdefault("extraInfo", {})
                extra["densityGrade"] = _SPECTEK_DENSITY_GRADE[grd]
            pos += 1
    else:
        # 新格式：贪心匹配的密度码 + 可选等级
        pos2 = pos + len(density_key)
        data["density"] = density_val
        if pos2 < len(rest) and rest[pos2].isdigit():
            grd = rest[pos2]
            pos2 += 1
            if grd in _SPECTEK_DENSITY_GRADE:
                extra = data.setdefault("extraInfo", {})
                extra["densityGrade"] = _SPECTEK_DENSITY_GRADE[grd]
        pos = pos2

    # 5. 位宽配置 (1 位)
    if pos < len(rest):
        data["deviceWidth"] = _SPECTEK_CONFIG.get(rest[pos], "Unknown")
        pos += 1

    # 6. 电压 (1 位)
    if pos < len(rest):
        data["voltage"] = _SPECTEK_VOLTAGE.get(rest[pos], "Unknown")
        pos += 1

    if is_old_format:
        # 旧格式：无 classification/pfp/interface，直接 2 位封装
        if pos + 1 < len(rest):
            pkg_type = rest[pos]
            pkg_func = rest[pos + 1]
            data["package"] = _SPECTEK_OLD_PKG_TYPE.get(pkg_type, pkg_type)
            cls = _SPECTEK_OLD_PKG_CLASS.get(pkg_func)
            if cls:
                data["classification"] = {"die": cls[0], "ce": cls[1]}
            extra = data.setdefault("extraInfo", {})
            extra["pkgFunc"] = _SPECTEK_OLD_PKG_FUNC.get(pkg_func, pkg_func)
    else:
        # 新格式：有 classification/pfp/interface/封装码
        # 7. 封装配置类型 (1 位) → die/ce/ch
        if pos < len(rest):
            cls = _SPECTEK_CLASS.get(rest[pos])
            if cls:
                data["classification"] = {"die": cls[0], "ce": cls[1], "ch": cls[2]}
            pos += 1

        # 8. PFP Type (1 位)
        if pos < len(rest):
            pfp = rest[pos]
            if pfp in _SPECTEK_PFP:
                extra = data.setdefault("extraInfo", {})
                extra["pfpType"] = _SPECTEK_PFP[pfp]
            pos += 1

        # 9. 接口 (1 位)
        if pos < len(rest):
            if rest[pos] in _SPECTEK_INTERFACE:
                data["interface"] = _SPECTEK_INTERFACE[rest[pos]]
            pos += 1

        # 10. 封装码（贪心最长匹配）
        if pos < len(rest):
            for key in _PACKAGE_KEYS:
                if rest[pos:].startswith(key):
                    data["package"] = _SPECTEK_PACKAGE[key]
                    pos += len(key)
                    break
            else:
                data["package"] = rest[pos:pos + 2] if pos + 1 < len(rest) else rest[pos:]
                pos += 2

    # 11. 可选 "-{speed}{prodgrade}"
    if pos < len(rest) and rest[pos] == "-":
        pos += 1
        spd = rest[pos:pos + 2] if pos + 1 < len(rest) else ""
        pos += 2
        if spd in _SPECTEK_SPEED:
            data["speed"] = _SPECTEK_SPEED[spd]
        grd = rest[pos:pos + 2] if pos + 1 < len(rest) else ""
        if grd in _SPECTEK_GRADE:
            extra = data.setdefault("extraInfo", {})
            extra["grade"] = _SPECTEK_GRADE[grd]

    return data


# ── 注册解码器 ───────────────────────────────────────────────────────


@register
class SpectekDecoder(BaseDecoder):
    """Spectek NAND Flash 解码器。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        if not pn:
            return False
        if any(pn.startswith(p) for p in _SPECTEK_PREFIXES):
            return True
        # Spectek Mark Code 全是 p 开头（精确 5 位或提取前 5 位）
        mark = pn[:5]
        if len(mark) == 5 and mark.isalnum() and mark[0] == "P":
            return True
        return False

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn:
            return None

        # 标准 Spectek NAND 料号
        if any(pn.startswith(p) for p in _SPECTEK_PREFIXES):
            return _decode_spectek_pn(pn)

        # Mark Code（取前 5 位字母数字）
        mark = pn[:5]
        if len(mark) == 5 and mark.isalnum() and mark[0] not in "NCDJ":
            resolved = resolve_spectek_mark(mark)
            if resolved:
                # 只有解析回 FB/FN/FT/FX/CB 前缀的才是 NAND，走 manager
                if resolved.startswith(_SPECTEK_PREFIXES):
                    result = get_manager().decode_pn(resolved)
                    if result:
                        result["vendor"] = "Spectek"
                        return result
                # DRAM（如 XAA 开头）→ 直接走 DramDecoder
                from .dram import DramDecoder
                result = DramDecoder().decode_pn(resolved)
                if result:
                    result["vendor"] = "Spectek"
                    return result
            return {"partNumber": pn, "vendor": "Spectek"}

        return None
