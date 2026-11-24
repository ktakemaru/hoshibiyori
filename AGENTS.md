# hoshibiyori — AI エージェント向け共通ルール(Codex / Claude Code)

星景写真撮影に特化した天気予報プロジェクト。設計の経緯・検証データ・既知の制約は `CLAUDE.md`(開発ログ兼仕様書、約84KB)にある。
このファイルは短い共通ルールだけを置く。**食い違いを見つけたら黙って直さず、ユーザーに報告する。**

## 1. 完了条件
- コードを変更したら、完了報告の前に `py -X utf8 -m unittest discover -s tests` を実行し、最後の行(`OK` / `FAILED` と件数)をそのまま報告する。
- 既存テストの期待値を書き換えない・削除しない・スキップしない。
- 機能を足すときは、既定の動作(引数なしの結果)を変えない。

## 2. 最初に読むもの(変更の種類 → `CLAUDE.md` の節)
| 変更 | 読む節 |
|---|---|
| 雲量判定(`elevation_cloud.py`) | 「標高考慮の雲量判定」「観測者に寄り添う」 |
| スコア・閾値・探索の流れ | 「探索モードの『見頃』時間帯算出…」(スコア式の既知の癖を含む) |
| 取得失敗・終了コード・ひまわり | 「yamabiyoriとの同期(2026-10-12)」 |
| 地形(DEM)・光害データ | 「DEM(標高)データ取得に関する注意」「光害データ(Black Marble 由来の指数)」、`step3_light_pollution/METHOD.md`・`UPDATE.md` |
| 候補地点データ・重複削除 | 「候補地点データの現状」「今後の課題」 |

