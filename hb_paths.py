"""保存先(キャッシュ・暦・生成物)の基準を決める。import時にディレクトリは作らない(書く側が必要時に作る)。

ROOT      : リポジトリ(プラグインとして入れたときはそのインストール先)。読み取り専用の静的データの基準。
DATA_ROOT : 書き込み先の基準。環境変数 HOSHIBIYORI_DATA_DIR が設定済みかつ空でなければそのパス(~展開・resolve)、
            なければ ROOT(従来どおり)。DATA_ROOT の下はリポジトリと同じ相対構成
            (step5_cloud_forecast/cloud_cache/、step1_astronomy/de421.bsp、report.html、out/ など)。
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "HOSHIBIYORI_DATA_DIR"
ROOT = Path(__file__).parent


def resolve_data_root(default: Path | None = None, env=None) -> Path:
    """環境変数が空でなければそのパス、なければ default(省略時は ROOT)。env は os.environ の代わりに渡せる(テスト用)。"""
    raw = (os.environ if env is None else env).get(ENV_VAR, "")
    if raw.strip():
        return Path(raw.strip()).expanduser().resolve()
    return ROOT if default is None else default


DATA_ROOT = resolve_data_root()


class _EphemerisLoad:
    """skyfield.api.load と同じ使い方(load.timescale()・load(暦ファイルのパス))で、暦を、そのファイルのフォルダを保存先にして開く。

    Skyfield は load('<絶対パス>') だと、パス全体を取得先URLの末尾に連結してしまい(…/bsp/C:/…/de421.bsp → 404)、
    暦が無いときに自動ダウンロードできない。保存先のフォルダを指定した Loader('<フォルダ>')('<ファイル名>') で開けば、
    取得先URLが正しくなる(…/bsp/de421.bsp)。フォルダは Loader が作る。暦が既にあれば通信しない。
    """

    @staticmethod
    def timescale(*args, **kwargs):
        from skyfield.api import load
        return load.timescale(*args, **kwargs)

    def __call__(self, path, **kwargs):
        from skyfield.api import Loader
        p = Path(path)
        return Loader(str(p.parent))(p.name, **kwargs)


ephemeris_load = _EphemerisLoad()
