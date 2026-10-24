# 段階R1: v1.0.0 リリース準備

ブランチ `stageR1`。push・タグの push・リリースの公開・履歴の書き換えはしていない。
**ライセンス上クリアかどうかは断定しない。** 以下は「一次情報で確認した事実」「確認できなかった点(未確認)」「本人が決める点」に分けて書く。

## 0. 分岐元について(保守的に判断した点)
指示の分岐元 `stageLP3b` は、ローカルにもリモート(`git ls-remote`)にも無かった。直近の作業ブランチ `stageLP3`(`278a97f`。`main` を祖先に含む)から分岐した。
`stageLP3b` が別の場所にあるなら、このブランチを付け替える必要がある(本人が決める点 1)。

## 1. 変更の記載
- README に「光害データの変更(1.0.0)」の節を追加した。「当初 Lorenz 氏の Light Pollution Atlas を検討・使用していたが、ライセンスが不明瞭なため、NASA Black Marble(VNP46A4)由来の自前計算に変更した。以前のコミットには旧データが含まれる」の趣旨。
- CHANGELOG の 1.0.0 の項(Changed)にも同じ趣旨を書いた。
- 履歴は書き換えていない。

## 2. 出典・ライセンスの監査(確認日 2026-10-24)

README の出典表を「提供元・条件(ライセンスと URL)・必要な表示・確認日」の 5 列に改めた。各行の根拠は次のとおり。

### 2-1. 一次情報で確認した事実

| 対象 | 確認したページ | 確認した内容 |
|---|---|---|
| (a) Open-Meteo | https://open-meteo.com/en/terms 、https://open-meteo.com/en/licence | 無料APIは「非商用に限る」(1日1万回・1時間5千回・1分600回未満)。商用の例は「購読・広告のあるサイトやアプリ」「商用製品・宣伝活動」。データは CC BY 4.0。表示は「データを表示する所の近くに Open-Meteo へのリンク」(例「Weather data by Open-Meteo.com」)、ライセンスへのリンク、変更した旨。元データとして JMA(JMA の条件)と ECMWF(CC BY)を列挙。規約ページに更新日の表示なし。応答のキャッシュについての記載なし |
| (b) 国土地理院 | https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html 、https://maps.gsi.go.jp/development/ichiran.html | コンテンツ利用規約は令和7年11月20日改正、公共データ利用規約(第1.0版)に準拠。出典の記載が必要(例「出典：国土地理院ウェブサイト(URL)」)、加工した場合は加工した旨を別に記載、国土地理院が作成したかのような公表は不可。地理院タイル一覧で、標高タイル(基盤地図情報数値標高モデル)は「出典の記載のみで(申請なく)利用可能なもの」。**テキスト形式の標高タイルは令和6年10月から更新停止**(本ツールの `gsi_dem.py` はテキスト形式を読む。ライセンスの問題ではないが、データが古いままになる) |
| (c) 気象庁 | https://www.jma.go.jp/jma/kishou/info/coment.html | 公共データ利用規約(第1.0版)に準拠。出典の記載が必要(例「出典：気象庁ホームページ(当該ページのURL)」)、加工した場合はその旨を別に記載。一部のコンテンツは個別法令(気象業務法第17条の予報業務の許可、第23条の警報の制限)による制約あり。ページ全体の更新日の表示なし |
| (d) OSM | https://www.openstreetmap.org/copyright 、https://osmfoundation.org/wiki/Licence/Attribution_Guidelines(2026-09-10 編集) | データは ODbL。改変・組み込んだデータを配布する場合は同じライセンス。データベースとして配布する場合は、OSM への帰属と ODbL の本文かリンクを、データ内か利用者が見る場所(README 等)に置く。「© OpenStreetMap contributors」は許容される表記 |
| (d) Nominatim | https://operations.osmfoundation.org/policies/nominatim/ | 最大1リクエスト/秒、識別可能な User-Agent(ライブラリ既定のものは不可)、結果のキャッシュ必須、大量のジオコーディングは推奨しない(小規模の一回限りは追加条件つきで可)、格子状の逆ジオコーディングなどの系統的な問い合わせは禁止、帰属表示、ODbL(継承)。結果の保存についてはキャッシュ必須以外の記載なし。更新日の表示なし |
| (e) NASA Black Marble | https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance(2026-10-21 更新)、https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A4/ | NASA主導ミッションのデータは既定で CC0(制限なし)、引用を強く推奨。製品ページの推奨引用は「NASA VIIRS Land Science Investigator-led Processing System. (2025). VIIRS/NPP Lunar BRDF-Adjusted Nighttime Lights Yearly L3 Global 15 arc second Linear Lat Lon Grid [Dataset]. NASA Level 1 and Atmosphere Archive and Distribution System Distributed Active Archive Center. https://doi.org/10.5067/VIIRS/VNP46A4.002」。製品の論文 Román et al. (2018) も掲載。**以前の表記「NASA LAADS DAAC」を推奨表記に直した**(README・レポートのフッター) |
| (f) Skyfield | https://github.com/skyfielders/python-skyfield/blob/master/LICENSE | MIT License |

