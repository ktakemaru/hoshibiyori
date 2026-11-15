# Changelog

このファイルは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式に従います。
ここに書くのは、実際に main にマージされた変更だけです。

## [Unreleased]

### Added
- **探索結果の JSON 出力(`explore_hoshibiyori.py --json-out <ファイル>`)**: ビヨリコンシェルなどが探索結果を機械的に読めるよう、スキーマ `hoshibiyori-explore/1`(`schemas/hoshibiyori-explore.schema.json`)の JSON を書き出す。近日中の候補(`FinalCandidate`)と見込み(`OutlookCandidate`)を全件(画面の上位N件で切らない)、データクラスの全項目に `score_kind`(`final`/`outlook`。式が違い絶対値を比べられない)・主要/参考・画面と同じ順位を付けて入れ、候補の夜(MSM/ECMWF の別つき)・使った閾値(コードの定数から)・基準地点・地点の件数・取得の集計(失敗セルは件数と理由の種類だけ)・版と commit も入れる。時刻はオフセットつき、欠損・NaN は `null`、数値は丸めない。終了コード0のときだけ一時ファイル経由で書き(2のときは書かず既存のファイルにも触れない)、最後に「探索結果の JSON を書きました: <パス>」を1行出す。付けないときの画面の出力・順位・終了コードは変わらない。`scripts/measure_explore.py` に `--json-out`(そのまま explore に渡す)。星空・星座モード(`--target stars`)では、このモードがスコアを順位に使わないため `finals`・`outlooks` の `score` を `null` で出し、`notes` に「星空・星座モードでは score を使いません(順位は rank を見てください)。」を足す(天の川モードは数値のまま)

### Fixed
- **`scripts/report_courses.py`・`scripts/weekend_page.py` が星空・星座モードのレポート(`report_stars.html`)を読めなかった**: 星空・星座モードのカードにはスコアのバッジと「狙い目」が無いため、「バッジ「score」が無い」で終了コード3になっていた。レポートのヘッダーの「星空・星座モード」でモードを見分け、このモードではスコアと狙い目を `null`(0 や推測で埋めない)、カードの「晴れ間 N時間」を `clear_hours` として読む。`report_courses.py` の出力(テキスト・JSON)は、このモードのときだけ「モード: 星空・星座モード ・ 天の川は対象外」の行と `"target": "stars"` を足し、スコアと狙い目の代わりに晴れ間を出す。`weekend_page.py` は、このモードではカードのスコアのタグと一覧表のスコアの列を出さず、見頃に晴れ間を出し、解説の照合で狙い目の代わりに晴れ間の時間を使う。両方に `--target {milkyway,stars}`(`stars` なら既定の入力を `report_stars.html` にする。レポートのモードと違えば終了コード3)を足した。天の川モードの出力・終了コード・今日のレポートかの確かめ・解説の数値の照合は変えていない

## [1.1.0] - 2026-11-15

星空・星座モード(`--target stars`)を追加した版。
待ち時間を短縮し(薄明・月の時刻の格子化と保存、まとめ計算、接続の使い回し)、Open-Meteo の利用上限(429)への対応を加えた。

### Added
- **星空・星座モード(`--target stars`)**: `explore_hoshibiyori.py` と `generate_report.py` に `--target {milkyway,stars}` を追加(既定は `milkyway`で従来どおり)。`stars` では銀河中心の高度・方角・地形(稜線)の条件を使わず、視界遮蔽雲量・月・光害(ALR)・夜景系除外・暗い時間帯で候補を選ぶ。順位は晴れ時間 → 平均雲量 → ALR → 月の影響が小さい時間(見込み側は雲を使わないため ALR → 月の影響が小さい時間)。レポートは `report_stars.html` に出力(`report.html` は上書きしない)し、見出しに「星空・星座モード」「天の川は対象外」を明記、「この時期の見どころ」から銀河中心を外す。`milkyway` の候補が5件未満のときは `--target stars` の案内を1行出す。
- **薄明・月の時刻を先に計算するコマンド** `scripts/warm_astro_cache.py --days 30`: 登録済みの全地点の0.25度格子(897地点 → 139セル)と基準地点について、今日から N 夜分を計算して保存する(通信しない。1夜ごとに保存するので途中で止めても大丈夫)

