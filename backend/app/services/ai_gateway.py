from __future__ import annotations

import json
import logging
import socket
import time
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from app.models import AIModelItem

logger = logging.getLogger(__name__)
TRANSIENT_HTTP_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
REQUEST_MAX_ATTEMPTS = 3
REQUEST_RETRY_BASE_DELAY_SECONDS = 0.75
_responses_api_support_cache: dict[str, bool] = {}


class AIMissingContentError(RuntimeError):
    pass


def _retry_delay_seconds(attempt: int) -> float:
    return REQUEST_RETRY_BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1))


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code in TRANSIENT_HTTP_STATUS_CODES


def _request_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "SuperLottoOracle/1.0",
    }


def _compat_retry_body_for_responses(body: dict, detail: str) -> dict | None:
    lowered = detail.lower()
    retry_body = dict(body)
    changed = False
    if "text" in retry_body and ("text.format" in lowered or "json_object" in lowered or "response_format" in lowered):
        retry_body.pop("text", None)
        changed = True
    if "reasoning" in retry_body and "reasoning" in lowered:
        retry_body.pop("reasoning", None)
        changed = True
    if "store" in retry_body and "store" in lowered:
        retry_body.pop("store", None)
        changed = True
    return retry_body if changed else None


def _compat_retry_body_for_chat(body: dict, detail: str) -> dict | None:
    lowered = detail.lower()
    retry_body = dict(body)
    changed = False
    if "response_format" in retry_body and ("response_format" in lowered or "json" in lowered):
        retry_body.pop("response_format", None)
        changed = True
    if "max_completion_tokens" in retry_body and "max_completion_tokens" in lowered:
        retry_body["max_tokens"] = retry_body.pop("max_completion_tokens")
        changed = True
    if "reasoning_effort" in retry_body and "reasoning_effort" in lowered:
        retry_body.pop("reasoning_effort", None)
        changed = True
    return retry_body if changed else None


