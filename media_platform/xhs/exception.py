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
