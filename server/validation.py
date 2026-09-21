import datetime
import re


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        return False
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def valid_version(value):
    return type(value) is int and 1 <= value <= 9007199254740991


def shipment_input(raw):
    out = {}
    for key in ('name', 'device', 'tracking'):
        value = raw.get(key)
        if not isinstance(value, str) or len(value.strip().encode('utf-16-le', errors='surrogatepass')) // 2 > 120 or re.search(r'[\ud800-\udfff]', value):
            raise ApiError('Bitte die Textfelder prüfen (maximal 120 Zeichen).')
        out[key] = value.strip()
    if not out['name']:
        raise ApiError('Bitte einen Namen eingeben.')
    if raw.get('carrier') not in ('DHL', 'FedEx'):
        raise ApiError('Bitte DHL oder FedEx auswählen.')
    if raw.get('reason') not in ('Offboarding', 'Gerätetausch (4 Jahre)', 'Sonstiges'):
        raise ApiError('Bitte einen gültigen Anlass auswählen.')
    if not valid_date(raw.get('shipped')) or (raw.get('arrived') != '' and not valid_date(raw.get('arrived'))):
        raise ApiError('Bitte ein gültiges Datum eingeben.')
    if raw['arrived'] and raw['arrived'] < raw['shipped']:
        raise ApiError('Das Eingangsdatum darf nicht vor dem Versand liegen.')
    if not isinstance(raw.get('id'), str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', raw['id']):
        raise ApiError('Ungültige Rücksendung.')
    out.update({key: raw[key] for key in ('id', 'carrier', 'reason', 'shipped', 'arrived')})
    return out
