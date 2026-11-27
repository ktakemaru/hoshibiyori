# 報告書: 天の川モードの速さと、コンシェル向けの出力の追加(2026-11-27)

指示書: `docs/concierge-followup-instructions.md`(提案の正本: `C:/biyori-concierge/docs/hoshibiyori-proposal-20261125.md`、読むだけ)。
通信は0回(固定キャッシュだけで確かめた)。push・PR・マージ・タグ・版上げはしていない(`plugin.json` は 1.2.0 のまま、CHANGELOG は `[Unreleased]`)。

## まとめ

1. 天の川モードの計算を、結果を1文字も変えずに短くした(主軸146地点・固定キャッシュ、CPU秒): `--nights` なし 152.2 → 7.0 秒、`--nights` 14夜・JSON つき 228.5 → 23.8 秒。
2. 遅さの原因は2つで、提案の見立て(見込みの1時刻ずつの計算)は正しかった。`--nights` 側は、保存を地点×夜ごとに読み直して時系列の変換をやり直していたのが主な原因だった(`_track` は 16 秒だけ)。
3. `--json-out` に `requested_nights[].sites[].night_rank`(聞かれた夜の中の順位)、`site_index[].origin`、`highlights`(夜に見られるもの)を足した。`dark` の夜の `passed` は月を条件にしていない、と注記とスキーマに書いた(項目は増やしていない)。
4. 既定の出力(画面・候補・順位・スコア・終了コード)は変わっていない。JSON の違いは足した項目と注記の文だけ(固定キャッシュの前後比較で確かめた)。
5. 全897地点の時間と、夏(銀河中心が見える時期)の実行は未確認。夏は単体テストで確かめた。

| 部 | ブランチ | 最後の commit | テスト(前 → 後) |
|---|---|---|---|
| 第1部 速さ | `fix/milkyway-speed`(main `3860af7` から) | `4a25ea5` | 680 → 691(OK, skipped=3) |
| 第2部 コンシェル向けの項目 | `feature/concierge-interface-2`(第1部の上) | `bfc0a92` | 691 → 698(OK, skipped=3) |
| 第3部 見どころ | `feature/json-highlights`(第2部の上) | `7dacde0`(この報告書の commit が最後) | 698 → 704(OK, skipped=3) |

## 第0部: 始める前の確かめと固定キャッシュ

- 始めたとき: ブランチ `main`、`git log -1` = `3860af7 Release/1.2.0 (#41)`、追跡中のファイルの未 commit の変更なし。テスト 680 件 `OK (skipped=3)`(167.3 秒)。止まる条件には当たらなかった。
- 固定キャッシュ: `C:/temp/hoshi-fixed-20261127/`(`cloud_cache` 619 ファイル[最新は 2026-11-25 22:08]・`astro_cache`・`de421.bsp` を写した。元は触っていない)。`scripts/measure_explore.py run --frozen`(期限を無視して読む・書かない・通信を止める)で実行し、天文計算の保存は写しの `astro_cache` に向けた。最初に1回ずつ空回しして(`warm/`)、前後どちらの実行も天文計算を保存から読むようにした。
- 直す前のコード: `git archive main` を `C:/temp/hoshi-followup-20261127/maincode/` に展開(`de421.bsp` と、追跡していない `horizon_curated_ext044/045_50km.csv` も写した。どちらも `stargazing_spots.json` からは参照されていない)し、`--code-root` で実行した。
- 「今の時刻」を固定する入口は無い。前後の実行はすべて 2026-11-27(JST)の 08:16〜09:06 に行った。
- 実行と出力: `C:/temp/hoshi-followup-20261127/{before,after1,after2,after3}/`(画面の行 `.log`、戻り値の全件 `.results.txt`、秒の `.json`、JSON `.out.json`)。

**比べるときに除くもの(先に決めた決まり)**
- 画面: `measure_explore.py` の `COMPARE_EXCLUDE`(「実行時間」で始まる行、「API呼び出し」「キャッシュヒット」を含む行、「天文計算のキャッシュ:」で始まる行)と、今回足した「探索結果の JSON を書きました:」で始まる行(書き出し先のフォルダが実行ごとに違うため)。戻り値の全件(`.results.txt`)は除くものなし。
- JSON: `generated_at`・`commit`・`dirty`(main の写しは git でないため null)。第2部・第3部では、足した項目(`site_index[].origin`・`requested_nights[].sites[].night_rank`・`highlights`)と `notes` も除き、`notes` は別に「既存の文の後ろに文が足されただけ」を確かめた。比べる道具はリポジトリの外(`C:/temp/hoshi-followup-20261127/tools/compare_json.py`)。

