import { scrypt, randomBytes, createHash, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';
const derive = promisify(scrypt);
const options = { N: 131072, r: 8, p: 1, maxmem: 256 * 1024 * 1024 };
let active = 0;
export const digest = value => createHash('sha256').update(value).digest('hex');
export function equalSecret(a, b) { return timingSafeEqual(Buffer.from(digest(a)), Buffer.from(digest(b))); }
export function validPassword(value) { return typeof value === 'string' && value.length >= 12 && value.length <= 128; }
export async function hashPassword(password, salt = randomBytes(16).toString('hex')) {
  if (active >= 2) { const error = new Error('Bitte gleich erneut versuchen.'); error.status = 429; throw error; }
  active++;
  try { const hash = await derive(password, salt, 64, options); return `${salt}:${hash.toString('hex')}`; }
  finally { active--; }
}
export async function verifyPassword(password, encoded) {
  const salt = encoded.split(':')[0];
  return equalSecret(await hashPassword(password, salt), encoded);
}
export const normalizeEmail = value => typeof value === 'string' ? value.trim().toLowerCase() : '';
export const validEmail = value => typeof value === 'string' && value.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