### Changed
- **薄明・月の時刻を0.25度格子の代表点で計算し、結果を保存する(精度が変わる変更)**: 本人の決定(撮影者には薄明の分単位の精度より待ち時間が重要)により、`explore_hoshibiyori.py`・`generate_report.py` の天文薄明・無月時間帯を、地点ごとではなく ECMWF と同じ0.25度格子の代表点で「セル×夜」1回だけ計算して同じ格子の地点で使い回し、結果を `step1_astronomy/astro_cache/`(データ領域の下、git管理外)に保存して次の実行から読むだけにした(`astro_grid_cache.py`)。計算の条件(格子の刻み・月の判定の閾値・サンプルの間隔・天体暦・保存の形式の版)が違えば保存済みは使わず、7日より前の夜は読み込みのときに消す。基準地点(石廊崎)は座標を丸めずに保存する。対象天体の方位・高度、雲量・光害・地形は地点ごとのまま。ずれの実測(全897地点 × 6夜): 薄明の時刻は最大0.61分(95%点0.5分)、無月時間帯の開始・終了は95%点0.5分で、0.22%(5,382件中12件)は判定の刻み(15分)の境目で15分ずれた。主要146件の固定キャッシュでは候補の顔ぶれ・上位20件は同じ(stars の僅差の順位が入れ替わる)。時間(固定キャッシュ・通信なし・主要146件、2回測った範囲): stars は地点ごと 46〜147秒 → 保存なし 30〜85秒 → 保存済み 1.2〜3.1秒、milkyway は 73〜212秒 → 55〜61秒 → 27〜50秒。**`--astro-grid site` で従来の地点ごとの計算に戻せる**(出力は変更前と同じ。保存は読まない・書かない)。画面の最初に「[天文計算] 薄明・月の時刻は0.25度格子の代表点で計算(N地点 → Mセル)」、最後に「天文計算のキャッシュ: 計算 N 件 / 保存済みを使用 M 件」を出す。`scripts/measure_explore.py` に `--astro-grid`・`--astro-cache-dir`。詳細は `docs/astro-grid-cache-report.md`
- **Open-Meteo とひまわりの取得で接続を使い回す**: `step5_cloud_forecast/cloud_forecast.py` の `_fetch_hourly_detailed` と `himawari_image.py` の `_http_get` が、毎回新しい接続を張る `requests.get` から、プロセス内で1つずつ持つ `requests.Session`(最初の通信のときに作る)に変わった。理由: ビヨリコンシェルの実測で、GitHub のマシンから api.open-meteo.com へ新しい接続を張ると60回中11回が TLS の途中で止まり(20秒の打ち切り)、1本の接続を使い回すと60回中0回だったため(ヤマビヨリ v1.9.1 と同じ考え方)。URL・パラメータ・User-Agent・キャッシュ・再試行・打ち切り・429/4xxの扱い・終了コード・レポートの中身は変えていない
- **Open-Meteo の利用上限(429)の種類で扱いを分ける**: 429 の本文の `reason` を読んで画面に出し(JSON でなければ本文の先頭200文字)、`minutely`・`hourly`・`daily`・`unknown` に分ける。`minutely`(1分の上限)は「1分の上限のため65秒待ちます(n/5)」と出して65秒待ち、同じセルを取り直す(1回の実行で合計5回まで。6回目は従来どおり中止)。`hourly`・`daily`・`unknown` は従来どおり中止(`OpenMeteoDailyLimitError`、終了コード2)で、中止の文に種類と reason を入れる。例外の名前は互換のためそのまま。ひまわりの 429 は変えていない
- **Open-Meteo への通信の間隔の調整**: 1回の通信の重さを `max(1, 変数の数/10) × max(1, 予報日数/14)` と見積もり(探索の1回は約2.4〜2.6)、直近60秒の重さの合計が `cloud_forecast.PACING_LIMIT_PER_MINUTE`(300 = 1分の上限600の半分)を超えないよう、通信の前(再試行も含む)に必要なだけ待つ。キャッシュヒットは数えない。待ちが起きたときだけ、集計の行の後ろに `… / 間隔の調整 N 秒` を、実行時間の内訳に「通信・間隔の調整・それ以外」を出す(待ちが無いときの画面の出力は従来と同じ)。理由: 天文計算が速くなって通信が間をあけずに続き、2026-11-13 の実行で253回目に 429 で中止したため
- **再試行を画面に出す**: 接続エラー・408・5xx で再試行するたびに、例外の名前・待つ秒数・何回目かを1行出す(回数・間隔・打ち切りは変えていない)
- `scripts/measure_explore.py` の秒数の JSON に、再試行・間隔の調整・429 の種類と reason・失敗セルを足した
- **通信時間の表示**: 実行の最後の「予報取得の集計」の行の後ろに、Open-Meteo の通信にかかった秒数(再試行と再試行の間の待ちを含む)・失敗した試行にかかった秒数・再試行の回数を足した(例: `… / 通信 132.4 秒(うち失敗の待ち 40.2 秒・再試行 2 回)`)。`explore_hoshibiyori.py` と `generate_report.py` は最後に、全体の秒数と通信以外の秒数(全体 − 通信)を1行で出す。画面の表示だけで、レポート(HTML)には出さない
- **通信以外の処理時間の短縮(探索)**: 出力(画面の文・候補・順位)を変えずに、`explore_hoshibiyori.py` の天文計算と雲量の集計を速くした。①月の影響の判定(`longest_negligible_window`)で、15分刻みの時刻を1つずつ `compute_moon_position` に渡していたのを、同じ式で時刻の配列を1回で Skyfield に渡す ②同じ格子セルの雲量の時系列を、地点×夜ごとに時刻の辞書へ直し直さない(`elevation_cloud.get_level_cloud_forecast`。キャッシュのキー・有効期限は同じ) ③見込み(`stage_outlook`)で、光害の足切りを天文計算より先に行う。実測(固定した雲量キャッシュ・通信なし、2026-11-12、`--target stars`): 主要146件で 690.2 秒 → 107〜144 秒、全地点から10件おき+石廊崎の91地点で 541.5 秒 → 62〜90 秒(ぶれは同じ PC のメモリの逼迫などによる)。全897地点での前後比較は、実行がメモリ不足で止められたため行っていない。計測用に `scripts/measure_explore.py` を追加(既定の動きは変えない)。詳細は `docs/astro-speedup-report.md`
- `plugin.json` の `version` を 1.1.0 に
- 取得処理の User-Agent のバージョンを 1.1.0 に

