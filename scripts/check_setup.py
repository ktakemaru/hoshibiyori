"""セットアップの確認(既定では通信しない)。

使い方:
    py -X utf8 scripts/check_setup.py             # 通信しない確認
    py -X utf8 scripts/check_setup.py --network   # 加えてOpen-Meteoに1リクエスト

終了コード: 0=必須項目はすべてOK(警告があっても0)、1=必須項目にNGあり。
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # リポジトリ直下の hb_paths を見つけるため
from hb_paths import DATA_ROOT, ENV_VAR  # noqa: E402
VERIFIED_PYTHON = (3, 15)  # 動作確認済みの版。READMEの「3.13以降」はコードからの推定で、実機確認は3.15のみ
REQUIRED = ["skyfield", "requests", "numpy", "PIL"]
OPTIONAL = ["playwright"]
CACHE_DIRS = [
    "step2_terrain/dem_cache", "step3_light_pollution/tile_cache", "step5_cloud_forecast/cloud_cache",
    "step5_cloud_forecast/weather_map_cache", "step5_cloud_forecast/himawari_cache",
]
EPHEMERIS = DATA_ROOT / "step1_astronomy" / "de421.bsp"


def check_python(version: tuple[int, int]) -> tuple[str, str]:
    cur = f"{version[0]}.{version[1]}"
    if version[:2] == VERIFIED_PYTHON:
        return "OK", f"Python {cur}(動作確認済みの版)"
    if version[:2] < (3, 13):
        return "NG", f"Python {cur}: 3.13以降が必要"
    return "WARN", f"Python {cur}: 動作確認は{VERIFIED_PYTHON[0]}.{VERIFIED_PYTHON[1]}のみ"


def check_import(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def check_writable(path: Path) -> bool:
    """ディレクトリ(無ければ最寄りの既存の親)に書き込めるか。ディレクトリは作らない。"""
    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        with tempfile.TemporaryFile(dir=target):
            return True
    except OSError:
        return False


def check_network() -> tuple[str, str]:
    import requests
    ua = "hoshibiyori-check-setup/0.1 (personal astrophotography tool; single request)"
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast",
                         params={"latitude": 35.0, "longitude": 139.0, "hourly": "cloud_cover", "forecast_days": 1},
                         timeout=20, headers={"User-Agent": ua})
    except requests.RequestException as e:
        return "NG", f"Open-Meteo接続失敗: {e}"
    if r.status_code == 429:
        return "NG", "Open-Meteoが429(利用上限)。回避せず、時間を置くこと"
    return ("OK", "Open-Meteo応答OK") if r.ok else ("NG", f"Open-Meteo HTTP {r.status_code}")


def run(network: bool = False) -> int:
    results: list[tuple[str, str]] = [check_python(sys.version_info)]
    for m in REQUIRED:
        ok = check_import(m)
        results.append(("OK" if ok else "NG", f"必須パッケージ {m}" + ("" if ok else "(pip install -r requirements.txt)")))
    for m in OPTIONAL:
        ok = check_import(m)
        results.append(("OK" if ok else "WARN", f"任意パッケージ {m}" + ("" if ok else "(無くても可。天気図セクションが省略される)")))
    enc = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")
    results.append(("OK", "標準出力はUTF-8") if enc == "utf8" else ("WARN", f"標準出力が{enc or '不明'}: -X utf8 を付けると日本語の文字化けを避けられる"))
    results.append(("INFO", f"データ領域: {DATA_ROOT}" + ("" if os.environ.get(ENV_VAR, "").strip() else f"({ENV_VAR} 未設定: リポジトリ内)")))
    for d in CACHE_DIRS:
        results.append(("OK", f"書き込み可 {d}") if check_writable(DATA_ROOT / d) else ("NG", f"書き込み不可 {d}"))
    if EPHEMERIS.exists():
        results.append(("OK", f"暦ファイル {EPHEMERIS.name} あり"))
    else:
        results.append(("WARN", f"{EPHEMERIS.name} なし: 初回実行時にJPLから自動ダウンロードされる(約17MB)"))
    if network:
        results.append(check_network())
    for status, msg in results:
        print(f"[{status:4}] {msg}")
    ng = sum(1 for s, _ in results if s == "NG")
    print("結果: " + ("必須項目はすべてOK" if ng == 0 else f"NGが{ng}件あります"))
    return 0 if ng == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--network", action="store_true", help="Open-Meteoに1リクエスト送る確認も行う")
    return run(ap.parse_args().network)


if __name__ == "__main__":
    sys.exit(main())
