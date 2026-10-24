# 段階LP3: 光害の既定を Black Marble 由来の指数(bm)に切り替える

ブランチ `stageLP3`(`stageLP2` から分岐。push していない)。git 履歴の書き換えはしていない。

## 1. やったこと

| 依頼 | 結果 |
|---|---|
| 1. 既定の `--lp-source` を bm に | `lp_source.DEFAULT_LP_SOURCE = "bm"`。`explore_hoshibiyori.py`・`generate_report.py`・`scripts/report_courses.py`・`scripts/weekend_page.py` の既定が bm。`--lp-source legacy` で従来の入力も使える |
| 2. 相対指数・順位差の明記 | レポート冒頭(`BM_RELATIVE_NOTE`+`BM_RANK_NOTE`)、フッター(Black Marble の出典・引用)、README(「光害の指数について」の項と出典表)に記載 |
| 3. `stargazing_spots.bm.json` から `lpi` を外す | `annotate_spots_bm.py` の `KEEP` から `lpi` を除き、再生成(146地点、`lpi` 0件) |
| 4. 現行ファイルの Lorenz 氏由来の値の除去 | 下の第3節 |
| 5. テスト | 全体 `Ran 434 tests` / `OK (skipped=3)`(LP2 の 429件に5件追加) |

### 出力ファイル名の変更(要確認)
既定(bm)のレポートは `report.html`、legacy は `report_legacy.html`。LP2 の `report_bm.html` は廃止(`.gitignore` には残した)。
`report_courses.py`・`weekend_page.py` が既定で読む名前を変えずに済み、AGENTS.md の手順も変わらない。週末ページは既定(bm)が `weekend_stargazing_<夜>.html`、legacy が `…_legacy.html`。

## 2. 既存テストの扱い
- legacy 形式のレポートを使う既存テスト(`test_report_courses.py`・`test_weekend_page.py`)は、期待値を変えず、呼び出しに `--lp-source legacy`(または `lp_source="legacy"`)を明示した。1件だけ、legacy の既定出力名が `…_legacy.html` になるため期待するファイル名を変えた(`test_default_path_uses_first_night`)。
- `test_lp_source.py` の「既定は legacy」を「既定は bm(`report_courses`・`weekend_page` も同じ値)」に置き換え、legacy が選べること・出力先が上書きされないこと・現行の地点ファイルに Lorenz 氏由来の値が無いこと・`site_type` が ALR の仮閾値と一致することを追加。
- 閾値の件数 N=141 は、`stargazing_spots.json` の `lpi` を読めなくなったため `lp_source.BM_THRESHOLD_N_PASS` の固定値にした(根拠の再計算は `bm_threshold.py`、光害タイルが要る)。

## 3. 除去したもの・残したもの(Lorenz 氏由来の値)

除去した(現行ファイルから。**git 履歴には残る**):
- `stargazing_spots.json`: `spots` 146件の `lpi`/`mpsas`/`bortle_approx`/`light_pollution_computed`、`viewpoint_reference` 751件の `light_pollution_computed`。実行前に `stargazing_spots.json.bak_before_lp3_20261024_071240.json`(git管理外)を取得。書式(インデント・CRLF)は変えていない。
- `site_type`: 同ファイルの146件を ALR(仮閾値 10.66)で引き直した。変わったのは2件(堂平天文台=暗い空→夜景系、富士山吉原=夜景系→暗い空。LP2 の食い違い2件と同じ)。`counts` の件数(暗い空141/夜景系5)は変わらない。`_note_site_type` を更新。
- `stargazing_spots.bm.json` の `lpi`(`site_type` は ALR 由来に変わった)。
- `tests/fixtures/sky_guide/*_data.json` の `spot.lpi`/`mpsas`(と出典文の Lorenz 氏の記載)。
- 星空ガイド: 出典文(`skyguide/build.py`)と `docs/sky_guide_style.md` から Lorenz 氏の記載を除いた。見出しの「光害 LPI…」欄は、値が無いと省かれる既存の挙動により出なくなる。
- `classify_site_darkness.py`: ALR で `site_type` と `counts` だけを書くよう書き換え(`lpi` 等は書かない)。

