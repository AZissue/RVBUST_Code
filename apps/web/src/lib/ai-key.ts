import { api } from './api'

const base64 = (data: ArrayBuffer | Uint8Array) => btoa(String.fromCharCode(...new Uint8Array(data instanceof Uint8Array ? data.buffer as ArrayBuffer : data)))
export async function sealApiKey(secret: string) {
  const { publicKey } = await api<{ publicKey: string }>('/ai/key-exchange')
  const der = Uint8Array.from(atob(publicKey), (c) => c.charCodeAt(0))
  const rsa = await crypto.subtle.importKey('spki', der, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt'])
  const aes = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt'])
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, aes, new TextEncoder().encode(secret))
  const wrappedKey = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, rsa, await crypto.subtle.exportKey('raw', aes))
  return ['v1', base64(wrappedKey), base64(iv), base64(ciphertext)].join('.')
}
