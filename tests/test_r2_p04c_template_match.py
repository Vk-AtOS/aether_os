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


def test_written_integration_clients_are_imported_by_the_app_and_use_the_configured_endpoint(tmp_path):
    # KAN-264: services/ai_client.py and rag_service.py were written but imported by nothing, and the OpenAI client could
    # not use an OpenAI-compatible endpoint (no base_url).
    import asyncio
    from types import SimpleNamespace

    from aether_os.phases.p04c_integration_codegen import task_agent

    src = tmp_path / "p04a_backend_codegen" / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    data = {"project_dir": str(tmp_path), "integration_map": {"integrations": [
        {"name": "OpenAI", "type": "ai"}, {"name": "ChromaDB", "type": "vector"}]}}
    asyncio.run(task_agent.run(SimpleNamespace(input_data=data), [], tmp_path / "p04c"))
    asyncio.run(task_agent.run(SimpleNamespace(input_data=data), [], tmp_path / "p04c"))     # idempotent
    main_py = (src / "main.py").read_text()
    assert main_py.count("services.integration_manager") == 1
    compile(main_py, "main.py", "exec")
    manager = (src / "services" / "integration_manager.py").read_text()
    assert "services.ai_client" in manager and "services.rag_service" in manager
    for f in ("ai_client.py", "rag_service.py"):
        code = (src / "services" / f).read_text()
        assert "LLM_BASE_URL" in code and "base_url=_BASE_URL" in code, f
