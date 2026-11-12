from httpx import RequestError


class DataFetchError(RequestError):
    """something error when fetch"""


class IPBlockError(RequestError):
    """fetch so fast that the server block us ip"""


class DouYinAccountBlockedError(DataFetchError):
    """抖音**账号**被风控：响应空/blocked/业务码要求停手。

    抖音和 B 站不一样：B 站封的是 IP，半小时后换个出口还能试；抖音封的是
    登录态本身，继续拿同一个 cookie 打只会把「临时风控」升级成「长期限制」。
    所以这里单列一个类型，让调用方 ``except`` 它就能立刻停批，也让
    ``tools.crawl_pacing.classify_failure`` 按类名直接判 ``PLATFORM_BLOCKED``
    （写 ``DY_BLOCKED_COOLDOWN_SEC`` 的 6 小时冷却），而不是被文案里的
    「频繁」「限制」误判成 15 分钟的限流。
    """


class CaptchaError(DataFetchError):
    """平台弹人机验证（抖音滑块 / 461 / 471）。

    与 ``DouYinAccountBlockedError`` 的区别只是「平台要你证明自己是人」还是
    「平台直接不让你进」，处置完全一致：立刻停手、落冷却、等人工处理。
    分开是为了日志能说清是哪一种，而不是笼统的「被拦了」。
    """


class PlatformAccessError(DataFetchError):
    """平台在 HTTP 层拒绝访问（401/403/429）。

    重试没有意义：429 是「太快了」，401/403 是「不让你进」，再打只会加深标记。
    """


class RateLimitError(DataFetchError):
    """平台明确说「操作太频繁」——还有救，冷却时间比账号拦截短。"""


#: 「必须立刻停手」的异常：账号级拦截，重试/换词/换页都没用。
#:
#: 写 ``except DataFetchError``（或更宽的 ``except Exception``）时，前面必须有
#: 一条 ``except BLOCKING_EXCEPTIONS: raise``，否则就是「记一条 error，然后继续
#: 把剩下的全打完」——2026-11-11 小红书 461 事故和 2026-12-02 抖音复核发现的
#: 吞异常分支都是这个形状。
BLOCKING_EXCEPTIONS = (
    DouYinAccountBlockedError,
    CaptchaError,
    PlatformAccessError,
    IPBlockError,
)


def is_blocking(exc: BaseException) -> bool:
    """这个异常是不是「平台已经拦你了，别再试」那一类。"""
    return isinstance(exc, BLOCKING_EXCEPTIONS)

#: 值得**整批停下来**的异常：风控/账号/验证码之外，还包括限流。
#:
#: ``BLOCKING_EXCEPTIONS`` 是"要按 PLATFORM_BLOCKED 落长冷却"的那一类；
#: 限流只需要 15 分钟的短冷却，所以它不在里面。但"短冷却"不等于"继续打"：
#: 已经被告知太快了还接着翻页，就是把短冷却变成账号异常的最快方式。
#: 翻页/批量循环里判断"要不要 break/raise"时用这个，而不是 BLOCKING_EXCEPTIONS。
ABORT_EXCEPTIONS = BLOCKING_EXCEPTIONS + (RateLimitError,)
