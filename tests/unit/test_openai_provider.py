import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import json

# Setup mock for openai module BEFORE importing the provider
import sys
mock_openai = MagicMock()
mock_async_openai = MagicMock()
mock_openai.AsyncOpenAI = mock_async_openai
sys.modules["openai"] = mock_openai

from app.llm_hub.providers.openai import OpenAIProvider

class TestOpenAIProvider:
    
    @pytest.fixture
    def mock_client(self):
        with patch("app.llm_hub.providers.openai.AsyncOpenAI") as MockClient:
            mock_instance = MockClient.return_value
            # Setup chat completion mock
            mock_instance.chat.completions.create = AsyncMock()
            # Setup embeddings mock
            mock_instance.embeddings.create = AsyncMock()
            yield mock_instance

    @pytest.fixture
    def provider(self, mock_client):
        return OpenAIProvider(api_key="test-key")

    @pytest.mark.asyncio
    async def test_chat_success(self, provider, mock_client):
        # Mock response
        mock_response = MagicMock()
        mock_response.id = "chatcmpl-123"
        mock_response.model_dump.return_value = {
            "id": "chatcmpl-123",
            "choices": [{"message": {"content": "Hello world"}}]
        }
        mock_client.chat.completions.create.return_value = mock_response

        messages = [{"role": "user", "content": "Hi"}]
        response = await provider.chat(messages)

        assert response["id"] == "chatcmpl-123"
        mock_client.chat.completions.create.assert_called_once()
        
        # Verify call args
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"] == messages
        assert call_kwargs["stream"] is False

    @pytest.mark.asyncio
    async def test_chat_error(self, provider, mock_client):
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        
        with pytest.raises(Exception, match="API Error"):
            await provider.chat([{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_stream_success(self, provider, mock_client):
        # Mock streaming response
        async def async_generator():
            chunks = [{"id": "1", "content": "Hello"}, {"id": "2", "content": " World"}]
            for chunk_data in chunks:
                chunk = MagicMock()
                chunk.model_dump.return_value = chunk_data
                yield chunk

        mock_client.chat.completions.create.return_value = async_generator()

        messages = [{"role": "user", "content": "Hi"}]
        chunks_received = []
        async for chunk in provider.stream(messages):
            chunks_received.append(chunk)

        assert len(chunks_received) == 2
        assert chunks_received[0]["content"] == "Hello"
        mock_client.chat.completions.create.assert_called_once()
        assert mock_client.chat.completions.create.call_args.kwargs["stream"] is True

    @pytest.mark.asyncio
    async def test_embeddings_success(self, provider, mock_client):
        mock_response = MagicMock()
        mock_data_1 = MagicMock()
        mock_data_1.embedding = [0.1, 0.2, 0.3]
        mock_response.data = [mock_data_1]
        
        mock_client.embeddings.create.return_value = mock_response

        texts = ["hello"]
        embeddings = await provider.embeddings(texts)

        assert len(embeddings) == 1
        assert embeddings[0] == [0.1, 0.2, 0.3]
        mock_client.embeddings.create.assert_called_once_with(input=texts, model="text-embedding-3-small")
