# Open-Meteo の利用上限への対応 報告書(2026-11-13)

ブランチ `feature/astro-speedup`(続きに commit。push はしていない)。指示書: `docs/open-meteo-pacing-instructions.md`。

## 要約(1分)

- **変えたこと**: ① 429 の本文の reason を読んで種類(minutely/hourly/daily/unknown)に分け、1分の上限だけは65秒待って取り直す(1回の実行で5回まで)。それ以外は従来どおり中止(終了コード2)。② 直近60秒の通信の重さが300(1分の上限600の半分)を超えないよう、通信の前に待つ。③ 再試行のたびに1行出す。④ 基準地点(石廊崎)の MSM のセルが取得の失敗で空なら、夜を見込み側に回さず中止する(終了コード2)。
- **テスト**: 全テスト `Ran 478 tests … OK (skipped=3)`(追加24件、すべて通信なし)。
- **実通信の確かめ(主要146件・`--target stars`・空のキャッシュ、1回)**: API呼び出し221回、**429は0回**、65秒待ち0回、**間隔の調整28.6秒**、再試行0回、失敗セル0、全体160.0秒、**MSMの夜は3夜**(6夜中)。終了コード0。
- **言えないこと**: 今回の通信の重さは合計でも約221×2.5≈560で、1分の上限600に届かない。つまり**間隔の調整が無くても429は出なかった実行**で、分かったのは「通常の実行を壊さない」ことまで。**間隔の調整が429を防ぐかは、本人の全地点の実行が最初の確かめ**になる。429 が出なかったので、**reason の実物の文面も確かめられていない**(分け方は「Minutely/Hourly/Daily の語の有無」)。
- **次は本人**: PowerShell で全地点の実行を1回(下の「本人が行う手順」)。

## 変えたこと

| 部 | ファイル | 内容 |
|---|---|---|
| 1 | `step5_cloud_forecast/cloud_forecast.py` | 429 のとき本文の JSON の `reason` を読む(読めなければ本文の先頭200文字)。`classify_rate_limit()` で daily→hourly→minutely の順に語を探し、無ければ unknown。`FetchOutcome` に `rate_limit_kind`・`rate_limit_reason` を足した。画面に「429(利用上限、種類=…)… reason: …」を出す |
| 1 | `step5_cloud_forecast/grid_cache.py` | `get_hourly` で minutely なら「1分の上限のため65秒待ちます(n/5)」と出して65秒待ち、同じセルを取り直す(`MINUTELY_RETRY_WAIT_SEC=65`、`MINUTELY_RETRY_MAX=5`、`GridCloudCache` 1つ=1回の実行で数える)。6回目と hourly/daily/unknown は `OpenMeteoDailyLimitError`(名前は据え置き)で中止し、文に種類と reason を入れる。受けた429は `rate_limit_events` に残す |
| 2 | `cloud_forecast.py` | `request_weight()` = `max(1, 変数の数/10) × max(1, 予報日数/14)`(探索の MSM 2.4、ECMWF 2.57)。`RequestPacer`(時計と sleep を差し替えられる)をプロセスに1つ持ち、各試行(再試行を含む)の前に `acquire()`。上限は `PACING_LIMIT_PER_MINUTE = 300` |
| 2 | `grid_cache.py` | `FetchSummary` に `pacing_sec`・`minutely_waits`・`minutely_wait_sec`。待ちがあったときだけ `console_line()` の後ろに「 / 間隔の調整 N 秒」、`timing_line()` を「通信・間隔の調整・それ以外」に分ける。間隔の調整の待ちは通信の秒数に入れない |
| 3 | `cloud_forecast.py` | 再試行のたびに「[再試行] Open-Meteo(…): 例外の名前 -> N秒待ってM回目を試します」。回数・間隔・打ち切りは同じ |
| 4 | `explore_hoshibiyori.py`・`generate_report.py`・`grid_cache.py` | `GridCloudCache.fetch_failed()`(通信もキャッシュヒットの計上もしない)で、基準地点の MSM のセルが「取りに行って失敗した」かを見る。そうなら `forecast_regime_for_night` が `ReferenceForecastUnavailable` を投げ、両スクリプトとも「基準地点の予報を取得できなかったため中止します」で終了コード2(レポートは書かない)。取得できて範囲の外なら従来どおり ECMWF |
| 5 | `scripts/measure_explore.py` | 秒数の JSON に再試行・失敗の待ち・間隔の調整・65秒待ち・429の記録・失敗セルを足した(`--primary-only` で通信ありの実行は元からできた) |
| 文書 | `CHANGELOG.md`・`CLAUDE.md` | `[Unreleased]` の Changed と Fixed、「取得失敗の扱い」に追記 |

変えていないもの: URL・パラメータ・変数の文字列・キャッシュのキーと有効期限・スコア・候補の選び方・順位・レポートの中身・ひまわりの429。

## テストの結果

`py -X utf8 -m unittest discover -s tests` → `Ran 478 tests in 81.397s` / `OK (skipped=3)`(commit 前に実行)。
既存のテストの期待値は変えていない。追加は `tests/test_open_meteo_pacing.py`(24件): 種類の分け方、JSON/非JSONの本文、minutely の待ちと同じセルの取り直し、5回の上限と6回目の中止、hourly/daily/unknown は待たずに中止、重さの計算、どの60秒にも上限を超えないこと、キャッシュヒットで待たないこと、再試行も間隔の調整に数えること、待った秒数の集計と表示、再試行の表示、基準地点の失敗で中止・範囲の外で ECMWF・範囲内で MSM、explore と generate_report の終了コード2。

