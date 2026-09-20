# Python package scripts

`check.py` keeps quality legs independent and uses `run-quiet.sh` so CI stays
readable while preserving a path to the full failing log. CI and release
checks invoke package smoke and standalone checks through the same wrapper.
`package-smoke.py` installs the built wheel and sdist into separate clean
virtual environments. `standalone-check.py` copies only this package to a
temporary directory and runs locked checks there. `release-prepare.py` updates
the package version.
`publish.py` builds a clean wheel and sdist, then publishes both to PyPI. Run
the release check before it.
