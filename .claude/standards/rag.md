# RAG Standard

Production-ready patterns for Retrieval-Augmented Generation (RAG) systems.

## Core Principles

1. **Chunking Strategy**: Break documents intelligently
2. **Vector Quality**: Use appropriate embeddings for domain
3. **Retrieval Precision**: Retrieve relevant context, not noise
4. **Prompt Versioning**: Version all prompts with metadata
5. **Observability**: Log retrieval quality and LLM performance
6. **Cost Awareness**: Monitor tokens and API costs

---

## Architecture Pattern

```
User Query
    ↓
Query Embedding
    ↓
Vector Search (Top-K)
    ↓
Reranking (optional)
    ↓
Context Assembly
    ↓
LLM Generation (with context)
    ↓
Response + Citations
```

---

## Document Processing

### Chunking Strategy

**MUST use semantic chunking, not fixed-size chunks.**

```python
# services/document_processor.py
from langchain.text_splitter import RecursiveCharacterTextSplitter
import structlog

logger = structlog.get_logger()

class DocumentProcessor:
    """Process documents for RAG."""

    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,        # ~250 tokens
            chunk_overlap=200,      # Overlap to preserve context
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    async def process_document(
        self,
        document_id: str,
        content: str,
        metadata: dict
    ) -> list[dict]:
        """Split document into chunks with metadata."""
        chunks = self.text_splitter.split_text(content)

        logger.info(
            "document_chunked",
            document_id=document_id,
            chunks_count=len(chunks)
        )

        return [
            {
                "text": chunk,
                "document_id": document_id,
                "chunk_index": i,
                "metadata": metadata
            }
            for i, chunk in enumerate(chunks)
        ]
```

### Metadata Enrichment

**MUST enrich chunks with metadata for filtering.**

```python
chunk_metadata = {
    "document_id": "doc_123",
    "source": "telegram_channel",
    "channel_id": "@news_channel",
    "published_at": "2025-01-15T10:00:00Z",
    "language": "ru",
    "topic": "technology",
    "chunk_index": 0,
    "total_chunks": 10
}
```

---

## Vector Storage

### Using Qdrant

```python
# services/vector_store.py
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import structlog

logger = structlog.get_logger()

class VectorStore:
    """Qdrant vector store wrapper."""

    def __init__(self, url: str, api_key: str):
        self.client = QdrantClient(url=url, api_key=api_key)
        self.collection_name = "documents"

    async def create_collection(self, vector_size: int = 1536):
        """Create collection for embeddings."""
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=vector_size,      # OpenAI ada-002: 1536
                distance=Distance.COSINE
            )
        )

    async def upsert_chunks(self, chunks: list[dict], embeddings: list[list[float]]):
        """Insert or update chunks."""
        points = [
            PointStruct(
                id=chunk["id"],
                vector=embedding,
                payload=chunk
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]

        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )

        logger.info("vectors_upserted", count=len(points))

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict | None = None
    ) -> list[dict]:
        """Search for similar chunks."""
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=filters
        )

        logger.info("vector_search", results_count=len(results), top_k=top_k)

        return [
            {
                "text": hit.payload["text"],
                "metadata": hit.payload["metadata"],
                "score": hit.score
            }
            for hit in results
        ]
```

---

## Embeddings

### OpenAI Embeddings

```python
# services/embedding_service.py
from openai import AsyncOpenAI
import structlog

logger = structlog.get_logger()

class EmbeddingService:
    """Generate embeddings for text."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = "text-embedding-3-small"  # Cost-effective

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=texts
            )

            embeddings = [item.embedding for item in response.data]

            logger.info(
                "embeddings_generated",
                count=len(texts),
                model=self.model,
                tokens=response.usage.total_tokens
            )

            return embeddings

        except Exception as e:
            logger.error("embedding_failed", error=str(e))
            raise

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query."""
        embeddings = await self.embed_texts([query])
        return embeddings[0]
```

---

## Retrieval

### Hybrid Search (Recommended)

Combine vector similarity + keyword matching for better results.

```python
# services/retrieval_service.py
class RetrievalService:
    """Hybrid retrieval: vector + keyword search."""

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_service: EmbeddingService
    ):
        self.vector_store = vector_store
        self.embedding_service = embedding_service

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict | None = None
    ) -> list[dict]:
        """Retrieve relevant chunks."""
        # Generate query embedding
        query_embedding = await self.embedding_service.embed_query(query)

        # Vector search
        results = await self.vector_store.search(
            query_vector=query_embedding,
            top_k=top_k * 2,  # Get more candidates
            filters=filters
        )

        # Rerank by keyword overlap (simple scoring)
        query_keywords = set(query.lower().split())

        for result in results:
            text_keywords = set(result["text"].lower().split())
            keyword_overlap = len(query_keywords & text_keywords) / len(query_keywords)
            result["keyword_score"] = keyword_overlap
            result["final_score"] = result["score"] * 0.7 + keyword_overlap * 0.3

        # Sort by final score
        results.sort(key=lambda x: x["final_score"], reverse=True)

        return results[:top_k]
```

---

## LLM Integration

### Prompt Template (MUST version)

```python
# prompts/rag_prompts.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class PromptVersion:
    """Versioned prompt template."""
    version: str
    created_at: str
    template: str
    description: str

RAG_PROMPT_V1 = PromptVersion(
    version="v1.0",
    created_at="2025-01-15",
    description="Basic RAG prompt with context",
    template="""Ты полезный ассистент. Используй предоставленный контекст для ответа на вопрос пользователя.

Контекст:
{context}

Вопрос: {question}

Инструкции:
- Отвечай только на основе предоставленного контекста
- Если в контексте нет информации для ответа, скажи "Я не нашел информацию по этому вопросу"
- Указывай источники, если это возможно
- Будь кратким и точным

Ответ:"""
)
```

