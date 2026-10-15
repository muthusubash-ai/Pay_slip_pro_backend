from unittest.mock import Mock

import httpx

URL = "/api/v1/ai-assistant/chat"


def test_ai_assistant_requires_auth(client):
    response = client.post(URL, json={"message": "hello"})
    assert response.status_code == 401


def test_ai_assistant_rejects_empty_message(client, auth_headers):
    response = client.post(URL, json={"message": ""}, headers=auth_headers)
    assert response.status_code == 400


def test_ai_assistant_without_configured_key_falls_back_to_local_answer(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "")

    def unexpected_call(*args, **kwargs):
        raise AssertionError("OpenAI must not be called when no API key is configured")

    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", unexpected_call)

    response = client.post(URL, json={"message": "How many employees do I have?"}, headers=auth_headers)
    assert response.status_code == 200
    assert "active employees" in response.json()["reply"]


def test_ai_assistant_returns_reply_on_success(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "sk-test-dummy-key")

    upstream_response = Mock(status_code=200)
    upstream_response.raise_for_status.return_value = None
    upstream_response.json.return_value = {
        "choices": [{"message": {"content": "You have 0 active employees right now."}}]
    }
    http_post = Mock(return_value=upstream_response)
    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", http_post)

    response = client.post(URL, json={"message": "How many employees do I have?"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["reply"] == "You have 0 active employees right now."

    # The real OpenAI key must never be echoed back to the client.
    assert "sk-test-dummy-key" not in response.text

    # Confirm the request was actually sent to OpenAI's chat completions endpoint with the key.
    http_post.assert_called_once()
    call_args = http_post.call_args
    assert call_args.args[0] == "https://api.openai.com/v1/chat/completions"
    assert call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test-dummy-key"
    assert call_args.kwargs["json"]["messages"][-1] == {
        "role": "user", "content": "How many employees do I have?"
    }


def test_ai_assistant_forwards_conversation_history_for_memory(client, auth_headers, monkeypatch):
    """Regression test: prior turns must reach the LLM so the assistant has memory of
    what was already asked/answered, instead of treating every message as a fresh chat."""
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "sk-test-dummy-key")

    upstream_response = Mock(status_code=200)
    upstream_response.raise_for_status.return_value = None
    upstream_response.json.return_value = {
        "choices": [{"message": {"content": "Her name is Priya, as you just told me."}}]
    }
    http_post = Mock(return_value=upstream_response)
    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", http_post)

    response = client.post(URL, json={
        "message": "What's her name again?",
        "history": [
            {"role": "user", "content": "My top employee is Priya."},
            {"role": "assistant", "content": "Got it, noted Priya as your top employee."},
        ],
    }, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["reply"] == "Her name is Priya, as you just told me."

    sent_messages = http_post.call_args.kwargs["json"]["messages"]
    # system prompt, context, then history in order, then the new user message last.
    assert sent_messages[-3] == {"role": "user", "content": "My top employee is Priya."}
    assert sent_messages[-2] == {"role": "assistant", "content": "Got it, noted Priya as your top employee."}
    assert sent_messages[-1] == {"role": "user", "content": "What's her name again?"}


def test_ai_assistant_truncates_history_to_most_recent_20(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "sk-test-dummy-key")

    upstream_response = Mock(status_code=200)
    upstream_response.raise_for_status.return_value = None
    upstream_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    http_post = Mock(return_value=upstream_response)
    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", http_post)

    long_history = [{"role": "user", "content": f"message {i}"} for i in range(30)]
    response = client.post(URL, json={"message": "latest", "history": long_history}, headers=auth_headers)
    assert response.status_code == 200

    sent_messages = http_post.call_args.kwargs["json"]["messages"]
    # 2 system messages + 20 history (most recent) + 1 new user message
    assert len(sent_messages) == 23
    assert sent_messages[2] == {"role": "user", "content": "message 10"}


def test_ai_assistant_falls_back_to_local_answer_on_upstream_error(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "sk-test-dummy-key")

    err_response = Mock(status_code=429, text='{"error": {"message": "rate limited"}}')
    upstream_response = Mock(status_code=429)
    upstream_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "rate limited", request=Mock(), response=err_response
    )
    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", Mock(return_value=upstream_response))

    response = client.post(URL, json={"message": "How is net pay calculated?"}, headers=auth_headers)
    assert response.status_code == 200
    assert "Gross Salary" in response.json()["reply"]


def test_ai_assistant_falls_back_to_local_answer_on_timeout(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "sk-test-dummy-key")

    def timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", timeout)

    response = client.post(URL, json={"message": "How is net pay calculated?"}, headers=auth_headers)
    assert response.status_code == 200
    assert "Gross Salary" in response.json()["reply"]


def test_ai_assistant_company_fallback_does_not_crash_on_missing_fields(client, auth_headers, monkeypatch):
    """Regression test: Company has no email/phone fields - the fallback must not reference them."""
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "")
    client.put("/api/v1/company/", json={"company_name": "Acme Corp"}, headers=auth_headers)

    response = client.post(URL, json={"message": "What is our company policy?"}, headers=auth_headers)
    assert response.status_code == 200
    assert "Acme Corp" in response.json()["reply"]


