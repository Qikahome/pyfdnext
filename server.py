"""pyfdnext HTTP API Server

Usage:
    python -m pyfdnext.server          # default :8000
    python -m pyfdnext.server --port 8080
"""

import os
import sys
from argparse import ArgumentParser

import uvicorn
from fastapi import FastAPI, Query

# ensure the backend dir is on sys.path for `from pyfdnext import ...`
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from pyfdnext import (
    decode_and_merge_pn,
    decode_and_merge_id,
    search_part_number,
    get_manager,
)

app = FastAPI(title="pyfdnext API", version="1.0.0")

_manager = get_manager()


@app.get("/decode")
def decode_pn(
    pn: str = Query(..., description="Part number"),
    lang: str = Query("eng", description="Language (eng/chs)"),
):
    """解码料号。"""
    result = decode_and_merge_pn(pn, _manager, lang=lang)
    if result is None:
        return {"error": "not found", "pn": pn}
    return result


@app.get("/decodeId")
def decode_id(
    id: str = Query(..., description="Flash ID hex string"),
    lang: str = Query("eng", description="Language (eng/chs)"),
):
    """解码 Flash ID。"""
    result = decode_and_merge_id(id, _manager, lang=lang)
    if result is None:
        return {"error": "not found", "id": id}
    return result


@app.get("/searchPn")
def search_pn(
    q: str = Query(..., description="Search query"),
    lang: str = Query("eng", description="Language (eng/chs)"),
    limit: int = Query(10, description="Max results"),
):
    """搜索料号。"""
    results = search_part_number(q, _manager, limit=limit, lang=lang)
    return results


def main():
    parser = ArgumentParser(description="pyfdnext HTTP API Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("pyfdnext.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
