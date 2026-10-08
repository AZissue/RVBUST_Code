#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UR Realtime (30003) 位姿字段取证器 —— 验证代码里那个写死的偏移量 200。

为什么需要它：src/logic/URRealtimeReader.cpp 里写死了
    constexpr int kPoseOffset = 8 + 48 * 4;   // 200
    constexpr int kPoseBytes  = 48;           // 6 个大端 double
并且假定：包体 = 8 字节时间戳 + 若干 48 字节块，第 5 个块就是 actual_TCP_pose。
这套块顺序来自 UR 官方 realtime 接口，但**不同固件版本的块集合并不完全一致**，
代码里那句 "Empirically confirmed" 并没有留下任何证据文件。

判据只有一个：示教器上读到的 TCP 位置，能不能在包里对应的字节上找到。

本脚本**只连一次、只读一个包、不发任何指令**，不会影响机器人运行。

用法：
    1. 用示教器把机器人停在一个好认的位姿，例如
           X = 123.456   Y = 200.0   Z = 300.0
    2. python reports/tools/probe_ur_offset.py --host 192.168.0.100 \
              --expect 123.456,200,300        # 注意是 mm，脚本自己换算成米去找
    3. 把整段输出发回来。

    python reports/tools/probe_ur_offset.py --selftest    # 自检，不联网

输出里的三样东西是关键：
    · 「代码假设的块（偏移 200）」解出来的 6 个数，与示教器是否一致；
    · --expect 在哪些偏移找到了你的坐标（应当正好是 200）；
    · 附近几个块的对照，用来判断块顺序有没有整体错位。
