# 段階LP2 報告: 新指数(ALR)を既存の光害(LPI)と並べて試せる状態にする

作業日: 2026-10-23 / ブランチ: `stageLP2`(`stageLP1` から分岐。commit のみ、push していない)

## 0. 事前確認

- `git show --stat 2e8747b`: `skyglow_bm_2025.npz`・`PROVENANCE.json`・`stargazing_spots.bm.json` が入っている。`blackmarble_cache/`(生データ)は 0 件(追跡されていない)。
- トークン文字列の検索(作業ツリー 367 ファイル[キャッシュ類を除く]と、全ブランチの全コミットの履歴): **検出なし**。

## 実施した範囲と未実施の範囲

| 項目 | 状態 |
|---|---|
| 1. 閾値の順位対応と食い違い一覧 | **実施** |
| 2. opt-in の切り替え(`--lp-source legacy\|bm`、既定 legacy)と単体テスト | **実施**(21件追加) |
| 3. 同じ日付・条件での legacy と bm の探索の並べ比較 | **実施**(第7節。近日中[MSM]は今日は候補なしのため見込み[ECMWF]のみ) |
| 4. 旧データ整理の計画 | **実施**(計画のみ。削除・値の消去はしていない) |
| `generate_report.py` の legacy・bm の通し実行 | **実施**(第8節。どちらも成功) |
| `report_courses.py`・`weekend_page.py` の bm 対応 | **実施**(第9節) |

(以下は最初の報告の記述を残したうえで、続きの作業[第7〜10節]で埋めた。当初「未実施」と書いた手順3と通し実行は、第7・8節で実施した。)

### 当初、手順3が未実施だった理由(経緯)

比較スクリプトをバックグラウンドで実行したところ、**システムがメモリ不足になり、実行中のコマンドが停止された**(Claude Code のメモリ逼迫時の自動停止)。停止の通知に「自分の判断で再実行しない」とあったため、その時点では再実行しなかった。原因の調査と再実行は第7節。

## 1. 閾値の順位対応

- 現行の方向フィルタの閾値: `explore_hoshibiyori.py` の `LPI_THRESHOLD = 5.0`(`LPI <= 5.0` を通す)。
- 主軸146件のうち通過する件数 **N = 141**(`stargazing_spots.json` の事前計算LPIと、光害タイルのキャッシュからの再計算の両方で141。両者の最大差 0.005 は丸めのため)。不通過の5件は `site_type=night_view`。
- ALR で同じ141件が通る閾値: ALR を小さい順に並べた141番目 = **10.3087**、142番目 = **11.0027**。その中点は 10.6557。仮の閾値は区間内の丸めた値 **`BM_ALR_THRESHOLD = 10.66`**(`lp_source.py`)。求め方は `bm_threshold.py`(再現可能。単体テストが「この定数で141件が通る」ことと境界の内側であることを固定している)。
- 論文 Table 3(ALR>10 で天の川が見えない)は日本に較正されていないため**閾値には使っていない**。参考までに ALR≦10 で通る件数は 140 件で、偶然ほぼ一致した(根拠にはしない)。
- 142番目(11.00)と141番目(10.31)の間隔は約0.7で、閾値の位置を少し動かしても件数が変わる地点は限られる(堂平天文台 11.00 が境界のすぐ外)。

### 食い違う地点(主軸146件中2件)

| 地点 | 県 | 標高m | site_type | LPI | ALR | LPI順位% | ALR順位% | 現行(LPI≦5.0) | 新(ALR≦10.66) |
|---|---|---|---|---|---|---|---|---|---|
| 富士山吉原（雲海スポット） | 静岡県 | 146 | night_view | 5.77 | 7.19 | 97.2 | 84.8 | 不通過 | 通過 |
| 堂平天文台 | 埼玉県 | 871 | dark_sky | 3.20 | 11.00 | 90.0 | 97.2 | 通過 | 不通過 |

