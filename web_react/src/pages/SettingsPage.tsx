import { useCallback, useEffect, useState } from 'react'
import { Save, Loader2, Check, Coins, KeyRound, Plus, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import { api, type AutomationStatus, type Strategy, type ProfileBrief, type CostSummary, type CostEntry, type AutomationPlatform } from '../lib/api'
import OnboardingWizard from '../components/OnboardingWizard'

export default function SettingsPage() {
  const [platform, setPlatform] = useState<AutomationPlatform>('bili')
  const [status, setStatus] = useState<AutomationStatus | null>(null)
  const [keywordsText, setKeywordsText] = useState('')
  const [noteUrlsText, setNoteUrlsText] = useState('')
  const [collectMode, setCollectMode] = useState('auto')
  const [dailySendLimit, setDailySendLimit] = useState(5)
  const [sendInterval, setSendInterval] = useState(300)
  const [sendWindowStart, setSendWindowStart] = useState('10:00')
  const [sendWindowEnd, setSendWindowEnd] = useState('22:00')
  const [freshnessA, setFreshnessA] = useState(48)
  const [freshnessB, setFreshnessB] = useState(168)
  // 根评论（热评）通道：不回复某个人，直接评在视频下争公域曝光。
  // 与逐条回复是两种动作，各有各的上限——回复触达确定但只一个人看见，
  // 根评论零通知、全看赞数排序。默认开，配额保守。
  const [hotEnabled, setHotEnabled] = useState(true)
  const [hotPerCycle, setHotPerCycle] = useState(2)
  const [hotMinPlay, setHotMinPlay] = useState(1000)
  const [hotSilence, setHotSilence] = useState(720)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  // 账号定位(策略档案)——上一版漏了这组状态声明导致白屏,补齐
  const [strategy, setStrategy] = useState<Partial<Strategy>>({})
  const [strategyDirty, setStrategyDirty] = useState(false)
  const [strategyBusy, setStrategyBusy] = useState(false)
  const [strategySaved, setStrategySaved] = useState(false)
  // 多档案：一个产品一份定位/受众/口吻。不同产品不能混用，所以「当前档案」
  // 是显式状态，切换后所有生成入口立刻按新档案走。
  const [profiles, setProfiles] = useState<ProfileBrief[]>([])
  const [profilesLoaded, setProfilesLoaded] = useState(false)
  const [activeProfileId, setActiveProfileId] = useState('')
  const [newProfileName, setNewProfileName] = useState('')
  const [profileBusy, setProfileBusy] = useState('')
  const [profileMsg, setProfileMsg] = useState('')
  // 费用统计
  const [costs, setCosts] = useState<CostSummary | null>(null)
  const [recentCalls, setRecentCalls] = useState<CostEntry[]>([])
  const [loginBusy, setLoginBusy] = useState(false)
  // 模型网关（服务端持久化；此前只有 growth 侧读它，llm.complete 只认环境变量）
  const [modelBaseUrl, setModelBaseUrl] = useState('')
  const [modelName, setModelName] = useState('')
  const [modelKey, setModelKey] = useState('')
  const [modelStatus, setModelStatus] = useState<{ configured: boolean; api_key_masked: string } | null>(null)
  const [modelBusy, setModelBusy] = useState('')
  const [modelMsg, setModelMsg] = useState('')

  const refreshStatus = useCallback(() => {
    api
      .automationStatus(platform)
      .then((s) => {
        setStatus(s)
        const c = s.config as Record<string, unknown>
        setKeywordsText(((c.keywords as string[]) ?? []).join('\n'))
        setNoteUrlsText(((c.note_urls as string[]) ?? []).join('\n'))
        setCollectMode(String(c.collect_mode ?? 'auto'))
        setDailySendLimit(Number(c.daily_send_limit ?? 5))
        setSendInterval(Number(c.send_interval_seconds ?? 300))
        setSendWindowStart(String(c.send_window_start ?? '10:00'))
        setSendWindowEnd(String(c.send_window_end ?? '22:00'))
        setFreshnessA(Number(c.freshness_a_hours ?? 48))
        setFreshnessB(Number(c.freshness_b_hours ?? 168))
        setHotEnabled(c.hot_comment_enabled !== false)
        setHotPerCycle(Number(c.hot_comment_max_per_cycle ?? 2))
        setHotMinPlay(Number(c.hot_comment_min_play ?? 1000))
        setHotSilence(Number(c.hot_comment_max_silence_hours ?? 720))
      })
      .catch(() => {})
  }, [platform])

  // 发送通道状态轮询:登录进行中加密轮询,平时也是低频刷新
  useEffect(() => {
    refreshStatus()
    const t = setInterval(refreshStatus, 4000)
    return () => clearInterval(t)
  }, [refreshStatus])

  useEffect(() => {
    api
      .strategyGet()
      .then((s) => {
        setStrategy(s.exists === false ? {} : s)
        setProfiles(s.profiles ?? [])
        setActiveProfileId(s.active_profile_id ?? '')
        setProfilesLoaded(true)
      })
      .catch(() => setProfilesLoaded(true))
    api
      .costsSummary()
      .then(setCosts)
      .catch(() => {})
    api
      .costsLedger(8)
      .then(setRecentCalls)
      .catch(() => {})
    api
      .modelSettingsGet()
      .then((m) => {
        setModelBaseUrl(m.base_url)
        setModelName(m.model_name)
        setModelStatus({ configured: m.configured, api_key_masked: m.api_key_masked })
      })
      .catch(() => {})
  }, [])

  const save = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const patch: Record<string, unknown> = {
        keywords: keywordsText.split('\n').map((k) => k.trim()).filter(Boolean),
        daily_send_limit: dailySendLimit,
        send_interval_seconds: sendInterval,
        send_window_start: sendWindowStart,
        send_window_end: sendWindowEnd,
        freshness_a_hours: freshnessA,
        freshness_b_hours: freshnessB,
        hot_comment_enabled: hotEnabled,
        hot_comment_max_per_cycle: hotPerCycle,
        hot_comment_min_play: hotMinPlay,
        hot_comment_max_silence_hours: hotSilence,
      }
      if (platform === 'xhs' || platform === 'dy') {
        patch.note_urls = noteUrlsText.split('\n').map((u) => u.trim()).filter(Boolean)
        patch.collect_mode = collectMode
      }
      await api.automationConfigUpdate(patch, platform)
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [platform, keywordsText, noteUrlsText, collectMode, dailySendLimit, sendInterval, sendWindowStart, sendWindowEnd, freshnessA, freshnessB, hotEnabled, hotPerCycle, hotMinPlay, hotSilence])

  const saveModel = async () => {
    setModelBusy('save')
    setModelMsg('')
    try {
      const res = await api.modelSettingsSave({
        base_url: modelBaseUrl,
        model_name: modelName,
        api_key: modelKey || undefined, // 留空 = 保留原 key
      })
      setModelStatus({ configured: res.configured, api_key_masked: res.api_key_masked })
      setModelKey('')
      setModelMsg('已保存。之后新发起的对话/选题/写稿/洞察都会用它。')
    } catch (e) {
      setModelMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setModelBusy('')
    }
  }

  const testModel = async () => {
    setModelBusy('test')
    setModelMsg('')
    try {
      const res = await api.modelSettingsTest({
        base_url: modelBaseUrl,
        model_name: modelName,
        api_key: modelKey || undefined,
      })
      setModelMsg(res.ok ? `连接正常：${res.reply ?? 'ok'}` : `连接失败：${res.error ?? '未知错误'}`)
    } catch (e) {
      setModelMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setModelBusy('')
    }
  }

  const saveStrategy = async () => {
    setStrategyBusy(true)
    try {
      const saved = await api.strategySave(strategy)
      setStrategy(saved)
      setProfiles(saved.profiles ?? [])
      setActiveProfileId(saved.active_profile_id ?? '')
      setStrategyDirty(false)
      setStrategySaved(true)
      setTimeout(() => setStrategySaved(false), 1500)
    } finally {
      setStrategyBusy(false)
    }
  }

  const loadProfile = async (profileId: string) => {
    setProfileBusy('load')
    setProfileMsg('')
    try {
      const s = await api.strategyGet(profileId)
      setStrategy(s.exists === false ? { profile_id: profileId } : s)
      setProfiles(s.profiles ?? [])
      setActiveProfileId(s.active_profile_id ?? '')
      setStrategyDirty(false)
    } catch (e) {
      setProfileMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setProfileBusy('')
    }
  }

  const switchProfile = async (profileId: string) => {
    setProfileBusy('switch')
    setProfileMsg('')
    try {
      const res = await api.strategySetActive(profileId)
      setProfiles(res.profiles)
      setActiveProfileId(res.active_profile_id)
      await loadProfile(res.active_profile_id)
      setProfileMsg('已切换。之后选题、写稿、回复筛选都按这份档案走。')
    } catch (e) {
      setProfileMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setProfileBusy('')
    }
  }

  const createProfile = async () => {
    const name = newProfileName.trim()
    if (!name) return
    setProfileBusy('create')
    setProfileMsg('')
    try {
      const res = await api.strategyCreateProfile({ name })
      setNewProfileName('')
      setProfiles((p) => [
        ...p,
        {
          profile_id: res.profile.profile_id ?? '',
          name: res.profile.name ?? name,
          niche: '',
          target_audience: '',
          is_active: false,
          is_configured: false,
          updated_at: '',
        },
      ])
      setProfileMsg('档案已创建。填完定位后点「切换到此档案」，否则它不会生效。')
    } catch (e) {
      setProfileMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setProfileBusy('')
    }
  }

  const deleteProfile = async (profileId: string) => {
    setProfileBusy('delete')
    setProfileMsg('')
    try {
      const res = await api.strategyDeleteProfile(profileId)
      setActiveProfileId(res.active_profile_id)
      const fresh = await api.strategyProfiles()
      setProfiles(fresh.profiles)
      await loadProfile(res.active_profile_id)
      setProfileMsg('档案已删除。')
    } catch (e) {
      setProfileMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setProfileBusy('')
    }
  }

  const setStrat = (patch: Partial<Strategy>) => {
    setStrategy((s) => ({ ...s, ...patch }))
    setStrategyDirty(true)
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-6 space-y-5">
      <header>
        <h1 className="text-lg font-semibold">设置</h1>
        <p className="text-xs text-stone-400">回复自动化的筛选与发送参数(保存即生效)</p>
      </header>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold">回复自动化参数</h2>
            <p className="text-xs text-stone-400">按平台独立配置(保存即生效);B站/小红书/抖音各有自己的队列、配额与节奏</p>
          </div>
          <div className="flex rounded-lg border border-stone-200 bg-white p-0.5">
            {(['bili', 'xhs', 'dy'] as const).map((pf) => (
              <button
                key={pf}
                onClick={() => setPlatform(pf)}
                className={clsx(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  platform === pf ? 'bg-(--brand) text-white' : 'text-stone-500 hover:text-stone-700',
                )}
              >
                {pf === 'bili' ? 'B站' : pf === 'xhs' ? '小红书' : '抖音'}
              </button>
            ))}
          </div>
        </div>

        {(platform === 'xhs' || platform === 'dy') && (
          <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/50 p-3">
            <div>
              <label className="text-xs text-stone-400">
                {platform === 'xhs'
                  ? '竞品笔记清单(每行一条完整链接,需带 xsec_token——从浏览器地址栏复制;留空则只按关键词搜索)'
                  : '对标视频清单(每行一条抖音视频链接,如 https://www.douyin.com/video/xxxx;留空则只按关键词搜索)'}
              </label>
              <textarea
                value={noteUrlsText}
                onChange={(e) => setNoteUrlsText(e.target.value)}
                rows={4}
                placeholder={platform === 'xhs' ? 'https://www.xiaohongshu.com/explore/xxxx?xsec_token=…' : 'https://www.douyin.com/video/xxxx'}
                className="mt-1 w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-xs outline-none focus:border-(--brand)"
              />
            </div>
            <div>
              <label className="text-xs text-stone-400">采集模式</label>
              <select
                value={collectMode}
                onChange={(e) => setCollectMode(e.target.value)}
                className="mt-1 w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm outline-none focus:border-(--brand)"
              >
                <option value="auto">自动(有清单爬清单,没清单按关键词)</option>
                <option value="list">只爬清单(读请求最少,推荐日常)</option>
                <option value="search">只按关键词搜索(发现新内容)</option>
              </select>
              <p className="mt-1 text-xs text-amber-600">
                {platform === 'xhs'
                  ? '建议:日常用清单模式固定盯重点竞品,每周手动跑一次关键词扫描补新笔记进清单'
                  : '建议:日常用清单模式固定盯重点对标视频,每周手动跑一次关键词扫描补新视频进清单'}
              </p>
            </div>
          </div>
        )}

        <div>
          <label className="text-xs text-stone-400">目标关键词(每行一个,用于自动化的目标视频池)</label>
          <textarea
            value={keywordsText}
            onChange={(e) => setKeywordsText(e.target.value)}
            rows={5}
            className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <NumField label="每日发送上限" v={dailySendLimit} set={setDailySendLimit} min={1} max={50} />
          <NumField label="发送间隔(秒)" v={sendInterval} set={setSendInterval} min={60} max={7200} />
          <NumField label="A 档新鲜度(小时)" v={freshnessA} set={setFreshnessA} min={1} max={720} />
          <NumField label="B 档新鲜度(小时)" v={freshnessB} set={setFreshnessB} min={24} max={720} />
          <div>
            <label className="text-xs text-stone-400">发送窗口开始</label>
            <input
              value={sendWindowStart}
              onChange={(e) => setSendWindowStart(e.target.value)}
              className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
            />
          </div>
          <div>
            <label className="text-xs text-stone-400">发送窗口结束</label>
            <input
              value={sendWindowEnd}
              onChange={(e) => setSendWindowEnd(e.target.value)}
              className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
            />
          </div>
        </div>

        <div className="rounded-xl border border-stone-200 bg-stone-50/60 px-4 py-3">
          <label className="flex items-center gap-2 text-sm text-stone-700">
            <input
              type="checkbox"
              checked={hotEnabled}
              onChange={(e) => setHotEnabled(e.target.checked)}
              className="h-4 w-4 accent-(--brand)"
            />
            同时发根评论（热评通道）
          </label>
          <p className="mt-1.5 text-xs leading-relaxed text-stone-500">
            逐条回复是<b>确定触达一个人</b>（平台会给对方发通知），根评论是<b>零通知</b>、和已有热评一起按赞数排序，
            赢了才有公域曝光。所以两者不是替代关系：评论区冷清或被热评占住的位置，发一条根评论比回十条更划算。
            只有 B 站能自动发根评论，小红书/抖音需要你手动发。
          </p>
          <div className="mt-3 grid grid-cols-2 gap-4">
            <NumField label="每轮根评论上限" v={hotPerCycle} set={setHotPerCycle} min={1} max={10} />
            <NumField label="最低播放量门槛" v={hotMinPlay} set={setHotMinPlay} min={1} max={1000000} />
          </div>
          <div className="mt-3">
            <NumField label="评论区安静多久就不发了（小时）" v={hotSilence} set={setHotSilence} min={1} max={8760} />
            <p className="mt-1 text-xs text-stone-400">
              看的是评论区最近还有没有人说话，不是视频发布多久——B 站评论常出现在发布一个月后，
              按发布时间筛会把还在长的视频全部错过。
            </p>
          </div>
        </div>

        <button
          onClick={save}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : saved ? <Check size={14} /> : <Save size={14} />}
          {saved ? '已保存' : '保存'}
        </button>
      </section>

      {/* 首次使用:还没有任何填过定位的档案时，先给最短路径，而不是让人去填一整页表单 */}
      {profilesLoaded && !profiles.some((p) => p.is_configured) && (
        <OnboardingWizard
          onDone={async (profileId) => {
            const fresh = await api.strategyProfiles()
            setProfiles(fresh.profiles)
            setActiveProfileId(profileId)
            setProfilesLoaded(true)
            await loadProfile(profileId)
          }}
        />
      )}

      {/* 产品档案:一个产品一份定位,做完 A 产品再做 B 产品时不用推翻重填 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-3">
        <div>
          <h2 className="text-sm font-semibold">产品档案</h2>
          <p className="text-xs text-stone-400">
            每个产品一份档案(定位/受众/口吻各自独立)。下方的「账号定位」与所有生成入口,
            都使用<b className="font-medium">当前档案</b>
          </p>
        </div>
        <div className="divide-y divide-stone-100 overflow-hidden rounded-xl border border-stone-200">
          {profiles.length === 0 && (
            <p className="px-3 py-3 text-xs text-stone-400">还没有档案,先建一个</p>
          )}
          {profiles.map((p) => (
            <div
              key={p.profile_id}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 text-sm',
                p.is_active ? 'bg-emerald-50/60' : 'bg-white',
              )}
            >
              <button
                onClick={() => loadProfile(p.profile_id)}
                className="min-w-0 flex-1 text-left hover:opacity-70"
                title="查看/编辑这份档案"
              >
                <p className="flex items-center gap-2 truncate font-medium">
                  {p.name || p.profile_id}
                  {p.is_active && (
                    <span className="shrink-0 rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-normal text-white">
                      当前
                    </span>
                  )}
                  {!p.is_configured && (
                    <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-normal text-amber-700">
                      未填定位
                    </span>
                  )}
                </p>
                <p className="truncate text-xs text-stone-400">
                  {p.niche || p.target_audience || '（还没填定位与受众）'}
                </p>
              </button>
              {!p.is_active && (
                <button
                  onClick={() => switchProfile(p.profile_id)}
                  disabled={profileBusy !== ''}
                  className="shrink-0 rounded-lg border border-stone-300 px-2.5 py-1 text-xs hover:bg-stone-50 disabled:opacity-40"
                >
                  切换到此档案
                </button>
              )}
              {!p.is_active && (
                <button
                  onClick={() => deleteProfile(p.profile_id)}
                  disabled={profileBusy !== ''}
                  className="shrink-0 rounded-lg p-1.5 text-stone-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                  title="删除这份档案"
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input
            value={newProfileName}
            onChange={(e) => setNewProfileName(e.target.value)}
            placeholder="新产品/账号名称,如：同城花店"
            className="min-w-0 flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm outline-none focus:border-stone-500"
          />
          <button
            onClick={createProfile}
            disabled={profileBusy !== '' || !newProfileName.trim()}
            className="flex shrink-0 items-center gap-1.5 rounded-lg border border-stone-300 px-3 py-2 text-sm hover:bg-stone-50 disabled:opacity-40"
          >
            <Plus size={14} />
            新建档案
          </button>
        </div>
        {profileMsg && <p className="text-xs text-stone-500">{profileMsg}</p>}
      </section>

      {/* 账号定位(策略档案) */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold">账号定位</h2>
            <p className="text-xs text-stone-400">
              所有内容生成的策略基座:选题规划、文案、回复、最强视频都会自动用这里的定位与口吻
            </p>
          </div>
          {strategy.niche && (
            <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs text-emerald-700">
              已建档{strategy.updated_at ? ` · ${strategy.updated_at.slice(5, 10)}` : ''}
            </span>
          )}
        </div>
        {activeProfileId && (
          <p className="rounded-lg bg-stone-50 px-3 py-2 text-xs text-stone-500">
            正在编辑档案：
            <b className="font-medium text-stone-700">
              {profiles.find((p) => p.profile_id === activeProfileId)?.name || activeProfileId}
            </b>
          </p>
        )}
        <TextField
          label="一句话定位(赛道+差异化)"
          value={strategy.niche ?? ''}
          placeholder="如:给新手的 AI 视频实战教程,只讲能落地的,不吹工具"
          onChange={(v) => setStrat({ niche: v })}
        />
        <TextField
          label="目标受众(具体到人群+痛点)"
          value={strategy.target_audience ?? ''}
          placeholder="如:想用 AI 做视频但没基础的上班族和学生,怕花钱怕学不会"
          onChange={(v) => setStrat({ target_audience: v })}
        />
        <TextField
          label="变现/目标"
          value={strategy.monetization ?? ''}
          placeholder="如:为 youvibe.cn 导流 + 建立个人品牌"
          onChange={(v) => setStrat({ monetization: v })}
        />
        <AreaField
          label="口吻(每行一条)"
          value={(strategy.tone_rules ?? []).join('\n')}
          placeholder={'如:\n说话直接,不端着\n爱举自己的翻车例子\n专业词后必跟一句大白话'}
          onChange={(v) =>
            setStrat({ tone_rules: v.split('\n').map((x) => x.trim()).filter(Boolean) })
          }
        />
        <AreaField
          label="禁区(每行一条)"
          value={(strategy.forbidden ?? []).join('\n')}
          placeholder={'如:\n不夸大效果\n不用引流话术'}
          onChange={(v) =>
            setStrat({ forbidden: v.split('\n').map((x) => x.trim()).filter(Boolean) })
          }
        />
        <AreaField
          label="参考账号/风格(每行一条:学什么)"
          value={(strategy.reference_styles ?? []).join('\n')}
          placeholder={'如:\nK桑 — 教调度不教工具堆砌\n影视飓风 — 信息密度高但节奏稳'}
          onChange={(v) =>
            setStrat({ reference_styles: v.split('\n').map((x) => x.trim()).filter(Boolean) })
          }
        />
        <TextField
          label="90天唯一目标(成功标准)"
          value={strategy.goal ?? ''}
          placeholder="如:把「AI创业者」人设立住,评论区出现等更新/怎么跟你学型信号"
          onChange={(v) => setStrat({ goal: v })}
        />
        <AreaField
          label="实战证据(可公开讲的经历与数字)"
          value={strategy.evidence ?? ''}
          placeholder={
            '如:\n操盘:公众号矩阵 0→X 万粉,周期 X 个月\nYouVibe:开发 X 个月,X 用户,收入 X(没收入就写"过程全公开")\n可公开:用户量级/投入时间;永不公开:内网域名/客户信息'
          }
          onChange={(v) => setStrat({ evidence: v })}
        />
        <button
          onClick={saveStrategy}
          disabled={strategyBusy || !strategyDirty}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
        >
          {strategyBusy ? (
            <Loader2 size={14} className="animate-spin" />
          ) : strategySaved ? (
            <Check size={14} />
          ) : (
            <Save size={14} />
          )}
          {strategySaved ? '已保存,全部生成入口已生效' : strategyDirty ? '保存定位' : '无改动'}
        </button>
      </section>

      {/* 发送通道(B站):登录态监控与扫码恢复 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-3">
        <div>
          <h2 className="text-sm font-semibold">发送通道(B 站)</h2>
          <p className="text-xs text-stone-400">受控回复的登录态与发送状态;失效了在这里扫码恢复</p>
        </div>
        <div className="rounded-xl bg-stone-50 px-3.5 py-2.5 text-xs space-y-1">
          <p>
            Cookie 状态:
            {status?.sender?.cookie_cached ? (
              <span className="font-medium text-emerald-600">已就绪</span>
            ) : (
              <span className="font-medium text-red-500">失效(批准的回复会排队等待)</span>
            )}
            {status?.sender?.account?.uname ? (
              <span className="text-stone-400">
                {' '}
                · 账号 {status.sender.account.uname} Lv.{status.sender.account.level ?? '?'}
              </span>
            ) : null}
          </p>
          {status?.sender?.login_flow?.message && (
            <p className="text-amber-600">{status.sender.login_flow.message}</p>
          )}
          {status?.sender?.wait_reason && (
            <p className="text-stone-400">发送节奏:{String(status.sender.wait_reason)}</p>
          )}
          {status?.sender && !status.sender.cookie_cached && !status.sender.login_flow?.running && (
            <p className="text-red-400">
              {String((status.sender as { last_error?: string }).last_error || '')}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={async () => {
              if (loginBusy || status?.sender?.login_flow?.running) return
              setLoginBusy(true)
              try {
                await api.biliLogin()
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e))
              } finally {
                setLoginBusy(false)
              }
            }}
            disabled={loginBusy || status?.sender?.login_flow?.running}
            className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {status?.sender?.login_flow?.running ? (
              <>
                <Loader2 size={14} className="animate-spin" /> 登录窗口已打开,等你扫码…
              </>
            ) : (
              '扫码恢复 B 站登录'
            )}
          </button>
          <p className="text-xs text-stone-400">本机会弹出浏览器窗口,用 B 站 App 扫码(3 分钟内有效)</p>
        </div>
      </section>

      {/* 模型网关 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            <KeyRound size={14} /> 模型网关
          </h2>
          <p className="text-xs text-stone-400">
            对话 / 选题 / 写稿 / 洞察 / 回复起草共用这一份配置。保存后写入服务端本地
            (仅本机可读)，接口只返回脱敏形式。
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs">
          <label className="space-y-1">
            <span className="text-stone-500">Base URL（根地址，不用带 /v1）</span>
            <input
              value={modelBaseUrl}
              onChange={(e) => setModelBaseUrl(e.target.value)}
              placeholder="https://api.deepseek.com"
              className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
            />
          </label>
          <label className="space-y-1">
            <span className="text-stone-500">Model</span>
            <input
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              placeholder="deepseek-v4-flash"
              className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
            />
          </label>
        </div>

        <label className="block space-y-1 text-xs">
          <span className="text-stone-500">
            API Key
            {modelStatus?.configured && (
              <span className="ml-2 text-emerald-600">已配置（{modelStatus.api_key_masked}）</span>
            )}
          </span>
          <input
            type="password"
            value={modelKey}
            onChange={(e) => setModelKey(e.target.value)}
            placeholder={modelStatus?.configured ? '留空则保留原 Key' : 'sk-...'}
            className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
          />
        </label>

        <div className="flex items-center gap-2">
          <button
            onClick={() => void saveModel()}
            disabled={modelBusy !== ''}
            className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
          >
            {modelBusy === 'save' ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            保存
          </button>
          <button
            onClick={() => void testModel()}
            disabled={modelBusy !== ''}
            className="flex items-center gap-1.5 rounded-lg border border-stone-200 px-3 py-1.5 text-xs text-stone-600 hover:border-(--brand)"
          >
            {modelBusy === 'test' ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            测试连接
          </button>
          {modelMsg && <span className="text-xs text-stone-500">{modelMsg}</span>}
        </div>
      </section>

      {/* 费用统计(只记账,不限流) */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="flex items-center gap-1.5 text-sm font-semibold">
              <Coins size={14} /> 费用统计
            </h2>
            <p className="text-xs text-stone-400">
              全部 LLM 消耗台账(对话/选题/写稿/洞察/回复起草),只记账不限制
            </p>
          </div>
          <button
            onClick={() => {
              api.costsSummary().then(setCosts).catch(() => {})
              api.costsLedger(8).then(setRecentCalls).catch(() => {})
            }}
            className="rounded-lg border border-stone-200 p-1.5 text-stone-400 hover:border-(--brand) hover:text-(--brand)"
          >
            刷新
          </button>
        </div>

        {!costs ? (
          <p className="py-4 text-center text-xs text-stone-400">还没有消耗记录</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl bg-stone-50 p-3">
                <p className="text-xs text-stone-400">今日</p>
                <p className="text-lg font-semibold">
                  {costs.today.calls} 次 · {costs.today.total_tokens.toLocaleString()} tokens
                </p>
                {costs.pricing.configured && (
                  <p className="text-xs text-stone-400">≈ ¥{costs.today.cost.toFixed(2)}</p>
                )}
              </div>
              <div className="rounded-xl bg-stone-50 p-3">
                <p className="text-xs text-stone-400">累计</p>
                <p className="text-lg font-semibold">
                  {costs.total.calls} 次 · {costs.total.total_tokens.toLocaleString()} tokens
                </p>
                {costs.pricing.configured ? (
                  <p className="text-xs text-stone-400">≈ ¥{costs.total.cost.toFixed(2)}</p>
                ) : (
                  <p className="text-xs text-stone-400">未配价格,按 tokens 统计</p>
                )}
              </div>
            </div>

            {costs.by_feature.length > 0 && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-stone-400">
                    <th className="py-1 font-normal">功能</th>
                    <th className="py-1 font-normal text-right">调用</th>
                    <th className="py-1 font-normal text-right">输入 tok</th>
                    <th className="py-1 font-normal text-right">输出 tok</th>
                    {costs.pricing.configured && <th className="py-1 font-normal text-right">费用</th>}
                  </tr>
                </thead>
                <tbody>
                  {costs.by_feature.map((f) => (
                    <tr key={f.feature} className="border-t border-stone-100">
                      <td className="py-1">{f.feature}</td>
                      <td className="py-1 text-right">{f.calls}</td>
                      <td className="py-1 text-right">{f.prompt_tokens.toLocaleString()}</td>
                      <td className="py-1 text-right">{f.completion_tokens.toLocaleString()}</td>
                      {costs.pricing.configured && (
                        <td className="py-1 text-right">¥{f.cost.toFixed(2)}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {recentCalls.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-stone-400">最近调用</p>
                {recentCalls.slice(0, 8).map((c, i) => (
                  <p key={i} className="flex items-center gap-2 text-xs text-stone-500">
                    <span className={c.ok ? 'text-emerald-500' : 'text-red-400'}>●</span>
                    <span className="w-32 shrink-0 truncate">{c.feature}</span>
                    <span className="text-stone-300">
                      {new Date(c.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
                    </span>
                    <span>{c.total_tokens.toLocaleString()} tok</span>
                    <span className="text-stone-300">{(c.duration_ms / 1000).toFixed(1)}s</span>
                    {!c.ok && c.error && <span className="truncate text-red-400">{c.error.slice(0, 60)}</span>}
                  </p>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold mb-2">红线(不可改)</h2>
        <ul className="text-xs text-stone-500 space-y-1 leading-relaxed">
          <li>· AI 只发现与起草,发送必须经人工批准</li>
          <li>· 草稿硬禁令:无产品名/链接/引流,禁说教腔与黑话(由 reply_style lint 强制执行)</li>
          <li>· 小红书/抖音通道额外硬校验:链接/联系方式/引流话术在批准与发送两道口都会被拦;撞风控自动停损暂停</li>
          <li>· 自动化不再自己定时扫描采集;采集走「采集」页手动批量或自动化页「立即采集」,再回来自动化页筛选</li>
        </ul>
        {status && (
          <p className="mt-3 text-xs text-stone-400">
            当前状态({platform === 'xhs' ? '小红书' : platform === 'dy' ? '抖音' : 'B站'}):{status.enabled ? '自动化已启用' : '自动化已暂停'} ·{' '}
            {platform === 'xhs' || platform === 'dy'
              ? status.sender.pause_until
                ? `发送停损暂停中(${String(status.sender.pause_until).slice(5, 16)})`
                : '发送通道正常(依赖已登录的浏览器)'
              : `Cookie ${status.sender.cookie_cached ? '已缓存' : '未就绪'}`}
          </p>
        )}
      </section>
    </div>
  )
}

function TextField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  placeholder?: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-xs text-stone-400">{label}</label>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
      />
    </div>
  )
}

function AreaField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  placeholder?: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-xs text-stone-400">{label}</label>
      <textarea
        value={value}
        placeholder={placeholder}
        rows={3}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
      />
    </div>
  )
}

function NumField({
  label,
  v,
  set,
  min,
  max,
}: {
  label: string
  v: number
  set: (n: number) => void
  min: number
  max: number
}) {
  return (
    <div>
      <label className="text-xs text-stone-400">{label}</label>
      <input
        type="number"
        value={v}
        min={min}
        max={max}
        onChange={(e) => set(Number(e.target.value) || min)}
        className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
      />
    </div>
  )
}
