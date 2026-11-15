# 報告書: `--json-out` の続き(第 1 部: 走査した全部の夜・星空・星座モードの見出し・README)

作成日: 2026-11-16 / ブランチ `feature/explore-json-nights`(main `6e4139a` から。push・PR はしていない)/ 指示書の写し `docs/explore-json-followup-instructions.md`

## 1. 結果

**完了**(A1〜A4 を満たした)。ただし、星空・星座モードの見出しの4行のうち、通しで確かめられたのは見込み一覧の2行だけ。近日中の2行は単体テストで確かめた(4 章)。

準備(3 章): 作業フォルダ `C:\hoshibiyori`。`git status --porcelain --untracked-files=no` は空だった。`git fetch origin` を1回実行し、`git merge --ff-only origin/main` は「Already up to date」。`git log --oneline -1` は `6e4139a Feature/report courses stars (#35)`。

## 2. できたこと

| ファイル | 内容 |
|---|---|
| `explore_hoshibiyori.py` | A: `stage1_moon_filter` に任意の引数 `scan_out` を追加した。ループで既に求めた値を写すだけで、選び方・並び・表示・`_reference_night` の呼び出し回数は変わらない。理由のコードの定数 `NOT_SELECTED_*` を追加。`_explore(…, collect_scan=False)` は真のときだけ `scanned_nights` を返し、`_run` は `--json-out` のときだけ真で呼ぶ。B: 星空・星座モードのときだけ、`print_final_report`・`print_outlook_report` の見出しを変える(定数 `STARS_HEADING_TARGET`・`STARS_FINAL_ORDER`・`STARS_OUTLOOK_ORDER`)。天の川モードの見出しの f 文字列はそのまま残した |
| `explore_json.py` | `build_explore_json(…, scanned_nights=None)` を追加。渡したときだけ `nights` の直後に `scanned_nights` を、`notes` に `SCANNED_NOTE` を足す(`STARS_NOTE` の前)。`scanned_night_records()` を追加 |
| `schemas/hoshibiyori-explore.schema.json` | `scanned_nights` と `$defs/scanned_night` を追加(理由のコードは enum) |
| `tests/test_explore_scanned_nights.py`(新規、11 件) | 全部の夜が日付順に入る / 選ばれた夜の集合が `nights` と一致 / 理由のコード / 時間帯の無い夜は時刻が `null` / `scan_out` の有無で選び方・表示・計算の回数が同じ / `--json-out` なしでは集めない(`scanned_night_records` が呼ばれず、`collect_scan=False`)/ `nights` の中身とキーの順が変わらない / スキーマ |
| `tests/test_explore_headings.py`(新規、4 件) | 天の川モードの見出し4行を文字列で固定 / 星空・星座モードの見出し4行 / 見出しの並び順の説明が順位キーの実際の順と合う |
| `README.md` | `--json-out` の説明に、星空・星座モードの `score` が `null` であること(順位は `rank`)と `scanned_nights` を追記した。終了コード2のときは書かないことは、もともと書かれていた |
| `AGENTS.md` 5 章・`CHANGELOG.md` `[Unreleased]` | `scanned_nights` の1行。A は `Added` の `--json-out` の項に追記、B は `Fixed` に1項目 |

commit: `74dcb40`(A)、`0415714`(B)、文書、この報告書。

指示書から読み替えた点・決めた点:

- **理由のコードは4つにした。** `stage1_moon_filter` の分かれ方は、想定の3つより1つ多かった(日没・日の出が求まらない夜の `continue` がある)。この分かれ方を `no_sunset_or_sunrise` とした。日本の緯度では起きない分かれ方だが、コードにある以上、コードを入れておいた。
- **`all_nights_timeline()` は使っていない。** 日没・日の出が求まらない夜を落とすので、全部の夜にならないため。HTML 用なので変えていない。代わりに、`stage1_moon_filter` のループの中で値を写すことにした。別の関数で回し直すと、「今日」を2回求めることになり、計算も増えるため。
- **`selected` は `nights` の日付の集合から決める。** 並べ替えを繰り返さないので、同点の扱いがずれない。
- **`moon_free_hours` の値**: 月の影響が小さい時間帯が無い夜は `0.0`(`reference_night` の値のまま)。天文薄明が求まらない夜と、日没・日の出が求まらない夜は `null`(計算していないため)。
- **スキーマの top-level の `required` に `scanned_nights` を入れていない。** `--json-out` の出力には必ず入る。入れると古い出力と既存のテストの検査が通らなくなるため。
- **見出しの対象の語**: `generate_report.py` の星空・星座モードの「星空・星座モード ・ 天の川は対象外」に合わせ、「星空・星座モード・天の川は対象外」とした。参考候補の見出しは、天の川モードにも並び順の説明が無いので、対象の語だけを直した。

