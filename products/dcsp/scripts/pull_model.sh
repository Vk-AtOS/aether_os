#!/bin/bash
# Script to pull the deepseek-coder:6.7b model manually.
# Ensure Ollama is running at localhost:11434 before execution.

echo "Pulling deepseek-coder:6.7b model from local Ollama..."
curl -X POST http://localhost:11434/api/pull -d '{"name": "deepseek-coder:6.7b"}'
echo -e "\nModel pull request sent."
