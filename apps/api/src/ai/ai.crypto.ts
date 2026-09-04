import { constants, createCipheriv, createDecipheriv, generateKeyPairSync, privateDecrypt, randomBytes, type KeyObject } from 'node:crypto';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { AIError } from './ai.types.js';

@Injectable()
export class AIKeyStore {
  private exchangeKeys?: { publicKey: KeyObject; privateKey: KeyObject };
  constructor(private readonly config: ConfigService) {}
  publicKey() {
    this.exchangeKeys ??= generateKeyPairSync('rsa', { modulusLength: 2048 });
    return this.exchangeKeys.publicKey.export({ format: 'der', type: 'spki' }).toString('base64');
  }
  unseal(envelope: string) {
    try {
      if (!this.exchangeKeys) throw new Error();
      const [version, wrappedKey, iv, payload, extra] = envelope.split('.');
      if (version !== 'v1' || extra !== undefined) throw new Error();
      const key = privateDecrypt({ key: this.exchangeKeys.privateKey, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: 'sha256' }, Buffer.from(wrappedKey, 'base64'));
      const data = Buffer.from(payload, 'base64'); const nonce = Buffer.from(iv, 'base64');
      if (key.length !== 32 || nonce.length !== 12 || data.length < 24 || data.length > 2064) throw new Error();
      const decipher = createDecipheriv('aes-256-gcm', key, nonce); decipher.setAuthTag(data.subarray(-16));
      const secret = Buffer.concat([decipher.update(data.subarray(0, -16)), decipher.final()]).toString('utf8');
      if (!/^[\x21-\x7e]{8,2048}$/.test(secret)) throw new Error();
      return secret;
    } catch { throw new AIError('KEY_EXCHANGE'); }
  }
  private key() {
    const text = this.config.get<string>('AI_CONFIG_ENCRYPTION_KEY') ?? '';
    if (!/^[a-f\d]{64}$/i.test(text)) throw new AIError('KEY_UNAVAILABLE');
    return Buffer.from(text, 'hex');
  }
  ready() { try { this.key(); return true; } catch { return false; } }
  encrypt(secret: string, id: string) {
    const iv = randomBytes(12); const cipher = createCipheriv('aes-256-gcm', this.key(), iv);
    cipher.setAAD(Buffer.from(id));
    const encrypted = Buffer.concat([cipher.update(secret, 'utf8'), cipher.final()]);
    return ['v1', iv.toString('base64'), cipher.getAuthTag().toString('base64'), encrypted.toString('base64')].join('.');
  }
  decrypt(encrypted: string | null, id: string) {
    if (!encrypted) throw new AIError('KEY_MISSING');
    try {
      const [version, iv, tag, data] = encrypted.split('.');
      if (version !== 'v1') throw new Error();
      const decipher = createDecipheriv('aes-256-gcm', this.key(), Buffer.from(iv, 'base64'));
      decipher.setAAD(Buffer.from(id)); decipher.setAuthTag(Buffer.from(tag, 'base64'));
      return Buffer.concat([decipher.update(Buffer.from(data, 'base64')), decipher.final()]).toString('utf8');
    } catch { throw new AIError('KEY_UNAVAILABLE'); }
  }
}
