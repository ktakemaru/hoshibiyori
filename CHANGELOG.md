# Changelog

このファイルは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式に従います。
ここに書くのは、実際に main にマージされた変更だけです。

## [1.0.0] - 2026-10-24

光害データを、ライセンスが不明瞭な外部データから、NASA Black Marble 由来の自前計算に切り替えた版。
個人利用向けの数値予報の整理ツールであり、公開サービスではない(README の免責)。

### Changed
- **光害を Black Marble 由来のスカイグロー指数 ALR に変更**。光害データは、当初 David Lorenz 氏の Light Pollution Atlas を検討・使用していたが、ライセンスが不明瞭なため、NASA Black Marble(VNP46A4、2025年)から Duriscoe et al. 2018 の手法で自前計算した指数に変更した。**以前のコミットには旧データが含まれる**(履歴は書き換えていない)。日本では未較正の相対指数で、空の明るさの等級(mag/arcsec²)・ボートル値は出さない。足切りは仮閾値 ALR 10.66(以前の判定と同じ件数が通る値)。スコア式は変えていない(内部値の規格化で光害の減点の大きさを保った)
- レポート・`scripts/report_courses.py`・`scripts/weekend_page.py` の光害の欄を、ALR と順位(主軸の地点のうち暗い方から何%)に。月込みの「実効的な空の明るさ」は表示しなくなった。週末ページの解説の verdict に等級(N.NN mag)は書けず、ALR の値はレポートの候補と照合される
- `stargazing_spots.json` の `site_type`(暗い空/夜景系)を ALR の仮閾値で引き直した(堂平天文台が夜景系、富士山吉原が暗い空に)
- レポートのフッターの出典表示: Open-Meteo の表示を「Weather data by Open-Meteo.com」と CC BY 4.0 へのリンク・加工した旨に、天気図を「出典：気象庁ホームページ(URL)」の形に、ODbL へのリンクを追加。Black Marble の引用を製品ページの推奨表記に合わせた
- 取得処理の User-Agent のバージョンを 1.0.0 に
- `plugin.json` の `version` を 1.0.0 に

### Added
- スカイグロー指数の派生データ `step3_light_pollution/data/skyglow_bm_2025.npz` と出所 `PROVENANCE.json`、取得・生成・検証のスクリプト(`step3_light_pollution/`)、手法と更新手順(`METHOD.md`・`UPDATE.md`)
- レポート冒頭の注記: 光害は日本で未較正の相対指数であることと、以前の光害データとの比較で上位の順位差が小さいこと
- README: 出典表を「提供元・条件(ライセンスとURL)・必要な表示・確認日」の形に改め、OSM 由来のデータファイルのライセンス(ODbL)、光害データの変更の経緯を追記

### Removed
- 以前の光害データ由来の値: `stargazing_spots.json` の `lpi`・`mpsas`・`bortle_approx`・`light_pollution_computed`、テスト用データ・ログ・検証記録の地点別の値、星空ガイドの見出しの光害欄
- 以前の光害データの取得処理(`step3_light_pollution/light_pollution.py` とタイルのキャッシュ処理)と、それに依存するスクリプト(`static_ranking.py`、`merge_external_spots_20260907.py`、`step3_light_pollution/run_5points.py` ほか、比較・検証用のスクリプト)
- 星空ガイドの見本 `docs/examples/senjogahara_sky_guide_20261009.html` と、見本からゴールデンを抽出する `scripts/extract_sky_guide_sample.py`(回帰テストは抽出済みの `tests/fixtures/sky_guide/` で続ける)

### Fixed
- README の星空ガイドの手順で、`scripts\render_sky_guide.py` の `\r` が改行文字になって壊れていた行

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
