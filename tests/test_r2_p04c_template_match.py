"""KAN-98 item 7: integration templates match whole words, not substrings."""
import pytest

from aether_os.phases.p04c_integration_codegen.templates import match_template


@pytest.mark.parametrize("name", ["Braintree", "Mailchimp", "Google Cloud Storage", "Fragment", "Raging Bull"])
def test_lookalikes_get_no_named_template(name):
    assert match_template(name) is None


@pytest.mark.parametrize("name,file", [("Stripe", "stripe_client.py"), ("OpenAI", "ai_client.py"),
                                       ("Azure OpenAI Service", "ai_client.py"), ("Open AI", "ai_client.py"),
                                       ("ChromaDB", "rag_service.py"), ("Twilio SMS", "sms_client.py")])
def test_real_names_still_match(name, file):
    assert match_template(name)[1] == file
