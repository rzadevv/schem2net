IMAGE := schem2net-kicad:10.0.6

.PHONY: install test lint format image corpus bench corpus-b bench-b

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

image:
	docker build -q -t $(IMAGE) -f docker/Dockerfile.kicad docker

corpus: image
	uv run schem2net build-corpus a

bench: corpus
	uv run schem2net bench a --split dev

corpus-b: image
	uv run schem2net build-corpus b

bench-b: corpus-b
	uv run schem2net bench b --split dev --drawing-only