(順位は146件内の百分位、0=最も暗い。)件数を揃えたので、食い違いは入れ替わりの2件だけ。前者は LPI が閾値をわずかに超えるだけで(5.77)、ALR では中位(84.8%)。後者は埼玉の山地で、新指数では関東平野の光をより強く拾う。実地でどちらが正しいかは未確認。

## 2. opt-in の切り替え

### 使い方と既定

- `py -X utf8 explore_hoshibiyori.py --lp-source legacy|bm`、`py -X utf8 generate_report.py --lp-source legacy|bm`。**既定は legacy**。
- **既定(legacy)の動作は変わっていない**: 旧版(`HEAD`)と新版の `render_html` に同じ合成データを渡して出力した HTML が**完全に一致**することを確認した(md5 一致、18,234 文字)。`generate_report.py` / `explore_hoshibiyori.py` の既存関数の呼び出し形も変えていない(追加は末尾の既定値つき引数のみ)。
- bm のレポートは **`report_bm.html`** に出す(`report.html` は上書きしない。`scripts/report_courses.py`・`weekend_page.py` が legacy の `report.html` の構造を読むため。`.gitignore` に追加済み)。

### 設計

- `step3_light_pollution/lp_source.py` の `BmLightPollutionStore` が `lp_store.get(lat, lon)` と同じ形の値を返し、呼び出し側の判定式・スコア式を変えずに入力だけを差し替える。
- bm の `brightness_ratio`(足切りとスコア減点に使う内部値)は **ALR を `LPI_THRESHOLD / BM_ALR_THRESHOLD` で線形に規格化した値**。こうすると、探索の判定式 `brightness_ratio <= LPI_THRESHOLD` が `ALR <= 10.66` と**完全に一致**し、スコアの光害減点(`値×10`)も閾値の位置で現行と同じ大きさになる。**規格化にはLPIの値を使っていない**(閾値の件数合わせのみ)ので、Lorenz 氏のデータに依存しない。内部値は画面に出さない。
- **bm では `mpsas` と `bortle_approx` を持たない(None)**。したがって「実効的な空の明るさ(月の影響込み)」は bm では計算できず、候補カードでは次のように置き換える: `光害(相対指数)  ALR 2.34(主軸の地点のうち暗い方から41%)`。夜景系の別枠(星空観賞向き)も同様。月の影響は、従来どおり「無月時間帯」(`moon_free_hours`)での絞り込みが効いているが、月明かりの強さを等級で出す表示は bm では無い。
- 範囲外の地点(格子の外)は ALR が None、内部値は inf(**通過させない**)。
- bm のとき `site_type`(`dark_sky`/`night_view`)は ALR の閾値で引き直す(既存の `site_type` は LPI 由来のため使わない)。
- レポートのフッターに、Black Marble の出典・引用(DOI 10.5067/VIIRS/VNP46A4.002、CC0、手法 Duriscoe et al. 2018)を載せ、冒頭に「相対指数であり絶対値ではない」「仮閾値は従来と同じ件数が通る値で、論文の目安ではない」の注記を出す。
- スコアの絶対値は legacy と bm で厳密には比べられない(減点が規格化した ALR のため)。順位の比較に使う。

### テスト

- 追加: `tests/test_lp_source.py` 21件(合成データのみ・通信なし): 閾値の一致と件数の再現、判定式が `ALR<=閾値` と一致、mpsas・ボートルが None、順位、範囲外は通過しない、`site_type`、CLIの既定と不正値、カード・夜景系・フッターの出し分け(legacy は mag/arcsec²・Lorenz 氏、bm は ALR・DOI・「相対指数」で mag/arcsec²・ボートルは出ない)。
- 全体: `py -X utf8 -m unittest discover -s tests` の最後の行 `Ran 418 tests in 62.646s` / `OK (skipped=3)`(LP1 の 397 件+新規 21 件。既存の期待値は変更していない。スキップ3件は既存のもの)。

### 既知の制約(bm)

