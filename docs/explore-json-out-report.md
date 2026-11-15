# 報告書: 探索結果の JSON 出力(`--json-out`)(第 1 部)

作成日: 2026-11-16 / ブランチ `feature/explore-json-out`(main `174c0ef` から。push・PR はしていない)

**指示書の読み替え**: T2 は、利用者の指示で「`git status --porcelain --untracked-files=no` が空でない」と読み替えて進めた(追跡していない 8 件には触れていない)。

## 1. 結果

**第 1 部は完了**(A1〜A4 を満たした。7 章の通しの確かめも実施)。第 2 部は別の報告書(`docs/report-courses-stars-report.md`)に書く。

準備(3 章): 作業フォルダ `C:\hoshibiyori`、`git fetch origin` を 1 回 → `git merge --ff-only origin/main` は「Already up to date」、`git log --oneline -1` = `174c0ef Release/1.1.0 (#33)`。

## 2. できたこと

| ファイル | 内容 |
|---|---|
| `explore_json.py`(新規) | JSON の組み立て `build_explore_json()`(通信・天文計算・ファイルの読み書きをしない純粋な関数)、一時ファイル経由の書き出し `write_json_atomic()`、版 `plugin_version()`、commit と dirty `git_state()`(引数の配列で `git` を呼ぶ) |
| `explore_hoshibiyori.py` | `--json-out` を追加。`_explore()` が JSON の材料(dict)を返すように、`_run()` に任意の `sink` を追加、`main()` は終了コード 0 のときだけ書く。`explore_thresholds()`・`write_explore_json()` を追加。画面の文と順番、スコア式・閾値の行は変えていない(削除行は `return _run(...)`・`def _run` の行・`_explore(...)` の呼び出し・`-> None` の 4 行だけ) |
| `schemas/hoshibiyori-explore.schema.json`(新規) | JSON Schema(必須の項目・型・`null` を許す項目) |
| `tests/test_explore_json.py`(新規) | 24 件。通信しない(`requests.get`・`requests.Session.get` を止めて確かめる)。スキーマの検査は依存を足さずにファイル内の小さな検査器で行う |
| `scripts/measure_explore.py` | `--json-out` をそのまま explore に渡す引数(指定しないときは渡さない) |
| `AGENTS.md` 5 章・`README.md`・`CHANGELOG.md` `[Unreleased]` の `Added` | 使い方の説明。版(`plugin.json`)は上げていない |
| `docs/explore-json-out-instructions.md` | 指示書の写し |

commit: `1fd4f6c`(実装とテスト)、`7ef9272`(新しい 3 ファイルの改行を CRLF にそろえた。リポジトリのほかのファイルが CRLF のため。中身は同じ)、`55ee48d`(文書)、この報告書。

## 3. テストの結果

- 変更前: `Ran 499 tests` / `OK (skipped=3)`
- 変更後: `Ran 523 tests` / `OK (skipped=3)`(499 + 新規 24。skip の件数は同じ)
- A3: `git diff main --stat` に出るのは上の表のファイルだけ(`elevation_cloud.py`・`lp_source.py`・`grid_cache.py`・候補地点データは出ていない)。A4: `requirements.txt` は変わっていない。

## 4. 終了コードの確認

実装の前に `main()` の説明と `_run()` を読んで確かめた: **0 = 完了**(一部の取得失敗は警告を出して 0)、**2 = 中止**(429 で `OpenMeteoDailyLimitError`、基準地点の MSM の取得失敗 `ReferenceForecastUnavailable`、失敗セル率が `FAILED_CELL_RATE_ABORT`(0.20)以上)。意味は変えていない。JSON は 0 のときだけ書き、2 のときは書かない・既存のファイルに触れない(テストで 3 つの経路を確かめた)。JSON の書き出し自体が失敗したとき(書き込み先の権限など)は、新しい終了コードを足さず、例外のまま止まる(既存のファイルは一時ファイル方式のため壊れない)。

## 5. JSON の見本

項目: `schema`、`generated_at`、`version`、`commit`、`dirty`、`target`、`astro_grid`、`thresholds`(`cloud_obstruction_threshold_pct`・`min_clear_window_hours`・`lp_alr_threshold`・`lp_index_limit`・`moon_phase_negligible_deg`・`num_nights_to_scan`・`num_candidate_nights`・`milkyway_few_results`・`failed_cell_rate_abort`)、`reference_site`(`name`・`lat`・`lon`)、`sites`(`primary`・`reference`・`total`・`with_horizon`)、`nights`(`NightCandidate` の全項目 + `regime`)、`finals`・`outlooks`(データクラスの全項目 + `score_kind`・`is_primary`・`group`・`rank`)、`fetch`(`status`・`total_cells`・`failed_cells`・`failed_rate`・`cache_hits`・`api_calls`・`rate_limited`・`retries`・`failure_reasons`)、`notes`(指示書 4.4 の 3 文)。

