"""Bounded PDF attachments, preserved byte-for-byte and served as downloads."""
import base64
import binascii
import re
from .validation import ApiError

MAX_PDF_BYTES = 10 * 1024 * 1024


def pdf_input(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApiError('Bitte eine PDF-Datei auswählen.')
    name, data = value.get('name'), value.get('data')
    if (not isinstance(name, str) or not name.strip() or len(name) > 120
            or not name.lower().endswith('.pdf')
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in name)
            or '/' in name or '\\' in name):
        raise ApiError('Bitte einen gültigen PDF-Dateinamen mit maximal 120 Zeichen verwenden.')
    if not isinstance(data, str):
        raise ApiError('Die PDF-Datei ist ungültig.')
    if len(data) > (MAX_PDF_BYTES + 2) // 3 * 4 + 64:
        raise ApiError('Die PDF-Datei darf maximal 10 MB groß sein.', 413)
    match = re.fullmatch(r'data:application/pdf;base64,([A-Za-z0-9+/=]+)', data)
    if not match:
        raise ApiError('Bitte eine PDF-Datei auswählen.')
    try:
        raw = base64.b64decode(match[1], validate=True)
    except (ValueError, binascii.Error):
        raise ApiError('Die PDF-Datei ist ungültig.') from None
    if len(raw) > MAX_PDF_BYTES:
        raise ApiError('Die PDF-Datei darf maximal 10 MB groß sein.', 413)
    # Recognize PDF framing without executing, rendering or decompressing content.
    # The original bytes (including digital signatures) remain unchanged.
    if not re.match(rb'%PDF-(?:1\.[0-7]|2\.0)(?:\r|\n|\s)', raw) or b'%%EOF' not in raw[-1024:]:
        raise ApiError('Die Datei wurde nicht als PDF erkannt. Bitte eine vollständige PDF-Datei auswählen.')
    return {'name': name.strip(), 'data': raw}
