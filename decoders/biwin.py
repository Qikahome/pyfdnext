"""佰维 (Biwin) 解码器，将 Biwin 料号映射到原厂料号后委托解码。"""
from . import register, BaseDecoder, get_manager


# ── 前缀映射规则 ───────────────────────────────────────────────────

# 按最长匹配优先排序
_PN_RULES: list[tuple[str, str, str]] = [
    # (biwin_prefix, mapped_prefix, vendor_name)
    ("BW29F", "MT29F", "Micron"),
    ("BWN", "YMN", "YMTC"),
    ("BW9", "K9", "Samsung"),
]


@register
class BiwinDecoder(BaseDecoder):
    """佰维 NAND 解码器：映射到原厂料号后委托解码。"""

    def check_pn(self, pn: str) -> bool:
        pn = pn.strip().upper()
        if not pn:
            return False
        return any(pn.startswith(prefix) for prefix, _, _ in _PN_RULES)

    def decode_pn(self, pn: str) -> dict | None:
        pn = pn.strip().upper()
        if not pn:
            return None

        for prefix, mapped_prefix, vendor in _PN_RULES:
            if pn.startswith(prefix):
                mapped_pn = mapped_prefix + pn[len(prefix):]
                result = get_manager().decode_pn(mapped_pn)
                if result:
                    result["partNumber"] = pn
                    result["vendor"] = f"Biwin-{vendor}"
                    result["extraInfo"] = {"originalPartNumber": mapped_pn, "originalVendor": vendor}
                else:
                    result = {
                        "partNumber": pn,
                        "vendor": f"Biwin-{vendor}",
                        "type": "NAND",
                        "extraInfo": {
                            "originalPartNumber": mapped_pn,
                            "originalVendor": vendor,
                            "note": "原厂解码未命中",
                        },
                    }
                return result

        return None
