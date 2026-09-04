import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { lookup } from 'node:dns/promises';
import { isIP, type LookupFunction } from 'node:net';
import http from 'node:http';
import https from 'node:https';
import { AIError } from './ai.types.js';

export function isPublicAddress(address: string) {
  if (isIP(address) === 4) {
    const [a, b] = address.split('.').map(Number);
    return !(a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) || (a === 192 && [0, 168].includes(b)) ||
      (a === 100 && b >= 64 && b <= 127) || (a === 198 && [18, 19, 51].includes(b)) || (a === 203 && b === 0));
  }
  // Only global unicast IPv6; reject mapped IPv4, local, multicast and transition ranges.
  return isIP(address) === 6 && /^[23]/.test(address) && !/^(2001:|2002:|3fff:)/i.test(address);
}

@Injectable()
export class AITransport {
  constructor(private readonly config: ConfigService) {}
  validateUrl(baseUrl: string) {
    let url: URL;
    try { url = new URL(baseUrl); } catch { throw new AIError('INVALID_CONFIG'); }
    const allowed = (this.config.get<string>('AI_ALLOWED_INTERNAL_ORIGINS') ?? '').split(',').map((x) => x.trim()).includes(url.origin);
    if (url.username || url.password || url.search || url.hash || !['https:', 'http:'].includes(url.protocol)) throw new AIError('UNSAFE_URL');
    if (!allowed && (url.protocol !== 'https:' || (url.port && url.port !== '443'))) throw new AIError('UNSAFE_URL');
    const host = url.hostname.replace(/^\[|\]$/g, '');
    if (!allowed && (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || (isIP(host) && !isPublicAddress(host)))) throw new AIError('UNSAFE_URL');
    return { url, host, allowed };
  }
  async request(baseUrl: string, path: string, apiKey: string, body: unknown | undefined, signal: AbortSignal): Promise<unknown> {
    const { url, host, allowed } = this.validateUrl(baseUrl);
    signal.throwIfAborted();
    // Resolve once, inspect every result and pin that answer to the connection to prevent DNS rebinding.
    const addresses = await new Promise<Array<{ address: string; family: number }>>((resolve, reject) => {
      const abort = () => reject(new AIError('TIMEOUT'));
      signal.addEventListener('abort', abort, { once: true });
      lookup(host, { all: true, verbatim: true }).then(resolve, () => reject(new AIError('NETWORK'))).finally(() => signal.removeEventListener('abort', abort));
    });
    signal.throwIfAborted();
    if (!addresses.length || (!allowed && addresses.some((a) => !isPublicAddress(a.address)))) throw new AIError('UNSAFE_URL');
    const endpoint = new URL(`${url.toString().replace(/\/$/, '')}/${path}`);
    const payload = body === undefined ? undefined : JSON.stringify(body);
    return new Promise((resolve, reject) => {
      const pinnedLookup = ((_hostname: string, options: { all?: boolean }, callback: (...args: unknown[]) => void) => {
        if (options.all) callback(null, addresses); else callback(null, addresses[0].address, addresses[0].family);
      }) as LookupFunction;
      const req = (url.protocol === 'https:' ? https : http).request(endpoint, {
        method: payload ? 'POST' : 'GET', signal, lookup: pinnedLookup,
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json', Accept: 'application/json', ...(payload ? { 'Content-Length': Buffer.byteLength(payload) } : {}) },
      }, (res) => {
        const status = res.statusCode ?? 500;
        if (status < 200 || status >= 300) {
          res.destroy();
          reject(new AIError(({ 401: 'AUTH', 403: 'FORBIDDEN', 404: 'NOT_FOUND', 429: 'RATE_LIMIT' } as const)[status as 401] ?? (status >= 300 && status < 400 ? 'UNSAFE_URL' : status === 400 || status === 422 ? 'INVALID_CONFIG' : 'PROVIDER_ERROR')));
          return;
        }
        const chunks: Buffer[] = []; let size = 0;
        res.on('data', (chunk: Buffer) => { size += chunk.length; if (size > 1024 * 1024) { res.destroy(); reject(new AIError('INVALID_OUTPUT')); } else chunks.push(chunk); });
        res.on('error', () => reject(new AIError(signal.aborted ? 'TIMEOUT' : 'NETWORK')));
        res.on('end', () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { reject(new AIError('INVALID_OUTPUT')); } });
      });
      req.on('error', () => reject(new AIError(signal.aborted ? 'TIMEOUT' : 'NETWORK')));
      req.end(payload);
    });
  }
}
