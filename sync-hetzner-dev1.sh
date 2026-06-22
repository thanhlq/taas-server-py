#!/bin/bash

# First, ensure the remote directory has write permissions
echo "Setting permissions on remote directory..."
ssh root@167.233.97.19 "chmod -R u+w ~/taas-server-py 2>/dev/null || true"

# Sync files with proper permissions
echo "Syncing files..."
rsync -avz --exclude '.venv' --exclude '.pytest_cache' --exclude '.git' --exclude '.ruff_cache' ./* root@167.233.97.19:~/taas-server-py

echo "Sync completed!"
