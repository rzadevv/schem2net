IMAGE := schem2net-kicad:10.0.6

.PHONY: install test lint format package-check image corpus bench corpus-b bench-b bench-schematic corpus-c bench-c corpus-d bench-d corpus-e bench-e corpus-f bench-f font roles eval-image

install:
	uv sync --locked --all-extras

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

# Direct Python calls keep uv from restoring the editable install over the wheel.
package-check:
	uv build
	.venv/bin/python -c 'from bench.release_smoke import check_distributions; check_distributions()'
	uv pip install --python .venv/bin/python --reinstall --no-deps dist/*.whl
	.venv/bin/python -c 'from schem2net import pipeline; assert "/site-packages/" in pipeline.__file__'
	.venv/bin/python -m pytest --cov=schem2net --cov-fail-under=80
	.venv/bin/python -m bench.release_smoke

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

corpus-d: image
	uv run schem2net build-corpus d

bench-d: corpus-d
	uv run schem2net bench d --split dev

corpus-e:
	uv run schem2net build-corpus e

bench-e: corpus-e
	uv run schem2net bench e --split dev

corpus-f: image
	uv run schem2net build-corpus f

bench-f: corpus-f
	uv run schem2net bench f --split dev

font: corpus-c
	uv run schem2net build-models font

roles: corpus corpus-b corpus-c
	uv run schem2net build-models roles

# The evaluation image: the runner (evaluate and its scorer), candidate and comparator,
# each a wheel built from its commit, all on the runner's locked core dependencies.
EVAL_RUNNER ?= $(shell git rev-parse --short HEAD)
EVAL_CANDIDATE ?= 56caa06
EVAL_COMPARATOR ?= 5d2417c
EVAL_IMAGE ?= schem2net-eval:$(EVAL_RUNNER)-$(EVAL_CANDIDATE)-$(EVAL_COMPARATOR)
EVAL_DIR := dist/eval-$(EVAL_RUNNER)-$(EVAL_CANDIDATE)-$(EVAL_COMPARATOR)

eval-image:
	test ! -e $(EVAL_DIR) || { echo "$(EVAL_DIR) exists: move it away to rebuild"; exit 1; }
	set -e; for side in runner:$(EVAL_RUNNER) candidate:$(EVAL_CANDIDATE) comparator:$(EVAL_COMPARATOR); do \
	  name=$${side%%:*}; rev=$${side#*:}; src=$(EVAL_DIR)/src-$$name; mkdir -p $$src; \
	  git rev-parse --verify --quiet "$$rev^{commit}" >/dev/null; \
	  git archive $$rev | tar -x -C $$src; \
	  SOURCE_DATE_EPOCH=$$(git log -1 --format=%ct $$rev) uv build -q --wheel $$src -o $(EVAL_DIR)/$$name; \
	  uv export -q --frozen --no-dev --no-emit-project --no-header --project $$src -o $(EVAL_DIR)/requirements-$$name.txt; \
	done
	diff -I '^#' $(EVAL_DIR)/requirements-runner.txt $(EVAL_DIR)/requirements-candidate.txt
	diff -I '^#' $(EVAL_DIR)/requirements-runner.txt $(EVAL_DIR)/requirements-comparator.txt
	cp $(EVAL_DIR)/requirements-runner.txt $(EVAL_DIR)/requirements.txt
	docker build -q --provenance=false -t $(EVAL_IMAGE) -f docker/Dockerfile.eval $(EVAL_DIR)
	sha256sum $(EVAL_DIR)/*/*.whl $(EVAL_DIR)/requirements.txt
	docker image inspect $(EVAL_IMAGE) --format '{{.Id}}'
