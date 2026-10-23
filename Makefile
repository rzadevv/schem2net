IMAGE := schem2net-kicad:10.0.6

.PHONY: install test lint format image corpus bench corpus-b bench-b bench-schematic corpus-c bench-c corpus-d bench-d corpus-e bench-e corpus-f bench-f font roles

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

bench-schematic: corpus
	uv run schem2net bench-schematic a --split all

corpus-c:
	uv run schem2net build-corpus c

bench-c: corpus-c
	uv run schem2net bench c --split dev

corpus-d:
	uv run schem2net build-corpus d

bench-d: corpus-d
	uv run schem2net bench d --split dev

corpus-e:
	uv run schem2net build-corpus e

bench-e: corpus-e
	uv run schem2net bench e --split dev

corpus-f:
	uv run schem2net build-corpus f

bench-f: corpus-f
	uv run schem2net bench f --split dev

font: corpus-c
	uv run schem2net build-models font

roles: corpus corpus-b corpus-c
	uv run schem2net build-models roles