- (当初の制約。第9節で解消)`report_courses.py` と `weekend_page.py` は当初 bm のレポートを読めなかった。`--lp-source bm` で読めるようにした。
- (当初の制約。第8節で解消)通し実行は、続きの作業で `generate_report.py` を legacy・bm の両方で実施した。`explore_hoshibiyori.py --lp-source bm` の通し実行は未実施(`compare_lp_sources.py` が同じ関数を呼ぶ)。

## 3. 並べて比較

当初は未実施。続きの作業で実施した(第7節)。

## 4. 旧データ整理の計画(実行していない)

**対象**: Lorenz 氏の Light Pollution Atlas 由来の値とその取得処理。ライセンス表記が無く、公開サービスへの組み込み前に著者への利用可否確認が必要(README・CLAUDE.md に未実施と明記)。

### 4-1. どこで使われているか

| 対象 | 場所 | 使われ方 |
|---|---|---|
| `stargazing_spots.json` の `lpi`/`mpsas`/`bortle_approx`(`spots` 146件) | `classify_site_darkness.py`・`merge_external_spots_20260907.py`(書き込み)、`explore_hoshibiyori.py` `_build_site`(`lpi_precomputed`→夜景系の別枠)、`skyguide/build.py`・`skyguide/render.py`(星空ガイドの見出しに「光害 LPI x / mag/arcsec²」)、`scripts/extract_sky_guide_sample.py` | 地点ごとの事前計算値 |
| `light_pollution_computed`(全897件) | `stargazing_spots.json` のみ(真偽のフラグ) | 計算済みの目印。読む側のコードは見当たらない(要確認) |
| `site_type`(`dark_sky`/`night_view`) | `explore_hoshibiyori.py` `_build_site`、`generate_report.py`(夜景系の別枠) | **LPI 閾値で分類した結果**(間接的に Lorenz 氏由来) |
| `stargazing_spots.bm.json` の `lpi` | LP1 で追加したファイル | **突き合わせ用に既存の lpi を写している**(新しいファイルにも Lorenz 氏由来の値が入っている) |
| `step3_light_pollution/light_pollution.py`(`LightPollutionTileStore`、取得・キャッシュ・ボートル近似) | `explore_hoshibiyori.py`・`generate_report.py`(import と `make_lp_store("legacy")`)、`classify_site_darkness.py`、`merge_external_spots_20260907.py`、`static_ranking.py`、`run_5points.py` | 実行時のLPI取得(通信あり、`tile_cache/`) |
| `LPI_THRESHOLD`(5.0) | `explore_hoshibiyori.py`、`generate_report.py`(表示)、`classify_site_darkness.py` | 足切り・分類の閾値。実地の成功・失敗例に基づく |
| 通し実行の LPI 表示 | `generate_report.py`(夜景系の別枠 `光害LPI`、フッターの出典)、`skyguide/build.py`(星空ガイドのフッターの出典「David Lorenz 氏」) | 画面表示 |
| 実効的な空の明るさ(`combine_sky_brightness(mpsas, ...)`、月込み) | `explore_hoshibiyori.py`→`generate_report.py`の候補カード、`scripts/report_courses.py`・`weekend_page.py`(HTMLから読む) | **mpsas(LPIからの換算)が入力** |
| README の出典表の行・構成表 | `README.md` 25・63・159・182 行 | 出典・説明 |
| テストのフィクスチャ・見本 | `tests/fixtures/sky_guide/*_data.json`(`lpi`/`mpsas`を含む)、`docs/examples/senjogahara_sky_guide_20261009.html`・`*_commentary*.json`(公開された見本に LPI の値と Lorenz 氏の出典) | 星空ガイドの回帰テスト・見本 |
| 変更しないバックアップ | `stargazing_spots.json.bak_*.json`(`.gitignore` 済み・手元のみ) | 旧データのコピー(追跡されていない) |
| LP2 で足したもの | `bm_threshold.py`・`bm_disagreements.py`・`compare_lp_sources.py`・`tests/test_lp_source.py` | **legacy の `lpi` を読む**(閾値の件数合わせと比較のため)。旧データを外す前に、件数 N=141 を固定値に置き換える必要がある |

