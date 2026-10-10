"""Reading a data file into a DataFrame.

Two entry points over the same logic: `load_table` for a path on disk, and
`read_uploaded_dataframe` for the bytes a FileUpload widget hands over. Pure -
no widgets and no app state, so the app and the CLI share them.

Headerless tables matter here: a csv whose first row is already data (ECG5000
and most of the UCR archive look like this) would otherwise lose that row to
pandas' column names.
"""
import io
import os
import ssl
from urllib.error import URLError
from urllib.parse import urlsplit, unquote
from urllib.request import urlopen

import pandas as pd


def table_location(path):
    """Keep web URLs intact; normalize local paths and obtain a reader filename."""
    value = os.fspath(path).strip()
    if value.lower().startswith(('http://', 'https://')):
        parts = urlsplit(value)
        if not parts.netloc:
            raise ValueError('Enter a complete HTTP or HTTPS file URL.')
        return value, unquote(parts.path.rsplit('/', 1)[-1]) or 'download.csv'
    value = os.path.abspath(os.path.expanduser(value))
    return value, os.path.basename(value)


def _url_ssl_context():
    """Retain system/custom CAs and supplement missing Python roots with certifi."""
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        # Older source checkouts can still use the system certificate store.
        pass
    else:
        context.load_verify_locations(cafile=certifi.where())
    return context


def read_table_source(path):
    """Read local or HTTP(S) bytes once, preserving URL query parameters."""
    location, filename = table_location(path)
    if location.lower().startswith(('http://', 'https://')):
        try:
            with urlopen(location, timeout=30, context=_url_ssl_context()) as response:
                content_type = response.headers.get('Content-Type', '').lower()
                content = response.read()
        except (URLError, ssl.SSLCertVerificationError) as exc:
            reason = getattr(exc, 'reason', exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise ValueError(
                    'HTTPS certificate verification failed. In this notebook run '
                    '%pip install --upgrade certifi, then restart the kernel. '
                    'If your network uses a private certificate authority, configure '
                    'SSL_CERT_FILE with its trusted CA bundle. Verification remains enabled.'
                ) from exc
            raise
        if 'text/html' in content_type or content.lstrip()[:100].lower().startswith((b'<!doctype html', b'<html')):
            raise ValueError('This URL returns a web page. Use a direct CSV or table download URL.')
    else:
        with open(location, 'rb') as file:
            content = file.read()
    return location, filename, content


def load_table(path) -> pd.DataFrame:
    """Read a local file or HTTP(S) URL, sniffing delimited headers."""
    _, filename, content = read_table_source(path)
    return read_uploaded_dataframe(content, filename)


def read_uploaded_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    """Best-effort reader for many formats. Requires optional deps for some types."""
    ext = os.path.splitext((filename or "").lower())[1]

    if ext in {".xlsx", ".xls"}:
        try:
            return pd.read_excel(io.BytesIO(content))
        except ImportError as e:
            raise RuntimeError("Reading Excel requires 'openpyxl'. Try: pip install openpyxl") from e

    if ext == ".parquet":
        try:
            return pd.read_parquet(io.BytesIO(content))
        except ImportError as e:
            raise RuntimeError("Reading Parquet requires 'pyarrow'. Try: pip install pyarrow") from e

    if ext in {".feather", ".arrow"}:
        try:
            import pyarrow.feather as feather
            return feather.read_table(io.BytesIO(content)).to_pandas()
        except ImportError as e:
            raise RuntimeError("Reading Feather/Arrow requires 'pyarrow'. Try: pip install pyarrow") from e

    if ext == ".json":
        return pd.read_json(io.BytesIO(content), lines=False)
    if ext in {".jsonl", ".ndjson"}:
        return pd.read_json(io.BytesIO(content), lines=True)

    # Delimited text, including the fallback for an unknown extension.
    sep = {".tsv": "\t", ".tab": "\t", ".psv": "|"}.get(ext, ",")
    header = 0 if _has_header(content, sep) else None
    try:
        return pd.read_csv(io.BytesIO(content), sep=sep, header=header)
    except Exception:
        return pd.read_csv(io.BytesIO(content), sep=None, engine="python", header=header)


def _has_header(content: bytes, sep: str) -> bool:
    """A first row whose every field parses as a number is data, not column names."""
    try:
        first = pd.read_csv(io.BytesIO(content), sep=sep, header=None, nrows=1).iloc[0]
    except Exception:
        return True                     # unreadable first row: let pandas decide
    return not all(_is_number(v) for v in first)


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