## 3. テストの結果

- 変更前: `Ran 537 tests` / `OK (skipped=3)`
- 変更後: `Ran 552 tests` / `OK (skipped=3)`(537 + 新規 15。skip の件数は同じ)
- 期待値を直した既存のテスト: **なし**。直してよい既存のテストを探したが、見出しの語で探しても `tests/` に探索の画面の見出しを確かめるものは無かった。`天の川銀河中心` が出てくる4ファイルは、`generate_report.render_html` に渡す対象の名前としての使い方だった。
- A3: `git diff main --stat` に出るのは上の表のファイルだけ。保護領域(`elevation_cloud.py`・`lp_source.py`・`grid_cache.py`・スコア式・閾値・候補地点データ)は変わっていない。A4: `requirements.txt`・`.gitignore`・`plugin.json` は変わっていない。

## 4. 通しの確かめの結果(固定キャッシュ・通信 0 回)

使ったもの:

- 固定キャッシュ: `C:\hoshibiyori-archive\open-meteo-pacing-20261113\live_cache`(221 セル)を `C:\temp\hoshibiyori-followup-check\live_cache` に写した。
- 実行のしかた: `--frozen --primary-only --max-minutes 30`。
- 変更前: `git archive main` を `main_code` に展開し、暦を写したもの。天文計算の保存先は `astro_before`・`astro_after`(利用者の保存済みは使っていない)。
- 実行の時間: 6 回とも 2026-11-16 01:49〜01:52(JST)の中で終えた。どれも `api_calls: 0`・失敗セル 0。

| 比べたもの | 結果 |
|---|---|
| 天の川: 変更前 vs 変更後(`--json-out` なし) | **同じ**(画面、全件の記録 `.results.txt`) |
| 星空・星座: 変更前 vs 変更後 | 画面で違うのは見出しの2行だけ(下に貼る)。`.results.txt` はバイト単位で同じ |
| `--json-out` なし vs あり(両モード) | 違うのは最後の1行「探索結果の JSON を書きました: …」だけ。`.results.txt` は同じ |
| JSON | 両モードともスキーマの検査で誤り 0。`scanned_nights` は 14 夜で、選ばれた6夜が `nights` と一致した |

星空・星座モードで違った行(`compare` の出力のまま):

```
-見込み一覧・主要候補(対象: 天の川銀河中心、星空撮影名所ベース、月・地形・光害による決定論的スコア順、上位20件)
+見込み一覧・主要候補(対象: 星空・星座モード・天の川は対象外、星空撮影名所ベース、光害(ALR)が小さい→月の影響が小さい時間が長い順、上位20件)
-見込み一覧・参考候補(対象: 天の川銀河中心、OSM展望データ由来・星空適性は未検証、上位10件)
+見込み一覧・参考候補(対象: 星空・星座モード・天の川は対象外、OSM展望データ由来・星空適性は未検証、上位10件)
```

**近日中の一覧の見出し2行は、通しでは出ない。** 固定キャッシュの夜が6夜とも見込み(ECMWF)側で、`print_final_report` が呼ばれないため。この2行は `tests/test_explore_headings.py` で確かめた。

`scanned_nights` の中身(この固定キャッシュの実行。両モードで同じ):

| 夜 | selected | regime | not_selected_reason | moon_free_hours |
|---|---|---|---|---|
| 11/16〜11/20 | true | ECMWF | null | 6.5 / 5.5 / 4.5 / 3.5 / 2.5 |
| 11/21・11/22 | false | null | not_in_top_n | 1.25 / 0.25 |
| 11/23〜11/26 | false | null | no_moon_free_window | 0.0 |
| 11/27・11/28 | false | null | not_in_top_n | 1.25 / 2.5 |
| 11/29 | true | ECMWF | null | 3.75 |

