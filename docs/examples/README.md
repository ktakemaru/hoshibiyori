# 見本(読み取り専用)

2026-10-09に作った「戦場ヶ原 星空ガイド」(Artifact)のHTMLのコピーを見本として置いていましたが、以前の光害データの値と出典を含んでいたため、
段階LP3b(2026-10-24)で削除しました(以前のコミットには残ります)。見本から抽出したゴールデン(`tests/fixtures/sky_guide/`、光害の値は除去済み)は残してあり、
`tests/test_sky_guide.py` の回帰テストはこれを基準にしています。

## 解説JSONの訂正例

- `senjogahara_20261009_commentary_corrected_v2.json` — **手本**。ゴールデン(`tests/fixtures/sky_guide/senjogahara_20261009_commentary.json`)の解説のうち、
  時刻の言い回しと数値(カードの高度・方位表の稜線の仰角)を機械照合(`skyguide/check_text.py`・`skyguide/check_numbers.py`)で合うように直したもの。
  旧い訂正例との差分は7か所(カードb・cの本文と、方位表の仰角5行)。
- `senjogahara_20261009_commentary_corrected.json` — 時刻の言い回しだけ訂正した版。数値の食い違いが残っているため手本にしない(参照用に残してある)。

どちらも編集しないでください(テスト `tests/test_sky_guide_examples.py` が差分を固定しています)。
