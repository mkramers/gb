default:
    @just --list

test:
    uv run pytest tests/ -v

fmt:
    uv run ruff format src/ tests/

lint:
    uv run ruff check src/ tests/

run:
    uv run gbb
