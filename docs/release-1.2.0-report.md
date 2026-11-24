# ホシビヨリ 1.2.0 リリースの準備の報告書

作成日: 2026-11-24 / ブランチ `release/1.2.0`(main `454f317` から) / 指示書 `docs/release-1.2.0-instructions.md`

通信・探索(`explore_hoshibiyori.py`)・レポートの生成(`generate_report.py`)はしていない(`--estimate` も実行していない)。push・PR・マージ・タグ・GitHub のリリースもしていない。

## 1. 始める前の状態(第 0 部)

- 追跡しているファイルの変更なし。main、`454f317fd7ee43b263921aaad9c1424700cf69c3`(2026-11-24 20:43:21 +0900、`Fix/sky highlights followup (#40)`)。`plugin.json` の `version` は 1.1.0。
- テスト: `Ran 678 tests in 136.545s` / `OK (skipped=3)`(この PC、Python は `py`)。
- タグの先頭は `v1.1.0`。`v1.2.0` は手元に無い(通信しないので、GitHub 側は見ていない)。
- 止まる条件に当たるものは無かった。

## 2. できたこと

| 部 | commit | 内容 |
|---|---|---|
| 第 0 部 | `c834690` | 指示書を `docs/release-1.2.0-instructions.md` に写した(元と 1 バイトも違わない) |
| 第 1 部 | `810dead` | 流星群の行の表示の直し(`generate_report.py`・テスト・CHANGELOG 1 行) |
| 第 2 部 | `a0b7e9b` | 版を 1.2.0 に(plugin.json・CHANGELOG・README・AGENTS.md・User-Agent 7 ファイル) |
| 第 3 部 | この報告書の commit | `docs/v1.2.0-release-notes.md`(リリースの文の下書き)と、この報告書 |

### 第 1 部

- 直した所は、文を作る `generate_report.guide_shower_text` だけ。月・惑星・星と同じ決まりの関数 `winter_milkyway.is_displayable` をそのまま使った(新しい値・決まりは足していない)。値(`radiant_start`・`radiant_end`)は変えていない。
- みずがめ座 η 流星群(2027-05-06 の夜)の文:
  - 前: 「極大の夜(5月6日の夜)に放射点が高度20°以上に出ているのは翌03:00〜翌03:00。月は出ていない(輝面比0%)。…」
  - 後: 「極大の夜(5月6日の夜)に放射点が高度20°以上に出ているのは30分より短い。月は出ていない(輝面比0%)。…」
- 1 分ごとに計算すると、この夜に高度 20° 以上なのは 03:02 から、暗い時間帯の終わりの 03:14 まで(約 13 分)で、文と合っている。
- 一度も高度 20° 以上に出ない夜は、すでに「極大の夜(○月○日の夜)には放射点が高度20°以上に出ない」と書く作りだったので、変えていない。指示書の「放射点**は**」とは助詞だけが違う(既存のテストが今の文を確かめている)。
- 今ある行は変わらない: この先 1 年の 7 群を直す前の関数で計算し、同じ決まりに当たるのはみずがめ座 η だけ。ふたご座の「20:00〜翌05:00」はテストでも確かめた。

### 第 2 部

- `plugin.json`: `version` を 1.2.0 に。`description` に「レポートには今の時期の見どころ(惑星・季節の星座・流星群)も出す。」を足した。
- `marketplace.json`: 版の欄が無く、説明は今も合っているので変えていない。
- `CHANGELOG.md`: `[Unreleased]` を `[1.2.0] - 2026-11-24` の節にし、空の `[Unreleased]` を残した。1.1.0 と同じ形で、要約 3 行と、版・User-Agent の 2 項目を足した。途中の言い方を 2 か所整えた(「2026-11-16 追記」を外す、「今と同じ」→「変わらない」)。同じことの重なりは見つからなかった。項目の順(Changed・Added・Fixed)は元のまま。
- `README.md`: 版 4 か所(見出し 1 つを含む)、見出し「既知の制約(1.2.0)」とその中身、「1.2.0 では未実測」、流星群の説明に 1 句、`docs/` の行。
- `AGENTS.md`: 第 5 節の「1.1.0 では未実測」を 1.2.0 に(1 か所だけ)。`SKILL.md`・`CLAUDE.md` には、今の版を指す番号が無いので変えていない。
- 指示書の材料と変えて書いた所: 「一覧と見込みは光害の小さい順」は、コードでは**星空・星座モードの見込み**の順(`outlook_rank_key`)。近日中は晴れ時間が先、天の川モードはスコア順なので、README にはコードのとおりに書いた。

## 3. テストの結果

