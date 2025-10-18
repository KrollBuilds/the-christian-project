#!/usr/bin/env bash
# Helper script to export the OpenAI API key into the current shell session.

echo "Enter your OpenAI API key (input hidden):"
read -rs OPENAI_API_KEY
export OPENAI_API_KEY
echo
echo "OPENAI_API_KEY exported for this shell session."
echo "Remember to 'source' this script (e.g., source scripts/export_openai_key.sh) so the variable persists in your shell."
