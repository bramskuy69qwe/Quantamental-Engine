#!/bin/bash
for f in $(find . -type f -name '*.py' -not -path './.venv/*' -not -path './__pycache__/*' | sort); do
  lines=$(wc -l < "$f")
  
  # Try to extract docstring (first """ ... """)
  purpose=$(sed -n '/^"""/,/^"""/p' "$f" | head -2 | tail -1 | xargs | cut -c1-110)
  
  # If no docstring, try first comment
  if [ -z "$purpose" ]; then
    purpose=$(grep -m1 "^[[:space:]]*#" "$f" | sed 's/^[[:space:]]*#[[:space:]]*//' | cut -c1-110)
  fi
  
  # If still nothing, mark as Module
  if [ -z "$purpose" ]; then
    purpose="Module"
  fi
  
  echo "$f|$lines|$purpose"
done
