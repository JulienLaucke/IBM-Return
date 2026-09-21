export function error(message, status = 400) { const e = new Error(message); e.status = status; return e; }
const date = v => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0,10) === v;
export function shipmentInput(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw error('Ungültige Eingabe.');
  const out = {};
  for (const key of ['name','device','tracking']) {
    if (typeof raw[key] !== 'string' || raw[key].trim().length > 120) throw error('Bitte die Textfelder prüfen (maximal 120 Zeichen).');
    out[key] = raw[key].trim();
  }
  if (!out.name) throw error('Bitte einen Namen eingeben.');
  if (!['DHL','FedEx'].includes(raw.carrier)) throw error('Bitte DHL oder FedEx auswählen.');
  if (!['Offboarding','Gerätetausch (4 Jahre)','Sonstiges'].includes(raw.reason)) throw error('Bitte einen gültigen Anlass auswählen.');
  if (!date(raw.shipped) || (raw.arrived !== '' && !date(raw.arrived))) throw error('Bitte ein gültiges Datum eingeben.');
  if (raw.arrived && raw.arrived < raw.shipped) throw error('Das Eingangsdatum darf nicht vor dem Versand liegen.');
  if (typeof raw.id !== 'string' || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(raw.id)) throw error('Ungültige Rücksendung.');
  return {...out, carrier:raw.carrier, reason:raw.reason, shipped:raw.shipped, arrived:raw.arrived, id:raw.id};
}
