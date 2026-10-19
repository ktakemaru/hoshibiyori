---
name: hoshibiyori
description: '「今週末の星空撮影に適した場所は」「◯◯の星空」「天の川はいつ見える」「星景撮影の天気」「星空ガイドを作って」のように、星空・天の川・星景写真の撮影に適した日と場所、地点の星空の見え方を聞かれたときに使う。月・雲量・光害・地形で夜と場所を絞り、星空シミュレーター付きの星空ガイドを作る。手順・閾値・数値の正本はプラグイン直下の AGENTS.md。'
when_to_use: '星空・天の川・星景写真の撮影計画、月明かりと雲量の見込み、地点ごとの星空ガイド(シミュレーター付き)、今週末の撮影候補ページ、天気図の解説の更新。'
allowed-tools:
  - Bash(HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}" python3 -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/check_setup.py")
  - Bash(HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}" python3 -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/moon_nights.py" *)
  - Bash(HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}" python3 -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/report_courses.py" *)
  - Bash(HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}" python3 -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/sky_lookup.py" *)
  - Bash(HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}" python3 -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/check_sky_guide_text.py" *)
---

# ホシビヨリ(星景撮影の天気予報)

このスキルは**薄い層**です。手順・閾値・数値の正本は `${CLAUDE_PLUGIN_ROOT}/AGENTS.md` で、ここには節番号で案内するだけにしています(重複して書かない)。食い違いを見つけたら黙って直さず、ユーザーに報告します。

## 0. 最初にやること

1. **`${CLAUDE_PLUGIN_ROOT}/AGENTS.md` を Read する。** プラグイン直下の `AGENTS.md`・`CLAUDE.md` は自動では読み込まれません。設計の経緯は `${CLAUDE_PLUGIN_ROOT}/CLAUDE.md`(約64KB)にあり、必要な節だけ読みます(どの節かは AGENTS.md §2 の表が案内します)。
2. `${CLAUDE_PLUGIN_ROOT}` や `${CLAUDE_PLUGIN_DATA}` が**展開されずそのまま見えている**、またはファイルが見つからないとき:
   - カレントに `hb_paths.py` と `AGENTS.md` があれば、そのフォルダをルートとして使う。
   - 無ければ Glob で `~/.claude/plugins` 配下から `hb_paths.py` を探し、見つかったフォルダを使ってよいかを**ユーザーに確認する**(黙って決めない)。
   - データ領域が決まらないときは、別の場所へ書かずに止めて確認する。

## 1. パスと環境変数

- `${CLAUDE_PLUGIN_ROOT}`(コードの置き場所。更新のたびに変わる)と `${CLAUDE_PLUGIN_DATA}`(更新後も残るデータ領域)は、Bash の環境変数としては入らず、**このスキル本文の文字列として置換**されます。コマンドの先頭に展開済みの値を付けて渡します。
- **読み替え(1文)**: AGENTS.md の `scripts/…`・`generate_report.py` などは `${CLAUDE_PLUGIN_ROOT}/` からの相対とし、AGENTS.md の `report.html`・`out/`・`weather_map_commentary.json`(とその `images` の相対パス)は、プラグイン利用時は「リポジトリ直下」ではなく**データ領域 `${CLAUDE_PLUGIN_DATA}` の下**と読み替える(`HOSHIBIYORI_DATA_DIR` を付けて実行する。AGENTS.md §4)。静的データ(`areas.json`・`stargazing_spots.json`・horizon CSV など)は `${CLAUDE_PLUGIN_ROOT}` 側のままです。
- **bash**: `HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}" python3 -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/check_setup.py"`
- **PowerShell**: `$env:HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}"; py -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/check_setup.py"`(AGENTS.md §8: 出力を `>` や `|` で受けない)
- **Python**: `${CLAUDE_PLUGIN_DATA}/venv` があればそれ(Windows は `venv/Scripts/python.exe`、それ以外は `venv/bin/python`)。無ければシステムの `py`(Windows)/`python3`。Windows では bash でも `py` を使う(`python3` は Microsoft Store のスタブで失敗することがある)。**常に `-X utf8` を付ける。**