## 第1部: 天の川モードの計算を速くする

### 直す前の内訳(主軸146地点・天の川モード・`--nights` 14夜・JSON つき・固定キャッシュ)

「実行時間の内訳(計算)」の行を先に足して測った(コードの残りは main と同じ):

| | 秒 |
|---|---|
| 全体 | 229.6 |
| 見込みの計算(`stage_outlook`) | **162.2** |
| 聞かれた夜(`--nights`)の計算(`requested_nights.evaluate`) | **66.4** |

cProfile(同じ条件、プロファイルの分だけ遅い 350 秒)で見た中身:
- 見込み: `compute_target_window` 229 秒のほぼ全部が `altaz_at_time` の 39,435 回の呼び出し(1時刻ずつ)。
- `--nights`: 121 秒のうち `_track` は 16 秒だけ。**93 秒は `_to_dict_by_time`(雲量の時系列の変換)**。`FetchedOnlyCache` が保存を地点×夜ごとに読み直し、毎回別のオブジェクトになるため、変換の使い回し(`_by_time_memo`、オブジェクトで引く)が効いていなかった。

### 入れた変更

1. `compute_target_window` を、時刻の列をまとめて Skyfield に渡す形にした。まとめた計算は1時刻ずつの計算と末尾の桁で違うことがあるため(前回の取り消しの理由):
   - まとめた値は「見える・見えない」の判定と「最も高い時刻」の選択にだけ使う。
   - 返す高度・方位は、選んだ時刻だけを従来と同じ1時刻の計算(`ts.from_datetime` → `altaz_at_time`)でやり直す。
   - 判定が末尾の桁で入れ替わりうるサンプル(地平線・稜線の高度との差、稜線の方位の丸めの境目[x.5°]との差、最も高い2時刻の差が `TARGET_TRACK_GUARD_DEG` = 1e-6° 未満)が1つでもあれば、従来の1時刻ずつの計算(`_compute_target_window_scalar`、1.2.0 のまま残した)に切り替える。
2. 時刻の列を使い回す(`_sample_times`。鍵に時刻の表し方[タイムゾーン]を入れた。4096件で空にする)。`requested_nights._track` も同じものを使う(作り方は以前と同じ)。
3. `FetchedOnlyCache` が、保存から読んだセルをその回のあいだ覚える(同じファイルを読み直さない → 変換の使い回しが効く)。読む中身は同じ。メモリは、星空・星座モードで探索がもともと持っているのと同じ程度(読んだセルの分)増える。
4. 「実行時間の内訳(計算)」の行(見込みの計算・`--nights` の計算の秒。第3部で見どころの秒も)。
5. `time_estimates.py` と `AGENTS.md` の表に「探索・天の川モード・全897地点・`--nights` 14夜・JSON つき(予報の保存あり。1.2.0、計算の短縮の前)= 約10分(583.2秒、2026-11-25、利用者の実測1回)」を足した。開始の予告・`--estimate` が選ぶ目安は変わらない(この行の鍵は状態 `nights` で、選ぶ処理は `warm`/`cold` だけを見るため)。**直したあとの全897地点の値は書いていない。**
6. 提案1の4(対象がどの地点でも地平線の上に出ない時期は地点ごとの計算を省く)は、やっていない。2・3 のあとで見込みの計算は 6〜8 秒になり、要らないと考える(全897地点での確かめは未)。
7. 近日中(第3段階 `stage3_direction_filter`)の1時刻ずつのループは変えていない(今日は MSM の候補の夜が0夜で、前後比較できないため)。第2部で関数 `peak_altitude_scalar` に移しただけ(中身は同じ)。

### 直したあとの秒(主軸146地点・固定キャッシュ・2026-11-27、各1回)

| 実行 | 直す前 全体 / CPU | 直したあと 全体 / CPU | 直したあとの内訳(計算) |
|---|---|---|---|
| 天の川・`--nights` なし・JSON | 161.1 / 152.2 | 7.4 / 7.0 | 見込み 6.3 |
| 天の川・`--nights` 14夜・JSON | 244.2 / 228.5 | 25.1 / 23.8 | 見込み 7.0 / `--nights` 16.6 |
| 星空・星座・`--nights` 14夜・JSON | 6.8 / 6.6 | 6.2 / 5.6 | 見込み 2.5 / `--nights` 2.2 |

