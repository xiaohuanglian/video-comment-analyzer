import { req } from './api'

export interface SystemStatus {
  model: { configured: boolean; base_url: string; model: string; api_key_masked: string; connection: string; environment_override: boolean };
  channels: {
    platform: string; label: string; state: string; login: string; enabled?: boolean; manual_hold?: boolean;
    cooldown_seconds?: number; cooldown_code?: string; pause_until?: string; message?: string;
    send_policy?: { daily_send_limit: number; send_interval_seconds: number; send_window_start: string; send_window_end: string };
    crawl_interval?: number[]; search_interval?: number[]; policy_source?: string;
  }[];
  note: string;
}

export const settingsApi = { systemStatus: () => req<SystemStatus>('/settings/system-status') }
