"""Named integration templates for p04c — deterministic, production-ready clients."""
from __future__ import annotations
from pathlib import Path

from .stripe import generate_stripe_client
from .sendgrid import generate_sendgrid_client
from .twilio import generate_twilio_client
from .openai_ai import generate_ai_client
from .rag import generate_rag_service

# Map lowercase integration names → (generator_function, output_filename)
NAMED_TEMPLATES: dict = {
    "stripe": (generate_stripe_client, "stripe_client.py"),
    "sendgrid": (generate_sendgrid_client, "email_client.py"),
    "twilio": (generate_twilio_client, "sms_client.py"),
    "openai": (generate_ai_client, "ai_client.py"),
    "anthropic": (generate_ai_client, "ai_client.py"),
    "ai": (generate_ai_client, "ai_client.py"),
    "rag": (generate_rag_service, "rag_service.py"),
    "vector": (generate_rag_service, "rag_service.py"),
    "chromadb": (generate_rag_service, "rag_service.py"),
}

__all__ = [
    "NAMED_TEMPLATES",
    "generate_stripe_client",
    "generate_sendgrid_client",
    "generate_twilio_client",
    "generate_ai_client",
    "generate_rag_service",
]
