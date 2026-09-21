import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from .database import backup_database


def main():
    load_dotenv()
    data = Path(os.environ.get('DATA_DIR', 'data'))
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S-%fZ')
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else data / 'backups' / f'returns-{stamp}.sqlite'
    backup_database(data / 'returns.sqlite', destination)
    print('Datenbanksicherung erstellt.')


if __name__ == '__main__':
    main()
