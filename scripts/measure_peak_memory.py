"""子プロセスのピークメモリを測る(Windows用。標準ライブラリのみ)。

    py -X utf8 scripts/measure_peak_memory.py -- <コマンド> [引数...]

子プロセスの標準出力・標準エラーはそのまま流し、終了後に PeakWorkingSetSize(物理メモリのピーク)と
PeakPagefileUsage(コミットされた仮想メモリのピーク)をMBで出す。段階LP2の比較スクリプトが
メモリ不足で停止された原因の調査用(通信・書き込みはしない)。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def read(handle) -> tuple[int, int]:
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(wintypes.HANDLE(int(handle)), ctypes.byref(pmc), pmc.cb):
        return 0, 0
    return pmc.PeakWorkingSetSize, pmc.PeakPagefileUsage


def main() -> int:
    if "--" not in sys.argv:
        print(__doc__)
        return 2
    cmd = sys.argv[sys.argv.index("--") + 1:]
    t0 = time.time()
    p = subprocess.Popen(cmd)
    ws = pf = 0
    while p.poll() is None:
        a, b = read(p._handle)
        ws, pf = max(ws, a), max(pf, b)
        time.sleep(0.2)
    a, b = read(p._handle)
    ws, pf = max(ws, a), max(pf, b)
    print(f"\n[measure_peak_memory] 終了コード {p.returncode} / {time.time() - t0:.1f}秒 / "
          f"ピーク物理メモリ {ws / 2**20:.0f}MB / ピークコミット {pf / 2**20:.0f}MB", flush=True)
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
