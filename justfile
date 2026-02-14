default:
    @just --list

test:
    uv run pytest tests/ -v

fmt:
    uv run ruff format src/ tests/

lint:
    uv run ruff check src/ tests/

build:
    uv cache clean gbb && uv tool install . --force

run:
    uv run gbb
