"""Validate uploads and retain only resized image pixels."""
import base64
import binascii
import io
import re
import threading
from PIL import Image, ImageOps, UnidentifiedImageError
from .validation import ApiError

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 20_000_000
_processing = threading.BoundedSemaphore(1)


def image_input(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > (MAX_BYTES + 2) // 3 * 4 + 64:
        raise ApiError('Das Bild darf maximal 5 MB groß sein.', 413)
    match = re.fullmatch(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)', value)
    if not match:
        raise ApiError('Bitte ein JPG-, PNG- oder WebP-Bild auswählen.')
    try:
        raw = base64.b64decode(match[2], validate=True)
    except (ValueError, binascii.Error):
        raise ApiError('Das Bild ist ungültig.') from None
    if len(raw) > MAX_BYTES:
        raise ApiError('Das Bild darf maximal 5 MB groß sein.', 413)
    if not _processing.acquire(blocking=False):
        raise ApiError('Ein Bild wird gerade verarbeitet. Bitte gleich erneut speichern.', 429)
    try:
        with Image.open(io.BytesIO(raw), formats=['JPEG', 'PNG', 'WEBP']) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ApiError('Das Bild darf maximal 20 Megapixel haben.')
            if getattr(source, 'is_animated', False):
                raise ApiError('Bitte ein einzelnes, nicht animiertes Bild auswählen.')
            source.load()
            with ImageOps.exif_transpose(source) as oriented:
                oriented.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                with oriented.convert('RGBA') as pixels:
                    # A new image excludes EXIF, GPS and embedded metadata.
                    with Image.new('RGB', pixels.size, 'white') as clean:
                        clean.paste(pixels, mask=pixels.getchannel('A'))
                        output = io.BytesIO()
                        clean.save(output, format='JPEG', quality=85)
                        return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ApiError('Das Bild konnte nicht gelesen werden. Bitte ein gültiges JPG-, PNG- oder WebP-Bild auswählen.') from None
    finally:
        _processing.release()