残したもの(判断が要る。第5節):
- `docs/examples/senjogahara_sky_guide_20261009.html`(公開された見本。LPI 値と Lorenz 氏の出典を含む。「読み取り専用」の運用のため変更していない)。
- `light_pollution.py` と legacy 用の処理(legacy を残す指示のため)。比較・検証用スクリプト(`bm_threshold.py`・`bm_disagreements.py`・`validate_skyglow_bm.py`・`analyze_*.py`)は、`legacy_ref.legacy_lpi()` で光害タイルから都度計算する(キャッシュ `step3_light_pollution/tile_cache/` があれば通信しない。無ければタイルを取得する)。
- `merge_external_spots_20260907.py`・`static_ranking.py`・`run_5points.py`(単発の旧スクリプト)。前者は再実行すると旧値が戻るので注記を入れた。
- `README.md` の出典表の Lorenz 氏の行(legacy のときだけ使う旨に変更)、CLAUDE.md の「光害データ取得に関する注意」(経緯として残す)。
- **git 履歴**: 過去のコミット(`stargazing_spots.json`・`stargazing_spots.bm.json`・fixtures・`docs/examples/`)に値が残る。

## 4. 確認できたこと・できていないこと
- 単体テストは全体で OK。bm/legacy の `site_type` 判定は、146地点で両方通ること(bm: 暗い空141/夜景系5、legacy: 同件数)を手元で確認(通信なし、キャッシュのタイルで計算)。
- **通し実行(`generate_report.py`)は、今回は再実行していない**。LP2 で bm の通し実行は成功済み(11.1分・失敗セル0)だが、その後に変えた点(`site_type` の引き直しを legacy にも入れた、夜景系の枠の値、出力名)は単体テストだけで確認した。実行は10〜30分・Open-Meteo 約220回・`report.html` を上書きするため、ご指示があれば実行する。
- 注記の「上位10件のうち6件が共通、上位2件は同じ」は、LP2 の並べ比較(見込み/ECMWF、2026-10-31〜11-05の6夜、主軸146件)の結果で、近日中(MSM)は候補が0件で未比較。注記の根拠はこの範囲に限られる。

## 5. 私(本人)が決める点
1. **公開リポジトリの `docs/examples/senjogahara_sky_guide_20261009.html`**: LPI 値・Lorenz 氏の出典を含む。値を外した版に差し替えるか、そのまま残すか。
2. **git 履歴の扱い**: 履歴に Lorenz 氏由来の値が残る。履歴の書き換え(公開済みリポジトリの改変、force push)を行うか。行わない場合、README に履歴に残る旨を書くか。著者への利用可否確認(未実施)の方針とも関係する。
3. **legacy を残す期間と、Lorenz 氏のタイル取得処理(`light_pollution.py`・`tile_cache/`・旧スクリプト)をいつ削除するか**。
4. **仮閾値 ALR 10.66**: 「従来と同じ件数が通る」という順位対応だけが根拠で、日本では未較正。実地の成功・失敗例(神磯の鳥居・安房埼灯台・菜の花台・高尾山)で確認するか、定数名を `BM_ALR_THRESHOLD` のままにするか。
5. **月込みの実効的な空の明るさ(mag/arcsec²)の代替**: bm では出ない。月相・月高度の表示などで代替するか。
6. **星空ガイドの見出しに ALR を載せるか**(現在は光害の欄が出ない)。
7. **通し実行(`generate_report.py`)を行ってよいか**(第4節)。
8. **出力名の変更(`report_bm.html` 廃止、legacy は `report_legacy.html`)でよいか**。
9. **注記の文言**: 「順位差は小さい」の根拠が6夜の比較に限られる点を、そのまま書くか、控えめにするか。
