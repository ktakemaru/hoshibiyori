# hoshibiyori 1.1.0 リリース準備の報告書

- 日付: 2026-11-15
- ブランチ: `release/1.1.0`(main `7c88acc` から作成)。push・PR・マージ・タグ・Release はしていない
- 指示書: `docs/release-1.1.0-instructions.md`(未追跡のまま。コミットに含めていない)
- 通信: していない(`generate_report.py`・`explore_hoshibiyori.py`・API 取得・`pip`・`gh`・`claude plugin` は実行していない)
- Python: `.venv\Scripts\python.exe` が無かったため `py` を使った

## 1. 変えたファイルと要点

| ファイル | 要点 |
|---|---|
| `.claude-plugin/plugin.json` | `version` を 1.1.0 に(`name`・`description` は不変) |
| `step5_cloud_forecast/cloud_forecast.py`・`himawari_image.py`、`step2_terrain/gsi_dem.py`、`step3_light_pollution/fetch_black_marble.py`、`step6_viewpoint_survey/fetch_viewpoints.py`、`step7_geocoding/reverse_geocode.py`、`scripts/check_setup.py` | User-Agent の版の文字列だけ `1.0.0` → `1.1.0`(名前・説明・形式は不変。各1行) |
| `CHANGELOG.md` | `[Unreleased]` の中身をそのまま `[1.1.0] - 2026-11-15` に移し、先頭に要約2行、`### Changed` の末尾に版の2項目。空の `[Unreleased]` を先頭に残した |
| `README.md` | 429 の扱い(3か所)、所要時間(2か所)、版(4か所)、探索モードに `--target stars` の案内、キャッシュの説明から「光害タイル」を外す、`scripts/`・`docs/` の行、`CLAUDE.md` の大きさ(約64KB → 約84KB)、「既知の制約(1.1.0)」の節、出典表の OSM の行に Nominatim の一括問い合わせの記録 |
| `AGENTS.md` | §5 の `generate_report.py` の所要時間(「10〜30分」「候補146件で実測約21分」)を本書の実測に置き換え。冒頭の `CLAUDE.md` の大きさを約84KB に |
| `skills/hoshibiyori/SKILL.md` | §4 の所要時間と「429 は即中止」を今の動きに。§3 の表の後に `--target stars` の1行。`CLAUDE.md` の大きさを約84KB に |
| `docs/release-1.1.0-report.md` | 本書 |

`git diff --stat main` で、コードの差分は User-Agent の版の文字列(7ファイル×1行)だけであることを確かめた。

## 2. `1.0.0` の分け方

### 1.1.0 に変えたもの(現在の版)

| 場所 | 内容 |
|---|---|
| `.claude-plugin/plugin.json` | `"version": "1.0.0"` |
| `step5_cloud_forecast/cloud_forecast.py` | `hoshibiyori-cloud-forecast/1.0.0` |
| `step5_cloud_forecast/himawari_image.py` | `hoshibiyori-himawari/1.0.0` |
| `step2_terrain/gsi_dem.py` | `hoshibiyori-terrain-horizon/1.0.0` |
| `step3_light_pollution/fetch_black_marble.py` | `hoshibiyori-lp1/1.0.0` |
| `step6_viewpoint_survey/fetch_viewpoints.py` | `hoshibiyori-research/1.0.0` |
| `step7_geocoding/reverse_geocode.py` | `hoshibiyori-research/1.0.0` |
| `scripts/check_setup.py` | `hoshibiyori-check-setup/1.0.0` |
| `README.md` | 冒頭のプラグインの案内、「できること(1.0.0、2026-10-24時点)」、「Claude Code プラグインとして使う」の位置づけ、「ステータス」 |

User-Agent は 1.0.0 の CHANGELOG で「取得処理の User-Agent のバージョンを 1.0.0 に」とまとめて上げたものなので、同じ範囲をすべて上げた。

### 変えなかったもの

| 場所 | 理由 |
|---|---|
| `CHANGELOG.md` の `## [1.0.0]` の節(見出しと「User-Agent / plugin.json を 1.0.0 に」の2項目) | 過去の版の記録 |
| `README.md` の「光害データの変更(1.0.0)」 | 過去の出来事 |
| `CLAUDE.md` の「v1.0.0 リリース準備(段階R1)」の節、光害の節 | 開発ログ(過去の記録) |
| `stargazing_spots.json` の `_note_site_type`(「README『光害データの変更(1.0.0)』を参照」) | 過去の節の名前を指している。保護領域でもある |
| `net_check.py` の User-Agent | 未追跡のファイルで、触らない指示 |
| `docs/release-1.1.0-instructions.md` | 指示書の中の記述 |
| 「公共データ利用規約 第1.0版」 | 別物の 1.0(`1\.0\.0` には当たらない) |

`.claude-plugin/marketplace.json` にはプラグインの版の欄が無かった(変更なし)。版を確かめているテスト(`tests/test_plugin_manifest.py`)は「CHANGELOG の最新の項と `plugin.json` の `version` が一致する」形で、期待値に `1.0.0` を直接書いていないため、変更は不要だった。

## 3. テストの結果

`py -X utf8 -m unittest discover -s tests`(通信なし): `Ran 499 tests` / `OK (skipped=3)`。失敗なし。

`plugin.json` と `marketplace.json` は Python の `json` で読めること、`name` が `hoshibiyori` / `hoshibiyori-marketplace`(プラグインの名前 `hoshibiyori`)のままであることを確かめた。

