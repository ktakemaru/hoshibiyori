# 星空ガイド 解説JSONの書き方

星空ガイド(星空シミュレーター付き)は、次の3層で作る。**HTMLは手で書かない。数値はエージェントが書かない。**

1. **数値JSON**(`hoshibiyori-skyguide-data/1`): `scripts/make_sky_guide.py` が既存ロジックで作る。
2. **解説JSON**(`hoshibiyori-skyguide-commentary/1`): エージェントが書く(この文書)。
3. **描画**: `scripts/render_sky_guide.py` が、固定のテンプレートに2つのJSONを差し込んで1ファイルのHTMLにする。

見本: `tests/fixtures/sky_guide/senjogahara_20261009_commentary.json`(戦場ヶ原 2026-10-09)。見本のHTMLは `docs/examples/`(読み取り専用)。

## 手順

```powershell
# 1. 数値JSON(通信しない。雲量はキャッシュにあれば入り、無ければ理由つきで省略される)
.\.venv\Scripts\python.exe -X utf8 scripts\make_sky_guide.py --spot 戦場ヶ原 --date 2026-10-09 --json-out out\senjogahara_data.json
# 2. 解説JSONを out\senjogahara_commentary.json に書く(下記)
# 3. 描画
.\.venv\Scripts\python.exe -X utf8 scripts\render_sky_guide.py --data out\senjogahara_data.json --commentary out\senjogahara_commentary.json --out out\senjogahara.html
```

- `--estimate` を付けると、通信が要る見込み(未キャッシュの雲量セル数・稜線CSVの有無)だけを表示して終了する。
- 通信が要る処理(`--cloud fetch --allow-network`)は、**所要時間とリクエスト数の見込みをユーザーに伝えて承認を得てから**行う。
- 一覧(`stargazing_spots.json`)にない地点は `--name --lat --lon --elevation --horizon-csv`。稜線CSVは `step2_terrain` の既存ツールで作る
  (国土地理院のDEMタイルの取得=通信が要る)。

## 解説JSONの項目(必須は ★)

| 項目 | 内容 |
|---|---|
| `schema` ★ | `hoshibiyori-skyguide-commentary/1` |
| `lead` ★ | リード文(2〜3文)。この夜の見どころ |
| `facts` ★ | 「この夜の条件」**ちょうど4項目**。各 `{key, value, sub}`(例: 暗くなる時間 / 月 / 雲 / 天の川の中心部) |
| `cards` ★ | 狙える構図(1件以上)。`{id, when, time, az, frame:{az,alt,w,h,lens}, title, tags:[[文字,"hot"/"hard"/""]], body, list:[…]}`。`time` は数値JSONの `times` のどれか、`az` は0以上360未満 |
| `directions` ★ | 周囲の山と方位の表(1件以上)。`{label, elevation, terrain, sky}`。`terrain` の `**山名**` は太字になる |
| `tips` ★ | 撮影メモ(1件以上)。`{title, body}` |
| `peaks` | パノラマに出す山名。`{az, name, basis}`。`basis` は `確認済み` か `推定`(必須)。`az` は数値JSONの `peak_candidates` の方位と3°以内 |
| `heading` / `title` | 見出し・ページ題(省略時は「<地点名>の星空」「<地点名> 星空ガイド」) |
| `initial_time` | シミュレーターの初期時刻(`times` のどれか。省略時は夜の中央) |
| `cloud_note` / `cards_lead` / `directions_note` | 補足文(省略時は既定文) |

必須要素(星空シミュレーター・事実4項目・構図カード・周囲の山と方位の表・撮影メモ・出典と免責)が欠けると描画はエラーになる。

## 書いてよい数値の出どころ

文章に入れる数値は、**数値JSONの `events` と `frames` から取る**。覚えや推測で書かない。

- `events`(決定論。同じ入力で同じ結果): 暗い時間帯、天の川の中心が稜線の上にいる区間と最大高度(`gc_above_ridge`)、主な天体・惑星が稜線の上にいる区間と
  昇る・沈む時刻と方位(`star_above_ridge`・`planet_above_ridge`)、北極星の高度(`polaris_altitude`)、月が出ている区間(`moon_up` / `moon_below_horizon_all_night`)。
- `frames[i]`: 時刻 `times[i]` の全天(各天体の[方位,高度]、月の方位・高度・輝面比・満ち欠けの向き)。
- `horizon_deg[方位]`: 方位1°ごとの稜線の仰角。`peak_candidates`: 稜線の極大(山名は付いていない)。
- 雲量: `cloud.hours`(あれば)。

注意: `events` の「稜線の上」は稜線(`horizon_deg`)を基準にしている。「昇る時刻」は地平線ではなく稜線を越える時刻で、見本の「1時すぎ」のような
言い方は数値と食い違うことがある(見本の木星は稜線を越えるのが01:57)。**時刻は `events` の `start` をそのまま使う。**

## 山の名前

- 山名は方位・距離からの**推定**。確認できていない山は `basis: "推定"` とし、表の文章にも「推定」「〜方面」と書く。
- `確認済み` にしてよいのは、方位・標高・距離が地図と一致して確認できたものだけ(見本では男体山)。確認方法を覚えていなければ `推定` にする。
- 山名が分からないピークは、名前を付けず方位と仰角だけを書く(`peaks` に入れない)。

## 雲量について

- 雲量は**全天の平均**の視界遮蔽雲量(観測者より上の雲)。**どの方角に雲が残るかは分からない**。文章で方角の雲を断定しない。
- 予報が取れない日付(過去・約2週間より先)や、通信しない設定でキャッシュが無いときは、雲量を省略してよい。理由はページに表示される(`cloud_omitted_reason`)。
  その場合、`facts` の「雲」には「予報なし」と書き、雲について推測を書かない。

## 月

月がある夜は、シミュレーターが月(月相つき)を描き、読み出しに高度・方位・輝面を出す。月明かりは天の川に直結するので、`facts` の「月」と構図の `body` に、
`events` の `moon_up`(出ている区間と最大高度)と `frames[*].moon.illum`(輝面比)から書く。

## 注意・免責(ページ下部に自動で入る)

- 出典: Skyfield(JPL DE421)、Open-Meteo(CC BY 4.0、気象庁MSM・ECMWF IFS)、国土地理院の標高タイルを加工、Light Pollution Atlas。
- 予報値であり、当日の空を保証しない。山名と構図の位置関係は現地で確認する。
- 位置が特定できる私的な情報(自宅・非公開の撮影地など)は、地点名・本文に書かない。
