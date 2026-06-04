"""群联 (Phison) 料号解码器。"""
from . import register, BaseDecoder
from ..utils import total_density


@register
class PhisonDecoder(BaseDecoder):
    """群联 (Phison) 料号解码器。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.upper().replace("6", "C")
        return (
            len(pn) == 10
            and (pn[4] == "G" or pn[0] == "C")
            and pn[0] in "TSIHDCN"
        )

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if len(pn) != 10:
            return None

        pn = pn.replace("0", "O")
        if pn[0] == "6":
            pn = "C" + pn[1:]
        if pn[4] == "6":
            pn = pn[:4] + "G" + pn[5:]

        data: dict = {"partNumber": pn, "type": "NAND", "width": "x8"}

        # 厂商
        vendor_map = {
            "T": "Toshiba", "S": "Kioxia", "I": "Micron", "K": "Micron",
            "H": "SK hynix", "D": "SanDisk", "C": "YMTC", "N": "Intel",
        }
        data["vendor"] = f"Phison-{vendor_map.get(pn[0], 'Unknown')}"

        # 封装
        pkg_map = {
            "A": "BGA132", "P": "BGA152", "1": "BGA152", "C": "BGA272",
            "O": "SAT-LGA60", "K": "SAT-LGA60", "R": "SAT-LGA60",
            "U": "SAT-LGA60", "X": "SAT-LGA60",
            "F": "TSOP48", "T": "TSOP48", "G": "TSOP48", "2": "BGA154",
        }
        data["package"] = pkg_map.get(pn[1], "Unknown")

        # CE / Die
        ce_die_map = {
            "1": (1, 1), "2": (2, 2), "5": (2, 2), "6": (2, 4),
            "7": (4, 4), "8": (4, 8), "A": (4, 16), "B": (8, 8),
            "C": (8, 16), "K": (6, 6),
        }
        ce, die = ce_die_map.get(pn[2], (0, "Unknown"))
        data["classification"] = {"ce": ce, "die": die}
        data["die"] = str(die)

        # 密度
        density_map = {
            "7": "16GB", "8": "32GB", "9": "64GB", "A": "128GB",
            "B": "256GB", "E": "192GB", "H": "512GB", "I": "1024GB",
            "J": "2048GB",
        }
        density = density_map.get(pn[3], "Unknown")
        data["density"] = density

        # 单 Die 密度
        if density != "Unknown" and data["die"] != "Unknown":
            try:
                data["dieDensity"] = total_density(density, str(1.0 / int(data["die"])))
            except (ValueError, ZeroDivisionError):
                pass

        # 制程和单元类型
        def _get_process_node(pn: str) -> tuple:
            first = pn[0]
            eighth = pn[8]
            if first in "TSD":  # 闪迪/恺侠
                return {
                    "H": ("24nm 2p(D2H)", "MLC"), "P": ("1ynm 4p(DFK)", "MLC"),
                    "R": ("1znm(THL)", "TLC"), "S": ("1znm 2p(DDL)", "MLC"),
                    "U": ("1znm 4p(DFL)", "MLC"),
                    "V": ("BiCS2", "TLC"), "I": ("BiCS3", "TLC"),
                    "W": ("BiCS4", "TLC"), "X": ("BiCS4.5", "TLC"),
                    "Y": ("BiCS5", "TLC"), "1": ("BiCS6", "TLC"),
                }.get(eighth, ("Unknown", "Unknown"))
            elif first == "H":  # 海力士
                return {
                    "P": ("16nm", "MLC"), "O": ("3DV4", "TLC"),
                    "W": ("3DV6", "TLC"), "X": ("3DV7", "TLC"),
                }.get(eighth, ("Unknown", "Unknown"))
            elif first in "IKN":  # IM
                return {
                    "N": ("20nm(L85)", "MLC"), "P": ("16nm(L95)", "MLC"),
                    "O": ("L06/B16/N18", "Unknown"), "V": ("B27A", "TLC"),
                    "W": ("N28A", "QLC"), "I": ("B27B", "TLC"),
                    "X": ("B36/B37/N38", "TLC/QLC"), "Y": ("B47R", "TLC"),
                    "Z": ("N48R", "QLC"), "1": ("B58R", "TLC"),
                    "2": ("N58R", "QLC"),
                }.get(eighth, ("Unknown", "Unknown"))
            elif first == "C":  # 长江存储
                dd = data.get("dieDensity", "")
                ymc = {"32GB": "JGS(X1-9050)", "64GB": "TAS(X2-9060)"}.get(dd, "Unknown")
                return {"O": (ymc, "TLC")}.get(eighth, ("Unknown", "Unknown"))
            return ("Unknown", "Unknown")

        data["processNode"], data["cellLevel"] = _get_process_node(pn)
        return data
