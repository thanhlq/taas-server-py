find . -name '__pycache__' -type d -exec rm -rf {} +
find . -name '*.pyc' -delete

# find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

uv cache clean --force

find . -name ".turbo" -print0 | xargs -0 rm -rf
find . -name ".next" -print0 | xargs -0 rm -rf
find . -name "tsconfig.tsbuildinfo" -print0 | xargs -0 rm -rf

find . -name "node_modules" -print0 | xargs -0 rm -rf

rm -rf ./venv
rm -rf .pytest_cache
rm -rf ./logs

uv sync --all-packages
# pnpm i
