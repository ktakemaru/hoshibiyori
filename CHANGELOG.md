# Changelog

このファイルは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式に従います。
ここに書くのは、実際に main にマージされた変更だけです。

## [0.1.0] - 2026-10-19

Claude Code プラグインとしての初回の版(個人利用の検証段階)。

### Added
- Claude Code プラグイン定義: `.claude-plugin/plugin.json`(`version` 0.1.0)、`.claude-plugin/marketplace.json`(`hoshibiyori-marketplace`)、スキル `skills/hoshibiyori/SKILL.md`(手順・閾値・数値の正本は `AGENTS.md`)(#22)
- 保存先の切り替え: 環境変数 `HOSHIBIYORI_DATA_DIR`(`hb_paths.py`)。設定すると、キャッシュ・天文暦・生成物(`report.html`・`out/`・`weather_map_commentary.json` など)の書き込み先がそのフォルダになる。未設定または空なら従来どおりリポジトリ直下(#21)
- `scripts/check_setup.py` が「データ領域」を表示する(#21)
- プラグイン定義と保存先切り替えの単体テスト(`tests/test_plugin_manifest.py`、`tests/test_data_dir.py`)(#21, #22)

### Fixed
- 天文暦 `de421.bsp` の自動取得を `Loader(保存先フォルダ)(ファイル名)` の形にした。絶対パスを `load` に渡すと、取得先URLが壊れて404になり、取得が成立していなかった。保存先フォルダは Loader が作る(#22)

### Changed
- `SKILL.md` の Python 呼び出しに `-B` を付け、プラグイン側に `__pycache__` を書かせない(#22)
