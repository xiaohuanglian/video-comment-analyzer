import { req, type AutomationPlatform } from './api'

export type ManualStatus = 'pending' | 'done' | 'skipped'
export interface ManualReply {
  id: string; platform: AutomationPlatform; comment_id: string; video_id: string;
  commenter: string; comment_text: string; video_title: string; reply_url: string;
  location_hint: string; match_reason: string; signal: string; worth: number;
  profile_name: string; profile_id: string; like_count: number; age_hours: number;
  status: ManualStatus; mode: 'ai' | 'rules';
}
export interface ManualJob {
  running: boolean; phase: string; message: string; profile_id?: string; mode?: string;
  summary?: { comments: number; examined: number; added: number; not_examined: number; model_failures: number; mode: string; profile_id: string };
}
export interface ManualList {
  items: ManualReply[]; total: number; counts: Record<ManualStatus, number>; job: ManualJob;
}
export const manualApi = {
  list: (platform: AutomationPlatform, status: ManualStatus, profileId: string, offset = 0) => req<ManualList>(`/manual-replies?${new URLSearchParams({ platform, status, profile_id: profileId, offset: String(offset), limit: '50' })}`),
  screen: (platform: AutomationPlatform, payload: { mode: 'ai' | 'rules'; profile_id: string; goal: string; limit: number; days: number }) => req<ManualJob>(`/manual-replies/screen?platform=${platform}`, { method: 'POST', body: JSON.stringify(payload) }),
  mark: (platform: AutomationPlatform, id: string, status: ManualStatus) => req<ManualReply>(`/manual-replies/${encodeURIComponent(id)}/mark?platform=${platform}`, { method: 'POST', body: JSON.stringify({ status }) }),
}
