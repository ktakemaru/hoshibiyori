"""scratch_merge_new_spots.pyでprefectureが正しく取得できていなかった不具合を修正する。

原因: Nominatim reverse geocodingの日本の住所では都道府県が"state"キーではなく
"province"キーで返る。reverse_geocode.pyのGeocodeResultはmunicipalityしか返さないため、
scratch_merge_new_spots.py側でraw_address.get("state")として誤って参照していた。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "step7_geocoding")
from reverse_geocode import reverse_geocode_municipality  # noqa: E402

ROOT = Path(__file__).parent

with open(ROOT / "stargazing_spots.json", encoding="utf-8") as f:
    data = json.load(f)

targets = [s for s in data["spots"] if s["origin"] == "curated_external" and not s.get("prefecture")]
print(f"修正対象: {len(targets)}件")

for i, spot in enumerate(targets, 1):
    geo = reverse_geocode_municipality(spot["lat"], spot["lon"])
    prefecture = geo.raw_address.get("province") if geo.raw_address else None
    spot["prefecture"] = prefecture
    print(f"  [{i}/{len(targets)}] {spot['name']:28s} -> {prefecture or '取得失敗'}")

with open(ROOT / "stargazing_spots.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("完了。")
