"""Named integration templates for p04c — deterministic, production-ready clients."""
from __future__ import annotations
import re

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

def match_template(name: str):
    """The named template for an integration, matched on whole words of its name.

    Substring matching handed Braintree/Mailchimp ("ai" in "braintree") the OpenAI client
    and Google Cloud Storage the RAG service ("rag" in "storage").
    """
    words = re.findall(r"[a-z0-9]+", name.lower())
    for key, entry in NAMED_TEMPLATES.items():
        if key in words or key == "".join(words):
            return entry
    return None


__all__ = [
    "match_template",
    "NAMED_TEMPLATES",
    "generate_stripe_client",
    "generate_sendgrid_client",
    "generate_twilio_client",
    "generate_ai_client",
    "generate_rag_service",
]
