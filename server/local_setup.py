import os
import secrets


def main():
    fd = os.open('.env', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write('APP_ENV=development\nAPP_ORIGIN=http://localhost:3000\nHOST=127.0.0.1\nPORT=3000\nDATA_DIR=./data\nSETUP_TOKEN=' + secrets.token_hex(32) + '\n')
    print('Lokale Konfiguration angelegt. Der Einrichtungsschlüssel steht in .env.')
    print('Start: python -m server')


if __name__ == '__main__':
    main()