"""
from __future__ import annotations

import argparse
import datetime
import os
import socket
import struct
import sys


class Tee:
    """同时写控制台和文件（理由同 probe_modbus_pose.py：现场控制台多为 GBK）。"""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, s: str) -> int:
        for st in self._streams:
            try:
                st.write(s)
            except UnicodeEncodeError:
                enc = getattr(st, "encoding", None) or "ascii"
                st.write(s.encode(enc, "replace").decode(enc, "replace"))
        return len(s)

    def flush(self) -> None:
        for st in self._streams:
            try:
                st.flush()
            except Exception:               # noqa: BLE001
                pass


def start_report(script_name: str, out_arg: str) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    default_dir = os.path.dirname(os.path.abspath(__file__))
    path = out_arg or os.path.join(default_dir,
                                   "{}.{}.txt".format(script_name, stamp))
    try:
        fh = open(path, "w", encoding="utf-8", newline="\n")
    except OSError as e:
        print("（报告文件写不了：{}，只输出到控制台）".format(e))
        return ""
    sys.stdout = Tee(sys.stdout, fh)
    return path

# UR realtime 包体的块布局（相对包体起点，即 4 字节长度前缀之后）。
# 每块 48 字节 = 6 个 big-endian double。这张表用于给人看的对照。
BLOCK_LABELS = {
    0:   "timestamp（秒）",
    8:   "q_actual（6 关节角，rad）",
    56:  "qd_actual（关节速度）",
    104: "qdd_actual（关节加速度）",
    152: "I_actual（关节电流）",
    200: "actual_TCP_pose  ← 代码取的就是这块",
    248: "actual_TCP_speed",
    296: "actual_TCP_force",
    344: "target_TCP_pose",
    392: "target_TCP_speed",
    440: "target_TCP_force",
    488: "TCP 力/力矩（另一组）",
}

ASSUMED_OFFSET = 8 + 48 * 4   # 200，与 URRealtimeReader.cpp 保持一致
BLOCK_BYTES = 48
SAFE_PACKET_MIN = 4 + ASSUMED_OFFSET + BLOCK_BYTES


def read_body(host: str, port: int, timeout: float) -> tuple[int, bytes]:
    """连一次，读一个 realtime 包。返回 (msgLen, body)。"""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        head = _recv_exact(s, 4)
        if head is None:
            raise TimeoutError("等待长度前缀超时（端口开放但没数据？确认是 30003 实时口）")
        (msg_len,) = struct.unpack(">I", head)
        if not 4 <= msg_len <= 8192:
            raise RuntimeError("包长度异常：{}（代码认为合法范围是 4..8192）".format(msg_len))
        body = _recv_exact(s, msg_len - 4)
        if body is None:
            raise TimeoutError("包体没收完")
        return msg_len, body


def _recv_exact(s: socket.socket, n: int):
    buf = b""
    while len(buf) < n:
        try:
            part = s.recv(n - len(buf))
        except socket.timeout:
            return None
        if not part:
            break
        buf += part
    return buf if len(buf) == n else None


def block_at(body: bytes, offset: int) -> list[float] | None:
    if offset < 0 or offset + BLOCK_BYTES > len(body):
        return None
    return list(struct.unpack_from(">6d", body, offset))


def find_pose(body: bytes, expect_mm: list[float], tol_mm: float) -> list[tuple[int, float]]:
    """在 8 字节对齐的偏移里找「连续三个值 == 示教器坐标」。

    返回 [(offset, 用的比例)]，比例 1.0 表示包里直接是 mm，0.001 表示是米。
    只认三连中，单个值巧合命中的概率太高，不足为凭。
    """
    hits: list[tuple[int, float]] = []
    for scale in (0.001, 1.0):          # 0.001 = UR 的米；1.0 = 万一已换算成 mm
        want = [v * scale for v in expect_mm]
        tol = tol_mm * scale
        for off in range(0, len(body) - 24 + 1, 8):
            got = struct.unpack_from(">3d", body, off)
            if all(abs(got[i] - want[i]) <= tol for i in range(3)):
                hits.append((off, scale))
    return hits


def scan(body: bytes, limit: int) -> None:
    print()
    print("  ── 包头若按 UR 官方块顺序，前若干块长这样（用于判断整体错位）──")
    for off in sorted(BLOCK_LABELS):
        if off > limit:
            break
        vals = block_at(body, off)
        if vals is None:
            break
        shown = " ".join("{:>11.4f}".format(v) for v in vals)
        print("     [{:>3}] {:<28} {}".format(off, BLOCK_LABELS[off], shown))


def selftest() -> int:
    print("自检：造一个包，验解码与查找")
    ok = True

    body = bytearray(ASSUMED_OFFSET + BLOCK_BYTES)
    struct.pack_into(">d", body, 0, 12345.678)                       # 时间戳
    struct.pack_into(">6d", body, 200, 0.123456, 0.200, 0.300,       # 米
                     0.1, 0.2, 0.3)
    body = bytes(body)

    vals = block_at(body, 200)
    print("  偏移 200 解出：{}".format(["%.6f" % v for v in vals]))
    ok &= abs(vals[0] - 0.123456) < 1e-9

    hits = find_pose(body, [123.456, 200.0, 300.0], 0.01)
    print("  用示教器坐标 123.456/200/300(mm) 查找 -> {}".format(hits))
    ok &= (len(hits) == 1 and hits[0] == (200, 0.001))

    # 不该在别的偏移误报
    hits = find_pose(body, [1.0, 2.0, 3.0], 0.01)
    print("  用一个包里没有的坐标查找 -> {}（期望空）".format(hits))
    ok &= (hits == [])

    print("自检：{}".format("通过" if ok else "失败"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="UR Realtime 位姿字段取证器（只读一个包）")
    ap.add_argument("--host", default="192.168.0.100")
    ap.add_argument("--port", type=int, default=30003)
    ap.add_argument("--expect", default="",
                    help="示教器上的 TCP 位置，mm，逗号分隔：x,y,z")
    ap.add_argument("--tol", type=float, default=0.05, help="匹配容差 mm（默认 0.05）")
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--out", default="", help="报告文件路径（默认落在本脚本同目录）")
    ap.add_argument("--selftest", action="store_true", help="只跑自检，不联网")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    report = start_report("probe_ur_offset", args.out)

    expect: list[float] = []
    if args.expect:
        try:
            expect = [float(x) for x in args.expect.replace("，", ",").split(",")]
        except ValueError:
            print("--expect 解析失败，要形如 123.456,200,300")
            return 1
        if len(expect) != 3:
            print("--expect 要正好 3 个数（x,y,z）")
            return 1

    print("UR Realtime 位姿字段取证")
    print("  目标 {}:{}".format(args.host, args.port))
    if expect:
        print("  示教器坐标 {},{},{} mm".format(*expect))
    print()

    try:
        msg_len, body = read_body(args.host, args.port, args.timeout)
    except Exception as e:  # noqa: BLE001
        print("读取失败：{}".format(e))
        print()
        print("请确认：机器人已开机、本机与机器人同网段、30003 端口可达、"
              "示教器上没有禁用 realtime 接口。这条失败信息也请发回。")
        if report:
            print()
            print("本段输出已存到：{}".format(report))
        return 2

    print("包长度 {} 字节（包体 {} 字节）".format(msg_len, len(body)))
    print("代码需要的字节数 {}，实际 {} -> {}".format(
        SAFE_PACKET_MIN, len(body),
        "够" if len(body) >= SAFE_PACKET_MIN else "不够，会直接报「数据包过短」"))

    vals = block_at(body, ASSUMED_OFFSET)
    print()
    print("  ── 代码假设的块（偏移 {}）解出来是 ──".format(ASSUMED_OFFSET))
    if vals is None:
        print("     （包太短，取不到 —— 这本身就是一个发现）")
    else:
        print("     xyz(m) = {:.6f} {:.6f} {:.6f}".format(*vals[:3]))
        print("     转 mm  = {:.4f} {:.4f} {:.4f}".format(*[v * 1000 for v in vals[:3]]))
        print("     姿态轴角(rad) = {:.6f} {:.6f} {:.6f}".format(*vals[3:]))

    if expect:
        print()
        print("  ── 在包里找示教器坐标（8 字节对齐、要求 x/y/z 三连同时命中）──")
        hits = find_pose(body, expect, args.tol)
        if not hits:
            print("     没找到。可能原因：包是关节混合/位姿已变；或该固件不叫这块；")
            print("     或实际位置与示教器读数差得比容差大（试试 --tol 1）。")
        for off, scale in hits:
            unit = "米（UR 的原始单位）" if scale != 1.0 else "毫米"
            label = BLOCK_LABELS.get(off, "（不在已知块表里）")
            print("     偏移 {:<4} 单位 {:<20} {}".format(off, unit, label))
            if off == ASSUMED_OFFSET:
                print("       -> 与代码写死的偏移一致，这条假设成立")
            else:
                print("       -> 与代码写死的 {} **不一致**，需要改 kPoseOffset".format(
                    ASSUMED_OFFSET))

    scan(body, limit=488)

    print()
    print("判读：")
    print("  · 偏移 200 的 xyz 与示教器一致             -> 换算与偏移都对")
    print("  · 找到一个块但偏移不是 200                 -> 固件块布局不同，改 kPoseOffset")
    print("  · 找到的块在 344（target_TCP_pose）        -> 读的是「目标」而非「实际」，需要改选块")
    print("  · 一个块都找不到                           -> 请附上示教器截图与包长，再判断")
    print("  · 长度够但姿态三个数是 0 或极大             -> 姿态可能不是轴角，另说")
    if report:
        print()
        print("本段输出已存到：{}".format(report))
        print("把这个 txt 文件发回来即可（控制台里的中文可能因代码页显示为乱码，文件不会）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