| とき | 件数 | 結果 |
|---|---|---|
| 変更前 | 678 | `Ran 678 tests in 136.545s` / `OK (skipped=3)` |
| 第 1 部 | 680 | `Ran 680 tests in 137.641s` / `OK (skipped=3)` |
| 第 2 部 | 680 | `Ran 680 tests in 151.428s` / `OK (skipped=3)` |
| 第 3 部(文書だけ) | 680 | `Ran 680 tests in 142.449s` / `OK (skipped=3)` |

- 足したもの 2 件(`tests/test_sky_highlights.py`): `RenderTests.test_short_radiant_window_has_no_times`(手で与えた値。天文暦が無くても動く)、`AstronomyTests.test_shower_text_of_short_and_usual_windows`(2027 年 5 月・2026 年 12 月・一度も出ない南緯 40° の夜)。
- **書き換えた既存のテスト: 無し。** 版の番号は `tests/test_plugin_manifest.py` が「CHANGELOG の最新の項と `plugin.json` の一致」で確かめる形で、番号を直接書いていない。

## 4. 版の番号を直した場所

| 場所 | 差分 |
|---|---|
| `.claude-plugin/plugin.json` | `version`(ほかに `description` の 1 文) |
| `scripts/check_setup.py` | `hoshibiyori-check-setup/1.1.0` → `1.2.0`(1 行。版の文字列だけ) |
| `step2_terrain/gsi_dem.py` | `hoshibiyori-terrain-horizon/`(同上) |
| `step3_light_pollution/fetch_black_marble.py` | `hoshibiyori-lp1/`(同上) |
| `step5_cloud_forecast/cloud_forecast.py` | `hoshibiyori-cloud-forecast/`(同上) |
| `step5_cloud_forecast/himawari_image.py` | `hoshibiyori-himawari/`(同上) |
| `step6_viewpoint_survey/fetch_viewpoints.py` | `hoshibiyori-research/`(同上) |
| `step7_geocoding/reverse_geocode.py` | `hoshibiyori-research/`(同上) |
| `README.md` | 冒頭の案内、「できること」の見出しと日付、「位置づけ」、「未実測」の行、「既知の制約」の見出し、「ステータス」 |
| `AGENTS.md` | 第 5 節の「未実測」の行 |
| `CHANGELOG.md` | `[1.2.0]` の節 |

User-Agent の 7 ファイルは、どれも差分が 1 行(`git diff --numstat` で `1 1`)で、変わったのは版の文字列だけ。改行コードも変わっていない。

`1.1.0` が残っている場所(追跡しているファイル):

- `CHANGELOG.md`: Keep a Changelog の URL と、1.1.0 の節(見出しと 2 項目)
- `README.md`: `docs/` の行の「1.1.0 と 1.2.0 のリリース準備」(過去の報告書の名前)
- `tests/test_concierge_interface.py`・`test_explore_json.py`・`test_explore_scanned_nights.py`: JSON の見本に渡す値
- `docs/` の過去の指示書・報告書と、今回の指示書・報告書・リリースの文(「1.1.0 と同じです」)

## 5. 変えていないことの確かめ

- `git diff main --numstat`: `step2_terrain`・`step3_light_pollution`・`step5_cloud_forecast`・`step6_viewpoint_survey`・`step7_geocoding`・`scripts` の差分は、上の 7 ファイルの `1 1` だけ。`step1_astronomy`(`targets.json`・`meteor_showers.json` を含む)・`step4_moonlight`・`explore_hoshibiyori.py`・`explore_json.py`・`schemas/`・`stargazing_spots.json`・`curated_spots.json` に差分は無い。
- `--json-out` のスキーマの名前と項目は変えていない(`version` の値は `plugin.json` から入るので 1.2.0 になる)。
- v1.1.0 と比べても、`step2_terrain`・`step3_light_pollution`・`step4_moonlight`・`step5_cloud_forecast`・`step7_geocoding`・`stargazing_spots.json`・`curated_spots.json` の差分は User-Agent の 1 行ずつだけ。スコア式と閾値の行も変わっていない(リリースの文の「変えていないこと」の根拠)。
- `AGENTS.md` は 27,735 バイト(変更前と同じ)。
- 追跡していないファイル(`net_check.py`、過去の指示書 2 つ、ログ 2 つ、地平線の CSV 2 つ)には触れていない。

## 6. 確かめられていないこと

- 実通信での探索・レポートの生成と、直したあとのレポートの実物の見た目。流星群の直しは、単体テストと、手元の天文暦を使った関数の呼び出しだけで確かめた。
- GitHub の CI(Python 3.13)。PR で確かめる。
- プラグインの更新が届くこと(7 章の 6)。`claude plugin validate` も実行していない。
- GitHub 側に `v1.2.0` のタグやリリースが無いこと。
- 流星群の「30分より短い」は、15 分ごとの計算の点で判定する。境目の夜では、本当の長さが 30 分を少し超えることがある(端ごとに最大で約 15 分)。30 分ちょうどでも丸めると同じ時刻になる夜は、決めた文のとおり「30分より短い」と出る。この先 1 年で文が変わるのはみずがめ座 η だけで、この夜は合っている。
- `docs/long-run-1124-report.md` の 7・13・14 章に書いた「確かめられていないこと」は、そのまま残っている(利用者に関係するものは README の「既知の制約(1.2.0)」に入れた)。

