from __future__ import annotations

from app.models.request import ChatStreamRequest


def test_chat_stream_request_prompt_aliases() -> None:
    assert ChatStreamRequest(userMessage="hello").get_prompt() == "hello"
    assert ChatStreamRequest(message="from rag").get_prompt() == "from rag"
    assert ChatStreamRequest(prompt="raw").get_prompt() == "raw"


def test_chat_stream_request_has_rag_context() -> None:
    plain = ChatStreamRequest(userMessage="hi")
    assert plain.has_rag_context() is False

    with_file_set = ChatStreamRequest(userMessage="hi", fileSetId="fs_abc")
    assert with_file_set.has_rag_context() is True

    with_kb_name = ChatStreamRequest(userMessage="hi", knowledgeBaseName="zsk1")
    assert with_kb_name.has_rag_context() is True


def test_chat_stream_request_to_rag_stream_request() -> None:
    request = ChatStreamRequest(
        userMessage="退款多久？",
        fileSetId="fs_test",
        conversationId="conv_1",
        options={"maxTurns": 5},
    )
    rag_request = request.to_rag_stream_request()
    assert rag_request.message == "退款多久？"
    assert rag_request.file_set_id == "fs_test"
    assert rag_request.conversation_id == "conv_1"
    assert rag_request.options.max_turns == 5
