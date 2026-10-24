# 段階LP3b: 以前の光害データ(Light Pollution Atlas)由来の値・データ・取得コードの除去

ブランチ `stageLP3b`(`stageR1` から作成済み)。push していない。git 履歴は書き換えていない。
README・CHANGELOG の「光害データの変更(1.0.0)」と出典表は R1 で作成済みのため、重複させず整理だけした。

**指示文が途中で切れていた点(保守的に判断した点)**: 受け取った指示は「1-f. … から、地点別の LPI / mpsas / bortle」で終わっていた。
1-f は「地点別の LPI・mpsas・ボートル近似の**数値**を除去する」と読んで実施し、2 以降(あったとすれば)は分からないため、
完了条件を「全テストが通ること」「`generate_report.py` の通し実行が成功すること」「この REPORT」とした。続きの指示があれば対応する。

## 0. 洗い出し(削除の前に実施)

検索語: Lorenz、djlorenz、Light Pollution Atlas、lpi、mpsas、bortle、LPI_THRESHOLD、`light_pollution.py`・`legacy_ref.py` の参照、旧タイルの取得処理、tile_cache(あわせて lp-source、report_legacy、legacy)。

| 場所 | 該当 | 分類 |
|---|---|---|
| `step3_light_pollution/light_pollution.py` | 旧タイルの取得・キャッシュ・LPI・mpsas・ボートル近似 | **除去**(1-b) |
| `step3_light_pollution/legacy_ref.py` | 比較用に旧タイルからLPIを計算 | **除去**(1-b) |
| `step3_light_pollution/run_5points.py`、`static_ranking.py`、`merge_external_spots_20260907.py` | `LightPollutionTileStore` を使う legacy 専用・単発のスクリプト(後者は地点に lpi 等を書き込む) | **除去**(1-b) |
| `explore_hoshibiyori.py` | `LightPollutionTileStore` の import、`LPI_THRESHOLD`(と地点別のLPI値を含むコメント)、`--lp-source`、`make_lp_store(lp_source)`、`_effective_mpsas`、候補の `lpi`/`effective_mpsas` 項目、表示の legacy 分岐 | **除去**(1-b・1-c)。内部値の項目は `lp_index` に改名 |
| `generate_report.py` | 同上の import、`LPI_THRESHOLD`、`--lp-source`、`OUTPUT_PATH_LEGACY`(`report_legacy.html`)、`_site_type` の legacy 分岐、夜景系の枠の `lpi`、カード・フッターの legacy 表示(Lorenz氏の出典) | **除去**(1-c) |
| `scripts/report_courses.py`・`scripts/weekend_page.py` | `--lp-source`、`LP_SOURCES`・`DEFAULT_LP_SOURCE`・`LEGACY_REPORT_NAME`、等級(mag/arcsec²)の解析・表示・照合、出力名 `_legacy` | **除去**(1-c)。旧形式(等級)のレポートは「旧形式です。再生成してください」で終了コード3 |
| `step3_light_pollution/lp_source.py` | `LP_SOURCES`・`DEFAULT_LP_SOURCE`・`LPI_THRESHOLD_REF`、`BmReading.mpsas/bortle_approx`、legacy の説明 | **除去**。規格化の基準は `LP_INDEX_LIMIT = 5.0` に改名(下の「スコア」) |
| `step3_light_pollution/compare_lp_sources.py`・`analyze_rank_shift.py`・`analyze_horizon_alr.py`・`bm_disagreements.py` | 旧タイル(`legacy_ref`・legacy の store)に依存する比較・検証 | **除去**(1-d)。結果は REPORT_LP2.md に残る |
| `step3_light_pollution/bm_threshold.py` | 旧LPIの通過件数を数えていた | **残す(タイル非依存に直した)**: 件数 N=141 を `lp_source.BM_THRESHOLD_N_PASS` から取り、ALR だけで閾値を求め直す。年次の更新(UPDATE.md)でALRが変わったときに閾値の動きを見るのに使え、`threshold_for_count` は単体テストがある |
| `step3_light_pollution/validate_skyglow_bm.py` | 旧LPIとの順位相関の節 | **残す(その節だけ削除)**: 残りの検証(都市・暗い地点の並び、近接2地点の比、前年との比較)はタイル不要で、UPDATE.md の年次更新手順が使う |
| `step3_light_pollution/annotate_spots_bm.py` | 説明文の「lpi は写さない」 | **残す**: 旧データに依存せず、`stargazing_spots.bm.json` を作る。説明文だけ直した |
| `docs/examples/senjogahara_sky_guide_20261009.html` | 見本(LPI 値と Lorenz 氏の出典) | **除去**(1-a)。`docs/examples/README.md` を更新 |
| `scripts/extract_sky_guide_sample.py` | 上の見本からゴールデンを抽出する(見本が無いと動かない) | **除去**。ゴールデン `tests/fixtures/sky_guide/` は残す |
| `tests/test_sky_guide.py` | 見本HTMLと比べる2件 | **除去**(見本が無いため)。ゴールデンを使う他のテストは残る |
| `skyguide/build.py`・`skyguide/render.py` | 地点の `lpi`/`mpsas` と見出しの「光害 LPI…」欄 | **除去** |
| `step4_moonlight/run_verification.py` | 石廊崎の背景輝度(旧データ由来の値) | **値を除去**: 仮定値 21.5 mag/arcsec² に置き換え、仮定であることを明記(月の影響の大きさを見る検証。地点値ではない) |
| `step4_moonlight/moon_brightness.py` | `mpsas`(月明かりのモデルの引数名) | **残す**: 旧データではなく Krisciunas & Schaefer のモデル。探索・レポートからは使っていない |
| `stargazing_spots.json` | `_note_site_type` の Lorenz 氏の記載 | **除去**(注記を書き換え。一括編集の前に `.bak_before_lp3b_*` を取得)。座標修正の記録の注記にある `run_5points.py` の名前は、当時の作業の記録として**残す** |
| `classify_site_darkness.py` | 説明文の Lorenz 氏の記載 | **除去**(説明文のみ) |
| `scripts/check_setup.py` | 書き込み確認の対象 `tile_cache` | **除去** |
| `.gitignore` | `tile_cache/`、`/report_legacy.html`・`/report_bm.html` | **残す(コメントを更新)**: 手元に残っている旧キャッシュ・旧レポートを誤ってコミットしないため |
| `requirements.txt` | コメントの Light Pollution Atlas・`light_pollution.py` | **除去**(コメント) |
| `AGENTS.md`・`skills/hoshibiyori/SKILL.md` | 保護領域の `LPI_THRESHOLD`、`--lp-source legacy` の手順、`tile_cache`、削除したスクリプト名 | **除去・更新** |
| `README.md` | 出典表の Lorenz 氏の行、`--lp-source`・legacy の記述、構成表、通信の記述 | **除去**(1-e)。「光害データの変更(1.0.0)」は経緯だけ |
| `CHANGELOG.md` | 1.0.0 の項の `--lp-source`・legacy の記述 | **整理**(1-e)。未リリースの `--lp-source` は載せず、0.1.0 からの差分として書き直した |
| `CLAUDE.md` | Lorenz 氏の記述(複数の節)、地点別のLPI値(閾値の経緯・確認データ)、石廊崎の 21.73、`light_pollution.py` 等 | **1段落にまとめた**(1-e)。「光害データ(Black Marble 由来の指数)」節の1段落だけに Lorenz 氏の名前が残る。地点別の数値は載せない |
| `step3_light_pollution/REPORT_LP1.md`・`REPORT_LP2.md` | 表の LPI 列、減点の legacy 列と差の列(LPI×10 から地点値が戻せる)、本文の「LPI 4.93」など | **数値を除去**(1-f。表は「—」、本文は「[除去]」)。順位(%)・ALR・集計値(中央値・分位など)は残した |
| `step3_light_pollution/REPORT_LP3.md`・`REPORT_R1.md` | `lpi` などの項目名、`LPI 4.93・6.49` の記載(R1) | 項目名は**残す**(値ではない)。R1 の数値は**除去** |
| `logs/*.log`(15件のうち3件に地点別の値) | `LPI=0.54 -> dark_sky`(62行)、`光害LPI 0.46`(各20行) | **数値を除去**(「[除去]」)。`LPI<=3.0` などの閾値の表示は地点別の値ではないので残す |
| `tests/test_skyglow_bm.py` | `"lpi": 1.0` などの合成値 | **残す**: 既存の項目が保たれるかを見るための合成値で、旧データではない |
| `tests/test_lp_source.py`・`test_lp_source_scripts.py` | 「Lorenz」「Light Pollution Atlas」「legacy_ref」 | **残す**: 出力に含まれないこと・モジュールが無いことを確かめるテストの文字列 |
| `tests/test_report_courses.py`・`test_weekend_page.py` | 合成カードの等級(21.806 など。旧データではない)と `--lp-source legacy` | **ALR の合成値に置き換え**(テストの意図は保った) |

