/** 本地表情包仓库：导入的 QQ 表情图片存 IndexedDB（跨会话持久，不占后端存储），
 *  发送时转成 File 走既有附件上传管线，故无需任何后端/表结构改动。
 *  ponytail: 先做浏览器本地库；要跨设备同步再升级为后端 per-user 表。 */

const DB_NAME = 'youdoo_stickers'
const STORE = 'stickers'

export interface StoredSticker {
  id: string
  name: string
  blob: Blob
}

/** 只保留图片文件（QQ 表情包即 gif/png/jpg 图片）；非图片直接丢弃。
 *  纯函数，是本模块唯一有分支的逻辑，单测覆盖它。 */
export function filterImageFiles(files: File[]): File[] {
  return files.filter((file) => file.type.startsWith('image/'))
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB unavailable'))
      return
    }
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then((db) => new Promise<T>((resolve, reject) => {
    const request = run(db.transaction(STORE, mode).objectStore(STORE))
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  }))
}

export async function listStickers(): Promise<StoredSticker[]> {
  const all = await tx<StoredSticker[]>('readonly', (store) => store.getAll())
  return all.sort((a, b) => a.name.localeCompare(b.name))
}

/** 导入若干文件为表情，返回实际入库（图片）的记录。 */
export async function importStickers(files: File[]): Promise<StoredSticker[]> {
  const images = filterImageFiles(files)
  const stored: StoredSticker[] = images.map((file) => ({
    id: crypto.randomUUID(),
    name: file.name,
    blob: file,
  }))
  for (const sticker of stored) {
    await tx('readwrite', (store) => store.put(sticker))
  }
  return stored
}

export async function deleteSticker(id: string): Promise<void> {
  await tx('readwrite', (store) => store.delete(id))
}
