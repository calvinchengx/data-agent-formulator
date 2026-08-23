# data-agent-formulator -- the same verbs as the family. There is no runtime
# here yet (docs/parity.md), so the targets that would start one say so rather
# than existing and doing nothing.
#
#   make doctor   # toolchain, and whether the upstream stack is reachable
#   make test     # the checks that hold this repository to itself
#   make check    # everything CI's quality job runs, in the order it runs it
ENV     ?= local
ENVFILE := $(if $(filter prod,$(ENV)),.env.prod,.env)

# Where the upstream checkout is, for `make doctor` to ask it whether its
# stack is up. Consumed over the network at run time; never built from here.
DAS_DIR ?= ../data-agent-service

ifeq ($(OS),Windows_NT)
  SHELL := sh.exe
  .SHELLFLAGS := -c
endif

PY ?= $(shell for c in python3.13 python3.12 python3 python py; do if "$$c" -c 'import sys; assert sys.version_info >= (3,12)' >/dev/null 2>&1; then echo "$$c"; break; fi; done)

.PHONY: help doctor login test witness witnesses check lint format

help: ## Show the available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

doctor: ## Check the toolchain, and that the upstream stack is reachable
	@ok=1; \
	for c in "$(PY)" uv; do command -v "$$c" >/dev/null 2>&1 && printf "  \033[32mok\033[0m    %s\n" "$$c" || { printf "  \033[31mFAIL\033[0m  %s not found\n" "$$c"; ok=0; }; done; \
	test -f $(ENVFILE) && printf "  \033[32mok\033[0m    $(ENVFILE) present\n" || printf "  \033[33mwarn\033[0m  $(ENVFILE) absent; copy .env.example\n"; \
	if [ -d $(DAS_DIR) ]; then \
	  printf "  \033[32mok\033[0m    upstream checkout at $(DAS_DIR)\n"; \
	  test -f $(DAS_DIR)/services/contract/openapi.json && printf "  \033[32mok\033[0m    upstream executor contract present\n" || { printf "  \033[31mFAIL\033[0m  upstream executor contract absent\n"; ok=0; }; \
	  $(MAKE) -s -C $(DAS_DIR) status >/dev/null 2>&1 && printf "  \033[32mok\033[0m    upstream stack reports OK\n" || printf "  \033[33mwarn\033[0m  upstream stack not up -- \`make up\` in $(DAS_DIR); not needed until there is a loader\n"; \
	else \
	  printf "  \033[31mFAIL\033[0m  no upstream checkout at $(DAS_DIR); the design is checked against its contract\n"; ok=0; \
	fi; \
	[ $$ok = 1 ] && echo "doctor: ready" || { echo "doctor: fix the FAIL rows"; exit 1; }

login: ## Sign in and write a short-lived token for the loader to read
	uv run python scripts/login.py $(ARGS)

test: ## The checks that hold this repository's scaffold to itself
	uv run --with pytest python -m pytest -q $(ARGS)

witness: ## Only the checks that need the upstream stack running
	uv run --with pytest python -m pytest -q -rs tests/test_identity_witness.py $(ARGS)

witnesses: ## Record what the suite witnessed, for the badge (--check to verify)
	uv run --with pytest python scripts/witnesses.py $(ARGS)

check: ## Everything CI's quality job runs, in the order it runs it
	# One command, because running a subset locally is how an unformatted file
	# ships: `ruff check` passes while `ruff format --check` does not, and only
	# the second is what CI asks.
	uv run --with ruff ruff check .
	uv run --with ruff ruff format --check .
	$(MAKE) --no-print-directory test
	$(MAKE) --no-print-directory witnesses ARGS=--check

lint: ## Ruff
	uv run --with ruff ruff check .

format: ## Ruff format
	uv run --with ruff ruff format .