### 2-2. 監査で直したもの
- レポートのフッター(`generate_report.py`): Open-Meteo の表示を「Weather data by Open-Meteo.com」(リンク)+CC BY 4.0 へのリンク+「雲量を加工して視界遮蔽雲量を算出」に。天気図を「出典：気象庁ホームページ (https://www.jma.go.jp/bosai/weather_map/)」の形に(以前はトップページへのリンクのみで、規約の例の「当該ページのURL」になっていなかった)。ODbL へのリンクを追加。
- Black Marble の引用(`lp_source.BM_CITATION`・README)を製品ページの推奨表記に合わせた。
- README に「データファイルのライセンス(MIT とは別)」の節を追加し、OSM 由来のデータを含むファイルは ODbL に従い、© OpenStreetMap contributors の表示が必要と明記した(対象: `stargazing_spots.json`、`curated_spots.json`、`step7_geocoding/curated_spots_geocoded.json`、`stargazing_spots.bm.json`、`step6_viewpoint_survey/viewpoints_kanto.json`、`step7_geocoding/candidate_sites.db`、`step7_geocoding/cross_dup_candidates_raw.json`、`step7_geocoding/pending_deletions_round2.json`)。

### 2-3. 未確認の点(断定しない)
1. **Open-Meteo の「非商用」の範囲**: 本ツールは個人利用で広告・購読はないが、公開リポジトリのコードを第三者が商用で使う場合の扱いは利用者側の問題で、本ツールとしては判断していない。README に「無料APIは非商用に限る」と明記した。
2. **Open-Meteo の元データ(JMA)の条件**: Open-Meteo のページは JMA の条件へのリンクを挙げるだけで、別途の表示が必要かは書いていない。本ツールは「気象庁MSM・ECMWF IFSの数値予報を配信」と書いているが、JMA の条件そのものは確認していない。
3. **気象庁の天気図・ひまわりの自動取得**: 利用規約に、プログラムによる自動取得の可否・頻度についての記載が見当たらなかった。気象庁の別ページ(過去の気象データのダウンロード)には「自動化ツール等による過度のアクセスはお控えください」とある。本ツールは1回の実行で天気図1セッション・ひまわりのタイル最大12枚(キャッシュあり)だが、可否は未確認。
4. **地理院タイルの取得量**: 利用規約・タイル一覧に、プログラムでの大量取得についての記載は見つからなかった(タイル一覧は長く、標高タイルの項と冒頭は確認したが全文の精査はしていない)。本ツールはキャッシュ・小休止・識別可能な User-Agent で取得している。
5. **OSM 由来のデータが ODbL の「派生データベース」にあたるか**: 量と利用の仕方による。判断はしていない。安全側に ODbL に従うものとして README に書いた。
6. **Nominatim の利用方針との整合(過去の作業)**: 2026-09 に逆ジオコーディング 757 件・順ジオコーディング約100件+62件を、1秒1件以下・キャッシュ・識別可能な User-Agent で行った記録がある(CLAUDE.md)。格子状ではないが、「大量のジオコーディングは推奨しない」に対して問題ないかは未確認。
7. **DE421 の利用条件**: JPL の一次情報を見つけられなかった。パブリックドメインとして扱われているという二次情報(Debian のパッケージの copyright ファイルに引用された JPL 職員のメール)のみ。README の旧表記「パブリックドメイン(NASA/JPL)」は断定をやめ「未確認」に改めた。
8. **curated(Web調査)の調査先サイトの利用条件**: 地名と座標(Nominatim)だけを収録し、説明文は独自に要約したと記録されているが、各サイトの条件は個別に確認していない。
9. **Duriscoe et al. 2018 の CC BY**: 段階LP1(2026-10-23)で確認したもので、今回は再確認していない。

### 2-4. 外部リスト(`external_spots_20260907.csv`)の出典
- 調べたもの: コミット履歴(初回コミット `2c6bacf` で追加、以降は変更なし)、`merge_external_spots_20260907.py`・`check_external_spots_dedup.py` の説明文、`logs/run_merge_external_spots.log`、CLAUDE.md。
- 分かったこと: 「ユーザーが別システムで収集した『場所名+座標』のみのリスト100件」「他システムから入手した」とだけ記録されている。CSV の列は「場所名」「位置情報」の2列で、出典の列・URL は無い。ログにも出典の記載は無い。
- **出典不明**(取り込み元の名称・URL・条件の記録が無い)。README の出典表にも「出典不明」と書いた(本人が決める点 3)。

## 3. バージョン
- `.claude-plugin/plugin.json` の `version` を 1.0.0 にした。`marketplace.json` には version の項目が無い。ほかにバージョンを持つファイルは README の記載のみ(3か所を更新)。
- **変えなかったもの**: 各取得処理の User-Agent の `/0.1`(`gsi_dem.py` など)。製品のバージョンではなく外部サービスへの識別名で、変える必要はないと判断した(本人が決める点 6)。`PROVENANCE.json` の `"version": "2"` は Black Marble のデータのコレクション番号で、無関係。
- CHANGELOG に `## [1.0.0] - 2026-10-24` の項(Changed / Added / Removed / Fixed)を作った。CHANGELOG の冒頭に「main にマージされた変更だけを書く」とあるが、この項は未マージ。日付はマージ・タグ付けの日に合わせて直す必要がある(本人が決める点 4)。
- README の「ステータス」を 1.0.0 に合わせ、「個人の星景撮影計画のために数値予報を整理するツールで、公開サービスではない」と、光害が未較正の相対指数である旨を書いた。免責の節はそのまま残した。
- `tests/test_plugin_manifest.py` に「CHANGELOG の最新の項と `plugin.json` の version が一致する」テストを追加した。
- タグ `v1.0.0` はローカルに作成した(第4節の確認がすべて通った後のコミットに付けた)。push していない。

## 4. 確認

| 項目 | 結果 |
|---|---|
| 全テスト | `py -X utf8 -m unittest discover -s tests` → `Ran 435 tests` / `OK (skipped=3)`(LP3 の 434 件に、バージョン一致のテスト1件を追加) |
| `generate_report.py` 通し実行(1回目、既定の bm) | 成功(終了コード0)。14.3分。取得セル190件・API呼び出し190回・失敗0件。MSM圏内0夜 / ECMWF圏内9夜(無月なし5夜)。見込みの候補1038件。**この実行はフッターの修正前のコードで始めた** |
| 通し実行(2回目、最終のコード) | 成功(終了コード0)。9.6分。API呼び出し0回(1回目のディスクキャッシュ190件を使用)・失敗0件。`report.html` に、Open-Meteo の「Weather data by Open-Meteo.com」・CC BY 4.0 と ODbL へのリンク・天気図ページの URL・Black Marble の推奨引用・相対指数と順位差の注記が入り、「Lorenz」「mag/arcsec」は0件であることを確認 |
| `scripts/report_courses.py`(既定の bm で `report.html` を読む) | 終了コード0。近日中(MSM)の夜が無いため、両コースとも「候補なし」(理由つき)。**bm のカードが実データで並ぶ状態は今回も確認できていない**(合成データのテストのみ) |
| プラグインの定義 | `claude plugin validate .`(Claude Code 2.1.309)→「Validation passed with warnings」、終了コード0。警告2件: ルートの CLAUDE.md はプラグインの文脈として読まれない(想定どおり。手順の正本は SKILL.md→AGENTS.md)、アイコンが無い(ICON_MISSING)。`claude plugin validate .claude-plugin/marketplace.json` → 通過 |
| トークン | 環境変数 `EARTHDATA_TOKEN` の値(設定済み)を、追跡中のファイルと全履歴(`git log --all -p`)で検索 → **検出なし**。`ghp_`・`sk-`・`AKIA`・JWT 形式・`Bearer <長い文字列>` の形も検出なし。`password`・`secret`・`api_key` は `.gitignore` の見出し1件のみ |
| 個人情報 | 追跡中のファイルのメールアドレスは、プラグイン定義の `ktakemaru@users.noreply.github.com`(GitHub の非公開用アドレス)と、CLAUDE.md の Lorenz 氏の公開アドレス(著者への確認先として記載)のみ。ユーザーのホームフォルダのパス・自宅などの記載は検出なし。**コミットの作成者情報には個人のメールアドレス(`takemaru@...`)が過去47+26件で使われている**(公開済みの履歴。書き換えはしていない。本人が決める点 11) |

ログは リポジトリ外の `C:\hoshibiyori-archive\r1-20261024\`(`generate_report_bm.log`・`generate_report_bm_2.log`)に置いた。

## 5. 本人が決める点
1. **分岐元**: `stageLP3b` が見つからなかったため `stageLP3` から分岐した。これでよいか。
2. **履歴に残る旧データ**: 以前のコミットに Lorenz 氏由来の値(LPI・mpsas・ボートル近似)が残る。README に明記したうえで残すか。著者への利用可否確認をするか。
3. **外部リストの出典(出典不明)**: `external_spots_20260907.csv` と、それから作った `curated_external` 62件(`stargazing_spots.json`)を、出典不明のまま 1.0.0 に含めるか。取り込み元が分かれば README に記載する。
4. **CHANGELOG の日付と「main にマージされた変更だけ」の方針**: 1.0.0 の日付を、マージ・タグの日に合わせるか。
5. **OSM 由来のデータの扱い**: README に ODbL と明記した。さらに、データを別ファイル・別フォルダに分けるか(案は下の 5-1。実行していない)。
6. **User-Agent の `/0.1`** を 1.0 に揃えるか。
7. **現行ファイルに残る Lorenz 氏由来の個別の値**(段階LP3で外さなかったもの): 開発ログ・検証記録の中の値。`CLAUDE.md`(閾値の経緯の LPI 値など)、`explore_hoshibiyori.py` のコメント(LPI 4.93・6.49)、`step4_moonlight/run_verification.py`(石廊崎 21.73 mag/arcsec²)、`tests/test_lp_source.py`(菜の花台の 6.49 をテスト用の値に使用)、`logs/*.log`(`run_merge_external_spots.log` に62件、`explore_run_*761.log` に各20件)、`step3_light_pollution/REPORT_LP1.md`・`REPORT_LP2.md`(比較表の LPI 値)、`docs/examples/senjogahara_sky_guide_20261009.html`(公開された見本)。外すか、経緯の記録として残すか。
8. **テキスト形式の標高タイルの更新停止(令和6年10月)**: PNG 形式への移行を今後の課題にするか。
9. **プラグインのアイコン**: `claude plugin validate` が ICON_MISSING の警告を出す(検証は通過)。アイコンを用意するか。
10. **タグとリリース**: ローカルのタグ `v1.0.0` を、main へのマージ後のコミットに付け直すか(現在は `stageR1` のコミットに付いている)。
11. **コミットの作成者のメールアドレス**: 今後のコミットを GitHub の非公開用アドレス(`…@users.noreply.github.com`)にするか(過去分は履歴の書き換えになるので、今回は何もしていない)。

### 5-1. OSM 由来のデータを分ける案(実行していない)
- 案A(最小): 今回のとおり README に ODbL と対象ファイルを明記するだけ。各 JSON の先頭に `_license`/`_attribution` の項目を足す(データの形は変わらないが、`stargazing_spots.json` 等の一括編集になるのでバックアップが要る)。
- 案B(分離): OSM 由来のデータを `data/osm/`(`viewpoints_kanto.json`・`candidate_sites.db`・`viewpoint_reference` を切り出した `viewpoint_reference.json`)に移し、そのフォルダに `LICENSE-ODbL.txt` と帰属表示を置く。`stargazing_spots.json` からは `viewpoint_reference` と `nominatim_display_name` を外し、読み込み側(`explore_hoshibiyori.load_candidate_sites` ほか)を2ファイル読みに変える。コードの変更とテストの更新が要る。
- 案C(最大): 座標も Nominatim 由来なので、主軸の地点も含めて地点データ全体を ODbL のデータとして `data/` に分け、コード(MIT)とデータ(ODbL)をフォルダで分ける。
