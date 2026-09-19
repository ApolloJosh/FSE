# Film Stock Exchange. `make dev` is the one command that gets you a running
# game with a full market and an account you can trade from.

PY ?= python3

.PHONY: help setup test dev seed mark site check clean

help:
	@echo "make setup   install dependencies"
	@echo "make dev     seed the market if empty, then serve on :8000"
	@echo "make test    run the test suite"
	@echo "make check   tests + crawl every page for dead links"
	@echo "make seed    rebuild two years of price history (--force)"
	@echo "make mark    the nightly job: reprice and mark positions"
	@echo "make site    build the read-only static market into site/"
	@echo "make clean   remove the local database and built site"

setup:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest tests/ -q

check: test
	$(PY) scripts/crawl.py

# Seeding exits 0 when the database already has prices, so this is safe to
# repeat - and a seed that genuinely fails stops here, rather than being
# swallowed and leaving uvicorn to fail with the same error a screen later.
# Sign in at /signin with "Continue as a test player".
dev:
	@test -f data/people.json || $(PY) -m fsx.cli snapshot
	@$(PY) -m app.jobs seed
	$(PY) -m uvicorn app.main:app --reload --port 8000

seed:
	$(PY) -m app.jobs seed --force

mark:
	$(PY) -m app.jobs mark

site:
	$(PY) -m fsx.cli site

clean:
	rm -rf site preview data/market.db data/market.db-wal data/market.db-shm
