"""
AI-Integrated Domain Pack for AetherOS.

Carries canonical entity graph, constraints, integrations, and architecture
notes for generating correct AI/LLM/RAG/chatbot backends and frontends.
"""
from __future__ import annotations

from aether_os.core.domain_packs import (
    DomainPack,
    EntitySpec,
    IntegrationSpec,
)

# ── Entities ──────────────────────────────────────────────────────────────────

_ENTITIES = [
    EntitySpec(
        name="KnowledgeBase",
        description=(
            "Named collection of indexed documents. Scoped per org. "
            "Tracks the embedding model used so vectors remain consistent."
        ),
        typical_fields=[
            "id", "name", "description",
            "embedding_model",  # e.g. text-embedding-3-small
            "doc_count",        # Integer — denormalized counter, refreshed on index
            "status",           # active / building / error
            "org_id",
            "created_at", "updated_at",
        ],
        unique_fields=["name"],  # unique per org
        fk_relationships=[],
        compliance_fields=[],
        indexes=["name", "org_id", "status"],
    ),
    EntitySpec(
        name="Document",
        description=(
            "A source file ingested into a KnowledgeBase. "
            "Chunked into Embeddings during the indexing pipeline."
        ),
        typical_fields=[
            "id", "title", "content",
            "file_path",   # unique — /docs/page-001.pdf format
            "mime_type",   # application/pdf, text/plain, text/markdown, etc.
            "status",      # pending / indexed / failed
            "org_id",
            "knowledge_base_id",
            "created_at", "updated_at",
        ],
        unique_fields=["file_path"],
        fk_relationships=["knowledge_base_id -> KnowledgeBase.id"],
        compliance_fields=[],
        indexes=["file_path", "org_id", "status", "knowledge_base_id"],
    ),
    EntitySpec(
        name="Embedding",
        description=(
            "A single vector chunk produced from a Document. "
            "Stored in Chroma (vector store); metadata row kept in Postgres for auditability."
        ),
        typical_fields=[
            "id",
            "document_id",   # FK → Document
            "vector_dim",    # Integer — must match model (1536 for text-embedding-3-small)
            "model_name",    # e.g. text-embedding-3-small
            "chunk_index",   # Integer — 0-based position within the document
            "chunk_text",    # non-empty — the text that was embedded
            "created_at",
        ],
        unique_fields=[],
        fk_relationships=["document_id -> Document.id"],
        compliance_fields=[],
        indexes=["document_id", "model_name"],
    ),
    EntitySpec(
        name="ChatSession",
        description=(
            "A conversation thread between a user and the RAG assistant. "
            "Tied to a KnowledgeBase that scopes retrieval."
        ),
        typical_fields=[
            "id",
            "user_id",             # FK → User
            "knowledge_base_id",   # FK → KnowledgeBase
            "title",
            "status",              # active / archived
            "created_at", "updated_at",
        ],
        unique_fields=[],
        fk_relationships=[
            "user_id -> User.id",
            "knowledge_base_id -> KnowledgeBase.id",
        ],
        compliance_fields=[],
        indexes=["user_id", "knowledge_base_id", "status"],
    ),
    EntitySpec(
        name="Message",
        description=(
            "A single turn in a ChatSession. Role must be one of user / assistant / system. "
            "token_count and latency_ms are captured for cost and quality monitoring."
        ),
        typical_fields=[
            "id",
            "session_id",    # FK → ChatSession
            "role",          # user / assistant / system
            "content",
            "token_count",   # Integer — prompt + completion tokens
            "latency_ms",    # Integer — time to first token in milliseconds
            "created_at",
        ],
        unique_fields=[],
        fk_relationships=["session_id -> ChatSession.id"],
        compliance_fields=[],
        indexes=["session_id", "role", "created_at"],
    ),
    EntitySpec(
        name="SearchResult",
        description=(
            "Persisted retrieval result for a user query within a ChatSession. "
            "Stores the query, top-k setting, and the JSON result for auditability."
        ),
        typical_fields=[
            "id",
            "session_id",    # FK → ChatSession
            "query",
            "top_k",         # Integer — number of chunks retrieved
            "result_json",   # JSON — list of {chunk_text, score, document_id}
            "created_at",
        ],
        unique_fields=[],
        fk_relationships=["session_id -> ChatSession.id"],
        compliance_fields=[],
        indexes=["session_id"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="openai",
        purpose=(
            "Embeddings (text-embedding-3-small → 1536 dims) and "
            "chat completions (gpt-4o for RAG-grounded answers)"
        ),
        env_vars=["OPENAI_API_KEY", "OPENAI_ORG_ID"],
        typical_methods=[
            "openai.embeddings.create",
            "openai.chat.completions.create",
        ],
    ),
    IntegrationSpec(
        name="chroma",
        purpose="Vector store for embedding persistence and similarity search",
        env_vars=["CHROMA_HOST", "CHROMA_PORT", "CHROMA_COLLECTION"],
        typical_methods=[
            "client.get_or_create_collection",
            "collection.add",
            "collection.query",
            "collection.delete",
        ],
    ),
    IntegrationSpec(
        name="sendgrid",
        purpose="Indexing completion notification emails to knowledge base owners",
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_indexing_complete",
            "send_indexing_failed",
        ],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    "Embedding.vector_dim MUST match the embedding model: 1536 for text-embedding-3-small, 3072 for text-embedding-3-large — enforce at the service layer before storing.",
    "Embedding.chunk_text MUST be non-empty (CheckConstraint: length(chunk_text) > 0) — reject blank chunks before calling the embedding API.",
    "Message.role MUST use an Enum: user / assistant / system — never a free-form string.",
    "NEVER store raw API keys in Message.content — scan content for key patterns (sk-...) and reject if found.",
    "KnowledgeBase.name must be unique per org_id — enforce via UniqueConstraint('name', 'org_id').",
    "All vector operations MUST use the same embedding model as stored in KnowledgeBase.embedding_model — mixing models corrupts similarity scores.",
    "Document.status transitions: pending → indexed (success) or pending → failed (error) — never skip states.",
    "Retrieval context MUST be injected into the prompt as a system message; never append retrieved text to the user message.",
    "ChatSession is scoped to one KnowledgeBase — never retrieve from a KB that the session is not linked to.",
    "Token usage MUST be recorded on every Message (token_count) for cost tracking and billing.",
    "SearchResult.result_json MUST be stored as JSON (not Text) with schema: [{chunk_text, score, document_id}].",
    "All org-scoped entities (Document, KnowledgeBase) MUST enforce org_id filter on every query — never leak cross-org data.",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    # 20 documents with unique /docs/page-NNN.pdf paths
    "file_path": "/docs/page-{i:03d}.pdf",
    "title": "Document {i}",
    "mime_type": "application/pdf|text/plain|text/markdown",
    "status_document": "pending|indexed|failed",
    "status_kb": "active|building|error",
    "embedding_model": "text-embedding-3-small",
    "vector_dim": "1536",
    "chunk_index": "{i}",
    "chunk_text": "This is chunk {i} of the indexed document content.",
    "model_name": "text-embedding-3-small",
    "role": "user|assistant|system",
    "content_message": "Message content for turn {i}.",
    "token_count": "{50 + i * 10}",
    "latency_ms": "{200 + i * 15}",
    "top_k": "5",
    "session_title": "Chat Session {i}",
    "kb_name": "KnowledgeBase-{i:02d}",
    "query": "What is the policy on item {i}?",
    # 5 knowledge bases, 10 chat sessions, 5 messages each = 50 messages
    "seed_counts": "documents:20, knowledge_bases:5, chat_sessions:10, messages_per_session:5",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Indexing pipeline: Document ingestion → chunking (500 token chunks, 50 token overlap) → embedding API call → Chroma upsert → Postgres Embedding row → Document.status='indexed'.",
    "RAG retrieval: embed query with same model as KB → Chroma similarity search (top_k) → inject chunks as system context → call chat completions → persist Message + SearchResult.",
    "Vector consistency: always read KnowledgeBase.embedding_model before calling the embedding API — never hardcode the model name at call sites.",
    "Chunking: use tiktoken to count tokens; target 500 tokens per chunk with 50-token overlap to maintain context across chunk boundaries.",
    "Async indexing: run Document ingestion as a FastAPI BackgroundTask (or Celery task) — never block the upload endpoint on embedding API calls.",
    "Chroma isolation: one Chroma collection per KnowledgeBase (named by KB id) — never share a collection across knowledge bases.",
    "Cost control: store token_count on every Message; implement a monthly budget cap per org — raise HTTP 429 when exceeded.",
    "Streaming: use Server-Sent Events (SSE) to stream chat completions token-by-token to the frontend — do not buffer the full response.",
    "Document deduplication: enforce unique file_path — if the same file is re-uploaded, update the existing Document record and re-index.",
    "PII in RAG: add a PII scrubber pass before storing chunk_text — never embed raw national IDs, credit card numbers, or passwords.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

AI_INTEGRATED_PACK = DomainPack(
    domain="ai_integrated",
    display_name="AI-Integrated / RAG / Chatbot",
    description=(
        "AI-powered applications with document ingestion, vector embeddings, "
        "knowledge bases, and RAG-grounded chat sessions."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["GDPR"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["AI_INTEGRATED_PACK"]
