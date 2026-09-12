"""星の日和(hoshibiyori) 気象庁(JMA)地上天気図のスクリーンショット取得。

Open-Meteoの数値予報(雲量)とは別に、実況・予想の地上天気図(前線・高低気圧配置)を
画像として取得し、レポートに参考表示する。スコア計算には使わない、人間が目で見る
補助資料という位置づけ。

取得方法について: 2026-09-06、姉妹プロジェクトyamabiyori
(C:\\mountain-weather\\mountain_weather_detail.py の fetch_jma_weather_map())の
実装を読み取り専用で参照し、「気象庁の天気図ページは静的URLでは配信されておらず、
JavaScriptで<img>タグに動的生成されたファイル名を書き込むため、単純なHTTP GETでは
取得できずブラウザ(Playwright)が必要」という技術的な制約と、「予想天気図はページ内の
『ひとつ後の時間を表示』ボタンで実況→+24h予想→+48h予想の2段階だけ進める」という
JMA側の仕様を把握した。コード自体は移植・コピーしておらず、hoshibiyori独自に
新規実装している(CLAUDE.md記載のプロジェクト独立性ルールに基づく、2026-09-06時点で
ユーザーが承認した一回限りの参照)。

このスクリーンショット機能自体は「都度Claudeが画像を見て解説文を書く」運用を想定しており
(yamabiyori側も同じ位置づけで、自動テキスト解釈は行っていない)、generate_report.py側で
自動的に文章化するロジックは持たない。

利用にあたっての配慮: 気象庁の一般向け公開ページへの生アクセスであり、Open-Meteo経由の
数値予報とは別の負荷源になる。ループ状に呼び出したり、レポート生成のたびに無条件で
呼び出したりしない(1回の実行につき1セッションのみ)。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

JMA_WEATHER_MAP_URL = "https://www.jma.go.jp/bosai/weather_map/"
DEFAULT_OUT_DIR = Path(__file__).parent / "weather_map_cache"

# JMAの天気図ページの「ひとつ後の時間を表示」ボタンは、実況から数えて+24h予想・+48h予想の
# 2段階までしか進まない(ページ自体の仕様。将来ページ側の挙動が変われば要調整)。
_FORECAST_STEP_LABELS = ["plus24h", "plus48h"]


def fetch_jma_weather_map(out_dir: str | Path = DEFAULT_OUT_DIR, include_forecast: bool = True) -> list[Path]:
    """JMA地上天気図の実況(+予想)をスクリーンショットして保存し、保存先パスのリストを返す。

    include_forecast=True(既定): 実況に加えて+24h予想・+48h予想も同一ブラウザセッション内で
    連続して取得する(サイトへのアクセスは1セッションで完結させ、負荷を抑える)。
    JMA側が想定より早く「次へ」を出さなくなった場合は、そこで打ち切って取得できた分だけ返す。

    ページはJSで<img>要素に画像を描画する方式で固定URLが無いため、Playwrightで
    その<img>要素だけをスクリーンショットする(周囲のメニュー等を含まず、天気図の
    ネイティブ解像度で保存できる)。
    """
    from playwright.sync_api import sync_playwright

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")

    # 天気図の<img>はsrc属性が"data/png/<ファイル名>"という相対パスで(JSが
    # jQueryの.attr("src", ...)で書き込むため先頭に"/"が付かない)、タイムスタンプ+
    # 観測種別コードを含む動的なファイル名で固定URLではない。「ひとつ後の時間を表示」
    # ボタンは<button>ではなく、title属性でそれと分かる<img class="weather-map-time-button">。
    # (2026-09-06、対象ページのDOM・JSソースを実機で調査して確認)
    _MAP_IMG_SELECTOR = 'img[src*="data/png/"]'
    _NEXT_BUTTON_TITLE = "ひとつ後の時間を表示"

    saved: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 900})
        page.goto(JMA_WEATHER_MAP_URL, wait_until="networkidle", timeout=30000)

        map_img = page.locator(_MAP_IMG_SELECTOR).first
        map_img.wait_for(state="visible", timeout=30000)
        current_path = out_dir / f"jma_weathermap_{timestamp}_now.png"
        map_img.screenshot(path=str(current_path))
        saved.append(current_path)

        if include_forecast:
            next_button = page.locator(f'img[title="{_NEXT_BUTTON_TITLE}"]').first
            for label in _FORECAST_STEP_LABELS:
                if next_button.count() == 0 or not next_button.is_visible():
                    break
                before_src = map_img.get_attribute("src")
                next_button.click()
                try:
                    page.wait_for_function(
                        """([sel, prev]) => {
                            const el = document.querySelector(sel);
                            return el && el.getAttribute('src') !== prev;
                        }""",
                        arg=[_MAP_IMG_SELECTOR, before_src],
                        timeout=8000,
                    )
                except Exception:
                    # JMA側がこれ以上先の予想を持たない場合、画像は差し替わらない。
                    # そこで打ち切り、取得できた分だけ返す。
                    break

                forecast_path = out_dir / f"jma_weathermap_{timestamp}_{label}.png"
                map_img.screenshot(path=str(forecast_path))
                saved.append(forecast_path)

        browser.close()

    return saved


if __name__ == "__main__":
    paths = fetch_jma_weather_map()
    print(f"保存件数: {len(paths)}")
    for p in paths:
        print(f"  {p}")
