import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys

# Setup mock for anthropic module BEFORE importing the provider
mock_anthropic = MagicMock()
mock_async_anthropic = MagicMock()
mock_anthropic.AsyncAnthropic = mock_async_anthropic
sys.modules["anthropic"] = mock_anthropic

from app.llm_hub.providers.anthropic import AnthropicProvider

class TestAnthropicProvider:
    
    @pytest.fixture
    def mock_client(self):
        with patch("app.llm_hub.providers.anthropic.AsyncAnthropic") as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.messages.create = AsyncMock()
            yield mock_instance

    @pytest.fixture
    def provider(self, mock_client):
        return AnthropicProvider(api_key="test-key")

    @pytest.mark.asyncio
    async def test_chat_success(self, provider, mock_client):
        mock_response = MagicMock()
        mock_response.id = "msg_123"
        mock_response.model_dump.return_value = {
            "id": "msg_123",
            "content": [{"text": "Hello world"}]
        }
        mock_client.messages.create.return_value = mock_response

        messages = [{"role": "user", "content": "Hi"}]
        response = await provider.chat(messages)

        assert response["id"] == "msg_123"
        mock_client.messages.create.assert_called_once()
        
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["messages"] == messages
        assert "stream" not in call_kwargs or call_kwargs["stream"] is False

    @pytest.mark.asyncio
    async def test_stream_success(self, provider, mock_client):
        async def async_generator():
            chunks = [{"type": "content_block_delta", "delta": {"text": "Hello"}}]
            for chunk_data in chunks:
                chunk = MagicMock()
                # Mock model_dump behavior
                chunk.model_dump.return_value = chunk_data
                yield chunk

        mock_client.messages.create.return_value = async_generator()

        messages = [{"role": "user", "content": "Hi"}]
        chunks_received = []
        async for chunk in provider.stream(messages):
            chunks_received.append(chunk)

        assert len(chunks_received) == 1
        mock_client.messages.create.assert_called_once()
        assert mock_client.messages.create.call_args.kwargs["stream"] is True

    @pytest.mark.asyncio
    async def test_embeddings_not_implemented(self, provider):
        with pytest.raises(NotImplementedError):
            await provider.embeddings(["text"])