def test_ai_assistant_is_rate_limited_per_user(client, auth_headers, monkeypatch):
    from app.auth.throttles import AIAssistantRateThrottle
    monkeypatch.setattr(AIAssistantRateThrottle, "get_rate", lambda self: "2/min")
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "")

    for _ in range(2):
        ok = client.post(URL, json={"message": "Hi"}, headers=auth_headers)
        assert ok.status_code == 200

    throttled = client.post(URL, json={"message": "Hi"}, headers=auth_headers)
    assert throttled.status_code == 429


def test_ai_assistant_returns_reply_on_gemini_success(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.ai_assistant_service.settings.GEMINI_API_KEY", "AQ.test-gemini-key")
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "")

    upstream_response = Mock(status_code=200)
    upstream_response.raise_for_status.return_value = None
    upstream_response.json.return_value = {
        "choices": [{"message": {"content": "Hello from Google Gemini!"}}]
    }
    http_post = Mock(return_value=upstream_response)
    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", http_post)

    response = client.post(URL, json={"message": "Hello"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["reply"] == "Hello from Google Gemini!"

    assert "AQ.test-gemini-key" not in response.text
    http_post.assert_called_once()
    call_args = http_post.call_args
    assert call_args.args[0] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert call_args.kwargs["headers"]["Authorization"] == "Bearer AQ.test-gemini-key"


def test_ai_assistant_gemini_native_fallback_on_compat_failure(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.ai_assistant_service.settings.GEMINI_API_KEY", "AQ.test-gemini-key")
    monkeypatch.setattr("app.services.ai_assistant_service.settings.OPENAI_API_KEY", "")

    err_response = Mock(status_code=400, text='{"error": "bad request"}')
    upstream_err = Mock(status_code=400)
    upstream_err.raise_for_status.side_effect = httpx.HTTPStatusError("bad request", request=Mock(), response=err_response)

    native_success = Mock(status_code=200)
    native_success.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Hello from Gemini Native fallback!"}]}}]
    }

    call_count = 0

    def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "generativelanguage.googleapis.com/v1beta/openai" in url:
            return upstream_err
        return native_success

    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", mock_post)

    response = client.post(URL, json={"message": "Hello"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["reply"] == "Hello from Gemini Native fallback!"
    assert call_count == 2


def test_ai_assistant_hermes_custom_endpoint_success(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.ai_assistant_service.settings.AI_BASE_URL", "http://localhost:8642/v1/chat/completions")
    monkeypatch.setattr("app.services.ai_assistant_service.settings.AI_API_KEY", "f38cd8bbfe4460bc01d3f7324b0d8d86be5f7265503b06da390fb89216e2f625")
    monkeypatch.setattr("app.services.ai_assistant_service.settings.AI_MODEL", "gpt-4o")

    upstream_response = Mock(status_code=200)
    upstream_response.raise_for_status.return_value = None
    upstream_response.json.return_value = {
        "choices": [{"message": {"content": "வணக்கம்! நான் PaySlipPro AI Assistant."}}]
    }
    http_post = Mock(return_value=upstream_response)
    monkeypatch.setattr("app.services.ai_assistant_service.httpx.post", http_post)

    response = client.post(URL, json={"message": "வணக்கம்"}, headers=auth_headers)
    assert response.status_code == 200
    assert "PaySlipPro AI Assistant" in response.json()["reply"]

    http_post.assert_called_once()
    call_args = http_post.call_args
    assert call_args.args[0] == "http://localhost:8642/v1/chat/completions"
    assert "Bearer f38cd8bbfe4460bc" in call_args.kwargs["headers"]["Authorization"]
    assert call_args.kwargs["json"]["model"] == "gpt-4o"

