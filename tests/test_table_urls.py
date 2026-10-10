"""The Add table button handles blank paths and direct download URLs."""
import io
from urllib.error import URLError
from unittest.mock import patch, ANY
import matplotlib
matplotlib.use('Agg')
import pandas as pd
from tablelab.file_readers import load_table, table_location
from tablelab.query_app import QueryApp


class Response(io.BytesIO):
    def __init__(self, content, content_type='text/csv'):
        super().__init__(content)
        self.headers = {'Content-Type': content_type}


def test_add_table_button_opens_picker_without_path():
    app = QueryApp()
    app.load_btn.click()
    assert app.picker.ui.layout.display == 'flex'
    assert 'Choose a file' in app.status.value


def test_add_table_button_reads_url_once_and_preserves_metadata():
    app = QueryApp()
    url = 'https://example.com/files/test.tsv?download=1'
    app.path.value = url
    with patch('tablelab.file_readers.urlopen', return_value=Response(b'id\tvalue\n1\t3\n2\t4\n')) as download:
        app.load_btn.click()
    download.assert_called_once_with(url, timeout=30, context=ANY)
    context = download.call_args.kwargs["context"]
    import ssl
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    pd.testing.assert_frame_equal(app.df, pd.DataFrame({'id': [1, 2], 'value': [3, 4]}))
    assert app.tables[0]['name'] == 'test.tsv'
    assert app.tables[0]['source_path'] == url
    assert app.tables[0]['read_options']['sep'] == '\t'
    assert url in app.python_code() and 'working directory' not in app.python_code()
    assert not app.load_btn.disabled
    app.code_target.value = 'pyspark'
    code = app.show_code()
    assert 'Download the source URL' in code and ".load('test.tsv')" in code


def test_url_failures_leave_loaded_table_available():
    app = QueryApp()
    app.add_table(pd.DataFrame({'id': [1]}), 'Original')
    app.path.value = 'https://example.com/file.csv'
    with patch('tablelab.file_readers.urlopen', side_effect=URLError('offline')):
        app.load_btn.click()
    assert 'offline' in app.status.value
    assert len(app.tables) == 1 and not app.load_btn.disabled
    with patch('tablelab.file_readers.urlopen', return_value=Response(b'<html>web page</html>', 'text/html')):
        app.load_btn.click()
    assert 'direct CSV' in app.status.value and len(app.tables) == 1


def test_shared_reader_and_local_button(tmp_path):
    url = 'https://example.com/a.jsonl?raw=1'
    with patch('tablelab.file_readers.urlopen', return_value=Response(b'{"id":1}\n{"id":2}\n', 'application/json')):
        assert load_table(url).id.tolist() == [1, 2]
    path = tmp_path / 'local.csv'
    path.write_text('id,value\n1,5\n')
    app = QueryApp()
    app.path.value = str(path)
    app.load_btn.click()
    assert app.df.value.tolist() == [5]
    assert table_location(url) == (url, 'a.jsonl')


def test_chart_app_add_button_also_accepts_urls():
    from tablelab.app import TableApp
    app = TableApp(zoom=False)
    app.load_btn.click()
    assert app.picker.ui.layout.display == 'flex'
    app.path.value = 'https://example.com/values.csv'
    with patch('tablelab.file_readers.urlopen', return_value=Response(b'id,value\n1,5\n2,6\n')):
        app.load_btn.click()
    assert app.df.value.tolist() == [5, 6]
    assert len(app.tables) == 1
    app.path.value = 'https://'
    app.load_btn.click()
    assert 'complete HTTP' in app.status.value



def test_certificate_error_explains_kernel_fix():
    import ssl
    app = QueryApp()
    app.path.value = 'https://example.com/file.csv'
    error = ssl.SSLCertVerificationError(1, 'unable to get local issuer certificate')
    with patch('tablelab.file_readers.urlopen', side_effect=URLError(error)):
        app.load_btn.click()
    assert '%pip install --upgrade certifi' in app.status.value
    assert not app.load_btn.disabled and not app.tables


def test_certificate_bundle_supplements_default_store():
    import certifi
    from tablelab.file_readers import _url_ssl_context
    with patch('tablelab.file_readers.ssl.create_default_context') as defaults:
        context = _url_ssl_context()
        defaults.assert_called_once_with()
        context.load_verify_locations.assert_called_once_with(cafile=certifi.where())