### Fixed
- **基準地点の予報が取れないと、夜が全部見込み側に回っていた**: MSM の範囲内かを決める基準地点(石廊崎)の MSM のセルが取得の失敗で空のとき、「MSM の範囲の外」と同じに扱われ、MSM の夜が0夜になっていた(2026-11-13、接続の切断で石廊崎のセルが取れなかった実行)。いまは「基準地点の予報を取得できなかったため中止します」と出して終了コード2で終える(`explore_hoshibiyori.py`・`generate_report.py`。レポートは更新しない)。取得はできたがその夜が範囲の外の場合は従来どおり

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
- 以前の光害データ由来の値: `stargazing_spots.json` の光害の4項目、テスト用データ・ログ・検証記録の地点別の値、星空ガイドの見出しの光害欄
- 以前の光害データの取得処理(`step3_light_pollution/light_pollution.py` とタイルのキャッシュ処理)と、それに依存するスクリプト(`static_ranking.py`、`merge_external_spots_20260907.py`、`step3_light_pollution/run_5points.py` ほか、比較・検証用のスクリプト)
- 星空ガイドの見本 `docs/examples/senjogahara_sky_guide_20261009.html` と、見本からゴールデンを抽出する `scripts/extract_sky_guide_sample.py`(回帰テストは抽出済みの `tests/fixtures/sky_guide/` で続ける)
- 開発時の作業報告書(リポジトリ外で保管)。結論は `CLAUDE.md` に要約した

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