### 4-2. 外すと何が壊れるか

- **探索・レポートの既定動作**(`legacy` の足切りとスコア減点、`site_type`、夜景系の別枠): 入力が無くなるので、先に既定を `bm` に切り替える必要がある。切り替えると、候補カードの「実効的な空の明るさ(mag/arcsec²)」が消える(bm には mpsas が無い)。
- **`scripts/report_courses.py` と `scripts/weekend_page.py`**: HTML の「実効的な空の明るさ」を正規表現で読むため、bm のレポートでは動かない(構造違い)。表記か読み取りの変更が要る。
- **星空ガイド**(`skyguide/build.py`・`render.py`): 見出しの光害の欄(LPI・mag/arcsec²)と、`spot` の `lpi`/`mpsas` を読む。値が無いときの描画(`lpi` が None なら欄を省く)は既にあるが、必須要素の検査・テストのフィクスチャは要確認。
- **テスト**: `tests/test_lp_source.py`(141件の再現)、`tests/fixtures/sky_guide/*_data.json`、星空ガイドの見本の回帰テスト(`docs/examples/` は「読み取り専用」の運用)。
- **`classify_site_darkness.py`・`merge_external_spots_20260907.py`・`static_ranking.py`・`run_5points.py`**: Lorenz 氏のタイル取得に依存する単発スクリプト(再実行しなければ壊れない。削除するか、bm に書き換える)。
- 月の影響を等級で表示する機能が事実上無くなる(`moon_brightness.combine_sky_brightness` は背景の等級が必要で、bm には較正された等級が無い)。代替(月相・月高度の表示のみ等)は本人が決める。

### 4-3. 外す手順(案。順序が重要)

1. **本人が決める**: 既定を bm にするか、LPI の閾値(5.0)に対応する閾値(暫定 ALR 10.66)をどう確定するか(実地の成功・失敗例の再確認、`LPI_THRESHOLD` の経緯参照)。
2. `--lp-source` の既定を `bm` に変える(`explore_hoshibiyori.py` / `generate_report.py`)。`report_courses.py`・`weekend_page.py`・星空ガイドを bm の表記に対応させる。実効的な空の明るさの代替表示を決める。
3. 件数 N=141 と閾値の根拠を固定値(定数・文書)にして、`bm_threshold.py`・`bm_disagreements.py`・`tests/test_lp_source.py` が `stargazing_spots.json` の `lpi` を読まないようにする。
4. `stargazing_spots.json` から `lpi`/`mpsas`/`bortle_approx`/`light_pollution_computed` を削除し、`site_type` を ALR で引き直す(**一括編集の前に `.bak_*` を取る**)。`stargazing_spots.bm.json` からも `lpi` を外す(`annotate_spots_bm.py` の `KEEP` から `lpi` を除く)。
5. `light_pollution.py`・`LightPollutionTileStore` の import と、`classify_site_darkness.py`・`merge_external_spots_20260907.py`・`static_ranking.py`・`run_5points.py` を削除または書き換え。`.gitignore` の `tile_cache/`、`scripts/check_setup.py` の `tile_cache` の項目、`LPI_THRESHOLD` を整理する。
6. README の出典表の Lorenz 氏の行・構成表・実行時間の記述、`generate_report.py` と `skyguide/build.py` のフッター、`docs/sky_guide_style.md` の出典を更新する。CLAUDE.md の「光害データ取得に関する注意」を過去の経緯として残す。
7. テストのフィクスチャ(`tests/fixtures/sky_guide/*_data.json`)と `docs/examples/` の見本から LPI を外すかどうかを決める(見本は読み取り専用の運用のため、別の方針が要る)。
8. 全テストと、bm でのレポート生成の通し実行を確認する。

### 4-4. 切り替え時に対応が必要な項目(公開リポジトリに Lorenz 氏由来の値が入っている点)

