import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { panelClass, primaryClass } from '../components/ui/helpers'

const questions = [
  ['没有 API Key，可以先用吗？', '可以先采集、查看本地评论。AI 分析和起草需要模型服务商提供的密钥。在“连接与设置”填写后，先测试、再保存。分析页的演示模式只用于了解操作，结果不能作为真实结论。'],
  ['为什么弹出浏览器、二维码或登录页面？', '采集需要登录对应平台。请在弹出的官方页面扫码或完成验证，保留启动工具的窗口。不要关闭采集用的浏览器。'],
  ['采集很慢，是卡住了吗？', '平台要求控制访问速度，停顿可能是正常等待。先看已采评论数和最近进展。出现验证码、账号限制或冷却提示时，按提示处理或等待，不要反复重试。'],
  ['没有采到数据，怎么办？', '先确认平台选对、关键词能在平台内搜索到内容，并查看采集结果提示。试一个更具体的词；登录失败先完成登录。不同平台的数据入口不同：B 站、抖音和小红书统一到“待回复列表”选择对应平台筛选。需求分析和受控发送属于可选工具。'],
  ['创建了分析任务，怎么还没结果？', '创建任务只准备数据，还需要手动点击“开始分析”。完成后再查看报告。第一次建议只选 100 条，确认分析方向合适后再扩大数量。'],
  ['待回复列表会自动替我发送吗？', '不会。点击原帖链接后由你在平台回复，“我已回复”只是你的手动记录，可以恢复。它与高级受控发送队列独立。'],
  ['点击批准，会发生什么？', '批准表示允许发送这条回复。若发送队列已开启，工具会在允许时段内按间隔发送。批准前请检查账号、对象、回复内容和附件；需要停止时暂停发送队列。'],
  ['换一台电脑，数据会跟着过去吗？', '不会自动同步。迁移前先退出工具，再备份原电脑的 data 文件夹和 .env 配置。browser_data 是登录状态，需要妥善保管；新电脑可重新扫码登录。不要把这些私人文件上传到 GitHub。'],
  ['界面打不开或提示连接失败？', '确认启动窗口还开着，等待出现启动成功提示后再打开 http://127.0.0.1:8766。若提示端口被占用，先关闭旧的工具窗口；不要随意结束不认识的程序。仍有问题，把启动窗口末尾的错误发给维护者，先遮住密钥和个人信息。'],
]

export default function HelpPage() {
  return <div className="mx-auto max-w-4xl space-y-6 px-5 py-7 sm:px-8">
    <header><p className="text-sm font-medium text-(--brand)">新手指南</p><h1 className="mt-2 text-2xl font-semibold">第一次用，照着做就好</h1><p className="mt-3 text-sm leading-7 text-stone-500">先走通一次“采集 → 筛选待回复列表 → 去平台回复”。不需要先理解模型、脚本或配置文件。</p></header>
    <section className={`${panelClass} space-y-5`}><h2 className="text-lg font-semibold">用一小批数据熟悉流程</h2>
      <ol className="list-decimal space-y-4 pl-5 text-sm leading-7 text-stone-600">
        <li><Link to="/collect" className="font-medium text-(--brand) underline">采集评论</Link>：选 B 站，输入与你业务相关的一个关键词，保持默认的“先试一下”，点击开始。若出现登录页，完成扫码。</li>
        <li><Link to="/settings#model-connection" className="font-medium text-(--brand) underline">连接 AI</Link>：请维护者提供服务地址、模型名称和密钥，填写后测试并保存。已有配置时不必重复填。</li>
        <li><Link to="/profiles?new=1" className="font-medium text-(--brand) underline">建立业务档案</Link>：回答做什么、面向谁、想了解什么，让分析和回复贴合业务。</li>
        <li><Link to="/reply-list" className="font-medium text-(--brand) underline">待回复列表</Link>：选择 B 站、抖音或小红书，选业务档案，点击“筛选待回复评论”。不使用 AI 时可选择规则初筛，但需要自己核对业务相关性。</li>
        <li>看评论原文和入选原因，点击“去平台回复”。在原帖评论区找到对方，手动回复后回到列表点击“我已回复”；打开原帖不会自动标记。抖音和小红书不保证链接直达具体评论，可复制原文辅助查找。</li>
      </ol><Link to="/collect" className={primaryClass}>从第一步开始<ArrowRight size={16} /></Link>
    </section>
    <section className="space-y-3"><h2 className="text-lg font-semibold">遇到问题，先看这里</h2>{questions.map(([question, answer]) => <details key={question} className={panelClass}><summary className="cursor-pointer text-sm font-medium">{question}</summary><p className="mt-3 text-sm leading-7 text-stone-600">{answer}</p></details>)}</section>
    <section className={`${panelClass} space-y-3`}><h2 className="font-semibold">界面里的词是什么意思？</h2><dl className="grid gap-4 text-sm sm:grid-cols-2">{[
      ['业务档案', '你做什么、想找谁，以及回复时的口吻。'], ['模型 / AI', '负责分析评论和起草回复的服务。'], ['API Key / 密钥', '模型服务商提供的访问凭据，像密码一样保管。'], ['数据 / 语料', '已采集的评论文件，分析时要先勾选。'], ['冷却', '平台暂时限制访问，需要等待恢复。'], ['批准', '允许发送当前这条回复，请在检查后操作。'],
    ].map(([term, meaning]) => <div key={term}><dt className="font-medium">{term}</dt><dd className="mt-1 leading-6 text-stone-500">{meaning}</dd></div>)}</dl></section>
  </div>
}
