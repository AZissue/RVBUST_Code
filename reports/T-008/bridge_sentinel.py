#!/usr/bin/env python3
"""T-008 判据 3：桥接层真的用了一个**独立的**返回码表示"SDK 内部异常"。

判据 2（tests/test_calibration_service.cpp 里的
`sdkInternalErrorIsDistinctFromBadParameters`）钉住了"映射文案"，这一条钉住
"桥接层确实把那个码用起来了" —— 两者一起才说明用户不会再看到「参数无效」。

做法：在 src/sdk/HandEyeSDKBridge.cpp 里取 `handEyeCalibrationMarker` 与
`handEyeCalibrationTcpTouch` 的函数体（按花括号配平切），要求各自都出现
`kSdkInternalError`。名字是**契约**：判据 2 在编译期就会引用它，改名字两边一起断。

用法：python reports/T-008/bridge_sentinel.py     # exit 0 = PASS
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                      # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "sdk" / "HandEyeSDKBridge.cpp"
HEADER = REPO_ROOT / "src" / "sdk" / "HandEyeSDKBridge.h"
FUNCS = ("handEyeCalibrationMarker", "handEyeCalibrationTcpTouch")
SENTINEL = "kSdkInternalError"


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def function_body(text: str, name: str) -> str | None:
    """从 `name(` 的第一次出现起，按花括号配平切出函数体。"""
    start = text.find(name + "(")
    if start < 0:
        return None
    i = text.find("{", start)
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


def main() -> int:
    if not SRC.exists() or not HEADER.exists():
        emit({"result": "FAIL", "why": "bridge files missing"})
        return 1
    src = SRC.read_text(encoding="utf-8", errors="replace")
    header = HEADER.read_text(encoding="utf-8", errors="replace")
    ok = True

    declared = f"constexpr int {SENTINEL}" in header.replace("inline ", "")
    ok &= declared
    emit({"check": f"HandEyeSDKBridge.h 声明了 {SENTINEL}", "ok": declared})

    for name in FUNCS:
        body = function_body(src, name)
        if body is None:
            ok = False
            emit({"check": f"{name} 函数体", "ok": False, "why": "没找到函数体"})
            continue
        used = SENTINEL in body
        ok &= used
        emit({"check": f"{name} 在异常路径上返回 {SENTINEL}", "ok": used,
              "body_lines": body.count("\n") + 1})

    # 该码不能等于 SDK 自己的"参数无效"(-1)
    m = re.search(r"constexpr int\s+" + SENTINEL + r"\s*=\s*(-?\d+)", header)
    value = int(m.group(1)) if m else None
    distinct = value is not None and value not in (-1, 0)
    ok &= distinct
    emit({"check": f"{SENTINEL} 的值与 -1 / 0 都不同", "ok": distinct, "value": value})

    emit({"result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
