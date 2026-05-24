import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.services.ai_gateway import _extract_chat_content, _extract_response_content, _parse_sse_response, _responses_api_support_cache, chat_completion


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class AIGatewayRetryTests(unittest.TestCase):
    def tearDown(self) -> None:
        _responses_api_support_cache.clear()

    def test_extract_chat_content_falls_back_to_reasoning_content(self) -> None:
        result = _extract_chat_content(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": '{"selected_schemes":[]}',
                        }
                    }
                ]
            }
        )

        self.assertEqual(result, '{"selected_schemes":[]}')

    def test_extract_chat_content_falls_back_to_choice_text(self) -> None:
        result = _extract_chat_content(
            {
                "choices": [
                    {
                        "text": '{"selected_schemes":[]}',
                        "message": {"content": None},
                    }
                ]
            }
        )

        self.assertEqual(result, '{"selected_schemes":[]}')

    def test_extract_chat_content_supports_nested_text_value(self) -> None:
        result = _extract_chat_content(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": {"value": '{"selected_schemes":[{"front_numbers":[1,2,3,4,5],"back_numbers":[1,2]}]}'},
                                }
                            ],
                        }
                    }
                ]
            }
        )

        self.assertIn('"selected_schemes"', result)

    def test_extract_response_content_supports_nested_text_value(self) -> None:
        result = _extract_response_content(
            {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": {"value": '{"selected_schemes":[],"overview":"ok"}'},
                            }
                        ]
                    }
                ]
            }
        )

        self.assertEqual(result, '{"selected_schemes":[],"overview":"ok"}')

    def test_extract_chat_content_supports_output_text_payload(self) -> None:
        result = _extract_chat_content({"output_text": '{"selected_schemes":[],"overview":"ok"}'})

        self.assertEqual(result, '{"selected_schemes":[],"overview":"ok"}')

    def test_parse_sse_response_prefers_done_text_without_duplication(self) -> None:
        payload = _parse_sse_response(
            "\n".join(
                [
                    'event: response.output_text.delta',
                    'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":"}',
                    'event: response.output_text.delta',
                    'data: {"type":"response.output_text.delta","delta":"true}"}',
                    'event: response.output_text.done',
                    'data: {"type":"response.output_text.done","text":"{\\"ok\\":true}"}',
                ]
            )
        )

        self.assertEqual(payload, {"output_text": '{"ok":true}'})

    def test_chat_completion_retries_transient_chat_error(self) -> None:
        calls = {"count": 0}

        def fake_urlopen(request, timeout=0):  # noqa: ARG001
            calls["count"] += 1
            if calls["count"] == 1:
                raise HTTPError(
                    request.full_url,
                    503,
                    "Service unavailable",
                    hdrs=None,
                    fp=io.BytesIO(b'{"error":{"code":503,"message":"Service temporarily unavailable"}}'),
                )
            return _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                }
            )

        with patch("app.services.ai_gateway.urlopen", side_effect=fake_urlopen), patch("app.services.ai_gateway.time.sleep"):
            result = chat_completion(
                "https://example.com/v1",
                "test-key",
                "test-model",
                "system",
                "user",
            )

        self.assertEqual(result, "ok")
        self.assertEqual(calls["count"], 2)

    def test_chat_completion_uses_streaming_fallback_when_nonstream_content_is_empty(self) -> None:
        calls = {"count": 0}

        def fake_urlopen(request, timeout=0):  # noqa: ARG001
            calls["count"] += 1
            body = json.loads(request.data.decode("utf-8"))
            if calls["count"] == 1:
                self.assertFalse(body["stream"])
                return _FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": None,
                                    "role": "assistant",
                                }
                            }
                        ]
                    }
                )
            self.assertTrue(body["stream"])
            return _FakeResponse({"output_text": '{"selected_schemes":[],"overview":"ok"}'})

        with patch("app.services.ai_gateway.urlopen", side_effect=fake_urlopen):
            result = chat_completion(
                "https://example.com/v1",
                "test-key",
                "test-model",
                "system",
                "user",
                json_mode=True,
            )

        self.assertEqual(result, '{"selected_schemes":[],"overview":"ok"}')
        self.assertEqual(calls["count"], 2)

    def test_chat_completion_skips_responses_after_proxy_400(self) -> None:
        calls = {"responses": 0, "chat": 0}

        def fake_urlopen(request, timeout=0):  # noqa: ARG001
            if request.full_url.endswith("/responses"):
                calls["responses"] += 1
                raise HTTPError(
                    request.full_url,
                    400,
                    "Bad Request",
                    hdrs=None,
                    fp=io.BytesIO(b'{"error":{"code":400,"message":"Service error, please retry","type":"proxy_error"}}'),
                )
            calls["chat"] += 1
            return _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ok",
                            }
                        }
                    ]
                }
            )

        with patch("app.services.ai_gateway.urlopen", side_effect=fake_urlopen):
            first = chat_completion(
                "https://example.com/v1",
                "test-key",
                "gpt-5-test",
                "system",
                "user",
            )
            second = chat_completion(
                "https://example.com/v1",
                "test-key",
                "gpt-5-test",
                "system",
                "user",
            )

        self.assertEqual(first, "ok")
        self.assertEqual(second, "ok")
        self.assertEqual(calls["responses"], 1)
        self.assertEqual(calls["chat"], 2)

    def test_chat_completion_retries_transient_responses_error(self) -> None:
        calls = {"count": 0}

        def fake_urlopen(request, timeout=0):  # noqa: ARG001
            calls["count"] += 1
            if calls["count"] == 1:
                raise HTTPError(
                    request.full_url,
                    503,
                    "Service unavailable",
                    hdrs=None,
                    fp=io.BytesIO(b'{"error":{"code":503,"message":"Service temporarily unavailable"}}'),
                )
            return _FakeResponse({"output_text": "ok"})

        with patch("app.services.ai_gateway.urlopen", side_effect=fake_urlopen), patch("app.services.ai_gateway.time.sleep"):
            result = chat_completion(
                "https://example.com/v1",
                "test-key",
                "gpt-5-test",
                "system",
                "user",
            )

        self.assertEqual(result, "ok")
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