## 1. 除去の結果

- **a.** 見本HTMLを削除。
- **b.** `light_pollution.py`・`legacy_ref.py`・タイルのキャッシュ処理・`LPI_THRESHOLD` などの legacy 専用の定数・`run_5points.py`・`static_ranking.py`・`merge_external_spots_20260907.py` を削除。
- **c.** `--lp-source` と legacy の分岐、`report_legacy.html` を削除。出力は `report.html` のまま。週末ページの出力名も `weekend_stargazing_<夜>.html` のみ。
- **d.** `compare_lp_sources.py`・`analyze_rank_shift.py`・`analyze_horizon_alr.py`・`bm_disagreements.py` を削除。`bm_threshold.py`・`validate_skyglow_bm.py`・`annotate_spots_bm.py` はタイル非依存の形で残した(理由は第0節)。
- **e.** README の出典表から Lorenz 氏の行を削除し、「光害データの変更(1.0.0)」を経緯だけにした。CHANGELOG の 1.0.0 も同様。CLAUDE.md は1段落にまとめ、地点別のLPIの数値を除いた。
- **f.** REPORT_LP1・LP2・R1 とログ3件から、地点別の LPI・mpsas・ボートル近似の数値を除去した。

### スコア(保護領域)は変えていない
探索の足切りは `brightness_ratio <= LP_INDEX_LIMIT`(5.0)、スコアは `- brightness_ratio × 10.0`(近日中)/`100 - brightness_ratio × 10.0`(見込み)のまま。
`brightness_ratio` は ALR×5.0/10.66 で、LP3 までの bm と同じ値。定数名を `LPI_THRESHOLD`(explore)から `LP_INDEX_LIMIT`(lp_source)に移した(指示の「LPI_THRESHOLD などの削除」に従い、値は保った)。
AGENTS.md の保護領域の表も更新した。

