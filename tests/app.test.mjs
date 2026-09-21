import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { createApp } from '../server/app.mjs';

test('Two-account authentication and shared return workflow over HTTP',async t=>{
 const dir=await mkdtemp(join(tmpdir(),'ibm-return-test-'));
 const config={database:join(dir,'returns.sqlite'),origin:'https://returns.example',production:true,setupToken:'test-only-setup-token-'.repeat(3),staticDir:resolve('dist')};
 let app=await createApp(config);
 async function listen(){await new Promise(r=>app.server.listen(0,'127.0.0.1',r));}
 await listen();
 const invoke=async(path,method='GET',body,cookie,origin=config.origin)=>{
  const res=await fetch(`http://127.0.0.1:${app.server.address().port}${path}`,{method,headers:{...(body?{'Content-Type':'application/json'}:{}),...(cookie?{Cookie:cookie}:{}),...(method!=='GET'&&origin?{Origin:origin}:{})},body:body?JSON.stringify(body):undefined});
  const json=await res.json().catch(()=>null);return {status:res.status,data:json,cookie:res.headers.get('set-cookie'),headers:res.headers};
 };
 const users=[{email:'one@example.test',password:'First-testing-password-12'},{email:'two@example.test',password:'Second-testing-password-34'}];
 let firstCookie,secondCookie,shipment;
 try{
  await t.test('anonymous APIs, origin enforcement and one-time two-account setup',async()=>{
   assert.equal((await invoke('/api/shipments')).status,401);
   assert.equal((await invoke('/api/auth/me')).status,401);
   assert.equal((await invoke('/api/setup')).data.configured,false);
   assert.equal((await invoke('/api/setup','POST',{token:config.setupToken,users},null,'https://evil.example')).status,403);
   assert.equal((await invoke('/api/setup','POST',{token:'wrong',users})).status,403);
   assert.equal((await invoke('/api/setup','POST',{token:config.setupToken,users:[...users,users[0]]})).status,400);
   assert.equal((await invoke('/api/setup','POST',{token:config.setupToken,users})).status,201);
   assert.equal((await invoke('/api/setup','POST',{token:config.setupToken,users})).status,409);
   assert.equal((await invoke('/api/setup')).data.configured,true);
   assert.throws(()=>app.db.prepare('INSERT INTO users (id,email,password_hash,created) VALUES (3,?,?,?)').run('three@example.test','none','now'));
   assert.ok(!JSON.stringify(app.db.prepare('SELECT password_hash FROM users').all()).includes(users[0].password));
  });
  await t.test('login failures and secure session cookies',async()=>{
   assert.equal((await invoke('/api/auth/login','POST',{...users[0],password:'incorrect'})).status,401);
   assert.equal((await invoke('/api/auth/login','POST',{email:'third@example.test',password:'not-an-account'})).status,401);
   const one=await invoke('/api/auth/login','POST',users[0]);assert.equal(one.status,200);
   assert.match(one.cookie,/HttpOnly/);assert.match(one.cookie,/SameSite=Strict/);assert.match(one.cookie,/Secure/);assert.match(one.cookie,/__Host-/);
   firstCookie=one.cookie.split(';')[0];
   secondCookie=(await invoke('/api/auth/login','POST',users[1])).cookie.split(';')[0];
   assert.equal((await invoke('/api/auth/me','GET',undefined,firstCookie)).data.user.email,users[0].email);
   assert.ok(!JSON.stringify(app.db.prepare('SELECT token_hash FROM sessions').all()).includes(firstCookie.split('=')[1]));
   assert.equal((await invoke('/api/auth/logout','POST',{},firstCookie,null)).status,403);
  });
  await t.test('shared CRUD, invalid input, retry and stale edit protection',async()=>{
   const draft={id:randomUUID(),name:'Synthetic example',carrier:'DHL',reason:'Offboarding',device:'TEST-DEVICE',tracking:'',shipped:'2026-09-15',arrived:''};
   assert.equal((await invoke('/api/shipments','POST',draft)).status,401);
   assert.equal((await invoke('/api/shipments','POST',{...draft,arrived:'2026-09-14'},firstCookie)).status,400);
   assert.equal((await invoke('/api/shipments','POST',{...draft,shipped:'2026-02-30'},firstCookie)).status,400);
   assert.equal((await invoke('/api/shipments','POST',{...draft,name:'   '},firstCookie)).status,400);
   const added=await invoke('/api/shipments','POST',draft,firstCookie);assert.equal(added.status,201);shipment=added.data.shipment;
   assert.equal((await invoke('/api/shipments','POST',draft,firstCookie)).status,200);
   assert.equal((await invoke('/api/shipments','POST',{...draft,name:'Different'},secondCookie)).status,409);
   const listed=await invoke('/api/shipments','GET',undefined,secondCookie);assert.equal(listed.data.shipments.length,1);
   const updated=await invoke('/api/shipments','PATCH',{...shipment,arrived:'2026-09-16'},secondCookie);assert.equal(updated.status,200);assert.equal(updated.data.shipment.version,2);
   assert.equal((await invoke('/api/shipments','PATCH',{...shipment,arrived:'2026-09-17'},firstCookie)).status,409);
   assert.equal((await invoke('/api/shipments','DELETE',{id:shipment.id,version:1},firstCookie)).status,409);
   assert.equal(app.db.prepare('SELECT creator,updater FROM shipments').get().creator,1);
   assert.equal(app.db.prepare('SELECT creator,updater FROM shipments').get().updater,2);
  });
  await t.test('records and valid sessions survive a process restart',async()=>{
   await app.close();app=await createApp(config);await listen();
   const result=await invoke('/api/shipments','GET',undefined,firstCookie);assert.equal(result.status,200);assert.equal(result.data.shipments[0].arrived,'2026-09-16');
  });
  await t.test('password changes revoke previous sessions and logout revokes current session',async()=>{
   const changed=await invoke('/api/auth/password','POST',{currentPassword:users[0].password,newPassword:'Replacement-testing-password-56'},firstCookie);assert.equal(changed.status,200);
   assert.equal((await invoke('/api/auth/me','GET',undefined,firstCookie)).status,401);
   const fresh=changed.cookie.split(';')[0];
   assert.equal((await invoke('/api/shipments','DELETE',{id:shipment.id,version:2},secondCookie)).status,200);
   assert.equal((await invoke('/api/auth/logout','POST',{},fresh)).status,200);
   assert.equal((await invoke('/api/auth/me','GET',undefined,fresh)).status,401);
   const bad=digestCookie(secondCookie);
   app.db.prepare('UPDATE sessions SET expires=0 WHERE token_hash=?').run(bad);
   assert.equal((await invoke('/api/shipments','GET',undefined,secondCookie)).status,401);
  });
  await t.test('brute-force throttling and private files are inaccessible',async()=>{
   let result;for(let i=0;i<11;i++)result=await invoke('/api/auth/login','POST',{email:'throttle@example.test',password:'invalid'});
   assert.equal(result.status,429);
   assert.equal((await invoke('/server/index.mjs')).status,404);
   assert.equal((await invoke('/data/returns.sqlite')).status,404);
   assert.equal((await invoke('/.env')).status,404);
   assert.equal((await invoke('/api/register','POST',users[0])).status,404);
  });
 }finally{await app.close();await rm(dir,{recursive:true,force:true});}
});
import { digest } from '../server/security.mjs';
const digestCookie=cookie=>digest(cookie.split('=')[1]);