**現在、公開リポジトリには Lorenz 氏由来の値が次の場所に入っている**(いずれも追跡されている):

1. `stargazing_spots.json` の `lpi`/`mpsas`/`bortle_approx`(`spots` 146件)と、それから導いた `site_type`。
2. `stargazing_spots.bm.json` の `lpi`(LP1 で追加したファイル。**新しく増やしたのは LP1 の私の作業で、突き合わせのための写しだった**。今後は外すのが望ましい)。
3. `tests/fixtures/sky_guide/*_data.json` と `docs/examples/senjogahara_*`(星空ガイドの見本・回帰テストの入力に LPI・mpsas と Lorenz 氏の出典)。
4. `light_pollution.py` と、その結果を使う各スクリプト(コード自体は取得手順であり、値ではない)。
5. **git の履歴**: 上記は過去のコミットにも残る。ファイルから消しても履歴には残る。履歴の書き換え(公開済みの `ktakemaru/hoshibiyori` の履歴の改変)は破壊的で、**本人の明示的な判断が要る**(この計画には含めていない)。
6. 著者への利用可否確認が未実施のまま、READMEに「公開サービスへ組み込む前に確認が必要」と明記している(現状は個人の検証目的の低頻度アクセス)。切り替えるなら、2・3・5 の対応方針(値だけ外すか、履歴まで扱うか)を決める。

## 5. 本人が決める点(続きの作業を反映)

1. **bm を既定にするか、いつ切り替えるか**。切り替える場合、仮閾値 ALR 10.66(件数合わせ)を実地の成功・失敗例で確かめるか。
2. 実効的な空の明るさ(月込み)を失うことの代替(月相・月高度の表示など)。
3. 公開リポジトリの Lorenz 氏由来の値の扱い(第4-4節の1〜6。特に git 履歴の扱い)。
4. 近日中(MSM圏内)の比較は、今回は候補が0件で実測できていない。雲の条件が満たされる夜がある日に、`compare_lp_sources.py` を再度走らせるか。

## 6. メモリ停止の調査(続きの作業・手順1)

**結論: 比較スクリプトはメモリを多く使わない。停止の原因は、スクリプト自身ではなくシステム全体のメモリ逼迫と考えられる(確証ではない)。**

- 環境: 物理メモリ 7.9GB、調査開始時の空きは約 2.0GB(`claude` 3プロセス計約1GB、メモリ圧縮約1GB、メールソフト・ウイルス対策・ブラウザ等が常駐)。
- 測定方法: `scripts/measure_peak_memory.py`(子プロセスの PeakWorkingSetSize / PeakPagefileUsage を0.2秒ごとに読む。最初は `py` ランチャーの子を測って10MBと小さすぎたため、実体の `python.exe` を直接指定して測り直した)。
- 実測(`compare_lp_sources.py`、主軸のみ):

| 対象 | ピーク物理メモリ | ピークコミット | 所要 |
|---|---|---|---|
| 6地点・1夜 | 54MB | 172MB | 19.6秒 |
| 24地点・2夜 | 59MB | 177MB | 54.3秒 |
| **146地点・全夜(本番)** | **83MB** | **199MB** | **838.8秒** |
| `generate_report.py`(legacy、146地点) | 95MB | 213MB | 708.2秒 |
| `generate_report.py --lp-source bm` | 101MB | 215MB | 663.9秒 |

