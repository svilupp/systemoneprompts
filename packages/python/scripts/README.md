# Python package scripts

`check.py` keeps quality legs independent and uses `run-quiet.sh` so CI stays
readable while preserving a path to the full failing log. `package-smoke.py`
installs the built wheel and sdist into separate clean virtual environments.
`standalone-check.py` copies only this package to a temporary directory and
runs locked checks there. `release-check.py` runs the deterministic check plus
archive smoke. `release-prepare.py` updates the package version.
`publish.py` publishes an explicitly named wheel or sdist and dry-runs unless
`--execute` is supplied.
