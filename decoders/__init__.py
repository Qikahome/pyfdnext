"""解码器注册与管理。

提供 BaseDecoder 基类 + DecoderManager，所有厂商解码器
继承并通过 @register 注册后，由 DecoderManager 统一调度。
"""

from typing import Any


# ── 通用工具 ─────────────────────────────────────────────────────────

def decode_die_cell_level(byte5: int | str) -> tuple[str, str]:
    """从 Flash ID 第5字节解码 Die 数量和 Cell Level。"""
    val = int(byte5, 16) if isinstance(byte5, str) else byte5
    die = ["1", "2", "4", "8"][val % 4]
    cell = ["SLC", "MLC", "TLC", "QLC"][val // 4]
    return die, cell


# Toggle 阵营公用容量映射 (Kioxia/Sandisk)
DENSITY_TOGGLE: dict[str, str] = {
    "D3": "1GB",    "D5": "2GB",    "D7": "4GB",    "DE": "8GB",
    "3A": "16GB",   "5A": "16GB",
    "3C": "32GB",   "4C": "32GB",   "5C": "32GB",
    "3E": "64GB",   "5E": "64GB",   "7E": "64GB",
    "48": "128GB",  "89": "128GB",
    "58": "80GB",
    "73": "170.625GB",  "77": "341.25GB",
    "49": "256GB",
    "40": "512GB",
    "41": "1TB",
}


class BaseDecoder:
    """解码器基类。

    子类至少实现一个匹配+解码方法。
    """

    id: str = ""

    # ── 料号解码 ──

    def check_pn(self, part_number: str) -> bool:
        return False

    def decode_pn(self, part_number: str) -> dict[str, Any] | None:
        return None

    # ── Flash ID 解码 ──

    def check_id(self, id_str: str) -> bool:
        return False

    def decode_id(self, id_str: str) -> dict[str, Any] | None:
        return None


class DecoderManager:
    """解码器管理器。"""

    def __init__(self):
        self._decoders: list[BaseDecoder] = []

    # ── 注册 ─────────────────────────────────────────────────

    def register(self, decoder: BaseDecoder):
        self._decoders.append(decoder)

    # ── 料号解码 ─────────────────────────────────────────────

    def decode_pn(self, pn: str) -> dict[str, Any] | None:
        for d in self._decoders:
            if d.check_pn(pn):
                result = d.decode_pn(pn)
                if result:
                    return result
        return None

    # ── ID 解码 ───────────────────────────────────────────────

    def decode_id(self, id_str: str) -> dict[str, Any] | None:
        for d in self._decoders:
            if d.check_id(id_str):
                result = d.decode_id(id_str)
                if result:
                    return result
        return None

    # ── 状态 ───────────────────────────────────────────────────

    @property
    def decoder_count(self) -> int:
        return len(self._decoders)


# 全局单例
_manager = DecoderManager()


def get_manager() -> DecoderManager:
    return _manager


def register(decoder_cls: type[BaseDecoder]) -> type[BaseDecoder]:
    """装饰器：注册解码器类到全局管理器，自动以模块名作为 id。"""
    decoder = decoder_cls()
    decoder.id = decoder_cls.__module__.rsplit(".", 1)[-1]
    _manager.register(decoder)
    return decoder_cls


# 导入各厂商解码器（从 decoders.json 读取清单）
import os
import json
import importlib

_decoders_list_path = os.path.join(os.path.dirname(__file__), "decoders.json")
if os.path.exists(_decoders_list_path):
    with open(_decoders_list_path, "r", encoding="utf-8") as _f:
        _decoder_modules: list[str] = json.load(_f)
    for _mod in _decoder_modules:
        importlib.import_module(f".{_mod}", __package__)
