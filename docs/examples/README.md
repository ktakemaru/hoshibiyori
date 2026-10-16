# 見本(読み取り専用)

`senjogahara_sky_guide_20261009.html` は、2026-10-09に作った「戦場ヶ原 星空ガイド」(Artifact)のコピーです。
星空ガイド+星空シミュレーターの**見本**であり、`tests/test_sky_guide.py` が「ゴールデン(`tests/fixtures/sky_guide/`)から描画したHTMLが
見本と同じ構造・同じ天体データになる」ことの基準に使います。**編集しないでください**(再現テストが意味を失います)。

見本には月がなく(月が地平線の下の夜に固定)、雲量の棒が12時間固定でした。`skyguide/` のテンプレートはこれらを一般化していますが、
ゴールデンでは見た目が変わらないことをテストで確認しています。

## 解説JSONの訂正例

- `senjogahara_20261009_commentary_corrected_v2.json` — **手本**。ゴールデン(`tests/fixtures/sky_guide/senjogahara_20261009_commentary.json`)の解説のうち、
  時刻の言い回しと数値(カードの高度・方位表の稜線の仰角)を機械照合(`skyguide/check_text.py`・`skyguide/check_numbers.py`)で合うように直したもの。
  旧い訂正例との差分は7か所(カードb・cの本文と、方位表の仰角5行)。
- `senjogahara_20261009_commentary_corrected.json` — 時刻の言い回しだけ訂正した版。数値の食い違いが残っているため手本にしない(参照用に残してある)。

どちらも編集しないでください(テスト `tests/test_sky_guide_examples.py` が差分を固定しています)。
