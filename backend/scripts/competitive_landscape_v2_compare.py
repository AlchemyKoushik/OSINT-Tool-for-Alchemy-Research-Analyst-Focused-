import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.analyze import run_analysis_request
from models.request_models import AnalyzeRequest


def _load_markets(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("Market batch file must contain a JSON array.")
    normalized_markets: List[Dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        topic = str(entry.get("topic", "")).strip()
        location_preference = str(entry.get("location_preference", "global")).strip() or "global"
        location_value = str(entry.get("location_value", "")).strip() or None
        if not topic:
            continue
        normalized_markets.append(
            {
                "topic": topic,
                "location_preference": location_preference,
                "location_value": location_value,
            }
        )
    return normalized_markets


def _company_names(result: Dict[str, Any], key: str) -> List[str]:
    return [str(item.get("heading", "")).strip() for item in list(result.get(key, []) or []) if str(item.get("heading", "")).strip()]


async def _run_single(topic: str, location_preference: str, location_value: str | None, use_v2: bool) -> Dict[str, Any]:
    request = AnalyzeRequest(
        topic=topic,
        section="competitive_landscape",
        location_preference=location_preference,
        location_value=location_value,
        debug=True,
        feature_flags={"competitive_landscape_v2": use_v2},
    )
    return await run_analysis_request(request_model=request, progress_callback=None, diagnostics=None)


async def _compare_market(entry: Dict[str, Any]) -> Dict[str, Any]:
    topic = str(entry["topic"])
    location_preference = str(entry["location_preference"])
    location_value = entry.get("location_value")

    v1_result = await _run_single(topic, location_preference, location_value, use_v2=False)
    v2_result = await _run_single(topic, location_preference, location_value, use_v2=True)

    v1_debug = dict(v1_result.get("debug", {}) or {})
    v2_debug = dict(v2_result.get("debug", {}) or {})
    return {
        "topic": topic,
        "location_preference": location_preference,
        "location_value": location_value,
        "v1": {
            "major_players": _company_names(v1_result, "major_players"),
            "emerging_players": _company_names(v1_result, "emerging_players"),
            "diagnostics": v1_debug.get("competitive_landscape_diagnostics", {}),
        },
        "v2": {
            "major_players": _company_names(v2_result, "major_players"),
            "emerging_players": _company_names(v2_result, "emerging_players"),
            "diagnostics": v2_debug.get("competitive_landscape_diagnostics", {}),
        },
    }


async def _main(markets: List[Dict[str, Any]]) -> Dict[str, Any]:
    comparisons: List[Dict[str, Any]] = []
    for entry in markets:
        comparisons.append(await _compare_market(entry))
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "market_count": len(comparisons),
        "comparisons": comparisons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Competitive Landscape v1 and v2 side by side.")
    parser.add_argument("--markets", required=True, help="Path to a JSON array of market definitions.")
    parser.add_argument("--output", required=True, help="Path to write the comparison JSON.")
    args = parser.parse_args()

    markets_path = Path(args.markets).resolve()
    output_path = Path(args.output).resolve()
    markets = _load_markets(markets_path)
    result = asyncio.run(_main(markets))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(str(output_path))


if __name__ == "__main__":
    main()
