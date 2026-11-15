"""
Seed template for AI-integrated apps (RAG, chat, embeddings).

Generates seed data for:
- DocumentStore: 20 documents with chunking metadata, embedding status
- ChatSession: 20 sessions with UUID session_id, model names, user FKs
- ChatMessage: 60 messages (3 per session), alternating roles
- KnowledgeBase: 5 knowledge bases with document counts
- SearchQuery: 20 queries with relevance scores

Embedding dimensions: 1536 (OpenAI text-embedding-3-small).
All UUIDs use a deterministic pattern for reproducibility.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

_MODEL_NAMES = [
    "gpt-4o", "claude-3-5-sonnet", "gpt-4o", "gpt-4o-mini",
    "claude-3-5-sonnet", "gpt-4o", "claude-3-5-sonnet", "gpt-4o",
    "gpt-4o-mini", "claude-3-5-sonnet", "gpt-4o", "claude-3-5-sonnet",
    "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "gpt-4o",
    "gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet", "gpt-4o",
]

_DOCUMENT_TITLES = [
    "Introduction to Machine Learning Fundamentals",
    "FastAPI Best Practices and Performance Patterns",
    "PostgreSQL Query Optimization Guide",
    "RAG Architecture for Production Systems",
    "Vector Database Comparison: Pinecone vs Weaviate vs pgvector",
    "Prompt Engineering Techniques for LLMs",
    "Building Multi-Agent Systems with Claude",
    "HIPAA Compliance for AI Healthcare Applications",
    "Financial Fraud Detection using ML",
    "Natural Language Processing with Transformers",
    "Kubernetes Deployment Patterns for AI Workloads",
    "Embedding Models: Evaluation and Selection",
    "LangChain vs LlamaIndex: When to Use Each",
    "Semantic Search Implementation Guide",
    "OpenAI API Rate Limits and Cost Optimization",
    "Fine-tuning LLMs on Domain-Specific Data",
    "AI Observability with LangSmith and Weights & Biases",
    "Retrieval Augmented Generation — Complete Tutorial",
    "Building Chatbots with Memory and Context",
    "Vector Embeddings: From Theory to Production",
]

_EMBEDDING_STATUSES = [
    "indexed", "indexed", "indexed", "pending", "indexed",
    "indexed", "indexed", "failed", "indexed", "indexed",
    "pending", "indexed", "indexed", "indexed", "indexed",
    "pending", "indexed", "indexed", "indexed", "indexed",
]

_KB_NAMES = [
    "Company Knowledge Base",
    "Product Documentation",
    "Customer Support FAQ",
    "Legal & Compliance Repository",
    "Engineering Runbooks",
]

_USER_MESSAGES = [
    "What are the key differences between RAG and fine-tuning?",
    "How do I implement semantic search with pgvector?",
    "Explain the attention mechanism in transformers.",
    "What is the best embedding model for my use case?",
    "How do I reduce hallucinations in my chatbot?",
    "Can you summarize the document about Kubernetes patterns?",
    "What are the HIPAA requirements for storing AI outputs?",
    "How do I optimize my vector database queries?",
    "Explain multi-agent orchestration patterns.",
    "What is the token limit for GPT-4o?",
    "How do I implement streaming responses in FastAPI?",
    "What is retrieval augmented generation?",
    "Compare cosine similarity vs dot product for embeddings.",
    "How do I chunk documents for optimal retrieval?",
    "What is the best way to evaluate RAG performance?",
    "How do I handle conversation memory in LLM apps?",
    "Explain the difference between semantic and keyword search.",
    "How do I reduce latency in my AI pipeline?",
    "What are the best practices for prompt caching?",
    "How do I implement tool use with Claude?",
]

_ASSISTANT_MESSAGES = [
    "RAG retrieves relevant context at inference time, while fine-tuning bakes knowledge into weights. RAG is preferred when data changes frequently.",
    "Install pgvector, add a vector column, create an HNSW index, then use the <=> operator for cosine distance queries.",
    "Attention computes a weighted sum of values based on query-key similarity scores, enabling the model to focus on relevant tokens.",
    "For general-purpose tasks, OpenAI text-embedding-3-small (1536 dims) offers the best cost/performance. For domain-specific work, consider fine-tuned models.",
    "Use system prompts to constrain scope, add retrieval grounding, validate outputs, and implement confidence thresholds.",
    "The document outlines 3 main patterns: sidecar containers, init containers, and DaemonSets for GPU workloads on K8s.",
    "Under HIPAA, AI-generated outputs containing PHI must be encrypted, access-logged, and covered by a BAA with your AI provider.",
    "Use HNSW indexes over IVFFlat for better recall. Tune ef_construction and m parameters based on your dataset size.",
    "Multi-agent systems use a router/orchestrator agent to delegate subtasks to specialist agents, combining their outputs.",
    "GPT-4o supports 128K tokens in context. With function calling enabled, reserve ~2K tokens for tool definitions.",
    "Use FastAPI's StreamingResponse with text/event-stream content type, and async generator functions to stream tokens.",
    "RAG is a technique that retrieves relevant documents from a knowledge base and injects them into the LLM context before generation.",
    "Cosine similarity normalizes magnitude, making it scale-invariant. Dot product considers magnitude, useful when embedding norms carry meaning.",
    "Optimal chunk size depends on your embedding model's context window and query type. 512-token chunks with 50-token overlap is a common starting point.",
    "Evaluate with metrics: faithfulness, answer relevancy, context recall, and context precision using frameworks like RAGAS.",
    "Store conversation turns in a database, summarize older turns to fit context limits, and inject recent history into the system prompt.",
    "Semantic search uses embedding similarity to find conceptually related content. Keyword search matches exact terms. Hybrid approaches combine both.",
    "Cache embeddings, use streaming, implement request batching, and deploy inference close to your database to minimize round trips.",
    "Use the Anthropic prompt caching API by marking large context blocks with cache_control. Cache hits reduce latency by ~60% and cost by 90%.",
    "Define tools as JSON schemas in the tools parameter. Claude will call them by returning tool_use blocks which your code executes.",
]

_SYSTEM_MESSAGE = (
    "You are a helpful AI assistant with access to the company knowledge base. "
    "Always cite your sources when answering questions. Be concise and accurate."
)

_SEARCH_QUERIES = [
    "how to implement vector search",
    "RAG best practices production",
    "embedding model comparison 2024",
    "reduce LLM hallucinations",
    "semantic search vs keyword search",
    "pgvector cosine similarity query",
    "OpenAI token limits and pricing",
    "LangChain agent tools tutorial",
    "fine-tuning vs RAG tradeoffs",
    "chatbot conversation memory patterns",
    "HIPAA AI compliance requirements",
    "transformer attention mechanism explained",
    "FastAPI streaming responses guide",
    "document chunking strategies",
    "RAG evaluation metrics RAGAS",
    "multi-agent orchestration patterns",
    "prompt caching best practices",
    "Claude tool use examples",
    "Kubernetes GPU workloads deployment",
    "vector database pgvector vs pinecone",
]

_RELEVANCE_SCORES = [
    "0.92", "0.88", "0.85", "0.79", "0.95",
    "0.83", "0.76", "0.91", "0.87", "0.80",
    "0.93", "0.82", "0.89", "0.94", "0.78",
    "0.86", "0.90", "0.84", "0.77", "0.96",
]


def get_ai_integrated_seed_data(entities: list[str]) -> dict[str, list[dict]]:
    """Return seed data keyed by entity name for AI-integrated app verticals.

    Embedding dimension: 1536 (OpenAI text-embedding-3-small).
    All session IDs are deterministic UUIDs for reproducibility.
    """
    result: dict[str, list[dict]] = {}
    now = datetime.utcnow()

    # ── 1. KnowledgeBase ─────────────────────────────────────────────────────
    # Created first as DocumentStore FK-references it
    if _any_match(entities, ["knowledgebase", "knowledge_base", "knowledgebases"]):
        result["KnowledgeBase"] = [
            {
                "id": i + 1,
                "name": _KB_NAMES[i],
                "description": f"Centralized repository for {_KB_NAMES[i].lower()} content.",
                "document_count": [12, 8, 35, 6, 20][i],
                "embedding_model": "text-embedding-3-small",
                "embedding_dimensions": 1536,  # must be consistent across all KB records
                "is_active": True,
                "owner_user_id": (i % 5) + 1,  # references User that exists
                "created_at": (now - timedelta(days=180 - i * 30)).isoformat(),
                "updated_at": (now - timedelta(days=5)).isoformat(),
            }
            for i in range(5)
        ]

    # ── 2. DocumentStore ─────────────────────────────────────────────────────
    if _any_match(entities, ["documentstore", "document_store", "document", "documents"]):
        result["DocumentStore"] = [
            {
                "id": i + 1,
                "knowledge_base_id": (i % 5) + 1,  # references KnowledgeBase
                "title": _DOCUMENT_TITLES[i],
                "content_summary": (
                    f"This document covers {_DOCUMENT_TITLES[i].lower()}. "
                    "It provides comprehensive guidance with examples and best practices."
                ),
                "source_url": f"https://docs.example-ai.com/{i+1:03d}/{_slug(_DOCUMENT_TITLES[i])}",
                "file_path": f"/storage/documents/kb-{(i%5)+1}/doc-{i+1:04d}.pdf",
                "mime_type": "application/pdf",
                "file_size_bytes": 50000 + i * 12000,
                "total_chunks": (i % 8) + 3,
                "embedding_status": _EMBEDDING_STATUSES[i],  # Enum: indexed/pending/failed
                # Embedding dimensions: 1536 — must be consistent across all documents
                "embedding_dimensions": 1536,
                "language": "en",
                "created_at": (now - timedelta(days=90 - i * 4)).isoformat(),
                "indexed_at": (
                    (now - timedelta(days=89 - i * 4)).isoformat()
                    if _EMBEDDING_STATUSES[i] == "indexed"
                    else None
                ),
                "updated_at": (now - timedelta(days=10 - i % 10)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 3. DocumentChunk ─────────────────────────────────────────────────────
    # Each chunk must have: chunk_size, chunk_index, source_document_id FK
    if _any_match(entities, ["documentchunk", "document_chunk", "chunk", "chunks"]):
        chunks = []
        chunk_id = 1
        for doc_idx in range(20):
            num_chunks = (doc_idx % 8) + 3
            for chunk_idx in range(num_chunks):
                chunks.append({
                    "id": chunk_id,
                    "source_document_id": doc_idx + 1,  # FK to DocumentStore
                    "chunk_index": chunk_idx,           # 0-based index within document
                    "chunk_size": 512,                  # tokens per chunk (consistent)
                    "content": (
                        f"Chunk {chunk_idx + 1} of document '{_DOCUMENT_TITLES[doc_idx][:40]}'. "
                        "This section covers key concepts and implementation details."
                    ),
                    "token_count": 512 - (chunk_idx * 10),
                    "embedding_status": _EMBEDDING_STATUSES[doc_idx],
                    # Embedding dimensions: 1536 — must be consistent
                    "embedding_dimensions": 1536,
                    "created_at": (now - timedelta(days=89 - doc_idx * 4)).isoformat(),
                })
                chunk_id += 1
                if chunk_id > 60:  # cap at 60 chunks for seed brevity
                    break
            if chunk_id > 60:
                break
        result["DocumentChunk"] = chunks

    # ── 4. ChatSession ───────────────────────────────────────────────────────
    # session_id must be UUID — not sequential int
    if _any_match(entities, ["chatsession", "chat_session", "chatsessions"]):
        result["ChatSession"] = [
            {
                "id": i + 1,
                "session_id": _det_uuid(i),  # UUID primary key
                "user_id": (i % 20) + 1,    # FK to users table
                "knowledge_base_id": (i % 5) + 1,  # FK to KnowledgeBase
                "model_name": _MODEL_NAMES[i],
                "title": f"Chat session about: {_SEARCH_QUERIES[i][:50]}",
                "total_messages": 3,  # 3 messages per session in seed
                "total_tokens_used": 1200 + i * 150,
                "is_active": (i % 8 != 7),
                "created_at": (now - timedelta(hours=240 - i * 12)).isoformat(),
                "last_message_at": (now - timedelta(hours=i)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 5. ChatMessage ───────────────────────────────────────────────────────
    # 3 messages per session: system, user, assistant
    # Roles: system/user/assistant Enum
    if _any_match(entities, ["chatmessage", "chat_message", "chatmessages", "message", "messages"]):
        messages = []
        msg_id = 1
        for session_idx in range(20):
            session_uuid = _det_uuid(session_idx)
            base_time = now - timedelta(hours=240 - session_idx * 12)

            # Message 1: system prompt
            messages.append({
                "id": msg_id,
                "session_id": session_uuid,   # FK to ChatSession.session_id
                "role": "system",
                "content": _SYSTEM_MESSAGE,
                "tokens_used": 85,
                "created_at": base_time.isoformat(),
            })
            msg_id += 1

            # Message 2: user question
            messages.append({
                "id": msg_id,
                "session_id": session_uuid,
                "role": "user",
                "content": _USER_MESSAGES[session_idx],
                "tokens_used": 25 + (session_idx % 30),
                "created_at": (base_time + timedelta(seconds=10)).isoformat(),
            })
            msg_id += 1

            # Message 3: assistant response
            messages.append({
                "id": msg_id,
                "session_id": session_uuid,
                "role": "assistant",
                "content": _ASSISTANT_MESSAGES[session_idx],
                "tokens_used": 200 + (session_idx % 150),
                "created_at": (base_time + timedelta(seconds=15)).isoformat(),
            })
            msg_id += 1

        result["ChatMessage"] = messages

    # ── 6. SearchQuery ───────────────────────────────────────────────────────
    if _any_match(entities, ["searchquery", "search_query", "searchqueries"]):
        result["SearchQuery"] = [
            {
                "id": i + 1,
                "user_id": (i % 20) + 1,           # FK to users
                "knowledge_base_id": (i % 5) + 1,  # FK to KnowledgeBase
                "session_id": _det_uuid(i),         # FK to ChatSession (nullable)
                "query_text": _SEARCH_QUERIES[i],
                "results_count": 3 + (i % 7),
                # avg_relevance_score as Decimal string — maps to Numeric(4,2)
                "avg_relevance_score": _RELEVANCE_SCORES[i],
                "top_document_id": (i % 20) + 1,   # FK to DocumentStore
                "response_time_ms": 80 + i * 15,
                "created_at": (now - timedelta(hours=i * 5)).isoformat(),
            }
            for i in range(20)
        ]

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _det_uuid(index: int) -> str:
    """Generate a deterministic UUID-format string from an integer index.

    Format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx (version 4 style).
    Not cryptographically random — for seed data only.
    """
    # Spread index across the 128 bits deterministically
    n = (index + 1) * 0x9E3779B97F4A7C15  # Fibonacci hashing
    n = n & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  # clamp to 128 bits
    hex_str = f"{n:032x}"
    # Inject version (4) and variant (8-b) bits
    return (
        f"{hex_str[0:8]}-{hex_str[8:12]}-4{hex_str[13:16]}"
        f"-{format(int(hex_str[16], 16) & 0x3 | 0x8, 'x')}{hex_str[17:20]}"
        f"-{hex_str[20:32]}"
    )


def _slug(title: str) -> str:
    """Convert a document title to a URL-safe slug."""
    return title.lower().replace(" ", "-").replace(":", "").replace(",", "")[:50]


def _any_match(entities: list[str], candidates: list[str]) -> bool:
    """Return True if any entity name (case-insensitive) matches a candidate."""
    lower_entities = [e.lower() for e in entities]
    return any(c in lower_entities for c in candidates)
