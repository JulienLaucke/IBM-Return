import { createServer } from 'node:http';
import { randomBytes } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { openDatabase } from './database.mjs';
import { hashPassword, verifyPassword, digest, equalSecret, validPassword, normalizeEmail, validEmail } from './security.mjs';
import { shipmentInput, error } from './validation.mjs';
const fields = 'id,name,carrier,reason,device,tracking,shipped,arrived,version,created';
const sessionSeconds = 8 * 60 * 60;
export async function createApp({ database, origin, production = true, setupToken, staticDir }) {
  const appUrl = new URL(origin);
  if (appUrl.origin !== origin || (production && appUrl.protocol !== 'https:')) throw new Error('APP_ORIGIN muss eine vollständige HTTPS-Origin ohne abschließenden Schrägstrich sein.');
  const db = openDatabase(database);
  if (!db.prepare('SELECT id FROM users LIMIT 1').get() && (typeof setupToken !== 'string' || setupToken.length < 32)) { db.close(); throw new Error('Für die Ersteinrichtung ist SETUP_TOKEN mit mindestens 32 Zeichen erforderlich.'); }
  const cookieName = production ? '__Host-ibm_return' : 'ibm_return_dev';
  const dummyHash = await hashPassword(randomBytes(24).toString('hex'));
  const root = resolve(staticDir);
  function cookie(token, maxAge = sessionSeconds) { return `${cookieName}=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${production ? '; Secure' : ''}`; }
  function cleanup() {
    const now = Date.now();
    db.prepare('DELETE FROM sessions WHERE expires <= ?').run(now);
    db.prepare('DELETE FROM rate_limits WHERE expires <= ?').run(now);
  }
  function limited(key, limit) {
    cleanup();
    const hashed = digest(key);
    db.prepare('INSERT INTO rate_limits (key,count,expires) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1').run(hashed,Date.now()+15*60*1000);
    if (db.prepare('SELECT count FROM rate_limits WHERE key=?').get(hashed).count > limit) throw error('Zu viele Versuche. Bitte in 15 Minuten erneut versuchen.',429);
  }
  function session(req) {
    const token = String(req.headers.cookie || '').split(';').map(x=>x.trim()).find(x=>x.startsWith(cookieName+'='))?.slice(cookieName.length+1);
    if (!token || !/^[a-f0-9]{64}$/.test(token)) return null;
    return db.prepare('SELECT u.id,u.email,s.token_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?').get(digest(token),Date.now()) || null;
  }
  function requireSession(req) { const user = session(req); if (!user) throw error('Deine Sitzung ist abgelaufen. Bitte erneut anmelden.',401); return user; }
  async function body(req) {
    if (!String(req.headers['content-type'] || '').toLowerCase().startsWith('application/json')) throw error('JSON-Eingabe erforderlich.',415);
    if (Number(req.headers['content-length']) > 16384) throw error('Eingabe zu groß.',413);
    let size=0; const chunks=[];
    for await (const chunk of req) { size+=chunk.length; if(size>16384) throw error('Eingabe zu groß.',413); chunks.push(chunk); }
    let value; try { value=JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw error('Ungültige Eingabe.'); }
    if(!value || typeof value!=='object' || Array.isArray(value)) throw error('Ungültige Eingabe.');
    return value;
  }
  function send(res,status,data,headers={}) { res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',...headers}); res.end(JSON.stringify(data)); }
  function beginSession(res,user) {
    cleanup();
    // Bound session growth while allowing both users on several devices.
    db.prepare('DELETE FROM sessions WHERE token_hash IN (SELECT token_hash FROM sessions WHERE user_id=? ORDER BY expires DESC LIMIT -1 OFFSET 4)').run(user.id);
    const token=randomBytes(32).toString('hex');
    db.prepare('INSERT INTO sessions (token_hash,user_id,expires) VALUES (?,?,?)').run(digest(token),user.id,Date.now()+sessionSeconds*1000);
    send(res,200,{user:{email:user.email}},{'Set-Cookie':cookie(token)});
  }
  const server=createServer(async(req,res)=>{
    res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Referrer-Policy','same-origin');
    res.setHeader('X-Frame-Options','DENY');
    res.setHeader('Permissions-Policy','camera=(), microphone=(), geolocation=()');
    res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'");
    if(production)res.setHeader('Strict-Transport-Security','max-age=31536000');
    try {
      const path=new URL(req.url,origin).pathname;
      const method=req.method;
      if (!['GET','HEAD','POST','PATCH','DELETE'].includes(method)) throw error('Methode nicht erlaubt.',405);
      if (['POST','PATCH','DELETE'].includes(method) && req.headers.origin !== origin) throw error('Ungültiger Ursprung der Anfrage.',403);
      if (path==='/api/health' && method==='GET') { db.prepare('SELECT 1').get(); return send(res,200,{ok:true}); }
      if (path==='/api/setup' && method==='GET') return send(res,200,{configured:!!db.prepare('SELECT id FROM users LIMIT 1').get()});
      if (path==='/api/setup' && method==='POST') {
        limited('setup:'+req.socket.remoteAddress,8);
        if(db.prepare('SELECT id FROM users LIMIT 1').get())throw error('Die Einrichtung ist bereits abgeschlossen.',409);
        const raw=await body(req);
        if(typeof raw.token!=='string' || !setupToken || !equalSecret(raw.token,setupToken))throw error('Einrichtungsschlüssel ungültig.',403);
        if(!Array.isArray(raw.users) || raw.users.length!==2)throw error('Bitte genau zwei Konten einrichten.');
        const users=raw.users.map(u=>({email:normalizeEmail(u?.email),password:u?.password}));
        if(users.some(u=>!validEmail(u.email)||!validPassword(u.password)) || users[0].email===users[1].email)throw error('Zwei unterschiedliche E-Mail-Adressen und Passwörter mit jeweils 12–128 Zeichen sind erforderlich.');
        const hashes=[]; for(const u of users)hashes.push(await hashPassword(u.password));
        db.exec('BEGIN IMMEDIATE');
        try {
          if(db.prepare('SELECT id FROM users LIMIT 1').get())throw error('Die Einrichtung ist bereits abgeschlossen.',409);
          users.forEach((u,i)=>db.prepare('INSERT INTO users (id,email,password_hash,created) VALUES (?,?,?,?)').run(i+1,u.email,hashes[i],new Date().toISOString()));
          db.exec('COMMIT');
        } catch(e){db.exec('ROLLBACK');throw e;}
        return send(res,201,{ok:true});
      }
      if(path==='/api/auth/login' && method==='POST') {
        limited('login-peer:'+req.socket.remoteAddress,30);
        const raw=await body(req); const email=normalizeEmail(raw.email);
        limited('login-email:'+email,10);
        if(!validEmail(email)||typeof raw.password!=='string'||raw.password.length>128)throw error('E-Mail oder Passwort stimmt nicht.',401);
        const user=db.prepare('SELECT * FROM users WHERE email=?').get(email);
        const valid=await verifyPassword(raw.password,user?.password_hash||dummyHash);
        if(!user || !valid || db.prepare('SELECT password_hash FROM users WHERE id=?').get(user.id)?.password_hash !== user.password_hash)throw error('E-Mail oder Passwort stimmt nicht.',401);
        db.prepare('DELETE FROM rate_limits WHERE key=?').run(digest('login-email:'+email));
        return beginSession(res,user);
      }
      if(path==='/api/auth/me' && method==='GET') { const user=requireSession(req); return send(res,200,{user:{email:user.email}}); }
      if(path==='/api/auth/logout' && method==='POST') {
        const user=requireSession(req);db.prepare('DELETE FROM sessions WHERE token_hash=?').run(user.token_hash);
        return send(res,200,{ok:true},{'Set-Cookie':cookie('',0)});
      }
      if(path==='/api/auth/password' && method==='POST') {
        const user=requireSession(req);limited('password:'+user.id,10);const raw=await body(req);
        if(!validPassword(raw.newPassword)||typeof raw.currentPassword!=='string'||raw.currentPassword.length>128)throw error('Das neue Passwort muss 12–128 Zeichen enthalten.');
        const old=db.prepare('SELECT password_hash FROM users WHERE id=?').get(user.id);
        if(!await verifyPassword(raw.currentPassword,old.password_hash))throw error('Das aktuelle Passwort stimmt nicht.',400);
        const encoded=await hashPassword(raw.newPassword);
        db.exec('BEGIN IMMEDIATE');
        try{
          const result=db.prepare('UPDATE users SET password_hash=? WHERE id=? AND password_hash=?').run(encoded,user.id,old.password_hash);
          if(!result.changes)throw error('Passwort wurde inzwischen geändert. Bitte erneut anmelden.',409);
          db.prepare('DELETE FROM sessions WHERE user_id=?').run(user.id);db.exec('COMMIT');
        }catch(e){db.exec('ROLLBACK');throw e;}
        return beginSession(res,user);
      }
      if(path==='/api/shipments') {
        const user=requireSession(req);
        if(method==='GET')return send(res,200,{shipments:db.prepare(`SELECT ${fields} FROM shipments ORDER BY created DESC,id DESC`).all()});
        if(!['POST','PATCH','DELETE'].includes(method))throw error('Methode nicht erlaubt.',405);
        const raw=await body(req);
        if(method==='DELETE') {
          if(typeof raw.id!=='string'||!Number.isInteger(raw.version)||raw.version<1)throw error('Ungültige Rücksendung.');
          const result=db.prepare('DELETE FROM shipments WHERE id=? AND version=?').run(raw.id,raw.version);
          if(!result.changes)throw error('Eintrag inzwischen geändert oder entfernt. Bitte die Liste aktualisieren.',409);
          return send(res,200,{ok:true});
        }
        const v=shipmentInput(raw), values=[v.name,v.carrier,v.reason,v.device,v.tracking,v.shipped,v.arrived];
        if(method==='POST') {
          const existing=db.prepare(`SELECT ${fields} FROM shipments WHERE id=?`).get(v.id);
          if(existing){if(values.some((x,i)=>x!==existing[['name','carrier','reason','device','tracking','shipped','arrived'][i]]))throw error('Eintrag existiert bereits mit anderen Angaben.',409);return send(res,200,{shipment:existing});}
          db.prepare('INSERT INTO shipments (name,carrier,reason,device,tracking,shipped,arrived,id,created,creator,updater) VALUES (?,?,?,?,?,?,?,?,?,?,?)').run(...values,v.id,new Date().toISOString(),user.id,user.id);
        }else {
          if(!Number.isInteger(raw.version)||raw.version<1)throw error('Ungültige Version.');
          const result=db.prepare('UPDATE shipments SET name=?,carrier=?,reason=?,device=?,tracking=?,shipped=?,arrived=?,updater=?,version=version+1 WHERE id=? AND version=?').run(...values,user.id,v.id,raw.version);
          if(!result.changes)throw error('Dieser Eintrag wurde inzwischen geändert oder entfernt. Bitte die Liste aktualisieren.',409);
        }
        return send(res,method==='POST'?201:200,{shipment:db.prepare(`SELECT ${fields} FROM shipments WHERE id=?`).get(v.id)});
      }
      if(path.startsWith('/api/'))throw error('Nicht gefunden.',404);
      if(!['GET','HEAD'].includes(method))throw error('Methode nicht erlaubt.',405);
      let decoded;try{decoded=decodeURIComponent(path);}catch{throw error('Ungültiger Pfad.',400);}
      const file=resolve(root,'.'+(decoded==='/'?'/index.html':decoded));
      if(!file.startsWith(root+sep) || decoded.includes('\0'))throw error('Nicht gefunden.',404);
      const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.woff2':'font/woff2'}[extname(file)];
      if(!mime)throw error('Nicht gefunden.',404);
      let bytes;try{bytes=await readFile(file);}catch{throw error('Nicht gefunden.',404);}
      res.writeHead(200,{'Content-Type':mime,'Cache-Control':extname(file)==='.html'?'no-store':'public, max-age=3600'});res.end(method==='HEAD'?undefined:bytes);
    }catch(e){
      if(!e.status)console.error('Request failed:',e.name);
      if(!res.headersSent)send(res,e.status||500,{error:e.status?e.message:'Die Anfrage konnte nicht verarbeitet werden. Bitte erneut versuchen.'},e.status===429?{'Retry-After':'900'}:{});
      else res.end();
    }
  });
  server.requestTimeout=15000; server.headersTimeout=10000;
  return {server,db,close:()=>new Promise(resolveClose=>server.close(()=>{db.close();resolveClose();}))};
}
