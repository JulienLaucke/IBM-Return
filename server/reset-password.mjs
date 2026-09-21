import { openDatabase } from './database.mjs';
import { hashPassword, normalizeEmail, validPassword } from './security.mjs';
import { resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { createInterface } from 'node:readline/promises';
import { Writable } from 'node:stream';
if(!process.stdin.isTTY)throw new Error('Bitte in einem interaktiven Terminal ausführen.');
const database=resolve(process.env.DATA_DIR||'data','returns.sqlite');
if(!existsSync(database))throw new Error('Datenbank nicht gefunden.');
let muted=false;
const output=new Writable({write(chunk,encoding,done){if(!muted)process.stdout.write(chunk);done();}});
const rl=createInterface({input:process.stdin,output,terminal:true});
let email,password;
try{
 email=normalizeEmail(await rl.question('E-Mail des bestehenden Kontos: '));
 process.stdout.write('Neues Passwort (Eingabe verborgen): ');muted=true;password=await rl.question('');muted=false;process.stdout.write('\n');
}finally{rl.close();}
if(!validPassword(password))throw new Error('Passwort muss 12–128 Zeichen enthalten.');
const db=openDatabase(database);
try{
 const user=db.prepare('SELECT id FROM users WHERE email=?').get(email);
 if(!user)throw new Error('Dieses Konto existiert nicht.');
 const encoded=await hashPassword(password);
 db.exec('BEGIN IMMEDIATE');
 try{db.prepare('UPDATE users SET password_hash=? WHERE id=?').run(encoded,user.id);db.prepare('DELETE FROM sessions WHERE user_id=?').run(user.id);db.exec('COMMIT');}catch(e){db.exec('ROLLBACK');throw e;}
 console.log('Passwort geändert. Bestehende Sitzungen wurden abgemeldet.');
}finally{db.close();}