- 地点数に対するピークの伸びは約0.2MB/地点で、**メモリが地点数に比例して膨らむ様子はない**(6→24→146地点で54→59→83MB)。
- 停止された最初の実行は、**参考候補(OSM展望データ751件)を含む全897件**が対象だった(`generate_report.py` は主軸146件のみ)。897件の外挿は約230MBで、これも大きくない(外挿であり実測していない。897件の実行はしていない)。
- 停止された2件のうち1件は、**ファイルの出現を待つだけの `until ... sleep` のシェルループ**だった。これはほぼメモリを使わない。したがって停止は「そのスクリプトがメモリを食った」ではなく、**システム全体が逼迫していたときに、バックグラウンドコマンドがまとめて停止された**という説明が最も整合する。
- 直したこと: 原因がスクリプトのメモリ消費ではないため、メモリ削減の修正は不要と判断し、**入れていない**。代わりに、(1) 比較スクリプトの既定の対象を `generate_report.py` と同じ**主軸146件のみ**に揃えた(参考候補を含めるのは `--include-reference`。実行時間・通信を無駄に増やさないため)、(2) `--sites-limit`/`--nights-limit` を足した。
- 注意: 空きメモリが約2GBの環境で、他のアプリを多く開いた状態では、長いバックグラウンド実行が再び停止される可能性がある。

## 7. 手順3: legacy と bm の並べ比較(実測)

実行: `compare_lp_sources.py`(主軸146件)。天文計算と雲量取得は1回だけで、光害の入力だけを切り替える。2026-10-23 夜に実行。

- **近日中(MSM圏内)**: 今日の候補夜(MSM圏内)は1夜で、雲フィルタを通る組み合わせが **0組**(視界遮蔽雲量30%以下が連続1時間以上の晴れ間なし)。したがって第3段階以降は legacy・bm とも0件で、**近日中の比較は実測できていない**(気軽コースの気象メモも「条件を満たす組み合わせは0/110件」)。
- **見込み(ECMWF圏内、6夜: 10/31〜11/5)**: 月・地形・光害の決定論的条件を満たす組み合わせは legacy・bm とも **690件**(雲量は足切りに使わない設計)。
  - 両方に入る684件。**legacyだけ**に入る6件=堂平天文台(6夜)、**bmだけ**に入る6件=富士山吉原(6夜)。手順1の食い違い2件がそのまま全夜に出た。
  - 主要候補の上位10件の重なりは **6件**(順位は変わる)。
  - 光害の足切りで落ちた(雲フィルタを通った組み合わせのうち)件数は両モードとも0(近日中の候補自体が無いため)。

上位10件の入れ替わり(見込み。スコアは両モードで尺度が違うため順位で比べる):

| 順位 | legacy(LPI) | bmでの順位 | bm(ALR) | legacyでの順位 |
|---|---|---|---|---|
| 1 | 11/5 八丈富士 | 1 | 11/5 八丈富士(ALR 0.17) | 1 |
| 2 | 11/5 白雲台 | 2 | 11/5 白雲台(0.30) | 2 |
| 3 | 11/5 白山 | 12 | 11/5 佐渡島・白木峰展望台(0.33) | 8 |
| 4 | 11/5 奥只見ダム | 11 | 11/5 能登半島・白米千枚田(0.37) | 6 |
| 5 | 11/5 石廊崎 | 8 | 11/5 柳田星の観察館満天星(0.53) | 16 |
| 6 | 11/5 能登半島・白米千枚田 | 4 | 11/5 ドンデン高原(0.27) | 7 |
| 7 | 11/5 ドンデン高原 | 6 | 11/4 八丈富士(0.17) | 19 |
| 8 | 11/5 佐渡島・白木峰展望台 | 3 | 11/5 石廊崎(0.85) | 5 |
| 9 | 11/5 黒部峡谷(欅平) | 22 | 11/5 見附島(0.44) | 41 |
| 10 | 11/5 上高地(河童橋) | 19 | 11/5 能登・ヤセの断崖(0.75) | 25 |

- legacy の上位10件から外れたのは 白山・奥只見ダム・黒部峡谷(欅平)・上高地(河童橋)(いずれも bm では10〜22位)。bm で新しく入ったのは 柳田星の観察館満天星・見附島・能登・ヤセの断崖・11/4の八丈富士。日本海側・離島(ALRが小さい地点)が上がり、山間部が下がる傾向(LP1の検証6-1と同じ向き)。
- 上位2件(八丈富士・白雲台)は両モードで一致。
- 重要な注意: 見込みは雲量を足切りに使わない設計のため、この比較は**光害・地形・月だけの違い**を表す。天気を含めた結果の違いは、近日中の候補が出る日でないと見えない。

