"""Password and session formats shared with existing databases."""
import hashlib
import hmac
import re
import secrets
import threading

from .validation import ApiError

_derivations = threading.BoundedSemaphore(2)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def equal_secret(left, right):
    return hmac.compare_digest(digest(left), digest(right))


def text_length(value):
    # Match the original JavaScript UTF-16 length constraint.
    return len(value.encode('utf-16-le', errors='surrogatepass')) // 2


def valid_password(value):
    return isinstance(value, str) and 12 <= text_length(value) <= 128 and not re.search(r'[\ud800-\udfff]', value)


def hash_password(password, salt=None):
    if not _derivations.acquire(blocking=False):
        raise ApiError('Bitte gleich erneut versuchen.', 429)
    try:
        salt = salt or secrets.token_hex(16)
        # Existing hashes use the hex salt as UTF-8 text, not decoded bytes.
        result = hashlib.scrypt(password.encode('utf-8'), salt=salt.encode('utf-8'),
                                n=131072, r=8, p=1, maxmem=256 * 1024 * 1024, dklen=64)
        return f'{salt}:{result.hex()}'
    finally:
        _derivations.release()


def verify_password(password, encoded):
    if not isinstance(encoded, str) or not re.fullmatch(r'[a-f0-9]{32}:[a-f0-9]{128}', encoded):
        return False
    if not isinstance(password, str) or text_length(password) > 128 or re.search(r'[\ud800-\udfff]', password):
        return False
    return equal_secret(hash_password(password, encoded.split(':')[0]), encoded)


def normalize_email(value):
    return value.strip().lower() if isinstance(value, str) else ''


def valid_email(value):
    return isinstance(value, str) and len(value) <= 254 and bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value)) and not re.search(r'[\ud800-\udfff]', value)
