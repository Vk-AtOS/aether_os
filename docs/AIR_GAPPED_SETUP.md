# Air-Gapped / Offline Setup

AetherOS can run 100% offline using Ollama for LLM inference and DuckDuckGo for web search.

## Requirements
- Ollama installed on the deployment machine
- At least one model pulled: `ollama pull llama3.1:8b`
- Python 3.9+, no internet required after setup

## Setup
1. Install Ollama: https://ollama.ai/download
2. Pull a model: `ollama pull llama3.1:8b`
3. Copy .env.example to .env and uncomment the AIR-GAPPED section
4. Set OFFLINE_MODE=true, PRIMARY_LLM=ollama
5. Start: `uvicorn aether_os.gateway.api:app --host 0.0.0.0 --port 8000`

## Minimal .env for Air-Gapped Mode

```bash
OFFLINE_MODE=true
PRIMARY_LLM=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_TIMEOUT=300
RETRIEVER=duckduckgo
AETHER_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
AETHER_ONE_ZT_SECRET=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
AETHER_ADMIN_USER=admin
AETHER_ADMIN_PASSWORD=<strong password>
CORS_ORIGINS=http://localhost:3000
```

## Performance Notes
- llama3.1:8b generates about 30-40 tokens/second on a modern CPU
- Full pipeline run: ~45-90 minutes on CPU (vs 11 min on Anthropic API)
- For speed on CPU: use mistral:7b (faster, slightly lower quality)
- For max quality on GPU: use llama3.1:70b (requires 40GB VRAM)
- For code generation: codellama:13b or deepseek-coder:6.7b give better results

## Tested Configuration
- Model: llama3.1:8b
- Hardware: 16GB RAM, Apple M2 (35 tok/s) or Intel i7 (18 tok/s)
- All 20 phases complete successfully

## How It Works

When `OFFLINE_MODE=true` the model router bypasses all cloud providers (Anthropic, Gemini, OpenRouter) and routes every LLM call directly to your local Ollama instance. No API keys are consulted, and no network calls are made to external services.

The `_is_provider_configured` check is also skipped for the Ollama entry — Ollama is always attempted and will fail at call time with a clear error if the Ollama daemon is not running.

## Troubleshooting

**"Connection refused" on port 11434:**
Ollama is not running. Start it with `ollama serve`.

**Very slow responses:**
Use a smaller model. `mistral:7b` is 30% faster than `llama3.1:8b` with similar code quality.

**Out of memory:**
Reduce `OLLAMA_MODEL` to a 3B or 7B parameter model, e.g. `qwen2.5-coder:3b`.

**Model not found:**
Run `ollama pull <model_name>` before starting AetherOS.