(第3部の見どころを入れたあとは、`--json-out` のときに約10〜12秒が足される。下の第3部を参照)

### 結果が1文字も変わらないことの確かめ

- 3つの実行とも、画面の行(上の決まりで除く行以外)・戻り値の全件(第2段階・第3段階・見込み)・JSON(`generated_at`・`commit`・`dirty` 以外)が、直す前と**1文字も違わなかった**(`measure_explore.py compare` と `compare_json.py` で「同じ」)。
- ただし今の季節は天の川モードの候補が0件で、この比較は「見えない → None」の道しか通らない。**銀河中心が見える時期の「今の時刻」を固定する入口は無い**ので、入口は足さずに単体テスト(`tests/test_milkyway_speed.py`)で確かめた:
  - 4/17・6/15・7/14・8/12・12/9 の夜 × 地形データのある4地点・無い4地点で、`compute_target_window` の戻り値が従来の計算と値・型・`repr` まで同じ(見える場合を10件以上含む)。手元の別の確かめでは216件(9夜×24地点)で同じ、切り替えは0回。
  - まとめた計算と1時刻ずつの計算の差は最大 8.5e-14°(余裕の 1e-6° の1万分の1より小さいことをテストで確かめる)。
  - 余裕を大きくして必ず切り替えさせても結果は同じ。
  - `stage_outlook` の戻り値の全件(`repr`)が、従来の計算に差し替えたときと同じ(夏の3夜)。
- 既存のテストで変えたもの: `tests/test_no_terrain_horizon.py` の作りもの(`FakeTs` に `from_datetimes` を足し、`altitude_fn` が時刻の列を受け取れるようにした)。**期待値は変えていない。** 時刻の列をまとめて渡す形になったため、1時刻用の作りもののままだと6件がエラーになった。

## 第2部: コンシェル向けの項目

### 足した項目

| 項目 | 意味 |
|---|---|
| `requested_nights[].sites[].night_rank` | その夜の中の順位(`group` ごとに1から)。`status: passed` の地点だけ、ほかは `null`。決め方は候補の一覧と同じ: 予報が MSM の夜(候補の夜は `regime`、それ以外は `forecast_regime`)は `finals`、ECMWF の夜は `outlooks` の順位キー(`final_rank_key`・`outlook_rank_key`)と同じ並べ方(`explore_json.ranked_groups`。`ranked_records` から分けた1か所。同じ値どうしは地点の並びのまま=今の一覧と同じ)。星空・星座モードの ECMWF の夜は「光害(ALR)が小さい→月の影響が小さい時間が長い順」。天の川モードはスコア順(スコアの式は `final_score`・`outlook_score` に移しただけ、出さない)。天の川モードでスコアが求まらない地点はグループの最後 |
| `site_index[].origin` | 地点の出どころ(候補の `origin` と同じ値): `curated` 78・`curated_external` 62・`curated+test_site` 3・`curated+viewpoint` 3(主軸)、`viewpoint` 747・`test_site` 4(参考) |
| `notes` の文・スキーマの `status` の説明 | 「`window_kind` が `dark` の夜の `passed` は、月を条件にしていません」(提案4。`window_kind` で足りるので項目は増やしていない)と、`night_rank` の決め方 |

スキーマ: `night_rank` と `site_index[].origin` を必須項目に足した(`/1` のまま)。

### 確かめ

- 固定キャッシュの前後比較: `--nights` なし(天の川・星空)は `site_index[].origin` のほか、`--nights` つき(天の川・星空)は `site_index[].origin`・`night_rank`・注記の文のほかは、画面・戻り値の全件・JSON が同じ。注記は既存の `REQUESTED_NOTE` の後ろに文が足されただけ。
- 実物(星空・星座、主軸146地点)で、候補の夜(12/5〜12/9 の5夜、どれも ECMWF)の `night_rank` と、同じ夜の `outlooks` の `rank` の、共通の地点どうしの並びがすべて同じ(43・100・1・11・57地点)。
- 単体テスト(`tests/test_concierge_interface_2.py`): 作りものの時刻・雲量で `_explore` を動かし、星空・星座モード(新月のころ、MSM と ECMWF の候補の夜の両方)と天の川モード(7月の新月のころ)で、`finals`・`outlooks` との並びの一致、`passed` だけに1から連番、スコアは `null`。スコアの関数が 1.2.0 の式と同じ値。
- 変えたテストの見本: なし(既存のテストは変えずに通った)。

