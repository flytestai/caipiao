from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from datetime import datetime
from urllib.parse import urlencode

from curl_cffi import requests as curl_requests

from app.models import LottoDraw, PrizeLevelItem

OFFICIAL_HISTORY_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
OFFICIAL_REFERER = "https://m.lottery.gov.cn/zst/dlt/"
GAME_NO_DLT = 85
PAGE_SIZE = 100
OFFICIAL_FETCH_MAX_WORKERS = 6


def _request_json(url: str) -> dict:
    response = curl_requests.get(
        url,
        headers={
            "Referer": OFFICIAL_REFERER,
        },
        impersonate="chrome124",
        timeout=20,
    )
    response.raise_for_status()
    return json.loads(response.text)


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


def fetch_history_pages(page_numbers: list[int], page_size: int = PAGE_SIZE) -> list[LottoDraw]:
    ordered_pages = [int(page_no) for page_no in page_numbers if int(page_no) >= 1]
    if not ordered_pages:
        return []
    max_workers = min(OFFICIAL_FETCH_MAX_WORKERS, len(ordered_pages))
    if max_workers <= 1:
        return [draw for page_no in ordered_pages for draw in fetch_history_page(page_no=page_no, page_size=page_size)[0]]

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="official-history") as executor:
        page_results = executor.map(
            lambda page_no: fetch_history_page(page_no=page_no, page_size=page_size)[0],
            ordered_pages,
        )
        return [draw for page_draws in page_results for draw in page_draws]


def fetch_recent_history(limit: int) -> list[LottoDraw]:
    page_size = min(max(limit, 1), PAGE_SIZE)
    draws, _ = fetch_history_page(page_no=1, page_size=page_size)
    return draws[:limit]
