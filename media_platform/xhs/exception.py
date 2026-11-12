from httpx import RequestError


class DataFetchError(RequestError):
    """something error when fetch"""


class IPBlockError(RequestError):
    """fetch so fast that the server block us ip"""


class NoteNotFoundError(RequestError):
    """Note does not exist or is abnormal"""


class CaptchaError(DataFetchError):
    """平台弹出人机验证（HTTP 461/471）。

    单独一个类型而不是裸 ``Exception``，是为了三件事：
    1. 让 ``@retry`` 能把它从重试名单里排除——撞验证码时**再打一次只会加重风控**，
       2026-11-11 那次事故里 3 个关键词各被重试了 3 次，等于对已被标记的账号
       又补了 9 次请求。
    2. 让 ``tools.crawl_pacing.classify_failure`` 认出它（message 里带 CAPTCHA /
       Verifytype，会判成 ``PLATFORM_BLOCKED``），从而写进跨进程平台冷却。
    3. 让调用方可以 ``except CaptchaError`` 明确停手，而不是笼统地吞掉所有异常。
    """


class PlatformAccessError(DataFetchError):
    """平台明确拒绝这次访问（HTTP 401/403/429，或业务码 300011 账号安全限制）。

    和 ``CaptchaError`` 的区别：验证码是"让你证明自己是人"，这个是"我不让你进"。
    ``300011`` 尤其要注意——它说的是**账号本身被限制**（异常/风控/权限），
    不是 IP 问题（那是 300012 ``IPBlockError``）。账号级限制换 IP、换 UA 都没用，
    唯一正确的反应是停手，等人工去官方页面处理。
    """


#: 「必须立刻停手」的异常：账号级拦截，重试/换词/换页都没用。
#: 各处的 ``except DataFetchError`` 必须先让它们穿过去，否则会出现
#: 「日志里记了一条 error，然后继续乖乖把剩下的词/笔记全打完」——正是
#: 2026-11-11 那次事故的行为。
BLOCKING_EXCEPTIONS = (CaptchaError, PlatformAccessError, IPBlockError)


def is_blocking(exc: BaseException) -> bool:
    """这个异常是不是「平台已经拦你了，别再试」那一类。"""
    return isinstance(exc, BLOCKING_EXCEPTIONS)
