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
- `py generate_report.py`(引数なし): **10〜30分・Open-Meteo API 約220回**(候補146件で実測約21分。候補数に比例して増える)。固定の `report.html`(**git 管理**)を上書きする。終了コード: 0=出力済み、2=失敗セル率20%以上または HTTP 429(`report.html` は更新しない)。
- 実行前に「所要時間・リクエスト数・書き込み先」を伝えて承認を得る。Open-Meteo の無料枠は同じ回線の他の利用と共有される。
- 長時間コマンドのタイムアウト対策(Windows の Codex で成り立つ方法)は**未確認**。確認できるまで、実行はユーザーに依頼するか、バックグラウンド実行+出力ファイルで行う。
- `explore_hoshibiyori.py` も引数なし(探索結果をコンソールに出す)。
- 再生成した `report.html` は、ユーザーが決めるまでコミットしない。

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
