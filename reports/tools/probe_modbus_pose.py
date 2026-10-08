#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modbus TCP 位姿寄存器转储器 —— 关掉「寄存器布局/字节序待真机确认」那一行。

为什么需要它：src/logic/RobotPose.cpp 目前**硬编码**了三条假设 ——
  1. 位姿从配置的「起始寄存器」开始、6 个值连续无间隔；
  2. Float32 占 2 个寄存器 / Int32 占 2 个 / Int16 占 1 个（12 或 6 个寄存器）；
  3. 字节序是**大端**（`QDataStream::BigEndian`），而且代码里**没有任何开关**能改。
判据是死的，机器人是活的：只有把真实寄存器读出来，才知道这三条哪一条不成立。

本脚本只发功能码 0x03（读保持寄存器），**只读不写**，不会碰机器人任何状态。

用法：
    python reports/tools/probe_modbus_pose.py --host 192.168.0.1 --port 502 --unit 1 --start 0
    # 机器人此时最好停在 x=100.000 y=200.000 z=300.000 A=10 B=20 C=30（mm/度）
    # 这样输出里的期望值那一列才有意义；停不到也别改，照实把原始值抄回来即可。

    python reports/tools/probe_modbus_pose.py --selftest     # 自检解码器本身，不联网

把整段输出原样发回来即可 —— 原始寄存器值在最后，那才是关键。
"""
from __future__ import annotations

import argparse
import datetime
import os
import socket
import struct
import sys


class Tee:
    """同时写控制台和文件。

    现场控制台多半是 GBK 代码页，直接 print 中文再贴回来会变成乱码，
    所以额外落一份 UTF-8 的 txt —— 那个文件才是要发回来的东西。
    """

    def __init__(self, *streams):
        self._streams = streams

    def write(self, s: str) -> int:
        for st in self._streams:
            try:
                st.write(s)
            except UnicodeEncodeError:      # 老控制台编不出的字符，替换而不是崩
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
    """把 stdout 接到 (控制台, UTF-8 文件)。返回文件路径；失败则只接控制台。"""
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

# ── 期望值：机器人停在 x=100 y=200 z=300 A=10 B=20 C=30 时，真·大端 Float32
#    应该读到的寄存器对。对不上不代表错，只说明假设不成立，看后面的判读表。
EXPECTED_F32 = {
    "x=100.000": (0x42C8, 0x0000),
    "y=200.000": (0x4348, 0x0000),
    "z=300.000": (0x4396, 0x0000),
    "A=10.000": (0x4120, 0x0000),
    "B=20.000": (0x41A0, 0x0000),
    "C=30.000": (0x41F0, 0x0000),
}


# ── 解码候选 ──────────────────────────────────────────────────────────
def _f32(hi: int, lo: int, order: str) -> float:
    """把两个寄存器按给定字节序解成 float32。order ∈ {ABCD, CDAB, DCBA}。"""
    raw = struct.pack(">HH", hi & 0xFFFF, lo & 0xFFFF)
    if order == "CDAB":          # 字序颠倒（两个 16 位字互换）
        raw = raw[2:] + raw[:2]
    elif order == "DCBA":        # 整 4 字节反序
        raw = raw[::-1]
    return struct.unpack(">f", raw)[0]


def _i32(hi: int, lo: int, order: str = "ABCD") -> int:
    raw = struct.pack(">HH", hi & 0xFFFF, lo & 0xFFFF)
    if order == "CDAB":
        raw = raw[2:] + raw[:2]
    elif order == "DCBA":
        raw = raw[::-1]
    return struct.unpack(">i", raw)[0]


def _i16(v: int) -> int:
    return struct.unpack(">h", struct.pack(">H", v & 0xFFFF))[0]


def decode_pairs(regs: list[int]) -> None:
    """按 Float32 / Int32×系数 逐对试解，把结果打成一张表。"""
    n = len(regs) // 2
    if n == 0:
        print("  （少于 2 个寄存器，无法成对解码）")
        return

    print("  ── 若按大端 Float32 解 ──")
    print("     位置/姿态   ABCD(代码假设)      CDAB(字序颠倒)     DCBA(整字节反序)")
    for i in range(n):
        hi, lo = regs[2 * i], regs[2 * i + 1]
        print("     [{:>2}]        {:>16.4f} {:>16.4f} {:>16.4f}"
              .format(i, _f32(hi, lo, "ABCD"), _f32(hi, lo, "CDAB"),
                      _f32(hi, lo, "DCBA")))

    print()
    print("  ── 若按大端 Int32 × 系数 解（raw 为有符号整数）──")
    print("     [i]           raw          ×0.001       ×0.01        ×0.1         ×0.0001")
    for i in range(n):
        hi, lo = regs[2 * i], regs[2 * i + 1]
        raw = _i32(hi, lo)
        print("     [{:>2}]  {:>12} {:>12.4f} {:>12.4f} {:>12.4f} {:>12.4f}"
              .format(i, raw, raw * 0.001, raw * 0.01, raw * 0.1, raw * 0.0001))


def decode_singles(regs: list[int]) -> None:
    """Int16×系数 是每 1 个寄存器一个值，单独一张表。"""
    print()
    print("  ── 若按大端 Int16 × 系数 解（每 1 个寄存器一个值）──")
    print("     [i]   raw(有符号)   ×0.1        ×0.01")
    for i, w in enumerate(regs):
        s = _i16(w)
        print("     [{:>2}] {:>12} {:>12.4f} {:>12.4f}".format(i, s, s * 0.1, s * 0.01))


def dump_raw(regs: list[int], start: int) -> None:
    print()
    print("  ── 原始寄存器（这一块最关键，请原样发回）──")
    for i in range(0, len(regs), 8):
        chunk = regs[i:i + 8]
        addr = start + i
        hexs = " ".join("{:04X}".format(w) for w in chunk)
        print("     [{}..{}]  {}".format(addr, addr + len(chunk) - 1, hexs))


# ── Modbus 读取 ───────────────────────────────────────────────────────
def read_holding(host: str, port: int, unit: int, start: int, count: int,
                 timeout: float) -> list[int]:
    """功能码 0x03 读保持寄存器。返回寄存器值列表（每个 0..65535）。"""
    if not 1 <= count <= 125:
        raise ValueError("一次最多读 125 个寄存器")

    req = struct.pack(">HHHBBHH", 0x0001, 0x0000, 0x0006, unit, 0x03, start, count)
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(req)

        head = _recv_exact(s, 6)                 # MBAP 前 6 字节
        if head is None:
            raise TimeoutError("等待响应超时（机器人没应答）")
        _tid, _pid, length, rsp_unit = struct.unpack(">HHHB", head)
        rest = _recv_exact(s, max(0, length - 1))
        if rest is None:
            raise TimeoutError("MBAP 之后的数据没收完")

    func = rest[0]
    if func == (0x03 | 0x80):
        code = rest[1] if len(rest) > 1 else -1
        raise RuntimeError("Modbus 异常码 {}（0x{:02X}）".format(code, code))
    if func != 0x03:
        raise RuntimeError("功能码异常：期望 0x03，收到 0x{:02X}".format(func))

    byte_count = rest[1]
    data = rest[2:2 + byte_count]
    if len(data) != byte_count:
        raise RuntimeError("字节数不符：声明 {}，实收 {}".format(byte_count, len(data)))
    if byte_count != count * 2:
        print("  ⚠ 机器人回的字节数（{}）与请求的寄存器数（{}）不一致 —— 这本身就是"
              "一个发现，记下来。".format(byte_count, count))

    return [struct.unpack(">H", data[i:i + 2])[0] for i in range(0, len(data), 2)]


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


# ── 自检：不联网，验证解码器本身没写错 ────────────────────────────────
def selftest() -> int:
    print("自检：解码器 vs 已知值")
    ok = True

    # x=100.0 大端 Float32 -> 寄存器 0x42C8 0x0000
    got = _f32(0x42C8, 0x0000, "ABCD")
    print("  ABCD 0x42C8 0x0000 -> {:.4f}（期望 100.0000）".format(got))
    ok &= abs(got - 100.0) < 1e-4

    # 字序颠倒后应当解出一个极小的数（不是 100）
    got = _f32(0x42C8, 0x0000, "CDAB")
    print("  CDAB 0x42C8 0x0000 -> {:.6g}（期望 ~2.4e-41，明显不是 100）".format(got))
    ok &= abs(got - 100.0) > 1.0

    # Int32 0x0001 0x86A0 = 100000，系数 0.001 -> 100.0
    raw = _i32(0x0001, 0x86A0)
    print("  Int32 0x0001 0x86A0 -> raw {}  ×0.001 = {:.4f}（期望 100.0000）"
          .format(raw, raw * 0.001))
    ok &= (raw == 100000)

    # 负数要能解出来（补码）
    raw = _i32(0xC248, 0x0000)
    print("  Int32 0xC248 0x0000 -> raw {}（期望 -1035468800，说明负数按补码读）".format(raw))

    # Int16 负值
    print("  Int16 0xFF9C -> {}（期望 -100）".format(_i16(0xFF9C)))
    ok &= (_i16(0xFF9C) == -100)

    print("自检：{}".format("通过" if ok else "失败"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Modbus TCP 位姿寄存器转储器（只读）")
    ap.add_argument("--host", default="192.168.0.1")
    ap.add_argument("--port", type=int, default=502)
    ap.add_argument("--unit", type=int, default=1, help="从站号（默认 1）")
    ap.add_argument("--start", type=int, default=0, help="起始寄存器（默认 0）")
    ap.add_argument("--count", type=int, default=12,
                    help="读几个寄存器（默认 12 = 6 个 Float32）")
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--out", default="", help="报告文件路径（默认落在本脚本同目录）")
    ap.add_argument("--selftest", action="store_true", help="只跑解码器自检，不联网")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    report = start_report("probe_modbus_pose", args.out)

    print("Modbus 位姿寄存器转储")
    print("  目标 {}:{}  从站号 {}  起始寄存器 {}  数量 {}"
          .format(args.host, args.port, args.unit, args.start, args.count))
    print()

    try:
        regs = read_holding(args.host, args.port, args.unit, args.start,
                            args.count, args.timeout)
    except Exception as e:  # noqa: BLE001 — 现场脚本，任何失败都要原样说出来
        print("读取失败：{}".format(e))
        print()
        print("这类失败本身也是证据，请连同机器人型号/固件一起发回。")
        if report:
            print()
            print("本段输出已存到：{}".format(report))
        return 2

    print("读回 {} 个寄存器".format(len(regs)))
    decode_pairs(regs)
    decode_singles(regs)
    dump_raw(regs, args.start)

    print()
    print("── 机器人停在 x=100 y=200 z=300 A=10 B=20 C=30 时，代码假设下应有的寄存器对 ──")
    for name, (hi, lo) in EXPECTED_F32.items():
        print("     {:>10}  0x{:04X} 0x{:04X}".format(name, hi, lo))
    print()
    print("判读（看原始寄存器那一块）：")
    print("  · 逐对与大端 Float32 表一致        -> 布局/字节序/格式三条假设全对")
    print("  · 每对两个值左右互换（如 0x0000 0x42C8）-> 字序颠倒(CDAB)，代码需要加字序开关")
    print("  · 整个表里找不到 0x42C8/0x4348/0x4396 -> 起始寄存器不对，或不是 Float32；")
    print("      从 --start 0 起多扫几段（--count 125）找这几个值出现的位置")
    print("  · 出现 0x0001 0x86A0 这类小整数      -> 是 Int32×系数，按上面的系数表读数")
    if report:
        print()
        print("本段输出已存到：{}".format(report))
        print("把这个 txt 文件发回来即可（控制台里的中文可能因代码页显示为乱码，文件不会）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
