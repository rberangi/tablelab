# Releases and versioning

TableLab's version is defined once, in `src/tablelab/__init__.py` as
`__version__`. Hatchling reads that value for wheel and source-package metadata.
The GUI, Python API, and command-line `--version` use the same value.

Use `MAJOR.MINOR.PATCH`: increment PATCH for fixes, MINOR for compatible features,
and MAJOR for incompatible public API changes. The current release is **0.3.0**;
the package remains in the 0.x development series.

## Prepare a release

1. Update `__version__` and add a dated entry to `CHANGELOG.md`.
2. Update the current-release and local-install examples in `README.md`.
3. Install development and release tools in your development environment:

   ```bash
   python -m pip install -e '.[dev,release]'
   ```

4. Run the tests:

   ```bash
   python -m pytest -q
   ```

5. Build the source archive and wheel. By default, build creates the wheel from
   the source archive, checking that the source release is complete:

   ```bash
   python -m build
   python -m twine check dist/tablelab-0.3.0-py3-none-any.whl dist/tablelab-0.3.0.tar.gz
   ```

   Replace `0.3.0` in commands with the version being released. Keep earlier
   artifacts if useful; validate and distribute the explicit new filenames.

6. Install the wheel into a separate environment and check both GUIs:

   ```bash
   python -m venv /tmp/tablelab-release-check
   /tmp/tablelab-release-check/bin/python -m pip install dist/tablelab-0.3.0-py3-none-any.whl
   /tmp/tablelab-release-check/bin/python -m tablelab --version
   /tmp/tablelab-release-check/bin/python -c 'from tablelab import QueryApp, TableApp; QueryApp(); TableApp(zoom=False)'
   ```

The source archive includes curated example notebooks, sample CSVs, tests,
changelog, and these instructions. Personal notebooks and cached outputs are
excluded. The wheel contains the importable package and its license/metadata.

Building does not publish a release. Uploading artifacts to PyPI and creating
repository tags are separate release actions.
