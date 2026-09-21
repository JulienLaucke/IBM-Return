import { z } from 'zod';
export function today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
const date = z.string().refine(v => /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0,10)===v,'Bitte ein gültiges Datum eingeben.');
export const shipmentInput = z.object({
 name: z.string().trim().min(1,'Bitte einen Namen eingeben.').max(120),
 carrier: z.enum(['DHL','FedEx']), reason: z.enum(['Offboarding','Gerätetausch (4 Jahre)','Sonstiges']),
 device: z.string().trim().max(120), tracking: z.string().trim().max(120),
 shipped: date, arrived: z.union([z.literal(''),date]),
}).refine(v=>!v.arrived || v.arrived>=v.shipped,{message:'Das Eingangsdatum darf nicht vor dem Versand liegen.',path:['arrived']});
export type ShipmentInput = z.infer<typeof shipmentInput>;
export type Shipment = ShipmentInput & { id:string; version:number; created:string };
