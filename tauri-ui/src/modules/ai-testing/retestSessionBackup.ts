// Large queues and tool evidence can exceed localStorage's per-origin quota.
// IndexedDB keeps the full cache independently of the backend's durable queue.
type SessionBackup = { savedAt: number; serialized: string };

const DATABASE = 'koi-retest-session-cache';
const STORE = 'sessions';
const KEY = 'current';
let database: Promise<IDBDatabase> | null = null;
let writes: Promise<void> = Promise.resolve();

function openDatabase(): Promise<IDBDatabase> {
  if (database) return database;
  database = new Promise<IDBDatabase>((resolve, reject) => {
    const request = window.indexedDB.open(DATABASE, 1);
    const timer = window.setTimeout(() => reject(new Error('Session cache open timed out')), 2000);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onerror = () => { window.clearTimeout(timer); reject(request.error); };
    request.onblocked = () => { window.clearTimeout(timer); reject(new Error('Session cache upgrade blocked')); };
    request.onsuccess = () => {
      window.clearTimeout(timer);
      request.result.onversionchange = () => { request.result.close(); database = null; };
      resolve(request.result);
    };
  }).catch(error => { database = null; throw error; });
  return database;
}

export async function readRetestSessionBackup(): Promise<SessionBackup | null> {
  if (typeof window === 'undefined' || !window.indexedDB) return null;
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, 'readonly');
    const request = transaction.objectStore(STORE).get(KEY);
    request.onsuccess = () => {
      const record = request.result;
      resolve(record && typeof record.savedAt === 'number' && typeof record.serialized === 'string' ? record : null);
    };
    request.onerror = () => reject(request.error);
  });
}

export function writeRetestSessionBackup(record: SessionBackup): Promise<void> {
  if (typeof window === 'undefined' || !window.indexedDB) return Promise.resolve();
  const next = writes.catch(() => {}).then(async () => {
    const db = await openDatabase();
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE, 'readwrite');
      transaction.objectStore(STORE).put(record, KEY);
      transaction.oncomplete = () => resolve();
      transaction.onabort = () => reject(transaction.error);
      transaction.onerror = () => reject(transaction.error);
    });
  });
  writes = next;
  return next;
}
