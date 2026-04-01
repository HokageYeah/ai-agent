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
    async def test_chat_should_retry_blank_choices_response(self, provider, mock_client):
        blank_response = MagicMock()
        blank_response.id = "chatcmpl-blank"
        blank_response.model = "MiniMax-M2.7"
        blank_response.usage = MagicMock(total_tokens=0)
        blank_response.choices = None
        blank_response.status = None
        blank_response.msg = None
        blank_response.error = None
        blank_response.base_resp = {"status_code": 0, "status_msg": ""}

        ok_response = MagicMock()
        ok_response.id = "chatcmpl-ok"
        ok_response.model = "MiniMax-M2.7"
        ok_response.usage = MagicMock(total_tokens=12)
        ok_response.choices = [{"message": {"content": "恢复成功"}}]
        ok_response.model_dump.return_value = {
            "id": "chatcmpl-ok",
            "choices": [{"message": {"content": "恢复成功"}}],
        }

        mock_client.chat.completions.create.side_effect = [blank_response, ok_response]

        response = await provider.chat([{"role": "user", "content": "Hi"}])

        assert response["id"] == "chatcmpl-ok"
        assert mock_client.chat.completions.create.await_count == 2

    @pytest.mark.asyncio
    async def test_chat_should_not_retry_when_blank_choices_has_explicit_error(self, provider, mock_client):
        error_response = MagicMock()
        error_response.id = "chatcmpl-fail"
        error_response.model = "MiniMax-M2.7"
        error_response.usage = MagicMock(total_tokens=0)
        error_response.choices = None
        error_response.status = 435
        error_response.msg = "Model not support"
        error_response.error = None
        error_response.base_resp = {"status_code": 435, "status_msg": "Model not support"}

        mock_client.chat.completions.create.return_value = error_response

        with pytest.raises(ValueError, match="无法获取回复内容"):
            await provider.chat([{"role": "user", "content": "Hi"}])

        assert mock_client.chat.completions.create.await_count == 1

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