## 2. セットアップ(初回・不足があるとき)

1. `scripts/check_setup.py` を実行する(通信しない)。「データ領域」の表示も確認する。
2. NG があれば結果をそのまま示し、**承認を得てから**次を行う(PyPI へ通信する)。自動では入れない(SessionStart フックは使わない)。
   - `python3 -m venv "${CLAUDE_PLUGIN_DATA}/venv"`(Windows は `py -m venv …`)
   - venv の python で `-m pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"`
   - Playwright は任意(AGENTS.md §4)。
3. 天文暦 `de421.bsp`(約17MB)は、無い場合の初回実行時に JPL から自動ダウンロードされ、データ領域に保存される。通信なので承認を得る(AGENTS.md §4)。

## 3. 質問と手順の対応

| 聞かれたこと | 従う手順 |
|---|---|
| 適した日と場所(今週末・直近◯日) | AGENTS.md **§11**(材料は今日の `report.html`。今日でなければ §5 の承認を得て生成を頼む) |
| ◯◯の星空・星空ガイドを作って・天の川はいつ見える | AGENTS.md **§10**(シミュレーター付きのガイド) |
| 今週末の撮影候補をHTMLで | AGENTS.md §11 の6(`scripts/weekend_page.py`) |
| 月の条件だけ知りたい | `scripts/moon_nights.py`(通信なし。AGENTS.md §11 の1) |
| 天気図の解説を更新したい | AGENTS.md **§12** |

## 4. 通信・長時間の前の承認

次の前に、**所要時間・通信先・回数・書き込み先(データ領域の絶対パス)**を伝えて承認を得る(AGENTS.md §5・§7)。

- `generate_report.py`(10〜30分・Open-Meteo 約220回ほか。詳細は §5)。`allowed-tools` には含めていない。
- `--cloud fetch --allow-network`(§10。先に `--estimate`)、天気図の取得(§12、気象庁)、PyPI、JPL。
- **HTTP 429 は即中止してユーザーに報告する。**別経路・リトライの連打・キャッシュの手作りで回避しない(§7)。

## 5. 守ること

- 星空ガイドは**毎回シミュレーター付き**で作る。**HTML は手で書かない**(§10)。
- **数値・スコア・閾値は自分で書かない・変えない。**数値はスクリプトの出力から取る。既存ロジックを推測で置き換えない(§6 保護領域)。
- 独自の予報(通過時刻の予測など)を書かない(§11・§12)。
- yamabiyori のコードを参照・コピーしない(§3)。

## 6. 回答の書き方

- **根拠**: どの地点・夜・データによるかを示す。
- **取得時刻**: `report.html` の「生成日時」(JST)を添える。今日でなければその内容で答えない(§5・§11)。
- **不確実性**: 雲量は全天の平均で方角は分からない(§10)。中期見込みの雲量は晴天率の参考で、足切りには使っていない(§11)。ひまわり画像は参考表示で、閾値は暫定(§5)。光害・ボートル値は目安。候補が無いコースは、出力の理由をそのまま伝え、空欄を埋めない(§11)。
- 出典・免責は、レポートやガイドに含まれるものを省かない。

## 7. 使わないスクリプト(保守・開発用)

ユーザーの明示的な依頼がない限り実行しない。

- リポジトリ直下: `static_ranking.py`、`classify_site_darkness.py`、`run_area_classification.py`、`merge_external_spots_20260907.py`、`check_external_spots_dedup.py`、`fix_curated_external_prefecture_20260907.py`
- `step2_terrain/precompute_terrain.py`・`step2_terrain/horizon_profile.py`、`step3_light_pollution/run_5points.py`、`step6_viewpoint_survey/`、`step7_geocoding/`、`step1_astronomy/run_seasonal_verification.py`、`step4_moonlight/run_verification.py`、`scripts/extract_sky_guide_sample.py`
- `tests/`(プラグイン利用時は実行しない)

## 8. 完了時

成果物(`report.html`・`out/…`)の**保存先を絶対パスで伝える**。共有するときは、まずファイルを直接送る方法を案内する(AGENTS.md §9)。
