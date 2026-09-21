import { DatabaseSync, backup } from 'node:sqlite';
import { existsSync, mkdirSync, chmodSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
const database=resolve(process.env.DATA_DIR||'data','returns.sqlite');
if(!existsSync(database))throw new Error('Datenbank nicht gefunden.');
const destination=resolve(process.argv[2]||`data/backups/returns-${new Date().toISOString().replaceAll(':','-')}.sqlite`);
if(existsSync(destination))throw new Error('Zieldatei existiert bereits. Bitte einen neuen Dateinamen wählen.');
mkdirSync(dirname(destination),{recursive:true,mode:0o700});
const db=new DatabaseSync(database,{readOnly:true});
try{await backup(db,destination);chmodSync(destination,0o600);console.log('Datenbanksicherung erstellt.');}finally{db.close();}