### LP3 の誤りの修正(報告)
段階LP3で `sed -i` を使ったときに、`stargazing_spots.json` の改行が CRLF から LF に変わり、そのままコミットしていた(`278a97f`。全10781行が差分になっていた)。
CRLF に戻したので、main との差分は内容の変更だけ(754行追加・2089行削除)になる。直前のコミットとの差分は全行になる。
同じ確認を変更した全ファイルで行い、`AGENTS.md` の8行(main で LF だった行)の改行も元に戻した。

## 2. テスト
`py -X utf8 -m unittest discover -s tests` → **`Ran 425 tests` / `OK (skipped=3)`**(R1 の 435 件から −10 件)。

| ファイル | 件数 | 変更 |
|---|---|---|
| `test_lp_source.py` | 25 → 19 | legacy の切り替え・既定・出力名のテストを削除し、「`--lp-source` が無い」「旧モジュールが無い」「既定の store の規格化」のテストに置き換え |
| `test_lp_source_scripts.py` | 12 → 9 | legacy 形式のテストを削除。旧形式(等級)のレポートを拒否するテストに置き換え |
| `test_report_courses.py` | 21 → 21 | 合成カードを ALR にし、期待値(表示文・JSONの項目)を ALR に合わせた |
| `test_weekend_page.py` | 62 → 63 | 同上。等級の照合のテストを「ALR の不一致」と「等級は書けない」の2件にした |
| `test_sky_guide.py` | 24 → 22 | 削除した見本HTMLと比べる2件を削除 |

## 3. 通し実行
- `py -X utf8 generate_report.py`(引数なし): **成功(終了コード0)**、10.3分。取得セル190件・API呼び出し0回(R1 の実行のディスクキャッシュが有効期限内)・失敗0件。
  `report.html` に「Lorenz」「Light Pollution Atlas」「LPI」「mag/arcsec」「ボートル」は0件、相対指数の注記と Black Marble の引用があることを確認した。
- `py -X utf8 scripts/report_courses.py`: 終了コード0。近日中(MSM)の夜が無いため両コースとも「候補なし」(理由つき)。**実データで ALR のカードが並ぶ状態は、今回も確認できていない**(合成データのテストのみ)。
- `explore_hoshibiyori.py --help`・`scripts/check_setup.py`: 動作を確認(check_setup は「必須項目はすべてOK」)。
- ログはリポジトリ外 `C:\hoshibiyori-archive\r1-20261024\generate_report_lp3b.log`。

## 4. 本人が決める点
1. **指示の続き**: 1-f の途中から先が届いていない。追加の作業があれば指示がほしい。
2. **手元(git 管理外)に残る旧データ**: `step3_light_pollution/tile_cache/`(旧タイルのキャッシュ)と `stargazing_spots.json.bak_*`(旧値を含むバックアップ)、`report_legacy.html`・`report_bm.html`(あれば)。削除していない。消すかどうか。
3. **REPORT_LP1・LP2 に残した「LPI順位(%)」**: 地点別の値は除去したが、旧データから求めた順位(%)は分析結果として残した。順位も外すか。
4. **`step4_moonlight/run_verification.py` の仮定値 21.5 mag/arcsec²**: 根拠のある地点値ではない。別の値にするか、地点を外して一般的な例にするか。
5. **`.gitignore` の旧キャッシュ・旧レポートの除外**: 手元の誤コミット防止のため残した。不要なら外す。
6. **CHANGELOG の 1.0.0 の日付とタグ**: R1 のとおり、main へのマージ後に付け直す前提(ローカルのタグ v1.0.0 は削除済み)。
