import { randomBytes } from 'node:crypto';
import { writeFileSync } from 'node:fs';
writeFileSync('.env',`NODE_ENV=development\nAPP_ORIGIN=http://localhost:3000\nHOST=127.0.0.1\nPORT=3000\nDATA_DIR=./data\nSETUP_TOKEN=${randomBytes(32).toString('hex')}\n`,{flag:'wx',mode:0o600});
console.log('Lokale Konfiguration angelegt. Der Einrichtungsschlüssel steht in .env.');
console.log('Start: node --env-file=.env server/index.mjs');