### 実物の例(星空・星座モード、2026-11-28 の夜。候補の上位の夜に入っていない夜)

```json
{"night_date": "2026-11-28", "selected": false, "forecast_regime": "ECMWF", "window_kind": "moon_free",
 "sites": [
  {"site_id": "curated:083", "site_name": "乗鞍畳平", "group": "primary", "status": "passed", "reasons": [],
   "clear_hours": 2.5, "alr": 0.9738131211696441, "score": null, "night_rank": 1},
  {"site_id": "curated_ext:015", "site_name": "日光白根山ロープウェイ山頂駅", "group": "primary", "status": "passed",
   "reasons": [], "clear_hours": 2.5, "alr": 1.5108523477673206, "score": null, "night_rank": 2},
  {"site_id": "curated:001", "site_name": "神磯の鳥居・大洗海岸", "group": "primary", "status": "failed",
   "reasons": ["cloud_filter"], "clear_hours": 0.0, "alr": 6.8808811319435765, "score": null, "night_rank": null}]}
```
(項目は抜粋)。`site_index` の例: `{"site_id": "curated:083", "name": "乗鞍畳平", "label": "乗鞍畳平(高山市)", …, "requires_lift_access": true, "origin": "curated"}`。

## 第3部: 夜に見られるもの(`highlights`)

### 足した項目

- `highlights`(必須。計算しなかったときは `null`): `basis`(`text`「基準の地点・平らな地平線の目安(地形・雲は見ていない)」、基準地点 石廊崎、`min_alt_deg` 15、`max_items_per_slot` 4、`terrain: false`・`clouds: false`)、`computed_at`、`showers[]`、`by_night{日付: … | null}`。
- `by_night` は夜の日付で引く(`scanned_nights[]`・`requested_nights[]` の `night_date` のどちらからでも引ける。同じ中身を2回持たない)。暗い時間帯が無い夜は `null`。冬の天の川の帯は従来どおり `scanned_nights[].winter_milky_way`。
- 夜ごと: `slots[]`(宵・夜半・明け方、始まり・終わり、`moonlit`・`moon_up_intervals`、`items[]` → `members[]` に `id`・`name`・`kind`・`start`・`end`・`peak_time`・`peak_az`・`peak_alt`・`faint_in_moonlight`・`coordinates_unverified`)、`not_visible[]`(その夜は一度も15°以上に出ない対象。`name`・`next_month`・`ids`・`kinds`・`coordinates_unverified`。冬の銀河中心はここに入る)。
- `showers[]`(30日以内に極大があるもの。夜によらないので1回だけ): `id`・`name`・`kind: 流星群`・`peak_time`・`zhr`・`zhr_note`「例年の目安(理想の条件での1時間あたりの出現数。その年の予報ではない)」・`caveat`(レポートと同じ注意の文)・`source`・`night_date`(極大の夜)・`radiant_min_alt_deg` 20・`radiant_start`/`radiant_end`・月。
- 値はレポートと同じ関数(`sky_highlights.build`・`upcoming_showers`)の結果。そのために `sky_highlights` の値に `id`・`coordinates_unverified`(`not_visible` には `ids`・`kinds`)を足し、`build` に計算済みの流星群を渡せるようにし(省略時は従来どおり)、高度の基準 15° を `sky_highlights.GUIDE_MIN_ALT_DEG` に移した(`generate_report.MIN_GUIDE_ALT_DEG` は同じ値を指す)。レポートの文は変えていない(文が読む項目は変えていない。既存のテストも変えずに通った)。
- `coordinates_unverified: true` は `targets.json` の `source` に「未照合」とある19件。`false` は惑星と従来からの7件で、**照合済みという意味ではない**(記録が無い)。種類を書いていない従来からの対象(オリオン座など)は `kind: null`。
- 時刻は丸めていない(レポートは30分単位に丸めて表示)。時間帯ごとの件数の上限(4件)と、見える時間が30分より短い対象を外す決まりはレポートと同じなので、**`slots` に無い対象が「見えない」とは限らない**(見えないのは `not_visible` だけ)。
- 計算は `--json-out` のときだけ(`_explore` の `collect_highlights`)。時間: 14夜で約10〜12秒(固定キャッシュ、「見どころ(--json-out)の計算」の行)。通信は増えない。探索・順位・スコアには使っていない。

