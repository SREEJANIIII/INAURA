import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import embedding_service
from app.core.config import get_settings
from app.services import retrieval_service


def _mock_settings(provider="gemini", api_key="test-gemini-key", model="gemini-embedding-001"):
    s = MagicMock()
    s.embedding_provider = provider
    s.embedding_api_key = api_key
    s.embedding_model = model
    s.embedding_dimension = None
    s.google_api_key = None
    s.gemini_embedding_model = model
    return s


def test_is_configured_false_when_missing():
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider=None, api_key=None)):
        assert embedding_service.is_configured() is False
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key=None)):
        assert embedding_service.is_configured() is False
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="", api_key="some")):
        assert embedding_service.is_configured() is False
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="none", api_key="some")):
        assert embedding_service.is_configured() is False


def test_is_configured_true_with_gemini():
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key="key123")):
        assert embedding_service.is_configured() is True
    # Fallback to GOOGLE_API_KEY
    s = _mock_settings(provider="gemini", api_key=None)
    s.google_api_key = "google-key"
    with patch("app.services.embedding_service.get_settings", return_value=s):
        assert embedding_service.is_configured() is True


def test_get_provider_normalization():
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="Gemini", api_key="k")):
        assert embedding_service.get_provider() == "gemini"
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider=None, api_key=None)):
        assert embedding_service.get_provider() is None


def test_dimension_is_768():
    assert embedding_service.DIMENSION == 768


def test_dummy_embedding_length():
    vec = embedding_service.dummy_embedding("hello world")
    assert len(vec) == 768
    assert all(isinstance(v, float) for v in vec)
    assert len(set(vec)) > 1  # not all same


def test_embed_text_returns_none_when_not_configured():
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider=None, api_key=None)):
        result = asyncio.run(embedding_service.embed_text("query"))
        assert result is None
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key=None)):
        result = asyncio.run(embedding_service.embed_texts(["a", "b"]))
        assert result is None


def test_embed_text_calls_gemini_with_correct_model_and_dimension():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embedding": {"values": [0.1] * 768}}
    mock_resp.text = "ok"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key="test-key", model="gemini-embedding-001")):
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(embedding_service.embed_text("hello"))

    assert result is not None
    assert len(result) == 768
    # Verify correct endpoint and payload
    called_args = mock_client.__aenter__.return_value.post.call_args
    assert called_args is not None
    url = called_args[0][0] if called_args[0] else called_args[1].get("url", "")
    assert "gemini-embedding-001" in url
    assert "embedContent" in url
    # Payload should contain outputDimensionality 768 and taskType RETRIEVAL_QUERY
    kwargs = called_args[1]
    payload = kwargs.get("json", {})
    assert payload.get("outputDimensionality") == 768
    assert payload.get("taskType") == "RETRIEVAL_QUERY"
    assert payload.get("model") == "models/gemini-embedding-001"


def test_embed_texts_batch_calls_batch_endpoint():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embeddings": [{"values": [0.1]*768}, {"values": [0.2]*768}]}
    mock_resp.text = "ok"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key="k", model="gemini-embedding-001")):
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(embedding_service.embed_texts(["hello", "world"]))

    assert result is not None
    assert len(result) == 2
    assert len(result[0]) == 768
    called_url = mock_client.__aenter__.return_value.post.call_args[0][0]
    assert "batchEmbedContents" in called_url
    payload = mock_client.__aenter__.return_value.post.call_args[1]["json"]
    assert len(payload["requests"]) == 2
    assert payload["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert payload["requests"][0]["outputDimensionality"] == 768


def test_embed_text_api_failure_raises():
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "rate limited"
    mock_resp.json.return_value = {}
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key="k")):
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Gemini embedding API error"):
                asyncio.run(embedding_service.embed_text("hello"))


