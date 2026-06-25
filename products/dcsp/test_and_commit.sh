#!/bin/bash
cd ~/Desktop/dcsp
source venv/bin/activate
python -m pytest tests/ -v
if [ $? -eq 0 ]; then
  git add .
  git commit -m "$1"
  echo "Tests passed. Committed."
else
  echo "Tests failed. Nothing committed."
fi
