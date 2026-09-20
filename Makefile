.PHONY: help check-typescript check-python check-conformance check-docs check \
	sync-shared release-check-typescript release-check-python publish-typescript publish-python

PUBLISH_FLAG = $(if $(EXECUTE),--execute,)

help:
	@printf '%s\n' \
		'make check-typescript  Run the self-contained TypeScript package checks' \
		'make check-python      Run the self-contained Python package checks' \
		'make check-conformance Run both package conformance adapters' \
		'make check-docs        Verify shared data and rendered documentation' \
		'make check             Run all deterministic repository checks' \
		'make release-check-typescript  Run TypeScript release checks' \
		'make release-check-python      Run Python release checks' \
		'make publish-typescript TYPESCRIPT_ARTIFACT=... [EXECUTE=1]' \
		'make publish-python PYTHON_ARTIFACT=... [EXECUTE=1]'

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

check: check-typescript check-python check-conformance check-docs

release-check-typescript:
	cd packages/typescript && sh scripts/run-quiet.sh "Release checks" -- bun run release:check

release-check-python:
	cd packages/python && sh scripts/run-quiet.sh "Release checks" -- uv run --locked python scripts/release-check.py

publish-typescript: release-check-typescript
	@test -n "$(TYPESCRIPT_ARTIFACT)" || { printf '%s\n' 'TYPESCRIPT_ARTIFACT is required'; exit 2; }
	cd packages/typescript && bun run release:publish -- --artifact "$(abspath $(TYPESCRIPT_ARTIFACT))" $(PUBLISH_FLAG)

publish-python: release-check-python
	@test -n "$(PYTHON_ARTIFACT)" || { printf '%s\n' 'PYTHON_ARTIFACT is required'; exit 2; }
	cd packages/python && uv run --locked python scripts/publish.py --artifact "$(abspath $(PYTHON_ARTIFACT))" $(PUBLISH_FLAG)
