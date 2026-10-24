# 年次の更新手順(Black Marble スカイグロー指数)

年に1回、NASA が新しい年次コンポジット(VNP46A4)を公開したら、派生データを作り直す。実行時(レポート・探索)は
派生データ `data/skyglow_bm_<年>.npz` だけを読み、トークンもネットワークも要らない。

## 前提

- Earthdata のトークン(User Profile → Generate Token)を環境変数 `EARTHDATA_TOKEN` に入れる。**値をログ・コミット・ファイルに書かない**。
  PowerShell: `$env:EARTHDATA_TOKEN = "<トークン>"`(そのセッションだけ有効)
- h5py が要る(HDF5の読み込み用。`requirements.txt` には入れていない)。Python 3.15 RC には h5py の wheel が無いので、
  3.13 などで venv を作る(例: `py -3.13 -m venv C:\tmp\venv313; C:\tmp\venv313\Scripts\python.exe -m pip install h5py numpy requests`)。
  取得スクリプト(requests のみ)は通常の Python でよい。

## 手順

1. 新しい年の粒度を確認(通信は認証不要の CMR のみ):
   `py -X utf8 step3_light_pollution\fetch_black_marble.py --product VNP46A4 --year <年> --list-only`
   範囲は `skyglow_bm.input_extent()`(地点の外接矩形+0.5°+300km)から自動算出される。地点を足した場合も同じ手順で追従できる。
2. 取得(約500MB、6タイル、逐次・取得済みは再取得しない・2秒間隔・429で即中止。回線によるが数分):
   `py -X utf8 step3_light_pollution\fetch_black_marble.py --product VNP46A4 --year <年>`
   `blackmarble_cache/`(git管理外)に置かれ、`data/PROVENANCE.json` にタイル名・sha256・取得日が追記される。
3. 派生データを作る(数秒):
   `C:\tmp\venv313\Scripts\python.exe -X utf8 step3_light_pollution\build_skyglow_bm.py --product VNP46A4 --year <年> --out step3_light_pollution\data\skyglow_bm_<年>.npz`
4. 検証(下記)。
5. 地点への付与(別ファイル。既存の `stargazing_spots.json` は変えない):
   `py -X utf8 step3_light_pollution\annotate_spots_bm.py --grid step3_light_pollution\data\skyglow_bm_<年>.npz`
6. `PROVENANCE.json` の `derived` を新しいファイルの sha256 に更新し、`METHOD.md`・README の年の記載を直す。

所要時間の目安: 取得 数分、計算 3秒(2025年分で実測)、検証 数秒。

## 検証項目

`py -X utf8 step3_light_pollution\validate_skyglow_bm.py --grid <新> --other 前年=<前の年のnpz>` で次を見る。

- 既存LPIとの順位相関(Spearman)が極端に下がっていないか(2025年分: 0.95)。
- 前年との順位相関(2025/2024: 0.999)と中央値の比(光が増減した分。2025/2024: 0.96)。
- 東京駅が最大級・八ヶ岳・阿智村・能登の外浦が暗い側という常識的な並び。
- 近接2地点(3km以内)の比が極端でない(2025年分: 最大 1.12)。
- `input_fill_pixels`(欠損画素数。2025年分: 約1,200)が急増していない。
- `py -X utf8 -m unittest discover -s tests` が通る。

## 注意

- 製品のバージョンが変わった(collection が version 2 でなくなった)場合は、DOI・レイヤー名・欠損値・単位を実ファイルで確認し直す。
  `METHOD.md` の係数(特に較正定数 C と雑音の切り捨て)がその製品でも妥当かは別途検討が要る。
- トークンが401/403で弾かれたら取得は中止する(別経路で回避しない)。