通信なしの配線の確かめ: `measure_explore.py run --frozen --primary-only`(空のキャッシュ)で、基準地点の中止の文が出て終了コード2になった。

## 第5部の値(実際の通信、1回だけ)

`py -X utf8 scripts/measure_explore.py run --primary-only --target stars --cache-dir <空のフォルダ> …`、コード `0fa3ed5`、2026-11-13 05:31〜05:34 JST。ログ等は `C:\hoshibiyori-archive\open-meteo-pacing-20261113\live_primary_stars.*`。

| 項目 | 値 |
|---|---|
| API呼び出し | 221回(キャッシュヒット1,513回、取得セル221件) |
| 429 | 0回(種類・reason の記録なし) |
| 65秒待ち | 0回 |
| 間隔の調整 | 28.6 秒 |
| 再試行 | 0回(例外なし) |
| 失敗セル | 0件 |
| 通信 | 35.7 秒 |
| 全体 | 160.0 秒(それ以外 95.7 秒、CPU 90.1 秒) |
| MSM の夜 | 3夜 / 6夜(ECMWF 3夜) |
| 終了コード | 0 |

集計の行(画面のまま): `取得セル221件 / API呼び出し221回 / キャッシュヒット1513回 / 失敗0件(0.0%) / 通信 35.7 秒(うち失敗の待ち 0.0 秒・再試行 0 回) / 間隔の調整 28.6 秒`

## 自分で決めたこと

- **「間隔の調整」は待ちが起きたときだけ出す**(指示書は「0秒のときも出してよい」)。既存テストの期待値(集計の行の末尾・内訳の行の完全一致)を変えないためと、「失敗が無いときの出力は今と同じ」に合わせるため。内訳の3つの分け方も、待ちがあったときだけ。
- 65秒待ちの秒数は「間隔の調整」に含めて出し、回数を括弧で添える(通信の秒数には入れない。入れないと「それ以外」が65秒ずつ膨らむため)。
- minutely の取り直しは新しい通信として API 呼び出しの回数に数える(取得セル数は増えない)。
- 間隔の調整はプロセスに1つ(`cloud_forecast._PACER`)。上限は IP アドレス単位なので、キャッシュの作り直しで数え直さない側にした。
- 基準地点の判定は **MSM のセルの失敗だけ**で中止する。ECMWF のセルの失敗は「範囲内か」の判定を変えないため(変更が小さい側)。
- 種類の判定は重い順(daily→hourly→minutely)に語を探す。複数の語があっても待たない側に倒れる。
- `measure_explore.py --frozen` は、固定キャッシュに石廊崎の MSM のセルが無いと、基準地点の中止で終了コード2になるようになった(配線の確かめで実際にそうなった)。古い固定キャッシュで比べるときは注意。
- AGENTS.md 第5節の終了コードの説明と、両スクリプトの `main()` の docstring には、基準地点の失敗による終了コード2をまだ書いていない(変更が小さい側)。
- `AGENTS.md` は変えていない(指示書の対象外)。ただし第7節「HTTP 429 が出たら即中止してユーザーに報告する」は、今は「1分の上限ならコードが65秒待って取り直す」と少し食い違う。エージェントの振る舞い(別経路やリトライの連打をしない)としては今のままでよいと判断したが、必要なら直してください。

## 言えること・言えないこと

言えること:
- 主要146件・空のキャッシュでは、429 も切断も無く最後まで終わり、MSM の夜が3夜あった。間隔の調整は28.6秒で、全体を大きくは延ばさなかった(通常の実行を壊さない)。
- `forecast_regime_for_night` の呼び出し元は `explore_hoshibiyori.py` と `generate_report.py` の2か所だけで(`scripts/`・`skyguide/` には無い)、どちらも新しい中止を扱っている。
- 基準地点の取得に失敗したとき、夜を見込み側に回さず終了コード2で止まる(テストと通信なしの配線の確かめ)。

言えないこと:
- **間隔の調整が429を防ぐか**: 今回の重さの合計(約560)は1分の上限600未満で、調整なしでも429は出なかったはずの実行。防げるかは全地点の実行で初めて分かる。
- **reason の実物の文面**: 429 が出なかったので確かめていない。語が入っていない文面なら unknown として中止する(待たない)。
- 朝の 429 が本当に1分の上限だったか(今回は再現しなかった)。
- 全897地点で 429 が出ないか。見積もりは約617回×約2.5=約1,540回分で、上限300/分なら通信全体で5〜6分かかる(最初の300回分は待たずに通る)。1時間の上限(5,000)は1回の実行では超えない見込みだが、同じ回線の他の利用と共有している。
- 朝の `ConnectionResetError(10054)` の原因(今回は0回)。

## 本人が行う手順

1. (済み)全テストが通り、`feature/astro-speedup` に commit 済み。
2. **「Windows PowerShell」ウィンドウ**で:
   1. `cd C:\hoshibiyori`
   2. `py -X utf8 explore_hoshibiyori.py --target stars`
   3. 最後まで終わることを確かめる(終了コード2で止まったら、`[中止]` の行の種類と reason を控える)。
   4. 上のほうの `[リードタイム判定]` の行で、**MSM精密予報圏内が 0夜でない**ことを確かめる。
   5. 最後の `予報取得の集計:` の行と `実行時間の内訳:` の行を控える(429 が出たら `種類=…` と reason の文面も)。
3. 問題がなければ、同じ **「Windows PowerShell」ウィンドウ**で:
   1. `git push -u origin feature/astro-speedup`
   2. ブラウザの **GitHub のリポジトリのページ**で、`feature/astro-speedup` から main への Pull Request を作る。
   3. 内容を確かめてマージする。