## 3. 独立性と観測者の視点
- 姉妹プロジェクト yamabiyori(`C:\mountain-weather\`)のコードを参照・import・コピーしない。`CLAUDE.md`「プロジェクトの独立性」の例外は、その都度ユーザーが承認した前例であり、恒常的な許可ではない。必要が生じたらその都度ユーザーに確認する。
- 評価は**星空撮影者の目線**(地表から見上げる頭上の雲・光害・月・地形)。yamabiyori の湿潤層ルール・降水判定・危険信号・山頂雲量の較正表など登山者向けの評価軸を持ち込まない(「観測者に寄り添う」節)。

## 4. セットアップ(通信しない確認から)
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # PyPI へ通信する。ユーザー承認後に
.\.venv\Scripts\python.exe scripts\check_setup.py                # 通信しない。--network のときだけ Open-Meteo に1リクエスト
```
- Skyfield の暦 `step1_astronomy/de421.bsp`(約17MB)は、無い場合の初回実行時に自動ダウンロードされる(JPL へ通信)。単体テストには不要。
- Playwright は任意(無ければ天気図セクションを省略)。
- Python は 3.15 RC で通し実行を確認。3.13 は依存の導入・`check_setup.py`・単体テストまで確認(通し実行は未確認)。
- 保存先の切り替え(任意): 環境変数 `HOSHIBIYORI_DATA_DIR` を設定すると、キャッシュ・天文暦・生成物(`report.html`・`out/`・`weather_map_commentary.json` など)の書き込み先がそのフォルダになる(リポジトリと同じ相対構成。`hb_paths.py` が決める)。**未設定または空なら従来どおりリポジトリ直下で、動作は変わらない。** 読み取り専用の静的データ(`areas.json`・`stargazing_spots.json`・horizon CSV など)は常にリポジトリ側。PowerShell の例: `$env:HOSHIBIYORI_DATA_DIR="C:\tmp\hb_data"`。`scripts/check_setup.py` が「データ領域」を表示する。

## 5. 実行(ユーザーが頼んだときだけ)

### 長い作業の前に伝える
- 30 秒以上かかる見込みの作業の前に、何をするかと時間の目安を 1 行で利用者に伝える。例: 「全 897 地点の星空の条件を調べます。6 分ほどかかります。」
- 伝えるのは、最初の長いコマンドを呼ぶ直前に 1 回だけ。途中の実況はしない。短い作業(30 秒未満)には出さない。
- 時間の目安は、下の表から引く。自分で見積もらない。表に無い作業・「未実測」の作業は「時間の目安はまだ測っていません」と言う。
- 条件で時間が大きく変わる作業(探索・レポートの生成)は、先に見積もりのコマンド(`--estimate`。通信しない)を実行して、その結果の時間を伝える。
- 終わったあとに「○分かかりました」と報告する必要はない。
- **選択肢を出すとき**(天の川モードか星空・星座モードか、など)は、選択肢ごとに時間の目安を添える。
- 30 秒は仮の値。

見積もり: `py -X utf8 explore_hoshibiyori.py --estimate`(`--target`・`--astro-grid` と併用可)、`py -X utf8 generate_report.py --estimate`。探索も計算もせず、天文計算の保存と雲量の保存(期限内)を読んで、4行を出して終了コード0で終わる。探索・レポートの生成は、始まりに同じ目安を標準エラーへ1行出す。

時間の目安の表(値は実測だけ。正本は `time_estimates.py` の `ESTIMATES` で、食い違うとテストが落ちる):

| 作業 | コマンド | 目安 | 出どころ |
|---|---|---|---|
| 探索・星空・星座モード・全897地点(保存が足りない) | `explore_hoshibiyori.py` `--target stars` | 約6分 | 2026-11-15、Windows・自宅回線、利用者の実測(360.9秒、通信あり・失敗0) |
| 探索・星空・星座モード・全897地点(保存がそろっている) | `explore_hoshibiyori.py` `--target stars` | 約10秒 | 2026-11-15、Windows・自宅回線、利用者の実測(10.1秒、通信0回) |
| 探索・星空・星座モード・全897地点・JSON つき | `explore_hoshibiyori.py` `--target stars --json-out …` | 約5分 | 2026-11-16、Windows・自宅回線、利用者の実測(通信617回) |
| 探索・星空・星座モード・全897地点・`--nights` 1夜・JSON つき(雲量の保存なし) | `explore_hoshibiyori.py` `--target stars --nights … --json-out …` | 約4分 | 2026-11-24、Windows、利用者の実測1回(243.1秒、API 456回・失敗0、天文計算の保存は14夜のうち4夜) |
| 探索・天の川モード・全897地点(保存が足りない) | `explore_hoshibiyori.py` | 未実測 | — |
| 探索・天の川モード・全897地点(保存がそろっている) | `explore_hoshibiyori.py` | 未実測 | — |
| レポートの生成・天の川モード・主軸146地点(保存が足りない) | `generate_report.py` | 未実測 | — |
| レポートの生成・天の川モード・主軸146地点(雲量が保存済み) | `generate_report.py` | 約2分 | 2026-11-15、Windows・自宅回線、利用者の実測(1.9分、通信0回) |
| レポートの生成・星空・星座モード・主軸146地点(保存が足りない) | `generate_report.py` `--target stars` | 未実測 | — |
| レポートの生成・星空・星座モード・主軸146地点(雲量が保存済み) | `generate_report.py` `--target stars` | 約21秒 | 2026-11-24、Windows、利用者の実測1回(20.9秒、API 0回) |
| 星空ガイド(数値JSON・描画) | `scripts/make_sky_guide.py`・`scripts/render_sky_guide.py` | 未実測 | — |
| コースの取り出し | `scripts/report_courses.py` | 未実測 | — |
| 週末ページ | `scripts/weekend_page.py` | 未実測 | — |
| 天気図・ひまわりの取得 | `step5_cloud_forecast/jma_weather_map.py` ほか | 未実測 | — |
| 薄明・月の時刻の先行計算 | `scripts/warm_astro_cache.py --days 30` | 未実測 | — |
| 単体テスト | `py -X utf8 -m unittest discover -s tests` | 約2分 | 2026-11-24、Windows、Claude Code の中で実測(658件で108.6秒) |

- `py generate_report.py`(引数なし): **Open-Meteo API 約220回(加えて気象庁へ、ひまわりの時刻一覧1回と赤外タイル最大12枚[3コマ×2×2、basetimeごとにキャッシュ]、天気図1セッション)**。所要時間の実測(2026-11-15、Windows、自宅回線): 主要146地点・天の川モードで雲量がキャッシュ済みなら約2分。**雲量のキャッシュが無い状態のレポート生成は 1.2.0 では未実測**。全897地点の探索(`explore_hoshibiyori.py`、星空モード)は Open-Meteo 約620回で、雲量のキャッシュが無い初回は約6分(通信617回)、同じ日の2回目は約10秒(通信0回)。固定の `report.html`(git管理外、.gitignore 済み)を上書きする。終了コード: 0=出力済み、2=失敗セル率20%以上・中止扱いの HTTP 429(下記)・基準地点(石廊崎)の MSM の予報が取得の失敗で空(`report.html` は更新しない)。429 は本文の `reason` で種類を分け、1分の上限(`minutely`)だけは65秒待って同じセルを取り直して続ける(1回の実行で合計5回まで。`grid_cache.MINUTELY_RETRY_WAIT_SEC`/`MINUTELY_RETRY_MAX`)。6回目と、`hourly`/`daily`/種類不明は中止して終了コード2。`explore_hoshibiyori.py` も同じ条件で終了コード2。
- ひまわりの「雲域の割合」(表示名は「雲域」)は、赤外の明るさの閾値(`himawari_image.py` `HIGH_CLOUD_BRIGHTNESS_THRESHOLD`)から出す参考値で、**閾値は暫定値**(晴れた夜は未較正)。スコア・足切りには使わない。
- 実行前に「所要時間・リクエスト数・書き込み先」を伝えて承認を得る。Open-Meteo の無料枠は同じ回線の他の利用と共有される。
- 長時間コマンドのタイムアウト対策(Windows の Codex で成り立つ方法)は**未確認**。確認できるまで、実行はユーザーに依頼するか、バックグラウンド実行+出力ファイルで行う。
- `explore_hoshibiyori.py` も引数なし(探索結果をコンソールに出す)。
- `explore_hoshibiyori.py --json-out <ファイル>`: 探索結果を JSON(スキーマ `hoshibiyori-explore/1`、`schemas/hoshibiyori-explore.schema.json`)で書き出す。近日中(`finals`)・見込み(`outlooks`)の候補を全件、閾値・夜・取得の集計・版と commit とともに入れる。終了コード0のときだけ書き(`fetch.status` が `ok`/`partial`)、2のときは書かず既存のファイルにも触れない。通信の量は付けないときと同じ。`--target`・`--astro-grid` と併用できる。
  - `scanned_nights`: 走査した全部の夜(日付順)。`selected`(候補の夜か)・`regime`(選ばれた夜だけ MSM/ECMWF)・`not_selected_reason`(`no_sunset_or_sunrise`/`no_astronomical_darkness`/`no_moon_free_window`/`not_in_top_n`)。スキーマの必須項目。
  - `site_id`(候補・一覧)と `site_index`(全地点の一覧: `site_id`・名前・`label`[見分けるための言い方]・市町村・緯度経度・主軸か参考か・リフト要): 同じ名前の地点が37組あるので、地点は名前でなく `site_id` で見分ける。
- `explore_hoshibiyori.py --nights 2026-11-28,2026-11-29`(夜の始まりの日付): 候補の上位6夜に入らない夜も雲量を調べ、`--json-out` の `requested_nights[]` と画面の数行に出す(候補の一覧・順位・`finals`・`outlooks` は変わらない。スコアは出さない)。**通信は増えない**(その回の通常の探索が取ったセルと期限内の保存だけを読む。取っていないセルの地点は `not_examined`)。「調べていない」(`window_kind: none`・`status: not_examined`)と「条件を通らなかった」(`status: failed`)を混ぜて答えない。`window_kind: dark` の夜は月が出ている(`moon` を添える)。`forecast_regime: ECMWF` の雲量は目安。
- 薄明・月の時刻は既定で0.25度格子(ECMWFと同じ)の代表点で計算し、`<データ領域>/step1_astronomy/astro_cache/`(git管理外)に保存して次の実行から読むだけにする(本人の決定、2026-11-13。地点ごとの計算との差は薄明で1分未満)。地点ごとの従来の計算に戻すのは `--astro-grid site`(explore・generate_report 共通。保存は読まない・書かない)。先に計算しておくのは `py -X utf8 scripts/warm_astro_cache.py --days 30`(通信しない)。
- ユーザーが「天の川にこだわらない」「星座」「冬」「明るい星・惑星を見たい」などと言ったら `--target stars`(星空・星座モード。銀河中心の高度・地形を条件にしない。出力は `report_stars.html` で `report.html` を上書きしない)を使う。天の川を撮るときは既定の `milkyway`。
- 「空の開け具合」(`sky_openness`)と「冬の天の川の帯」(`winter_milky_way`)は参考の情報で、順位・足切りには使っていない。「ECMWFだけの予報(目安)」の印の付いた夜は、雲量で足切りしていない。
- `report.html` は追跡しない。生成日時が今日でなければ答えに使わない。

## 6. 保護領域(ユーザーの明示的な指示と承認なしに変えない)
| 対象 | 場所 | 現在値・備考 |
|---|---|---|
| 視界遮蔽雲量の見上げ型ハイブリッド | `step5_cloud_forecast/elevation_cloud.py` | 全層雲量が主、気圧面は観測者より下の雲の差し引きのみ。API変数は `level_hourly_vars()` に一元化 |
| スコア式 | `explore_hoshibiyori.py` の `FinalCandidate.score` / `OutlookCandidate.score` | 近日中と中期見込みで式が異なり絶対値は比較不可 |
| 光害閾値 | `step3_light_pollution/lp_source.py` `BM_ALR_THRESHOLD`(と内部値の基準 `LP_INDEX_LIMIT`) | ALR 10.66(以前の判定で通った主軸の141件と同数が通る仮の値。日本未較正)。`LP_INDEX_LIMIT` 5.0 はスコアの光害減点の大きさを保つための規格化の基準 |
| 雲量閾値・最小晴れ間 | `CLOUD_OBSTRUCTION_THRESHOLD` / `MIN_CLEAR_WINDOW_HOURS` | 30.0% / 1.0時間 |
| 失敗セル率と終了コード | `step5_cloud_forecast/grid_cache.py` `FAILED_CELL_RATE_ABORT` | 0.20。0/2 の意味は上記(第5節) |
| 格子セルキャッシュとTTL | `grid_cache.py` `CACHE_TTL_SEC` | MSM 3時間 / ECMWF 6時間 |
| 候補地点データ | `stargazing_spots.json`、`curated_spots.json` ほか | 一括編集の前に必ずバックアップ(`.bak_*`)を取る |
| 重複削除30グループ | `step7_geocoding/pending_deletions_round2.json` | ユーザーの目視承認待ち。勝手に適用しない |
| 地点の ID(`stargazing_spots.json` の `id`) | `tests/fixtures/site_ids.json` | 一度決めたら変えない・使い回さない・地点を外したら欠番にする(fixture の `retired` に移す)。日本語の入った ID(`test:富士山頂` など)もそのまま使う |
| 地形データの無い地点の地平線の判定 | `explore_hoshibiyori.py` の `compute_target_window`・`stage3_direction_filter` | 天の川モードで、地形地平線のデータが無い地点は地平線を高度0°として判定する(0°より上のときだけ見える。新しい閾値は作らない)。2026-11-16 利用者承認 |

## 7. 外部サイトへのアクセスの節度
- タイル(DEM・ひまわり)・Black Marble の生データ・格子セルのディスクキャッシュを無効化しない。新規取得の小休止(`gsi_dem.py` `_POLITE_DELAY_SEC` など)を削らない。識別可能な User-Agent を維持する。
- Nominatim は1秒1リクエスト以下(`reverse_geocode.py` `MIN_REQUEST_INTERVAL_SEC`)。
- HTTP 429 で中止したら(1分の上限の65秒待ちはコードが自動で行う。それ以外の429と、待ちの回数の上限を超えたとき)、そのままユーザーに報告する。手で再実行を重ねる・別経路・リトライの連打・キャッシュの手作りで回避しない。通信の間隔の調整(`cloud_forecast.PACING_LIMIT_PER_MINUTE`)を削らない。
- 単体テストは通信しない(`requests.get` 等をモック)。テストのために実通信しない。

## 8. PowerShell の注意
- `python` は `-X utf8` を付ける(日本語出力の文字化け対策)。
- python の出力を `>` や `|` で受けない(PowerShell 5.1 は UTF-16/BOM になりうる)。ログが要るときは python 側でファイルへ書くか、`logs/` へ `Out-File -Encoding utf8` を明示する。
- venv は activate せず、`.\.venv\Scripts\python.exe` を直接呼ぶ。
- (yamabiyori の同種の注意を踏襲したもの。hoshibiyori の全スクリプトでの再現は未検証)

## 9. コミットと共有
- main へ直接 push しない(PR 経由)。GitHub の設定変更は個別に承認を得る。
- `git add -A` は使わず、ファイルを指定する。キャッシュ(`dem_cache/`・`blackmarble_cache/`・`cloud_cache/`・`weather_map_cache/`・`himawari_cache/`)、`*.bsp`、`.bak` 系をコミットしない。`.gitignore` は行末コメント非対応(コメントは独立した行に書く)。
- HTML を共有するときは、まずファイルを直接送る方法を案内する。

## 10. 星空ガイド(星空シミュレーター付き)
「◯◯の星空」「星空ガイド」と頼まれたら、**必ずシミュレーター付きのガイド**を作る。書き方は `docs/sky_guide_style.md`。
1. 数値JSON: `scripts/make_sky_guide.py --spot <地点> --date <夜の開始日> --json-out out/…_data.json`(既定は通信しない。数値は既存ロジックが計算する。**数値を自分で書かない**)
2. 解説JSON(`hoshibiyori-skyguide-commentary/1`)を書く。文中の数値は数値JSONの `events` と `frames` から取る。山名は `basis`(確認済み/推定)を付ける
3. 描画: `scripts/render_sky_guide.py --data … --commentary … --out out/…html`。`out/` に保存して場所を伝える。描画は解説の時刻の言い回し(「N時すぎ」等)を `events` と機械照合し、食い違いがあれば出力しない
   - 解説に書く高度・方位・方位表の稜線の仰角は `scripts/sky_lookup.py --data … --az 345 15` / `--time 21:40 --names アルタイル …` で引く(描画は数値の食い違いも既定で止める。警告だけにするのは `--warn-numbers`。規則は `docs/sky_guide_style.md`「数値の照合」)
- **HTMLは手で書かない**(テンプレートに2つのJSONを差し込む)。必須要素(シミュレーター・事実4項目・構図・山と方位の表・撮影メモ・出典と免責)が欠けるとエラー
- 通信が要る処理(`--cloud fetch --allow-network`)の前に、`--estimate` の結果と所要時間・リクエスト数の見込みを伝えて承認を得る
- 雲量は全天の平均で方角は分からない。取れない日付は省略でき、理由がページに出る
- `--no-check-text`(時刻の言い回しの照合を省く)は、ユーザーの明示的な許可なしに使わない

## 11. 「適した日と場所」を聞かれたとき
「直近14日間で星景撮影に適した日と場所は?」のような問い。流れは「月で時期を絞る → 雲量で場所を絞る(ここまでが `generate_report.py` の探索) → 候補の夜と地点で星空ガイドを作る(第10節)」。
1. 材料を決める
   - `report.html` の「生成日時: YYYY-MM-DD HH:MM JST」(ヘッダーの「対象天体: … ・ 生成日時: …」)が**今日**なら、それを読んで答えてよい。同じ日でも数時間以上経っていれば、近日分(MSM)の予報は更新されている可能性があると伝える。
   - 今日でない・`report.html` が無いときは、その内容で答えない。第5節の手順(所要時間・リクエスト数・書き込み先を伝えて承認を得る)で実行を頼む。実行をユーザーに任せるなら `py -X utf8 generate_report.py` を案内し、結果が出るまで日付や地点を断定しない。
   - 待つ間は `py -X utf8 scripts/moon_nights.py`(通信なし・数秒。`--start-date`・`--days`・`--spot`・`--json-out`)で月の条件だけは答えられる。雲量は未評価と断り、場所は断定しない。
2. 答え方
   - 候補は「日付・地点・見頃の時間帯・視界遮蔽雲量・光害」で示す。
   - 「星空撮影に適した日と場所は?」と聞かれたら、**気軽コースと硬派コースの両方**を最初に示す(片方だけで答えない)。材料は `py -X utf8 scripts/report_courses.py` の出力(通信なし。`--top`・`--json-out`・`--out`。今日の `report.html` でなければ終了コード2で止まり、構造が違えば3)。`report.html` を目視で読み写さない。
   - 各コースの上位3件を、日付・地点・見頃の時間帯・視界遮蔽雲量・光害(ALRと順位。日本で未較正の相対指数)・東京からの距離で示し、コース条件の違いを一言添える(気軽=東京から直線250km圏内で離島・本格登山・リフト要を除く / 硬派=距離・アクセスを問わず条件のみ)。
   - 順序は、近場・気軽を求めるなら気軽が先、遠征・ベスト・登山可を求めるなら硬派が先、どちらでもなければ気軽が先。
   - 候補が無いコースは、出力の理由(MSM圏内の夜が無い等)をそのまま伝え、空欄を埋めない。「気象メモ」(気軽コースの雲量の注記)があれば添える。
   - 答えたあと、選んだ(または筆頭を提案して承認された)地点と夜で、第10節の星空ガイドに進む案内を一言添える(下の3)。
   - 近日中(MSM)と中期見込み(ECMWF)はスコアの式が違い、絶対値は比べられない(第6節)。中期見込みの雲量は晴天率の参考表示で、足切りには使われていないと断る。
   - 雲量は全天の平均で、方角ごとの雲は分からない(第10節と同じ)。
   - 光害は Black Marble 由来のALR(日本で未較正の相対指数)。空の明るさ(mag/arcsec²)は無いので、順位・段階の目安としてだけ伝える。解説JSONの verdict に等級(N.NN mag)は書けず、ALR の値はレポートの候補と照合される。
   - 「今の時期の見どころは?」「流星群は?」と聞かれたら、今日のレポートの「この時期の見どころ」から答える(自分の知識で天体・時刻・極大の日を足さない)。基準の地点・平らな地平線の目安で、地形・雲を見ていないこと、星・星団の座標は星表と未照合の目安であることを添える(流星群の値は 2026-11-24 に Wikipedia「List of meteor showers」と照合済み)。流星群の出現数には「理想の条件での目安で、実際に見える数はこれより少ない。突発的な増減は予測できない」を必ず添える。月食・月と惑星の接近・ダイヤモンド富士は、まだ計算していないと言う。
3. 星空ガイドへ進む
   - ユーザーが選んだ(または筆頭候補を提案して承認された)地点と夜で、第10節の手順に進む。
   - `--spot` にはレポートに出た地点名をそのまま使う(`stargazing_spots.json` の name と同じ表記)。見つからないときは推測で置き換えず、そのままユーザーに報告する。
   - `--date` は「夜の開始日」(10/17の夜なら 2026-10-17)。
4. 雲量のキャッシュ
   - ガイドの雲量は既定で、有効期限内(MSM 3時間 / ECMWF 6時間)のキャッシュだけを使う。探索の実行から時間が経つと雲量が省略され、理由がページに出る。省略を「晴れ」と読み替えない。
   - 雲量を入れたいときは `--estimate` の結果と所要時間・リクエスト数を伝え、承認を得てから `--cloud fetch --allow-network` を使う(第10節と同じ)。
5. 数値の扱いは第10節のとおり(数値を自分で書かない)。
6. 「今週末(または◯日)の星空撮影に適した所を、HTMLで」と頼まれたら、`scripts/weekend_page.py` を使う(数値・表・カードはコードが作る。読み写さない)。
   - 手順: ①今日の `report.html` を確認(無ければ第5節)②天気図の取得と解説(第12節)③解説JSON(`hoshibiyori-weekend-commentary/2`: `verdict`[`title`/`body`/`tone`=good|neutral|warn、最大4件]と `extra_notes` のみ。`weather` 欄は廃止)を書く ④ `py -X utf8 scripts/weekend_page.py --commentary …` ⑤保存先を伝える。
   - 天気の概況は `weather_map_commentary.json`(schema /2、第12節)だけが情報源で、週末ページ側では書かない。有効(12時間以内・画像3枚が実在)かつレポートの天気図と取得時刻・画像が一致するときだけ本文と3枚の図を出し、それ以外は「天気図の解説は未更新のため表示していません」の一行(終了コード0)になる。②で第12節の更新をしてから実行する。
   - `verdict` の地点名・時刻(HH:MM)・件数・N時間・%・km・空の明るさは、レポートの候補データと機械照合され、食い違えば終了コード5。数値はスクリプト/`report_courses.py` の出力から取る。旧 `/1` の `weather` 欄は無視して警告する。
   - 解説は、公式の天気図・衛星画像の説明にとどめ、独自の予報(通過時刻の予測など)を書かない。解説の数値は `weekend_page.py` / `report_courses.py` の出力から取る(自分で書かない)。
   - 出力先(既定 `out/weekend_stargazing_<最初の夜>.html`)に同名のファイルがあると、上書きせず終了コード4で止まる。別名(`--out`)にするかユーザーに確認し、`--force` はユーザーの許可なしに使わない。終了コード: 2=古い/無い、3=構造違い、5=解説JSON不正。
   - 「アクセス要確認」の注記は `access_check_notes.json`(確認済みの事実ではない)。追加はユーザーが指示したときだけ。

## 12. 天気図の解説を更新するとき
レポートの地上天気図の解説は `weather_map_commentary.json`(リポジトリ直下、git管理外)から読む。schema `/2`・`based_on` から生成時刻まで12時間以内・`images` の3枚が実在、の3つが揃うときだけ表示し、そのときは気象庁へ取得に行かず、`images` の画像(解説の元にした図)を使う。揃わない場合(超過・未来・無い・壊れている・`/1`・画像が無い)は、従来どおり取得して画像だけを出し、解説は表示しない。
1. 天気図を取得する(`step5_cloud_forecast/jma_weather_map.py` を実行。`weather_map_cache/fetched_at.txt` に取得時刻が入る。気象庁へ通信する)
2. 取得した画像を見て、実況と+24h/+48hの高低気圧・前線の配置を事実として書く
3. 次の形で保存する。`images` は読んだ画像のパス(リポジトリ直下からの相対。絶対パスや `..` は無効、シンボリックリンクで外へ出るものも無効)
   `{"schema": "hoshibiyori-weathermap-commentary/2", "based_on": "<取得時刻 JST・タイムゾーン付き>", "text": "…", "images": {"now": "step5_cloud_forecast/weather_map_cache/….png", "plus24h": "…", "plus48h": "…"}}`
4. レポートを生成する
- 解説は公式の天気図の説明にとどめ、独自の予報(通過時刻の予測など)は書かない。