## 8. 手順3: `generate_report.py` の通し実行

| モード | 結果 | 所要時間 | ピーク物理メモリ | 出力 |
|---|---|---|---|---|
| legacy(引数なし) | **成功(終了コード0)** | 11.8分(実測708秒) | 95MB | `report.html` |
| `--lp-source bm` | **成功(終了コード0)** | 11.1分(実測664秒) | 101MB | `report_bm.html`(`report.html` は無変更) |

- どちらも失敗セル0件(0.0%)、候補地点146件、MSM圏内1夜・ECMWF圏内8夜。legacy は Open-Meteo API 24回(キャッシュヒット2370回)、bm は API 0回(キャッシュヒット2394回。legacy の直後でキャッシュが温まっていたため)。
- 見込み(ECMWF)の条件を満たす組み合わせは両モードとも **932件**(近日中は0件)。
- bm の実行ログに、光害の入力・仮閾値(`ALR<=10.66`)・出力先が出る。第3段階の判定の表記も `ALR<=10.66(仮閾値・相対指数)` に切り替わる。
- 近日中の候補が0件だったため、**実レポートの候補カード(bm の ALR 表記)は今回は生成されていない**。カードの描画と解析は合成データのテスト(第9節)で確認した。
- ひまわり: 3コマ・タイル4/4枚を取得(どちらも)。

## 9. 手順2: `report_courses.py` と `weekend_page.py` の bm 対応

- `--lp-source legacy|bm`(既定 legacy)を追加。bm は既定で `report_bm.html` を読み、カードの「光害(相対指数)  ALR x.xx(主軸の地点のうち暗い方から N%)」を解析する。等級(mpsas)は無い。
- `report_courses.py`: bm のとき JSON に `lp_source: "bm"`・`lp_note`、カードに `alr`・`alr_rank_pct`(`effective_mpsas` は無い)。テキスト出力に相対指数の注意書き。legacy のレポートに bm、bm のレポートに legacy の指定をすると、「`--lp-source …` を付けてください」と案内して終了コード3。
- `weekend_page.py`: bm のカード・全候補の一覧表を ALR で表示し、冒頭に相対指数の注記(「空の明るさ(mag/arcsec²)は表示していません」)。フッターはレポートのもの(Black Marble の出典・引用)をそのまま使う。出力名は既定で `weekend_stargazing_<日付>_bm.html`(legacy と別名)。解説JSONの verdict の機械照合は、bm では「N.NN mag」を書けないとし、ALR の値を候補と突き合わせる(legacy のレポートで ALR を書くとエラー)。
- **legacy の出力は変わっていない**: 旧版(`8921b0d`)と新版で、`weekend_page.render_page` の HTML・`report_courses` の JSON・テキストが md5 で一致。
- テスト: `tests/test_lp_source_scripts.py` 11件(bm のレポートは `generate_report.render_html(lp_source="bm")` の実際の描画関数で作る)。全体: `Ran 429 tests` / `OK (skipped=3)`。
- 実レポート(`report_bm.html`、候補0件)で `report_courses.py --lp-source bm` を実行し、候補0件の場合も解析できて終了することを確認した(カードがある場合の解析は合成データのテスト)。

## 10. `git push` する前に確認すべきこと(3点以内)

1. `stargazing_spots.bm.json` に Lorenz 氏由来の `lpi` の写しが入っていること(第4-4節の2)を承知のうえで push するか。
2. CI(`windows-latest`)で `unittest discover` が通ること(新規テストは `stargazing_spots.json` と `skyglow_bm_2025.npz` を読む。どちらも追跡されている)。
3. 近日中の候補が出る日の bm レポート(`report_bm.html` のカード表示)を、push 前に一度目視で確認したい(今回は候補0件で実カードは未確認)。