## 7. 利用者がやること

「Claude Code」は、この Claude Code のウィンドウ。行頭の `!` も打つ。1 行ずつ打ち、Claude の返事や画面の文章は貼り付けない。

1. **push(Claude Code)**: `! git push -u origin release/1.2.0`
   → `[new branch]` と出れば成功。
2. **PR とマージ(ブラウザの GitHub)**:
   1. `https://github.com/ktakemaru/hoshibiyori/compare/main...release/1.2.0` を開く(base `main` ← compare `release/1.2.0`)→「Create pull request」。
   2. 「tests」のチェックが緑になるのを待つ → 「Squash and merge」→「Confirm squash and merge」。
   → 「Merged」(紫)になれば成功。**マージのあとに直しが要るときは、このブランチを使い回さず、main から新しいブランチを作る**(2026-11-24 に、使い回して衝突したため)。
3. **手元を main に(Claude Code)**: `! git switch main` → `! git pull`
   → `Fast-forward` と、変わったファイルの一覧が出れば成功。
4. **タグ(Claude Code)**:
   1. `! git log --oneline -1` → 先頭が release/1.2.0 のマージの commit(題名は PR の題名、例「Release/1.2.0 (#41)」)であることを確かめる。違えば先に進まない。
   2. `! git tag v1.2.0` → 何も出なければ成功。
   3. `! git push origin v1.2.0` → `[new tag]` と `v1.2.0 -> v1.2.0` が出れば成功。
5. **GitHub のリリース(ブラウザ)**:
   1. リポジトリの Code タブの右側の列にある「Releases」→「Draft a new release」(または `https://github.com/ktakemaru/hoshibiyori/releases/new`)。
   2. Choose a tag で `v1.2.0`(新しく作るのではなく、今あるもの)を選ぶ。題名に `v1.2.0`。
   3. 本文に `docs/v1.2.0-release-notes.md` の中身を全部貼る → 「Publish release」。
   → Releases の先頭が `v1.2.0` で「Latest」の印が付けば成功。
6. **プラグインの更新の確かめ(PowerShell)**: `claude plugin update hoshibiyori@hoshibiyori-marketplace`
   → 1.2.0 に更新されたと出れば成功。1.1.0 のときの手順は `docs/release-1.1.0-instructions.md` の §7 の 5(追跡していないファイル。`docs/release-1.1.0-report.md` の 8 章から指している)と、README の「更新」。
7. **Codex 側**: Codex で別のフォルダを使っているなら、そのフォルダの PowerShell で `git switch main` → `git pull`。`git log --oneline -1` が 4 の 1 と同じなら成功。
8. **追跡していないファイルの片付け(任意)**: 一覧は `docs/long-run-1124-report.md` の 8 章。`net_check.py` は消してよい、過去の指示書 2 つは commit の候補、地平線の CSV 2 つは残す。この作業では消していない・commit していない。

## 8. 利用者に決めてほしいこと

1. **タグの種類**: `v1.1.0` は注釈つきのタグ(`git tag -a`)。7 章の 4 は指示書のとおり注釈なしの `git tag v1.2.0`。そろえるなら、4 の 2 の代わりに `! git tag -a v1.2.0 -m "v1.2.0"`。決めなければ、指示書のとおりでよい。
2. `docs/long-run-1124-report.md` の 10 章に残っている項目(空の開け具合を順位に使うか、仮の値、星・星団の座標の照合、標高の食い違いなど)。リリースの前に決める必要は無い。

## 9. 次の版の候補

- 見込みの一覧・カレンダーに「気軽コース」の考え方を入れる(離島が上位に並ぶ件)。
- 空の開け具合を、星空・星座モードの順位に使うか。
- 星・星団の座標と、組・1 等星の印の照合。4 月こと・みずがめ η・オリオン・しし座流星群の極大の日の照合。
- ダイヤモンド富士・パール富士、月と惑星の接近、月食(材料は `docs/long-run-1124-report.md` の 12 章)。
- 地形データの無い 809 地点の地平線の計算。春〜夏の天の川モードで、0° の判定が見頃と順位にどう影響するかの確かめ。
- 見えている時間帯(対象・流星群の放射点)の始まりと終わりを、15 分の点ではなく細かく求める(6 章の境目の夜)。
- 見積もりで「通信あり」が余分に出る場合の直しと、未実測の作業の実測。
- `CHANGELOG.md` の 1 項目が長いので、書き方を短くする。