## 5. 未確認のこと

- 近日中(`finals`)が1件以上ある状態の、実際の探索での見出しと JSON(上の理由)。
- `no_sunset_or_sunrise`・`no_astronomical_darkness` が実際の探索で出ること(日本の緯度では起きない見込み。単体テストでだけ確かめた)。
- 実通信での実行、全 897 地点での実行(指示書どおり行っていない)。

## 6. コンシェル側への申し送り

- **`scanned_nights`(追加の項目)**: 走査した全部の夜(既定 14 夜)が日付順に入る。項目は `nights` と同じ(`night_date`・`sunset`・`sunrise`・`dark_start`・`dark_end`・`window_start`・`window_end`・`moon_free_hours`)に、次の3つが付く。
  - `selected`: 候補の夜(`nights`)に入ったか。
  - `regime`: 選ばれた夜だけ `MSM`/`ECMWF`。選ばれていない夜は `null`。
  - `not_selected_reason`: 選ばれた夜は `null`。

  理由のコード:

  | コード | 意味 |
  |---|---|
  | `not_in_top_n` | 月の影響が小さい時間帯はあるが、長さの順で上位 N 夜(`thresholds.num_candidate_nights`)に入らなかった。時間帯の時刻と長さは入っている |
  | `no_moon_free_window` | 暗い時間に、月の影響が小さい時間帯が無い(月が明るい夜)。時刻は `null`、`moon_free_hours` は `0.0` |
  | `no_astronomical_darkness` | 天文薄明の終わり・始まりが求まらない(暗くならない)。`dark_*` 以降は `null` |
  | `no_sunset_or_sunrise` | 日没・日の出が求まらない。日没・日の出以降はすべて `null` |

- 「今週末は月が明るいので星空に向かない」と言うときの根拠は `no_moon_free_window`、または `not_in_top_n` で `moon_free_hours` が短い夜。`not_in_top_n` は、雲量を調べていない(候補の夜より月の条件が悪いだけ)という意味。
- `nights` の中身・並び(月の影響が小さい時間が長い順)は変えていない。`scanned_nights` は日付順。
- `notes` に `scanned_nights は走査した全部の夜です。…` が足される。星空・星座モードでは、その後ろに `STARS_NOTE` が続く。
- `scanned_nights` が無い JSON(この変更の前の出力)もありうる。必須として扱わないこと。

## 7. 利用者がやること

1. **push**(PowerShell):
   ```
   cd C:\hoshibiyori
   git switch feature/explore-json-nights
   git push -u origin feature/explore-json-nights
   ```
   GitHub で PR を作る。第 2 部のブランチ `fix/no-terrain-horizon` も同じ手順(第 2 部の報告書に書いた)。どちらも main から切っている。2つ目をマージするときは `CHANGELOG.md` の `[Unreleased]` で衝突する見込み。そのときは main を取り込み、両方の項目を残して解決する。
2. **実通信での確かめ**(PowerShell):
   ```
   py -X utf8 explore_hoshibiyori.py --target stars --json-out C:\temp\hoshi-stars.json
   py -X utf8 explore_hoshibiyori.py --json-out C:\temp\hoshi-milkyway.json
   ```
   - 成功の見分け方: 画面の最後に「探索結果の JSON を書きました: …」と出て、`echo $LASTEXITCODE` が 0 になる。JSON に `scanned_nights`(14 件)があり、星空・星座モードの一覧の見出しに「天の川銀河中心」が出ない。
   - 目安(`AGENTS.md` 5 章より): 全 897 地点の探索は Open-Meteo 約 620 回。雲量のキャッシュが無い初回は約 6 分(通信 617 回)、同じ日の2回目は約 10 秒(通信 0 回)。`--json-out` は通信を増やさない。
   - MSM の範囲の夜がある状態で実行すると、近日中の一覧の見出しも見られる(Claude Code の中では確かめられなかった点)。

## 8. 利用者に決めてほしいこと

- スキーマの top-level の `required` に `scanned_nights` を入れるか(今は入れていない。入れると古い出力が検査で通らない)。
- 参考候補の見出しにも並び順の説明を入れるか(今は天の川モードに合わせて入れていない)。
- リポジトリ直下の `dem_cache/` の扱い(今回は何もしていない)。
