"""Version and public entry points for installable releases."""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import tablelab


def test_version_and_public_gui_entry_points():
    assert re.fullmatch(r'\d+\.\d+\.\d+', tablelab.__version__)
    from tablelab import QueryApp, TableApp, query_main, main
    from tablelab.query_app import main as query_launcher
    from tablelab.app import main as chart_launcher
    assert query_main is query_launcher and main is chart_launcher
    assert QueryApp.__module__ == 'tablelab.query_app'
    assert TableApp.__module__ == 'tablelab.app'
    assert '__version__' in dir(tablelab) and 'query_main' in dir(tablelab)


def test_cli_version_does_not_require_a_file():
    process = subprocess.run([sys.executable, '-m', 'tablelab', '--version'],
                             capture_output=True, text=True, check=True)
    assert process.stdout.strip() == f'tablelab {tablelab.__version__}'


def test_release_notebooks_have_no_local_paths_or_saved_outputs():
    root = Path(__file__).parents[1]
    for name in ('chart_gui', 'tablelab_queries'):
        notebook = json.loads((root / 'examples' / (name + '.ipynb')).read_text())
        for cell in notebook['cells']:
            source = ''.join(cell['source'])
            assert '/Users/' not in source
            if cell['cell_type'] == 'code':
                assert cell['execution_count'] is None and cell['outputs'] == []
                ast.parse(source)
