# スカイグロー指数(Black Marble 起点)の手法と出典 — 段階LP1

`skyglow_bm.py` が実装する指数の式・係数の出典と、本実装で決めた点の記録。
**出力は絶対値ではなく、相対的な暗さの指数として扱う**(理由は末尾の「限界」)。

## 1. 手法の出典

Duriscoe, D. M., Anderson, S. J., Luginbuhl, C. B., Baugh, K. E. (2018),
"A simplified model of all-sky artificial sky glow derived from VIIRS Day/Night band data",
*J. Quant. Spectrosc. Radiat. Transf.* 214, 133–145. doi:10.1016/j.jqsrt.2018.04.028
(CC BY 4.0。NOAA Repository https://repository.library.noaa.gov/view/noaa/21007 の PDF を取得して読んだ。2026-10-23)

考え方: 観測点から半径内の各画素の上向き放射輝度 `r_i` に、距離 `d_i` のべき乗の重み(指数は距離とともに変わる)を
掛けて足し合わせると、全天平均の人工スカイグローの「自然の背景に対する比」(ALR)に比例する。

## 2. 式・係数と論文内の出典

| 項目 | 本実装の値 | 論文の出典 |
|---|---|---|
| ALR の近傍和 | `ALR = (1/C) Σ r_i d_i^(−α)` | 式(9)、p.135 §1.3 |
| 指数 α | `α(d) = 2.3·(d/350)^0.28`(d は km) | 式(11)、p.139 §3.1。検算: α(1km)=0.45、α(300km)=2.20 は同 §3.1 本文の「−0.45(1km)〜−2.20(300km)」と一致(単体テストで固定) |
| 較正定数 C | 562.72 | p.139 §3.2(米国西部24地点の線形回帰の傾き。原点を通す回帰) |
| 影響半径 | 300 km | p.135 §2.3、p.138 §2.5(300 km、環38本) |
| 雑音の切り捨て | 0.5 nW/cm²/sr 未満は 0 | p.135 §2.2.2(エアグローなどの背景。S/N≥5 の考え方) |
| 輝度の単位 | nW/cm²/sr | p.135 §2.2.2(Black Marble の層の単位 `nWatts/(cm^2 sr)` と同じ) |
| ALR の自然の背景 | 250 µcd/m²(全天平均) | p.134 式(6) |
| ALR の目安(Table 3) | 〜0.33 良好 / 0.33〜2 やや悪い / 2〜10 悪い / 10超 天の川が見えない | p.142 Table 3, §4.2 |

指示書は余白を「約200km(推定値)」としていたが、論文が影響半径の上限を 300 km としている(§2.3: 実測では最大300kmの
光のドームが見え、理論側は350kmまでを推奨)ため、**入力の余白は 300 km を採用した**(`INPUT_MARGIN_KM`)。

## 3. 本実装で決めた点(論文に無い。`UNCALIBRATED` は較正していない値)

| 項目 | 値 | 理由・影響 |
|---|---|---|
| 計算用の平面 | 範囲の中心を原点とする方位等距離図法(球近似) | 論文は単一点なら中心の gnomonic(誤差0.07%)、地図なら Albers 等積。中心から約700 km 以内の誤差は 0.3% 以下 |
| 平面の画素 `PLANE_PIXEL_KM` | 1 km **UNCALIBRATED** | 論文は 450 m。1 km へ集約(前進投影で総量保存)してからFFTで畳み込み、数秒で終わる。近距離(〜数km)の分解能は粗い |
| 画素の面積の重み | `輝度 × 画素面積 / (0.45 km)²` | 論文が等積450m画素に再投影して足しているのに合わせる(緯度経度格子のままだと高緯度ほど画素が小さく、過小になる) |
| 同一画素内の距離 `D_MIN_KM` | 0.4 km **UNCALIBRATED** | 距離0では d^−α が定義できない。1 km 画素内の平均距離(≒0.38 km)を代表値にした |
| 輝度の層 | VNP46A4 `AllAngle_Composite_Snow_Free`(年次、全観測角、積雪の無い期間) | 指示書どおり。HDF5内のレイヤー名・単位・欠損値(−999.9→0扱い)は実ファイルで確認(2026-10-23) |
| 入力の年 | 2025(取得時点で最新の完全な年)。2024・VJ146A4(2025)は比較用 | 比較の結論は CLAUDE.md「段階LP1」節 |
| 雑音の切り捨ての適用先 | 年次コンポジット | 論文は月次コンポジット(EOG)に適用。Black Marble は別処理(月光補正・積雪除外・時間合成)のため、同じ 0.5 が適切かは未確認 |
| 出力格子 | 0.01° 間隔、地点の外接矩形+0.5° | 余白内の縁は影響半径が入力に収まる(入力範囲=出力範囲+300 km) |
| 地点への補間 | 双一次補間 | |

## 4. 限界(指数を相対順位に限る理由)

1. **C は米国西部・VIIRS 月次コンポジット・Garstang の K=0.35(低エアロゾル)での較正値**(§2.4, §3.2)。湿潤で
   エアロゾルの多い日本、別処理の Black Marble 年次コンポジットには**未較正**。絶対値(ALR の数値、Table 3 のクラス)を
   そのまま日本の空の明るさとして読まない。
2. Black Marble は**地表の輝度**で空の明るさではない。分光特性(LED への置換で DNB の見かけの輝度が下がる)による
   系統差も論文の限界(§4.3.1、p.142)。
3. 論文は**全天平均**(ALR)。星空撮影で効くのは天頂付近の暗さ(ZLR)で、ALR/ZLR は 1.6〜3.3 と距離で変わる(Table 2,
   §4.1)。本指数は ZLR ではない。
4. 観測点の標高・地形による遮蔽は扱わない。水面近傍の散乱光を光源と誤計上する問題(§4.3.2、p.142-143)も補正していない。
   標高の高い地点は遠方の光のドームをより多く見るため本指数は過小になりうる(筆者の推測。検証していない)。
5. 近距離は 1 km 画素のため、数km以内の個別の光源(駐車場の街灯、町)の影響は粗い。

## 5. 引用・出典の表示

- 手法: 上記 Duriscoe et al. 2018(CC BY 4.0)。
- データ: NASA VIIRS Land Science Investigator-led Processing System. (2025). VIIRS/NPP Lunar BRDF-Adjusted
  Nighttime Lights Yearly L3 Global 15 arc second Linear Lat Lon Grid [Dataset]. NASA Level 1 and Atmosphere Archive and
  Distribution System Distributed Active Archive Center. https://doi.org/10.5067/VIIRS/VNP46A4.002
  (LAADS の製品ページ https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A4/ の記載。2026-10-23 確認。
  製品ページに利用条件の記載は無い。)
- 利用条件: NASA Earthdata「データ利用ガイダンス」(https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance、
  2026-10-23 確認)に「NASA主導ミッションのデータは Creative Commons Zero(CC0)」「利用に制限は無いが引用を強く推奨」「NASA を出典として
  明示する」とある。**制限のあるデータはその旨が表示される**とあるが、VNP46A4 に制限の表示は見当たらなかった。
  法的な最終確認(再配布する派生データとしての扱い)はしていない。
