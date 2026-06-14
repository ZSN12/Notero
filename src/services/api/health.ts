import { request } from './core';

export interface AsrHealthResponse {
  status: string;
  asr: string;
}

export async function getAsrHealth(): Promise<AsrHealthResponse> {
  return request<AsrHealthResponse>('/api/health/asr');
}