候補 1 件分の例(**数値は見本**。7 章の固定キャッシュでの実行から形だけを写し、値は短くした):

```json
{
  "night_date": "2026-11-16", "site_name": "八丈富士", "municipality": "八丈町", "origin": "curated",
  "site_lat": 33.137349, "site_lon": 139.767181, "requires_lift_access": false,
  "visible_start": "2026-11-16T22:19:16.860983+09:00", "visible_end": "2026-11-17T04:34:16.860983+09:00",
  "target_az": null, "target_alt": null, "horizon_alt": null, "terrain_available": false,
  "lp_index": 0.0792, "clear_sky_pct": 0.0, "moon_free_hours": 6.25, "score": 0.0,
  "alr": 0.1688, "alr_rank_pct": 0.68,
  "score_kind": "outlook", "is_primary": true, "group": "primary", "rank": 1
}
```

決めたこと(指示書で決まっていなかった点):

- **並びと順位**: 画面と同じく「主要候補(順位キーの降順)→ 参考候補(同じ)」の順に並べ、`rank` は各 `group` の中で 1 から(画面の「[N位]」と同じ)。同点は Python の安定ソートで画面と同じ順。
- **`nights`**: 第 1 段階が返す**候補の夜**(月の条件で上位 `num_candidate_nights` 夜)だけを入れた。走査した 14 夜の全部は、探索の中で保持されていないため入れていない(入れるには計算を足す必要がある)。並びは第 1 段階の戻り値の順(月の影響が小さい時間の長い順)。
- **`dirty`**: 追跡しているファイルの変更だけを見る(`git status --porcelain --untracked-files=no`)。追跡していないファイルは数えない。
- **`failure_reasons`**: 失敗の理由の文字列の、最初の「:」より前だけを種類として数える(例 `ConnectionResetError`、`client_error (HTTP 404)`、`HTTP 429 (minutely)`)。理由の本文に URL や座標が入りうるため。
- **時差の無い datetime**: 探索のコードでは作られない(すべて `astimezone(JST)` か `tzinfo=JST` 由来であることを読んで確かめた)。万一あれば推測で `+09:00` を付けず `null` にする。
- **秒以下**: 天文計算の時刻はマイクロ秒を含む。丸めないという決まりに従い、そのまま出した。`generated_at` は秒まで。
- **`lp_alr_threshold`**: 定数 `BM_ALR_THRESHOLD` ではなく、探索で実際に使った `lp_store.alr_threshold` を入れた(既定ではどちらも 10.66)。
- 文字コードは UTF-8(BOM なし)、`indent=2`、キーは定義の順(データクラスの項目順)で固定。`allow_nan=False` で NaN が残れば書き出しが失敗する(その前に `null` にしている)。

## 6. 通信なしでの通しの確かめ(7 章)

固定キャッシュ `C:\hoshibiyori-archive\open-meteo-pacing-20261113\live_cache`(2026-11-13 05:33 取得の 221 セル、`docs/astro-grid-cache-report.md` に記載の置き場)を使い、`--frozen --primary-only --max-minutes 30`、天文計算の保存先は `C:\temp\hoshibiyori-json-check\astro_before`・`astro_after`(利用者の保存済みは使っていない)。変更前のコードは `git archive main` を `C:\temp\hoshibiyori-json-check\main_code` に展開し、暦を写した。実行はすべて 2026-11-16 00:45〜00:51(JST)の中。通信は 0 回(`api_calls: 0`)。

| 確かめ | 結果 |
|---|---|
| stars: 変更前 vs 変更後(`--json-out` なし)の `compare` | **同じ**(画面と、全件の記録 `.results.txt`) |
| milkyway: 変更前 vs 変更後 | **同じ** |
| `--json-out` なし vs あり(stars・milkyway) | 違いは最後の 1 行「探索結果の JSON を書きました: …」だけ |
| JSON の中身 | 両モードともスキーマの検査で誤り 0、BOM なし、時刻はすべてオフセットつき。件数は `.results.txt` と同じ(stars: 夜 6・finals 0・outlooks 846、milkyway: 夜 6・finals 0・outlooks 360)。画面の上位 20 件と JSON の先頭 20 件の並びが一致 |

