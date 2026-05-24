from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models import LottoDraw, PrizeLevelItem

OFFICIAL_HISTORY_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
OFFICIAL_REFERER = "https://m.lottery.gov.cn/zst/dlt/"
GAME_NO_DLT = 85
PAGE_SIZE = 100


def _request_json(url: str) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": OFFICIAL_REFERER,
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_record(item: dict) -> LottoDraw:
    values = [int(part) for part in item["lotteryDrawResult"].split()]
    return LottoDraw(
        issue=str(item["lotteryDrawNum"]),
        draw_date=datetime.fromisoformat(item["lotteryDrawTime"]).date(),
        front_numbers=sorted(values[:5]),
        back_numbers=sorted(values[5:7]),
        raw_result=item["lotteryDrawResult"],
        pool_balance_afterdraw=item.get("poolBalanceAfterdraw"),
        prize_level_list=[
            PrizeLevelItem(
                prize_level=prize.get("prizeLevel", ""),
                award_type=int(prize.get("awardType", 0) or 0),
                stake_amount=prize.get("stakeAmount"),
                stake_amount_format=prize.get("stakeAmountFormat"),
                stake_count=prize.get("stakeCount"),
                total_prize_amount=prize.get("totalPrizeamount"),
            )
            for prize in item.get("prizeLevelList", [])
        ],
    )


def fetch_history_page(page_no: int = 1, page_size: int = PAGE_SIZE) -> tuple[list[LottoDraw], int]:
    query = urlencode(
        {
            "gameNo": GAME_NO_DLT,
            "provinceId": 0,
            "isVerify": 1,
            "pageNo": page_no,
            "pageSize": page_size,
        }
    )
    payload = _request_json(f"{OFFICIAL_HISTORY_URL}?{query}")
    success = payload.get("success")
    error_code = str(payload.get("errorCode"))
    if str(success).lower() != "true" or error_code != "0":
        raise RuntimeError(f"Official source error: {payload.get('errorMessage') or payload}")

    value = payload["value"]
    draws = [_normalize_record(item) for item in value["list"]]
    return draws, int(value["pages"])


def fetch_recent_history(limit: int) -> list[LottoDraw]:
    page_size = min(max(limit, 1), PAGE_SIZE)
    draws, _ = fetch_history_page(page_no=1, page_size=page_size)
    return draws[:limit]
