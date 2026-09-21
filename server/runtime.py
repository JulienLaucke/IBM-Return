import os
from pathlib import Path

from dotenv import load_dotenv
from .app import create_app

ROOT = Path(__file__).resolve().parent.parent


def configuration():
    # Explicit deployment variables always take precedence over local settings.
    load_dotenv(ROOT / '.env', override=False)
    production = os.environ.get('APP_ENV', os.environ.get('NODE_ENV', 'development')) == 'production'
    port = int(os.environ.get('PORT', '3000'))
    origin = os.environ.get('APP_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL') or ('' if production else f'http://localhost:{port}')
    if not origin:
        raise ValueError('APP_ORIGIN fehlt.')
    return dict(database=Path(os.environ.get('DATA_DIR', ROOT / 'data')).resolve() / 'returns.sqlite',
                origin=origin, production=production, setup_token=os.environ.get('SETUP_TOKEN'), static_dir=ROOT / 'dist')


def application():
    return create_app(**configuration())
