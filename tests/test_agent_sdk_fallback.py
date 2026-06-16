from __future__ import annotations

from app.services.agent import (
    _is_mcp_partial_transport_error,
    _mcp_partial_stream_attempts,
    _should_fallback_mcp_partial_stream,
)


def test_mcp_partial_stream_attempts_without_mcp() -> None:
    assert _mcp_partial_stream_attempts(False) == [True]


def test_mcp_partial_stream_attempts_with_mcp_prefers_partial_first() -> None:
    from app.config import settings

    assert settings.agent_sdk_include_partial_with_mcp is True
    assert _mcp_partial_stream_attempts(True) == [True, False]


def test_is_mcp_partial_transport_error_detects_control_channel_race() -> None:
    detail = (
        "CLIConnectionError: ProcessTransport is not ready for writing "
        "while handling MCP control response"
    )
    assert _is_mcp_partial_transport_error(detail, []) is True


def test_should_fallback_only_on_first_partial_mcp_attempt() -> None:
    detail = "CLIConnectionError: ProcessTransport is not ready for writing"
    assert _should_fallback_mcp_partial_stream(
        use_partial=True,
        has_mcp=True,
        streamed_any_text_delta=False,
        result_text="",
        error_detail=detail,
        stderr_lines=[],
        attempt_idx=0,
        total_attempts=2,
    )
    assert _should_fallback_mcp_partial_stream(
        use_partial=True,
        has_mcp=True,
        streamed_any_text_delta=False,
        result_text="",
        error_detail=detail,
        stderr_lines=[],
        attempt_idx=1,
        total_attempts=2,
    ) is False


def test_should_not_fallback_after_text_already_streamed() -> None:
    detail = "CLIConnectionError: ProcessTransport is not ready for writing"
    assert _should_fallback_mcp_partial_stream(
        use_partial=True,
        has_mcp=True,
        streamed_any_text_delta=True,
        result_text="",
        error_detail=detail,
        stderr_lines=[],
        attempt_idx=0,
        total_attempts=2,
    ) is False
