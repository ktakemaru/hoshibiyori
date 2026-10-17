# hoshibiyori — AI エージェント向け共通ルール(Codex / Claude Code)

星景写真撮影に特化した天気予報プロジェクト。設計の経緯・検証データ・既知の制約は `CLAUDE.md`(開発ログ兼仕様書、約64KB)にある。
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
| 地形(DEM)・光害データ | 「DEM(標高)データ取得に関する注意」「光害データ取得に関する注意」 |
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

## 5. 実行(ユーザーが頼んだときだけ)
- `py generate_report.py`(引数なし): **10〜30分・Open-Meteo API 約220回**(候補146件で実測約21分。候補数に比例して増える)。固定の `report.html`(git管理外、.gitignore 済み)を上書きする。終了コード: 0=出力済み、2=失敗セル率20%以上または HTTP 429(`report.html` は更新しない)。
- 実行前に「所要時間・リクエスト数・書き込み先」を伝えて承認を得る。Open-Meteo の無料枠は同じ回線の他の利用と共有される。
- 長時間コマンドのタイムアウト対策(Windows の Codex で成り立つ方法)は**未確認**。確認できるまで、実行はユーザーに依頼するか、バックグラウンド実行+出力ファイルで行う。
- `explore_hoshibiyori.py` も引数なし(探索結果をコンソールに出す)。
- `report.html` は追跡しない。生成日時が今日でなければ答えに使わない。

## 6. 保護領域(ユーザーの明示的な指示と承認なしに変えない)
| 対象 | 場所 | 現在値・備考 |
|---|---|---|
| 視界遮蔽雲量の見上げ型ハイブリッド | `step5_cloud_forecast/elevation_cloud.py` | 全層雲量が主、気圧面は観測者より下の雲の差し引きのみ。API変数は `level_hourly_vars()` に一元化 |
| スコア式 | `explore_hoshibiyori.py` の `FinalCandidate.score` / `OutlookCandidate.score` | 近日中と中期見込みで式が異なり絶対値は比較不可 |
| 光害閾値 | `explore_hoshibiyori.py` `LPI_THRESHOLD` | 5.0。実地の成功・失敗例に基づく暫定値 |
| 雲量閾値・最小晴れ間 | `CLOUD_OBSTRUCTION_THRESHOLD` / `MIN_CLEAR_WINDOW_HOURS` | 30.0% / 1.0時間 |
| 失敗セル率と終了コード | `step5_cloud_forecast/grid_cache.py` `FAILED_CELL_RATE_ABORT` | 0.20。0/2 の意味は上記 |
| 格子セルキャッシュとTTL | `grid_cache.py` `CACHE_TTL_SEC` | MSM 3時間 / ECMWF 6時間 |
| 候補地点データ | `stargazing_spots.json`、`curated_spots.json` ほか | 一括編集の前に必ずバックアップ(`.bak_*`)を取る |
| 重複削除30グループ | `step7_geocoding/pending_deletions_round2.json` | ユーザーの目視承認待ち。勝手に適用しない |

## 7. 外部サイトへのアクセスの節度
- タイル(DEM・光害・ひまわり)・格子セルのディスクキャッシュを無効化しない。新規取得の小休止(`gsi_dem.py` `_POLITE_DELAY_SEC` など)を削らない。識別可能な User-Agent を維持する。
- Nominatim は1秒1リクエスト以下(`reverse_geocode.py` `MIN_REQUEST_INTERVAL_SEC`)。
- HTTP 429 が出たら即中止してユーザーに報告する。別経路・リトライの連打・キャッシュの手作りで回避しない。
- 単体テストは通信しない(`requests.get` 等をモック)。テストのために実通信しない。

## 8. PowerShell の注意
- `python` は `-X utf8` を付ける(日本語出力の文字化け対策)。
- python の出力を `>` や `|` で受けない(PowerShell 5.1 は UTF-16/BOM になりうる)。ログが要るときは python 側でファイルへ書くか、`logs/` へ `Out-File -Encoding utf8` を明示する。
- venv は activate せず、`.\.venv\Scripts\python.exe` を直接呼ぶ。
- (yamabiyori の同種の注意を踏襲したもの。hoshibiyori の全スクリプトでの再現は未検証)

## 9. コミットと共有
- main へ直接 push しない(PR 経由)。GitHub の設定変更は個別に承認を得る。
- `git add -A` は使わず、ファイルを指定する。キャッシュ(`dem_cache/`・`tile_cache/`・`cloud_cache/`・`weather_map_cache/`・`himawari_cache/`)、`*.bsp`、`.bak` 系をコミットしない。`.gitignore` は行末コメント非対応(コメントは独立した行に書く)。
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
   - 近日中(MSM)と中期見込み(ECMWF)はスコアの式が違い、絶対値は比べられない(第6節)。中期見込みの雲量は晴天率の参考表示で、足切りには使われていないと断る。
   - 雲量は全天の平均で、方角ごとの雲は分からない(第10節と同じ)。
3. 星空ガイドへ進む
   - ユーザーが選んだ(または筆頭候補を提案して承認された)地点と夜で、第10節の手順に進む。
   - `--spot` にはレポートに出た地点名をそのまま使う(`stargazing_spots.json` の name と同じ表記)。見つからないときは推測で置き換えず、そのままユーザーに報告する。
   - `--date` は「夜の開始日」(10/17の夜なら 2026-10-17)。
4. 雲量のキャッシュ
   - ガイドの雲量は既定で、有効期限内(MSM 3時間 / ECMWF 6時間)のキャッシュだけを使う。探索の実行から時間が経つと雲量が省略され、理由がページに出る。省略を「晴れ」と読み替えない。
   - 雲量を入れたいときは `--estimate` の結果と所要時間・リクエスト数を伝え、承認を得てから `--cloud fetch --allow-network` を使う(第10節と同じ)。
5. 数値の扱いは第10節のとおり(数値を自分で書かない)。

## 12. 天気図の解説を更新するとき
レポートの地上天気図の解説は `weather_map_commentary.json`(リポジトリ直下、git管理外)から読む。schema `/2`・`based_on` から生成時刻まで12時間以内・`images` の3枚が実在、の3つが揃うときだけ表示し、そのときは気象庁へ取得に行かず、`images` の画像(解説の元にした図)を使う。揃わない場合(超過・未来・無い・壊れている・`/1`・画像が無い)は、従来どおり取得して画像だけを出し、解説は表示しない。
1. 天気図を取得する(`step5_cloud_forecast/jma_weather_map.py` を実行。`weather_map_cache/fetched_at.txt` に取得時刻が入る。気象庁へ通信する)
2. 取得した画像を見て、実況と+24h/+48hの高低気圧・前線の配置を事実として書く
3. 次の形で保存する。`images` は読んだ画像のパス(リポジトリ直下からの相対。絶対パスや `..` は無効、シンボリックリンクで外へ出るものも無効)
   `{"schema": "hoshibiyori-weathermap-commentary/2", "based_on": "<取得時刻 JST・タイムゾーン付き>", "text": "…", "images": {"now": "step5_cloud_forecast/weather_map_cache/….png", "plus24h": "…", "plus48h": "…"}}`
4. レポートを生成する
- 解説は公式の天気図の説明にとどめ、独自の予報(通過時刻の予測など)は書かない。