### 確かめ

- 固定キャッシュの前後比較(4つの実行): `highlights`・`notes`・第2部の項目のほか、画面・戻り値の全件・JSON が同じ。スキーマの検査に通る。
- 単体テスト(`tests/test_json_highlights.py`): 冬(11/28)と夏(7/14)の夜で、レポートの `build_sky_guide` と JSON が、同じ対象(ID・名前)・同じ時刻(始まり・終わり・最も高い時刻)・同じ高度・同じ時間帯と月・同じ「見えない」の一覧・同じ流星群。夏は銀河中心が `slots` に入り、冬は `not_visible` に `ids: ["galactic_center"]` で入る。未照合の印・`kind: null`・暗い時間帯が無い夜の `null`・`--json-out` のときだけ計算すること。

### 実物の例(2026-11-28 の夜の明け方の1件、抜粋)

```json
{"key": "dawn", "label": "明け方", "start": "2026-11-29T02:00:00+09:00", "end": "2026-11-29T05:02:10.032112+09:00", "moonlit": true,
 "items": [{"type": "planets", "name": "惑星", "in_season": null, "has_first_magnitude": true, "members": [
   {"id": "mars", "name": "火星", "kind": "惑星", "faint_in_moonlight": false, "coordinates_unverified": false,
    "start": "2026-11-29T02:00:00+09:00", "end": "2026-11-29T05:02:10.032112+09:00",
    "peak_time": "2026-11-29T05:02:10.032112+09:00", "peak_az": 162.17109741267254, "peak_alt": 67.69916696802125}, …]}, …]}
```

## 確かめられていないこと

- 全897地点での時間(Claude Code の中では以前メモリ不足で止まったため、行っていない)と、全897地点での前後比較。`FetchedOnlyCache` が読んだセルを覚える分のメモリの増え方も、全897地点では測っていない。
- 夏(銀河中心が見える時期)の天の川モードの実行の前後比較(今日の日付でしか実行できない)。単体テストだけ。近日中(第3段階)の天の川の候補がある場合の `night_rank`(MSM の夜)も単体テストだけ。
- GitHub のマシンでの時間。
- `generate_report.py` の実行(天気図・ひまわりの通信が要るため、行っていない)。レポートの見どころの文は単体テストで確かめた。
- 時間はどれも1回ずつの実測(同じPCで別のウィンドウの作業が動いていた)。前後の差は20倍以上あり、結論は変わらないと考える。

## 利用者がやること

1. (ホシビヨリの Git Bash か PowerShell、`C:\hoshibiyori`)`git push -u origin fix/milkyway-speed` → GitHub で main への PR を作る。
2. 同じウィンドウで `git push -u origin feature/concierge-interface-2` → PR の base を `fix/milkyway-speed` にする(1 をマージしたあとなら main)。
3. 同じウィンドウで `git push -u origin feature/json-highlights` → PR の base を `feature/concierge-interface-2` にする(2 をマージしたあとなら main)。マージは 1 → 2 → 3 の順。
4. (ホシビヨリの PowerShell、`C:\hoshibiyori`)全897地点の実測。続けて2回、星空・星座モード → 天の川モードの順(コンシェルと同じ)。1回目は雲量の保存が古ければ Open-Meteo へ約620回通信する(約4〜6分):
   ```powershell
   $n = (0..13 | ForEach-Object { (Get-Date).AddDays($_).ToString('yyyy-MM-dd') }) -join ','
   py -X utf8 explore_hoshibiyori.py --target stars --nights $n --json-out C:\temp\hoshi-stars-897.json
   py -X utf8 explore_hoshibiyori.py --nights $n --json-out C:\temp\hoshi-milkyway-897.json
   ```
   それぞれの最後の「実行時間の内訳: …」と「実行時間の内訳(計算): …」の行を控える。