README の節へのリンクは `#claude-code-プラグインとして使う`・`#探索の目的を切り替える--target`(新規)・`#通信を伴う処理`(新規)の3つで、いずれも実在する見出しに対応する。

## 4. コードと文書が食い違っていた点

- README・`SKILL.md` の「429 が出たら即中止」: コード(`grid_cache.MINUTELY_RETRY_WAIT_SEC = 65.0`・`MINUTELY_RETRY_MAX = 5`、`cloud_forecast.classify_rate_limit`)では、1分の上限は65秒待って取り直す。コードに合わせて直した。`AGENTS.md` と `CLAUDE.md` は既に今の動きになっていた。
- README の「取得失敗の扱い」に、基準地点(石廊崎)の予報が取れないときの中止(`ReferenceForecastUnavailable`、explore・generate_report)と、通信の間隔の調整(`PACING_LIMIT_PER_MINUTE = 300.0`)が無かった。足した。
- README のキャッシュの説明の「光害タイル」: 光害は同梱の派生データを読むだけで、取得しない。外した。
- CHANGELOG の `[Unreleased]`(1.1.0 に移した記述)とコードの食い違いは見つからなかった(65秒・5回・300・終了コード2・基準地点の中止は一致)。

## 5. 既知の制約(README に書いた3件)と確かめた根拠

1. 見出しの「対象: 天の川銀河中心」: `explore_hoshibiyori.py` の `print_outlook_report`・最終候補の一覧は `target = get_target(TARGET_ID)`(`TARGET_ID = "galactic_center"`、`targets.json` の name は「天の川銀河中心」)を `--target` に関係なく使っている。
2. `report_courses.py`・`weekend_page.py` が `report_stars.html` に未対応: 既定の入力は `report.html` だけで、解析は「スコア N」のバッジと「(狙い目 HH:MM)」を必須にしている(`report_courses.py` 163・178行)。星空モードのカードはスコアのバッジを出さず、見頃は「(晴れ間 N時間)」(`generate_report.py` 800・805行)。
3. 「うち地形データなし」の件数のほうが大きく出る: `stage3_direction_filter` の `no_terrain_count` は、地形データの無い地点を光害の足切りの前に数えている(653行)が、通過件数 `len(finals)` は光害も満たしたものだけ。README には「光害の足切りの前に数えているため」と原因を1句添えた。

## 6. 書かなかった項目と理由

- 所要時間は本書の実測(探索 約6分/617回・約10秒/0回、レポート 約2分、約220回・約620回)だけを書いた。AGENTS.md にあった「候補146件で実測約21分」は、「10〜30分をやめ、次の実測だけを書く」に従って外した(古い測定のため)。
- `CLAUDE.md` は本文を変えていない。Grep(`429`・`即中止`・`10〜30分`・`10-30`)で当たったのは今の動きの記述と、ひまわりの429(ひまわりは今も即中止で正しい)だけだった。CLAUDE.md の「Codex対応」の節の「本ファイルは約64KB」は開発ログの過去の記述として残した。
- README の依存の説明「`numpy`(標高・光害タイルの配列処理)」の「光害タイル」は、指示の対象(キャッシュの説明)の外なので残した。次の版で「光害の派生データ」に直すかは本人が判断する。

- README の「できること」の探索モードは「候補地点146件」のままで、今回足した実測の「全897地点・約620回」(主要146件+参考751件)と並ぶ。指示の対象外なので直していない(次の版で書き分けるかは本人が判断する)。

## 7. 迷って判断したこと

- **`AGENTS.md`・`SKILL.md` の「約64KB」も約84KB に直した**(指示は README だけ)。同じ事実の古い記述で、§4 の「README と同じ古い記述があれば直す」に当たると判断した。`CLAUDE.md` の実際の大きさは 86,371 バイト。「約64KB」を書いた時点(`92920fd`)の `CLAUDE.md` は 65,261 バイトで、1024 で割る数え方だったため、同じ数え方で約84KB とした。
- **Nominatim の一括問い合わせ**: `CLAUDE.md` に記録があった(757件の候補地点DBを逆ジオコーディングで構築、curated 99件の順ジオコーディング[2026-09-06]、外部リスト62件の逆ジオコーディング[2026-09-07])。レートリミッタ(1秒1リクエスト以下)は記録に明記のある前の2つだけに書き、757件は「DBの件数」として書いた(問い合わせ回数とは記録されていない)。出典表の OSM の行に、記録にある事実と「利用方針に沿っていたかは未確認」だけを書いた。757件の日付は記録に無いため「2026-09」とした(`CLAUDE.md` の「2026-09 の Nominatim での一括ジオコーディング」の記述による)。62件の逆ジオコーディングは `reverse_geocode.py`(Nominatim)によるものとして数えた。
- `docs/` の行には追跡済みのファイルだけを書いた(未追跡の `hoshibiyori_stars_mode_instructions.md`・本書の指示書は含めていない)。`docs/examples/` は空でなかった(`README.md` と解説JSONの訂正例2つ)ので記述を残し、中身に合わせて「見本」→「解説JSONの訂正例」に直した。
- コミットは3つ(版の更新 / CHANGELOG / README・文書・本書)。途中で4つに分けていたものを、push 前に `git reset --soft` で文書と本書を1つにまとめ直した。
- `cloud_forecast.py` の版の更新で、最初に使った `sed` が改行コード(CRLF)を変えて全行の差分になったため、取り消して1行だけを書き換え直した(コミットの差分は1行)。

## 8. このあと本人が行うこと

指示書の §7(push → PR → CI → Squash and merge → タグ v1.1.0 → Release → `claude plugin update` での確かめ)。
