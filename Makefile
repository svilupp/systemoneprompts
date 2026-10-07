.PHONY: help check-typescript check-python check-conformance check-docs check \
	sync-shared check-cache-parity release-check-typescript release-check-python publish-typescript publish-python

help:
	@printf '%s\n' \
		'make check-typescript  Run the self-contained TypeScript package checks' \
		'make check-python      Run the self-contained Python package checks' \
		'make check-conformance Run both package conformance adapters' \
		'make check-docs        Verify shared data and rendered documentation' \
		'make check             Run all deterministic repository checks' \
		'make release-check-typescript  Run TypeScript release checks' \
		'make release-check-python      Run Python release checks' \
		'make publish-typescript  Check and publish the npm package' \
		'make publish-python      Check and publish the Python package'

check-typescript:
	cd packages/typescript && sh scripts/run-quiet.sh "Checks" -- bun run check

check-python:
	cd packages/python && sh scripts/run-quiet.sh "Checks" -- uv run --locked python scripts/check.py

check-conformance:
	cd packages/typescript && sh scripts/run-quiet.sh "Conformance" -- bun run test:conformance
	cd packages/python && sh scripts/run-quiet.sh "Conformance" -- uv run --locked python scripts/conformance.py

sync-shared:
	uv run --project tools python tools/sync-shared.py

check-docs:
	uv run --project tools python tools/sync-shared.py --check
	python3 tools/render-spec.py --check
	python3 tools/check-docs.py

check-cache-parity:
	cd packages/typescript && sh scripts/run-quiet.sh "Cache parity" -- python3 ../../tools/check-cache-parity.py

check: check-typescript check-python check-conformance check-docs check-cache-parity

release-check-typescript:
	cd packages/typescript && sh scripts/run-quiet.sh "Release checks" -- bun run release:check

release-check-python:
	cd packages/python && sh scripts/run-quiet.sh "Release checks" -- uv run --locked python scripts/release-check.py

publish-typescript: release-check-typescript
	cd packages/typescript && bun run release:publish

publish-python: release-check-python
	cd packages/python && uv run --locked python scripts/publish.py
