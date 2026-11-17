import type { AutomationCandidate } from './api'

export function replyLocation(c: AutomationCandidate, fallbackPlatform = 'bili') {
  const platform = c.platform || fallbackPlatform
  const name = platform === 'dy' ? '抖音' : platform === 'xhs' ? '小红书' : 'B站'
  const isHot = c.action === 'hot_comment'
  let url = c.comment_url || c.video_url || ''
  if (platform === 'bili') {
    url ||= `https://www.bilibili.com/video/${c.video_id.startsWith('BV') ? c.video_id : `av${c.video_id}`}`
    if (!isHot) url = `${url.split('#')[0]}#reply${encodeURIComponent(c.comment_id)}`
  } else if (platform === 'dy') {
    url ||= `https://www.douyin.com/video/${encodeURIComponent(c.video_id)}`
  } else {
    url ||= `https://www.xiaohongshu.com/explore/${encodeURIComponent(c.video_id)}`
  }
  return { url: /^https?:\/\//i.test(url) ? url : '', name, isHot }
}