### RAG Generation

```python
# services/rag_service.py
from openai import AsyncOpenAI
from prompts.rag_prompts import RAG_PROMPT_V1
import structlog

logger = structlog.get_logger()

class RAGService:
    """RAG pipeline."""

    def __init__(
        self,
        retrieval_service: RetrievalService,
        openai_api_key: str
    ):
        self.retrieval = retrieval_service
        self.client = AsyncOpenAI(api_key=openai_api_key)
        self.model = "gpt-4o-mini"

    async def generate_answer(
        self,
        question: str,
        filters: dict | None = None
    ) -> dict:
        """Generate answer using RAG."""
        # Retrieve relevant chunks
        chunks = await self.retrieval.retrieve(
            query=question,
            top_k=5,
            filters=filters
        )

        # Assemble context
        context = "\n\n".join([
            f"[Источник {i+1}]: {chunk['text']}"
            for i, chunk in enumerate(chunks)
        ])

        # Build prompt
        prompt = RAG_PROMPT_V1.template.format(
            context=context,
            question=question
        )

        # Generate response
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Ты полезный ассистент."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for factual answers
                max_tokens=500
            )

            answer = response.choices[0].message.content

            # Log AI request
            logger.info(
                "rag_generation",
                prompt_version=RAG_PROMPT_V1.version,
                model=self.model,
                chunks_used=len(chunks),
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )

            return {
                "answer": answer,
                "sources": [chunk["metadata"] for chunk in chunks],
                "confidence": chunks[0]["final_score"] if chunks else 0.0
            }

        except Exception as e:
            logger.error("rag_generation_failed", error=str(e))
            raise
```

---

## Observability

### Logging Requirements

**MUST log:**
- Query and retrieval results
- Prompt version used
- Model and parameters
- Token usage and cost
- Latency
- Retrieval quality metrics

```python
logger.info(
    "rag_request",
    query=query,
    chunks_retrieved=len(chunks),
    prompt_version="v1.0",
    model="gpt-4o-mini",
    input_tokens=150,
    output_tokens=75,
    total_tokens=225,
    cost_usd=0.0003,
    latency_ms=850,
    top_score=chunks[0]["score"] if chunks else 0.0
)
```

---

## Cost Optimization

### Token Management

```python
def estimate_tokens(text: str) -> int:
    """Rough token count estimation."""
    return len(text) // 4

def truncate_context(chunks: list[dict], max_tokens: int = 3000) -> list[dict]:
    """Truncate context to fit token budget."""
    selected = []
    total_tokens = 0

    for chunk in chunks:
        chunk_tokens = estimate_tokens(chunk["text"])
        if total_tokens + chunk_tokens > max_tokens:
            break
        selected.append(chunk)
        total_tokens += chunk_tokens

    return selected
```

### Caching

```python
# Cache embeddings for frequent queries
from redis import asyncio as aioredis
import json

class EmbeddingCache:
    """Cache embeddings in Redis."""

    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url)

    async def get_embedding(self, text: str) -> list[float] | None:
        """Get cached embedding."""
        key = f"emb:{hash(text)}"
        cached = await self.redis.get(key)
        return json.loads(cached) if cached else None

    async def set_embedding(self, text: str, embedding: list[float]):
        """Cache embedding for 7 days."""
        key = f"emb:{hash(text)}"
        await self.redis.setex(key, 604800, json.dumps(embedding))
```

---

## Evaluation

### Retrieval Quality

```python
def evaluate_retrieval(query: str, retrieved_chunks: list[dict], ground_truth: str) -> dict:
    """Evaluate retrieval quality."""
    # Check if any chunk contains ground truth
    relevant_count = sum(
        1 for chunk in retrieved_chunks
        if ground_truth.lower() in chunk["text"].lower()
    )

    precision = relevant_count / len(retrieved_chunks) if retrieved_chunks else 0
    recall = 1.0 if relevant_count > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "top_score": retrieved_chunks[0]["score"] if retrieved_chunks else 0.0
    }
```

---

## Best Practices

### DO

- ✅ Version all prompts with metadata
- ✅ Log all AI requests (version, input, output, tokens, cost)
- ✅ Use semantic chunking (not fixed-size)
- ✅ Enrich chunks with metadata for filtering
- ✅ Implement retry logic with exponential backoff
- ✅ Cache embeddings for frequent queries
- ✅ Monitor retrieval quality and LLM performance
- ✅ Use lower temperature (0.2-0.3) for factual answers
- ✅ Provide citations/sources in responses

### DON'T

- ❌ Use magic strings for prompts (version them)
- ❌ Ignore token costs (monitor and optimize)
- ❌ Use fixed-size chunking (use semantic)
- ❌ Retrieve too many chunks (quality > quantity)
- ❌ Skip metadata (needed for filtering)
- ❌ Use high temperature for factual QA
- ❌ Trust LLM output blindly (validate)
- ❌ Skip observability (log everything)

---

## Common Patterns

### Question Answering

```python
answer = await rag_service.generate_answer(
    question="Какие новости были вчера?",
    filters={"date": "2025-01-14"}
)
```

### Summarization

```python
summary = await rag_service.summarize_documents(
    document_ids=["doc_1", "doc_2"],
    max_length=200
)
```

### Semantic Search

```python
results = await retrieval_service.retrieve(
    query="статьи про ИИ",
    top_k=10,
    filters={"topic": "technology"}
)
```

---

## References

- [OpenAI Embeddings](https://platform.openai.com/docs/guides/embeddings)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [LangChain Text Splitters](https://python.langchain.com/docs/modules/data_connection/document_transformers/)
- Framework standards: `.claude/standards/aiogram.md` (for AI Engineer role)