def test_retrieval_vector_search_uses_gemini_and_calls_rpc():
    # Mock embedding to return 768-d vector
    mock_embedding = [0.1] * 768
    mock_rpc_data = [
        {"id": "1", "role": "Software Engineer", "skill": "Python", "skill_category": "Programming",
         "importance": 0.85, "demand": 0.90, "interview_relevance": 0.75, "required_level": 0.80,
         "industry_confidence": 0.90, "source": "test", "source_url": "https://example.com",
         "description": "test", "similarity": 0.92}
    ]
    mock_supabase = MagicMock()
    mock_supabase.rpc.return_value.execute.return_value.data = mock_rpc_data

    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key="k")):
        with patch("app.services.embedding_service.embed_text", new=AsyncMock(return_value=mock_embedding)):
            with patch("app.services.retrieval_service.get_supabase_client", return_value=mock_supabase):
                result = asyncio.run(retrieval_service.retrieve("Software Engineer", top_k=5))

    # Should have used vector search path (note contains vector search)
    assert result["role"] == "Software Engineer"
    # Since we mocked RPC to return data, vector search should succeed
    mock_supabase.rpc.assert_called()
    # Verify correct RPC name and dimension
    called_rpc_name = mock_supabase.rpc.call_args[0][0]
    assert called_rpc_name == "match_industry_requirements"
    # Check that query_embedding dimension is 768
    call_kwargs = mock_supabase.rpc.call_args[0][1] if len(mock_supabase.rpc.call_args[0]) > 1 else mock_supabase.rpc.call_args[1]
    assert len(call_kwargs["query_embedding"]) == 768


def test_retrieval_fallback_when_embedding_fails():
    # Simulate embedding API failure -> should fallback to keyword
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key="k")):
        with patch("app.services.embedding_service.embed_text", new=AsyncMock(side_effect=RuntimeError("API down"))):
            result = asyncio.run(retrieval_service.retrieve("Software Engineer"))
    # Fallback should still return results via industry_service
    assert result["count"] > 0
    assert "deterministic fallback" in result["note"] or "INAU" in result["note"]


def test_retrieval_keyword_fallback_when_not_configured():
    # When not configured, should use keyword path
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider=None, api_key=None)):
        result = asyncio.run(retrieval_service.retrieve("Software Engineer"))
    assert result["count"] > 0
    assert result["role"] == "Software Engineer"
    # Should be deterministic fallback note
    assert "fallback" in result["note"].lower() or "deterministic" in result["note"].lower() or "vector" not in result["note"].lower()


def test_vector_search_chunks_calls_correct_rpc():
    mock_embedding = [0.1] * 768
    mock_data = [{"id": "chunk-1", "role": "Software Engineer", "topic": "Test", "content": "test content", "skills_mentioned": '["Python"]', "source": "test", "source_url": "https://example.com", "source_quality": 0.9, "similarity": 0.88}]
    mock_supabase = MagicMock()
    mock_supabase.rpc.return_value.execute.return_value.data = mock_data

    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key="k")):
        with patch("app.services.embedding_service.embed_text", new=AsyncMock(return_value=mock_embedding)):
            with patch("app.services.retrieval_service.get_supabase_client", return_value=mock_supabase):
                result = asyncio.run(retrieval_service.synthesize_custom_role("Quantum Computing Engineer"))

    # synthesize_custom_role should attempt vector search; if mocked returns chunk, it will use it
    # Our mock returns chunk for any RPC, so should be synthesized (needs >=2 skills, but our mock only has 1 skill, so will be insufficient_data)
    # Instead test direct _vector_search_chunks
    mock_supabase2 = MagicMock()
    mock_supabase2.rpc.return_value.execute.return_value.data = mock_data
    with patch("app.services.embedding_service.get_settings", return_value=_mock_settings(provider="gemini", api_key="k")):
        with patch("app.services.embedding_service.embed_text", new=AsyncMock(return_value=mock_embedding)):
            with patch("app.services.retrieval_service.get_supabase_client", return_value=mock_supabase2):
                from app.services.retrieval_service import _vector_search_chunks
                chunks = asyncio.run(_vector_search_chunks("test query", 5))
    assert chunks is not None
    assert len(chunks) == 1
    assert mock_supabase2.rpc.call_args[0][0] == "match_industry_knowledge_chunks"