def _post_json_with_retries(
    normalized_base: str,
    path: str,
    api_key: str,
    body: dict,
    *,
    timeout: int,
    endpoint: str,
    error_prefix: str,
    compat_retry_mutator=None,
) -> dict:
    current_body = dict(body)
    compatibility_retry_used = False
    for attempt in range(1, REQUEST_MAX_ATTEMPTS + 1):
        request = Request(
            urljoin(normalized_base, path),
            data=json.dumps(current_body).encode("utf-8"),
            headers=_request_headers(api_key),
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return _read_json_response(response, endpoint=endpoint)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if compat_retry_mutator and not compatibility_retry_used:
                retry_body = compat_retry_mutator(current_body, detail)
                if retry_body is not None:
                    compatibility_retry_used = True
                    current_body = retry_body
                    logger.info("[AI] retrying %s with compatibility payload after HTTP %s", endpoint, exc.code)
                    continue
            if _is_retryable_http_status(exc.code) and attempt < REQUEST_MAX_ATTEMPTS:
                delay = _retry_delay_seconds(attempt)
                logger.warning("[AI] transient HTTP %s from %s, retrying in %.2fs", exc.code, endpoint, delay)
                time.sleep(delay)
                continue
            raise RuntimeError(f"{error_prefix}: HTTP {exc.code} {detail}") from exc
        except (TimeoutError, socket.timeout, URLError) as exc:
            if attempt < REQUEST_MAX_ATTEMPTS:
                delay = _retry_delay_seconds(attempt)
                logger.warning("[AI] transient network error from %s, retrying in %.2fs: %s", endpoint, delay, exc)
                time.sleep(delay)
                continue
            raise RuntimeError(f"{error_prefix}: {exc}") from exc
    raise RuntimeError(f"{error_prefix}: exhausted retries")


def _read_json_response(response, *, endpoint: str) -> dict:
    raw = response.read().decode("utf-8", errors="replace")
    if not raw.strip():
        raise RuntimeError(f"AI {endpoint} returned empty response body")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        sse_payload = _parse_sse_response(raw)
        if sse_payload is not None:
            return sse_payload
        snippet = raw[:500].replace("\r", "\\r").replace("\n", "\\n")
        raise RuntimeError(f"AI {endpoint} returned non-JSON response body: {snippet}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"AI {endpoint} returned JSON {type(payload).__name__}, expected object")
    return payload


def _payload_preview(payload: dict) -> str:
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        raw = repr(payload)
    return raw[:1200]


def _append_text_fragments(target: list[str], value) -> None:
    if isinstance(value, str):
        if value.strip():
            target.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _append_text_fragments(target, item)
        return
    if not isinstance(value, dict):
        return

    for key in (
        "output_text",
        "content",
        "text",
        "value",
        "reasoning_content",
        "message",
        "delta",
    ):
        nested = value.get(key)
        if nested is not None and nested is not value:
            _append_text_fragments(target, nested)

    function = value.get("function")
    if isinstance(function, dict):
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments.strip():
            target.append(arguments)


def _extract_visible_text(*candidates) -> str | None:
    parts: list[str] = []
    for candidate in candidates:
        _append_text_fragments(parts, candidate)
    content = "\n".join(part.strip() for part in parts if isinstance(part, str) and part.strip()).strip()
    return content or None


def _parse_sse_response(raw: str) -> dict | None:
    if "data:" not in raw:
        return None

    delta_parts: list[str] = []
    done_parts: list[str] = []
    completed_response: dict | None = None
    last_object: dict | None = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            item = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        last_object = item

        item_type = item.get("type")
        delta = item.get("delta")
        if item_type == "response.output_text.delta" and isinstance(delta, str):
            delta_parts.append(delta)
            continue

        text = item.get("text")
        if item_type in {"response.output_text.done", "response.output_text.completed"} and isinstance(text, str):
            done_parts.append(text)
            continue

        response_obj = item.get("response")
        if item_type == "response.completed" and isinstance(response_obj, dict):
            completed_response = response_obj

    text = "".join(done_parts or delta_parts).strip()
    if text:
        return {"output_text": text}
    if completed_response is not None:
        return completed_response
    return last_object


def chat_completion(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.4,
    max_completion_tokens: int = 4096,
    json_mode: bool = False,
    reasoning_effort: str | None = None,
    timeout: int = 60,
) -> str:
    """Call an OpenAI-compatible model endpoint and return the assistant content."""
    normalized_base = _normalize_api_base(base_url)
    should_try_responses = _prefer_responses_api(model) and _responses_api_support_cache.get(normalized_base, True)
    if should_try_responses:
        try:
            return _responses_completion(
                normalized_base=normalized_base,
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=max_completion_tokens,
                json_mode=json_mode,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
            )
        except RuntimeError as exc:
            detail = str(exc)
            if "proxy_error" in detail or "HTTP 400" in detail:
                _responses_api_support_cache[normalized_base] = False
                logger.info("[AI] marking /responses unsupported for %s after error: %s", normalized_base, detail)
            logger.info("[AI] responses API unavailable or empty; falling back to chat completions: %s", exc)

    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "stream": False,
    }
    if max_completion_tokens > 0:
        body["max_completion_tokens"] = max_completion_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort

    payload = _post_chat_completion(normalized_base, api_key, body, timeout=timeout)
    try:
        return _extract_chat_content(payload)
    except AIMissingContentError:
        retry_body = dict(body)
        retry_body["temperature"] = 0
        retry_body["max_completion_tokens"] = max(max_completion_tokens, 8192)
        retry_body["reasoning_effort"] = "minimal"
        retry_body["messages"] = [
            {"role": "system", "content": "You must output only one valid JSON object. No reasoning text, no markdown."},
            *body["messages"],
            {
                "role": "user",
                "content": (
                    "Your previous response had no visible content. Retry now. "
                    "Return only the required JSON object with selected_schemes, overview, key_factors, and final_advice."
                ),
            },
        ]
        retry_body["stream"] = True
        logger.info("[AI] empty assistant content; retrying with streaming fallback, minimal reasoning, and larger output budget")
        retry_payload = _post_chat_completion(normalized_base, api_key, retry_body, timeout=timeout)
        try:
            return _extract_chat_content(retry_payload)
        except AIMissingContentError as exc:
            logger.warning("[AI] chat completion payload still lacks visible content after retry: %s", _payload_preview(retry_payload))
            raise RuntimeError(
                "AI response still missing visible content after retry; try another model or an endpoint that supports visible chat content."
            ) from exc


def _prefer_responses_api(model: str) -> bool:
    return model.strip().lower().startswith("gpt-5")


def _normalize_api_base(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    return cleaned + "/"


def _responses_completion(
    *,
    normalized_base: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    json_mode: bool,
    reasoning_effort: str | None,
    timeout: int,
) -> str:
    body: dict = {
        "model": model,
        "instructions": system_prompt,
        "input": user_prompt,
        "max_output_tokens": max(max_output_tokens, 8192),
        "store": False,
    }
    if json_mode:
        body["text"] = {"format": {"type": "json_object"}}
    if reasoning_effort:
        body["reasoning"] = {"effort": reasoning_effort}
    payload = _post_responses(normalized_base, api_key, body, timeout=timeout)
    return _extract_response_content(payload)


def _post_responses(normalized_base: str, api_key: str, body: dict, *, timeout: int) -> dict:
    return _post_json_with_retries(
        normalized_base,
        "responses",
        api_key,
        body,
        timeout=timeout,
        endpoint="/responses",
        error_prefix="AI responses request failed",
        compat_retry_mutator=_compat_retry_body_for_responses,
    )


def _extract_response_content(payload: dict) -> str:
    content = _extract_visible_text(
        payload.get("output_text"),
        payload.get("output"),
    )
    if content:
        return content
    raise AIMissingContentError(f"AI responses output missing content: {payload}")


def _post_chat_completion(normalized_base: str, api_key: str, body: dict, *, timeout: int) -> dict:
    return _post_json_with_retries(
        normalized_base,
        "chat/completions",
        api_key,
        body,
        timeout=timeout,
        endpoint="/chat/completions",
        error_prefix="AI request failed",
        compat_retry_mutator=_compat_retry_body_for_chat,
    )


def _extract_chat_content(payload: dict) -> str:
    content = _extract_visible_text(
        payload.get("output_text"),
        payload.get("choices"),
        payload.get("output"),
    )
    if content:
        return content

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"AI response missing choices: {payload}")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = _extract_visible_text(
        message.get("content"),
        choice.get("text"),
        message.get("text"),
        message.get("reasoning_content"),
        choice.get("reasoning_content"),
        message.get("output_text"),
        choice.get("output_text"),
        choice.get("delta"),
    )
    if content:
        return content
    raise AIMissingContentError(f"AI response missing content: {payload}")


def fetch_model_list(base_url: str, api_key: str) -> list[AIModelItem]:
    normalized_base = _normalize_api_base(base_url)
    request = Request(
        urljoin(normalized_base, "models"),
        headers=_request_headers(api_key),
        method="GET",
    )
    with urlopen(request, timeout=20) as response:
        payload = _read_json_response(response, endpoint="/models")

    items = payload.get("data", [])
    models: list[AIModelItem] = []
    for item in items:
        model_id = item.get("id")
        if not model_id:
            continue
        models.append(AIModelItem(id=str(model_id), owned_by=item.get("owned_by")))
    models.sort(key=lambda item: item.id.lower())
    return models
