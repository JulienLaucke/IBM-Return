'use client';
import { useEffect, useState, useCallback } from 'react';
import { Plus, ArrowUpRight, Package, Truck, Check, Laptop, Pencil, LockKeyhole, RotateCcw, Trash2, ArrowLeftRight, LoaderCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '@/components/ui/alert-dialog';
import { Toaster } from 'sonner';
import { toast } from 'sonner';
import { shipmentInput, today, type Shipment, type ShipmentInput } from '@/lib/shipment';
const format=(s:string)=>s ? new Intl.DateTimeFormat('de-DE').format(new Date(s+'T12:00:00')) : '—';
const blank=():ShipmentInput=>({name:'',carrier:'DHL',reason:'Offboarding',device:'',tracking:'',shipped:today(),arrived:''});
async function api(method='GET',value?:unknown){
 const r=await fetch('/api/shipments',{method,headers:value?{'Content-Type':'application/json'}:undefined,body:value?JSON.stringify(value):undefined,cache:'no-store'});
 const data=await r.json().catch(()=>({error:'Verbindung unterbrochen. Bitte erneut versuchen.'})) as {error?:string; shipments:Shipment[]; shipment:Shipment};
 if(r.status===401)window.dispatchEvent(new Event('session-expired'));
 if(!r.ok)throw new Error(data.error||'Die Anfrage ist fehlgeschlagen.');return data;
}
export default function ReturnDesk({onLogout, onPassword, email}:{onLogout:()=>void;onPassword:()=>void;email:string}){
 const [rows,setRows]=useState<Shipment[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[tab,setTab]=useState('all');
 const [open,setOpen]=useState(false),[editing,setEditing]=useState<Shipment|null>(null),[draft,setDraft]=useState<ShipmentInput>(blank),[draftId,setDraftId]=useState('');
 const [saving,setSaving]=useState(false),[formError,setFormError]=useState(''),[remove,setRemove]=useState<Shipment|null>(null),[deleteError,setDeleteError]=useState('');
 const refresh=useCallback(async()=>{setLoading(true);setError('');try{const data=await api();setRows(data.shipments);}catch(e){setError((e as Error).message);}finally{setLoading(false);}},[]);
 useEffect(()=>{void refresh();},[refresh]);
 const start=useCallback(()=>{setEditing(null);setDraft(blank());setDraftId(crypto.randomUUID());setFormError('');setOpen(true);},[]);
 function edit(row:Shipment,arrival=false){setEditing(row);setDraft({...row,arrived:arrival?today():row.arrived});setDraftId(row.id);setFormError('');setOpen(true);}
 function field<K extends keyof ShipmentInput>(k:K,v:ShipmentInput[K]){setDraft(d=>({...d,[k]:v}));}
 async function save(e:React.FormEvent){e.preventDefault();if(saving)return;const parsed=shipmentInput.safeParse(draft);if(!parsed.success){setFormError(parsed.error.issues[0].message);return;}
  setSaving(true);setFormError('');try{const {shipment}=await api(editing?'PATCH':'POST',{...parsed.data,id:draftId,version:editing?.version});setRows(r=>editing?r.map(x=>x.id===shipment.id?shipment:x):[shipment,...r.filter(x=>x.id!==shipment.id)]);setOpen(false);toast.success(editing?'Rücksendung aktualisiert':'Rücksendung erfasst');}catch(e){setFormError((e as Error).message);}finally{setSaving(false);}
 }
 async function deleteEntry(){if(!remove||saving)return;setSaving(true);setDeleteError('');try{await api('DELETE',{id:remove.id,version:remove.version});setRows(r=>r.filter(x=>x.id!==remove.id));setRemove(null);setOpen(false);toast.success('Rücksendung gelöscht');}catch(e){setDeleteError((e as Error).message);}finally{setSaving(false);}}
 const underway=rows.filter(x=>!x.arrived).length,arrived=rows.length-underway;
 const filtered=rows.filter(x=>tab==='all'||(tab==='open'?!x.arrived:!!x.arrived));
 return <div className="desk"><Toaster position="bottom-right"/>
  <header className="topbar"><div className="brand"><span className="brand-icon"><ArrowLeftRight size={22}/></span><span>IBM<span className="brand-light">@Return</span></span><span className="brand-divider"/><span className="workspace-label">IT Asset Management</span></div><div className="account-tools"><span className="private" title={email}><LockKeyhole size={14}/><span>{email}</span></span><Button variant="ghost" onClick={onPassword}>Passwort</Button><Button variant="outline" onClick={onLogout}>Abmelden</Button></div></header>
  <main className="workspace">
   <div className="eyebrow"><Laptop size={15}/> GERÄTERÜCKSENDUNGEN</div>
   <div className="page-title"><div><h1>Alles auf dem Rückweg.</h1><p>Rechner versenden. Eingang dokumentieren. Überblick behalten.</p></div><Button className="primary-action" onClick={start}><Plus size={19}/> Rücksendung erfassen</Button></div>
   <section className="metrics" aria-label="Übersicht"><div className="metric"><div><span>Rücksendungen gesamt</span><strong>{loading||error?'—':rows.length.toString().padStart(2,'0')}</strong></div><span className="metric-icon"><Package/></span></div><div className="metric open-metric"><div><span>Unterwegs</span><strong>{loading||error?'—':underway.toString().padStart(2,'0')}</strong></div><span className="metric-icon"><Truck/></span></div><div className="metric"><div><span>Eingetroffen</span><strong>{loading||error?'—':arrived.toString().padStart(2,'0')}</strong></div><span className="metric-icon green"><Check/></span></div></section>
   <section className="records"><div className="records-heading"><div><h2>Rücksendungsübersicht</h2><p>Versand und Eingang an einem Ort</p></div><Button variant="ghost" onClick={refresh} disabled={loading} aria-label="Liste neu laden"><RotateCcw size={16} className={loading?'spin':''}/><span className="refresh-label">Aktualisieren</span></Button></div>
    <Tabs value={tab} onValueChange={setTab} className="records-tabs"><TabsList variant="line" className="status-tabs"><TabsTrigger value="all">Alle <span>{rows.length}</span></TabsTrigger><TabsTrigger value="open">Unterwegs <span>{underway}</span></TabsTrigger><TabsTrigger value="arrived">Eingetroffen <span>{arrived}</span></TabsTrigger></TabsList>
     <TabsContent value={tab}>
      {error?<div className="load-error" role="alert"><p>{error}</p><Button variant="outline" onClick={refresh}>Erneut versuchen</Button></div>:loading?<div className="loading-rows" role="status" aria-label="Rücksendungen werden geladen">{[1,2,3].map(i=><Skeleton key={i} className="h-14 w-full"/>)}</div>:<>
      <Table><TableHeader><TableRow><TableHead>Mitarbeitende / Gerät</TableHead><TableHead>Anlass</TableHead><TableHead>Versanddienst</TableHead><TableHead>Verschickt am</TableHead><TableHead>Eingetroffen am</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Aktion</TableHead></TableRow></TableHeader><TableBody>{filtered.map(row=><TableRow key={row.id}>
       <TableCell><div className="person"><span className="avatar">{row.name.split(/\s+/).map(s=>s[0]).slice(0,2).join('').toUpperCase()}</span><div><strong>{row.name}</strong><small>{row.device||'Keine Gerätenummer'}</small></div></div></TableCell>
       <TableCell><span className="reason">{row.reason==='Gerätetausch (4 Jahre)'?'Gerätetausch':row.reason}</span>{row.reason==='Gerätetausch (4 Jahre)'&&<small className="secondary-line">Nach 4 Jahren</small>}</TableCell>
       <TableCell><span className={'carrier '+row.carrier.toLowerCase()}>{row.carrier}</span>{row.tracking&&<small className="tracking">{row.tracking}</small>}</TableCell>
       <TableCell className="date-cell">{format(row.shipped)}</TableCell><TableCell className="date-cell">{format(row.arrived)}</TableCell>
       <TableCell><span className={'status '+(row.arrived?'received':'transit')}>{row.arrived?<Check size={14}/>:<Truck size={14}/>} {row.arrived?'Eingetroffen':'Unterwegs'}</span></TableCell>
       <TableCell><div className="row-actions">{!row.arrived&&<Button variant="ghost" className="receive-button" onClick={()=>edit(row,true)}>Eingang <ArrowUpRight size={14}/></Button>}<Button variant="ghost" size="icon" aria-label={`${row.name} bearbeiten`} onClick={()=>edit(row)}><Pencil size={16}/></Button></div></TableCell>
      </TableRow>)}</TableBody></Table>
      {!filtered.length&&<Empty className="empty-records"><EmptyHeader><EmptyMedia variant="icon"><Package/></EmptyMedia><EmptyTitle>{rows.length?'Keine Rücksendungen in dieser Ansicht':'Deine erste Rücksendung beginnt hier'}</EmptyTitle><EmptyDescription>{rows.length?'Sobald sich der Status ändert, erscheint der Eintrag hier.':'Erfasse Name, Versanddienst und Versanddatum. Den Eingang trägst du später nach.'}</EmptyDescription></EmptyHeader>{!rows.length&&<Button variant="outline" onClick={start}><Plus size={16}/> Rücksendung erfassen</Button>}</Empty>}
      <div className="table-footer"><span>{filtered.length} {filtered.length===1?'Rücksendung':'Rücksendungen'}</span><span>Status aus deinen Datumseinträgen</span></div></>}
     </TabsContent>
    </Tabs>
   </section>
   <footer className="page-footer"><span>IBM@RETURN <span className="footer-slash">/</span> IT Operations</span><span>Manuelle Erfassung · DHL & FedEx</span></footer>
  </main>
  <Dialog open={open} onOpenChange={v=>{if(!saving)setOpen(v);}}><DialogContent className="entry-dialog" showCloseButton={!saving}><DialogHeader><div className="dialog-icon"><Package size={22}/></div><DialogTitle>{editing?'Rücksendung bearbeiten':'Rücksendung erfassen'}</DialogTitle><DialogDescription>Versand dokumentieren und den Eingang jederzeit nachtragen.</DialogDescription></DialogHeader>
   <form onSubmit={save} className="entry-form"><fieldset disabled={saving}>
    <div className="field"><Label htmlFor="name">Name der Mitarbeiterin / des Mitarbeiters *</Label><Input id="name" value={draft.name} onChange={e=>field('name',e.target.value)} placeholder="Vor- und Nachname" maxLength={120} required autoFocus/></div>
    <div className="form-grid"><div className="field"><Label htmlFor="reason">Anlass</Label><Select value={draft.reason} onValueChange={v=>field('reason',v as ShipmentInput['reason'])} disabled={saving}><SelectTrigger id="reason"><SelectValue/></SelectTrigger><SelectContent>{['Offboarding','Gerätetausch (4 Jahre)','Sonstiges'].map(v=><SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent></Select></div><div className="field"><Label htmlFor="device">Geräte- / Seriennummer <span>optional</span></Label><Input id="device" value={draft.device} onChange={e=>field('device',e.target.value)} maxLength={120} placeholder="z. B. Asset-Nummer"/></div></div>
    <div className="form-divider">VERSAND</div>
    <div className="form-grid"><div className="field"><Label htmlFor="carrier">Versanddienst *</Label><Select value={draft.carrier} onValueChange={v=>field('carrier',v as ShipmentInput['carrier'])} disabled={saving}><SelectTrigger id="carrier"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="DHL">DHL</SelectItem><SelectItem value="FedEx">FedEx</SelectItem></SelectContent></Select></div><div className="field"><Label htmlFor="tracking">Sendungsnummer <span>optional</span></Label><Input id="tracking" value={draft.tracking} onChange={e=>field('tracking',e.target.value)} maxLength={120} placeholder="Sendungsnummer eingeben"/></div></div>
    <div className="form-grid"><div className="field"><Label htmlFor="shipped">Verschickt am *</Label><Input id="shipped" type="date" value={draft.shipped} onChange={e=>field('shipped',e.target.value)} required/></div><div className="field"><Label htmlFor="arrived">Eingetroffen am <span>optional</span></Label><Input id="arrived" type="date" value={draft.arrived} min={draft.shipped} onChange={e=>field('arrived',e.target.value)}/></div></div>
    <p className="form-note">Eingangsdatum leer lassen, solange der Rechner unterwegs ist.</p>
   </fieldset>
   {formError&&<p role="alert" className="form-error">{formError}</p>}
   <div className="form-actions">{editing&&<Button type="button" variant="ghost" className="delete-button" disabled={saving} onClick={()=>{setRemove(editing);setDeleteError('');}} aria-label="Rücksendung löschen"><Trash2 size={17}/></Button>}<div className="grow"/><Button type="button" variant="outline" onClick={()=>setOpen(false)} disabled={saving}>Abbrechen</Button><Button type="submit" disabled={saving}>{saving?<LoaderCircle size={16} className="spin"/>:<Check size={16}/>} {saving?'Speichert …':'Speichern'}</Button></div>
   </form></DialogContent></Dialog>
  <AlertDialog open={!!remove} onOpenChange={v=>{if(!v&&!saving)setRemove(null);}}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Rücksendung löschen?</AlertDialogTitle><AlertDialogDescription>Der Eintrag für {remove?.name} wird dauerhaft entfernt.</AlertDialogDescription></AlertDialogHeader>{deleteError&&<p role="alert" className="form-error">{deleteError}</p>}<AlertDialogFooter><AlertDialogCancel disabled={saving}>Abbrechen</AlertDialogCancel><AlertDialogAction variant="destructive" disabled={saving} onClick={e=>{e.preventDefault();void deleteEntry();}}>{saving?'Löscht …':'Eintrag löschen'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
 </div>;
}
