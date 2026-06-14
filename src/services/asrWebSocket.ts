import { API_BASE } from '@/config';
import { getToken } from '@/services/auth';
import type { BackendNote } from '@/services/api';

const IS_DEV = import.meta.env.DEV;

export interface ASRWebSocketCallbacks {
  onPartial: (text: string, startMs: number, endMs: number) => void;
  onFinal: (text: string, startMs: number, endMs: number) => void;
  onStatus: (message: string) => void;
  onError: (detail: string) => void;
  onDone: (note: BackendNote | null) => void;
}

/**
 * WebSocket client for real-time streaming ASR.
 *
 * Protocol:
 *   Send: binary PCM int16 frames, or JSON control messages
 *   Receive: partial / final / status / error / done
 */
export class ASRWebSocketClient {
  private ws: WebSocket | null = null;
  private sessionId: string;
  private callbacks: ASRWebSocketCallbacks;
  private _connected = false;
  private _endPromise: Promise<void> | null = null;
  private _endResolve: (() => void) | null = null;

  constructor(sessionId: string, callbacks: ASRWebSocketCallbacks) {
    this.sessionId = sessionId;
    this.callbacks = callbacks;
  }

  get connected() {
    return this._connected;
  }

  connect(): Promise<void> {
    const token = getToken();
    const wsUrl = `${API_BASE.replace(/^http/, 'ws')}/ws/asr/${this.sessionId}?token=${token}`;
    this.ws = new WebSocket(wsUrl);

    return new Promise((resolve, reject) => {
      this.ws!.onopen = () => {
        this._connected = true;
        if (IS_DEV) console.log('[ASRWebSocket] connected');
        this.sendJson({ type: 'start' });
        resolve();
      };
      this.ws!.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleMessage(data);
        } catch {
          // ignore non-JSON
        }
      };
      this.ws!.onerror = (err) => {
        this._connected = false;
        if (IS_DEV) console.error('[ASRWebSocket] error:', err);
        reject(new Error('WebSocket 连接失败'));
      };
      this.ws!.onclose = () => {
        this._connected = false;
        if (IS_DEV) console.log('[ASRWebSocket] closed');
        if (this._endResolve) {
          this._endResolve();
          this._endResolve = null;
        }
      };
    });
  }

  sendAudioFrame(pcmData: Int16Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(pcmData.buffer);
    }
  }

  sendJson(data: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  pause(): void {
    this.sendJson({ type: 'pause' });
  }

  resume(): void {
    this.sendJson({ type: 'resume' });
  }

  end(): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return Promise.resolve();
    }

    if (this._endPromise) {
      return this._endPromise;
    }

    this._endPromise = new Promise((resolve) => {
      this._endResolve = resolve;
      // Send end message; done handler will resolve
      this.sendJson({ type: 'end' });

      // Safety timeout: if server never replies, resolve anyway after 60s
      setTimeout(() => {
        if (this._endResolve) {
          this._endResolve();
          this._endResolve = null;
        }
      }, 60000);
    });

    return this._endPromise;
  }

  close(): void {
    this._connected = false;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    if (this._endResolve) {
      this._endResolve();
      this._endResolve = null;
    }
  }

  private handleMessage(data: Record<string, unknown>) {
    if (IS_DEV) console.log('[ASRWebSocket] message:', data.type, data);
    switch (data.type) {
      case 'partial':
        this.callbacks.onPartial(data.text as string, data.start_ms as number, data.end_ms as number);
        break;
      case 'final':
        this.callbacks.onFinal(data.text as string, data.start_ms as number, data.end_ms as number);
        break;
      case 'status':
        this.callbacks.onStatus(data.message as string);
        break;
      case 'error':
        this.callbacks.onError(data.detail as string);
        break;
      case 'done':
        this.callbacks.onDone((data.note as BackendNote | undefined) || null);
        if (this._endResolve) {
          this._endResolve();
          this._endResolve = null;
        }
        break;
    }
  }
}