5. (Claude Code)控えた秒を渡して「時間の目安の表に入れて」と頼む(`time_estimates.py` の `ESTIMATES` と `AGENTS.md` 第5節の表を一緒に直す。`tests/test_wait_notice.py` が食い違いを確かめる)。1.2.0 の 583.2 秒の行は「短縮の前」として残すか消すかを決める。
6. 版を上げるか(1.2.1 か 1.3.0。JSON の項目の追加があるので 1.3.0 が自然と考える)を決める。上げるなら `plugin.json` の `version` と CHANGELOG の見出し。

## コンシェル側で直すこと(書くだけ。`C:\biyori-concierge` は書き換えていない)

- 足した項目: `requested_nights[].sites[].night_rank`(その夜の中の順位、`group` ごと、`passed` だけ)、`site_index[].origin`(出どころ)、`highlights`(夜ごとの見どころ)。どれもスキーマの必須項目で、`/1` のまま。**取り出す版のスキーマで検査しているので、この版より前の出力は今のスキーマに通らない。**
- `docs/hoshibiyori-mapping.md` で直す行:
  - 31行(`site_index[]`): 「`origin`(出どころの語)は入っていない」→ 入った。ODbL の表示は `origin` が `viewpoint` の地点(と、OSM の地点と統合した `curated+viewpoint` 3地点。座標は curated 側)に付ければよい(どこまで付けるかはコンシェルで決める)。
  - 40行(`.sites[]`): `dark` の夜の `passed` の意味は、ホシビヨリの注記とスキーマにも書かれた。
  - 44行(`finals[]`・`outlooks[]`): 「候補の夜でない夜の地点には `rank` が無い」→ `night_rank` で並べられる。並びは「主軸を先 → `night_rank` → 距離」にできる。`night_rank` は夜の中の順位で、`finals`・`outlooks` の `rank`(夜をまたいだ通しの番号)とは数が違う。
  - 4章 `evidence[]`・`details` の `rank`: 候補の夜でない夜は `night_rank` を使える。
  - 5章(見どころ): 「JSON に無い」→ `highlights.by_night[night_date]` と `highlights.showers` にある。
- 「どの星や惑星が見えるかは、この予報に含まれていません」(`concierge/brief.py` 589行の `no_star_objects`、`docs/answer-voice.md` 166・187行)をやめられる条件:
  1. 出力に `highlights` があり、その夜の `highlights.by_night[night_date]` が `null` でない(古い版の出力・暗い時間帯が無い夜は今の文のまま)。
  2. 書くのは `slots[].items[].members[]` の名前と時刻(と `not_visible` の「今の時期は見えない」)だけにし、`basis.text`(基準の地点・平らな地平線の目安。地形・雲は見ていない)を必ず添える。
  3. `coordinates_unverified: true` の対象は「目安」と分かる書き方にする(または書かない)。
  4. 流星群の出現数は `zhr_note` と `caveat` を必ず添える。
  5. `slots` に無い対象を「見えない」と書かない(上限4件・30分より短い対象は入らない)。
  - あわせて `docs/answer-checks.md` 170行の `star_object` の決まり(名前を書かない)を、上の条件のときは書いてよい、に直す必要がある。
- 1モードの上限 1500 秒(仮置き)は、利用者の全897地点の実測が出てから見直せる(主軸146地点では天の川モードの計算が約10分の1になった)。

## 決めてほしいこと

1. **星空・星座モードで予報が MSM の夜の `night_rank`**: `finals` と食い違わないよう、MSM の夜は `finals` の決め方(晴れ時間が長い → 平均雲量が低い → ALR が小さい → 月の影響が小さい時間が長い)にした。利用者の決定の文「光害(ALR)が小さい → 月の影響が小さい時間が長い順」は ECMWF の夜(`outlooks`)の決め方で、今週末(11/28・11/29)のような MSM の外の夜はこちらになる。MSM の夜も ALR → 月の順にしたいなら、`finals` の `rank` とは並びが変わる(直すのは `requested_nights.evaluate` の `list_kind` の1か所)。
2. 近日中(第3段階)の銀河中心の1時刻ずつのループも、第1部と同じやり方でまとめるか(今は変えていない。夏に MSM の候補の夜があるときの時間に効く。今日は前後比較できない)。
3. 版を上げるか、上げるなら番号(上の「利用者がやること」6)。
4. 1.2.0 の 583.2 秒の時間の目安の行を、全897地点の新しい実測を入れたあとに残すか。
