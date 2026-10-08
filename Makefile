PYTHON ?= python

.PHONY: dev verify test eval-dry-run report memo-count

dev:
	$(PYTHON) run_local.py

verify:
	$(PYTHON) verify_setup.py

test:
	$(PYTHON) -m unittest discover -s tests -v

eval-dry-run:
	$(PYTHON) -m eval.runner --split dev --arch both --mode live --repeats 1 --dry-run > results/dev_dry_run.txt && cat results/dev_dry_run.txt

report:
	$(PYTHON) -m eval.report_checkpoint

memo-count:
	wc -w docs/memo.md
