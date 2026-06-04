"""i18n 翻译模块。

解码器输出英文，通过 translate_output() 转换为目标语言。
"""

import json
import os
from typing import Any

_LANG_DIR = os.path.join(os.path.dirname(__file__), "resources", "lang")

_cache: dict[str, dict[str, str]] = {}


def _load_lang(lang: str = "chs") -> dict[str, str]:
    """加载语言包（带缓存）。"""
    if lang not in _cache:
        path = os.path.join(_LANG_DIR, f"{lang}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _cache[lang] = json.load(f)
        else:
            _cache[lang] = {}
    return _cache[lang]


def translate_output(data: dict[str, Any] | None, lang: str | None = None) -> dict[str, Any] | None:
    """翻译解码结果中的可翻译字段。

    如果 lang 为空或 "eng"，不翻译直接返回。
    否则递归翻译所有字符串值（匹配语言包 key 的替换为对应翻译）。
    """
    if not data or not lang or lang == "eng":
        return data

    lang_pack = _load_lang(lang)
    if not lang_pack:
        return data

    return _translate_dict(data, lang_pack)


def _translate_dict(d: Any, lang_pack: dict[str, str]) -> Any:
    """递归翻译字典/列表中的字符串值。"""
    if isinstance(d, dict):
        return {k: _translate_dict(v, lang_pack) for k, v in d.items()}
    if isinstance(d, list):
        return [_translate_dict(item, lang_pack) for item in d]
    if isinstance(d, str):
        return lang_pack.get(d, lang_pack.get(d.lower(), d))
    return d