**限界**: 固定キャッシュは 3 日前のもので、今日の夜が MSM の範囲に入らず(6 夜とも ECMWF)、**`finals`(近日中)が 0 件の状態でしか通しを確かめられていない**。`finals` の形はテスト(手で作った候補)でだけ確かめた。

## 7. 未確認のこと

- `finals` が 1 件以上ある実際の探索での JSON(上の限界)。
- 全 897 地点での実行(指示書どおり行っていない)。
- 実通信での実行(行っていない)。

## 8. コンシェル側への申し送り

- **地点に変わらない ID が無い**。今は `site_name` と `site_lat`・`site_lon` で識別するしかない。ID を足すには候補地点データ(`stargazing_spots.json`、保護領域)の変更が要るので入れていない。案: `spots`・`viewpoint_reference` の各エントリに `id`(例 `curated-001` のような由来+連番、一度振ったら変えない)を足し、`_build_site()` で読み、`FinalCandidate`/`OutlookCandidate` に `site_id` を足す。
- **名前の対応**: 指示書の項目名に合わせ、データクラスの項目名をそのまま使った(`site_name`・`municipality`・`window_start`/`window_end`(近日中)・`visible_start`/`visible_end`(見込み)・`mean_obstruction`・`clear_hours`・`moon_free_hours`・`alr`・`alr_rank_pct`・`lp_index`・`score`)。足した項目は `score_kind`・`is_primary`・`group`・`rank`・夜の `regime`。
- **取れなかった項目**: 走査した 14 夜の全部(候補の 6 夜だけ)、地点の標高(候補のデータクラスに無い)、東京からの距離(探索では計算しない)、夜景系の分類 `site_type`(候補のデータクラスに無い)。
- **stars モードの `score` は 0.0**(並びは順位キーで決まる)。順位は `rank` を使うこと。`target_az`・`target_alt`・`horizon_alt` は `null`。
- **見込み(milkyway)の観察(既存の動きで、変えていない)**: 固定キャッシュの milkyway の `outlooks` 360 件は、すべて地形データが無い地点で、`target_alt`(銀河中心の最大高度)が 0 以下だった。地形データが無い地点では、見込みの「見頃」の判定(`compute_target_window`)が高度を見ずに「見える」と扱うため、11 月のように銀河中心が暗い時間に昇らない時期でも候補になる。コンシェル側で天の川の候補として扱う前に、`target_alt` が正かどうかを見る必要がある。直すかどうかは保護領域(探索の判定)の判断なので、利用者に決めてほしいこと(下)に書いた。
- **実測していないこと**: GitHub のマシンでの所要時間、`--target milkyway` のあとに `--target stars` を続けたときに通信が増えないか(同じ格子セルのキャッシュが効くはずだが未実測)。

## 9. 利用者がやること

1. **push**: PowerShell で `cd C:\hoshibiyori` → `git switch feature/explore-json-out` → `git push -u origin feature/explore-json-out` → GitHub で PR を作る(第 2 部のブランチも同じ手順)。
2. **実通信での確かめ**(PowerShell): `py -X utf8 explore_hoshibiyori.py --target stars --json-out C:\temp\hoshi-stars.json`
   - 成功の見分け方: 画面の最後に「探索結果の JSON を書きました: C:\temp\hoshi-stars.json」と出て、そのファイルができる。終了コードは `echo $LASTEXITCODE` で 0。
   - 目安(`AGENTS.md` 5 章の記述): 全 897 地点の探索(星空モード)は Open-Meteo 約 620 回、雲量のキャッシュが無い初回は約 6 分(通信 617 回)、同じ日の 2 回目は約 10 秒(通信 0 回)。`--json-out` は通信を増やさない。
   - 余裕があれば、MSM の範囲の夜がある状態(実行の直後)で `finals` が入っているかを見る(Claude Code の中では確かめられなかった点)。

## 10. 利用者に決めてほしいこと

- リポジトリ直下の `dem_cache/` が `.gitignore` で除外されていない(除外されているのは `step2_terrain/dem_cache/` だけ)。CLAUDE.md の「DEM タイルのキャッシュは除外済み」と食い違う。足すかどうか(今回は変えていない)。
- 地点 ID を候補地点データに足すか(上の案)。
- 見込み(milkyway)で、地形データの無い地点が銀河中心の高度 0 以下でも候補になる動きを直すか(探索の判定=保護領域)。
- `nights` に走査した 14 夜の全部を入れるか(今は候補の夜だけ)。
