import os
import loguru
import sys
from functools import partial
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generator,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
)
import time
import numpy as np
import fcntl
from pydantic import BaseModel, Field
from cachetools import cached, TTLCache

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from config import base_config

def build_logger(log_file: str = "log"):
    """
    build a logger with colorized output and a log file, for example:

    logger = build_logger("api")
    logger.info("<green>some message</green>")

    user can set basic_settings.log_verbose=True to output debug logs
    """
    logger = loguru.logger.opt(colors=True)
    logger.opt = partial(loguru.logger.opt, colors=True)
    log_file = os.path.join(log_file, 'log_markify_{time:YYYY-MM-DD}.log')
    logger.add(log_file, colorize=False, rotation='00:00', retention='180 days', encoding='utf-8')
    logger.error = logger.opt(exception=True).error
    return logger

logger = build_logger(base_config.LOG_PATH)

class BaseResponse(BaseModel):
    code: int = Field(200, description="API status code")
    msg: str = Field("success", description="API status message")
    data: Any = Field(None, description="API data")

    class Config:
        json_schema_extra = {
            "example": {
                "code": 200,
                "msg": "success",
            }
        }





def set_httpx_config(
        timeout: float = 30,
        proxy: Union[str, Dict] = None,
        unused_proxies: List[str] = [],
):
    """
    设置httpx默认timeout。httpx默认timeout是5秒，在请求LLM回答时不够用。
    将本项目相关服务加入无代理列表，避免fastchat的服务器请求错误。(windows下无效)
    对于chatgpt等在线API，如要使用代理需要手动配置。搜索引擎的代理如何处置还需考虑。
    """

    import os

    import httpx

    httpx._config.DEFAULT_TIMEOUT_CONFIG.connect = timeout
    httpx._config.DEFAULT_TIMEOUT_CONFIG.read = timeout
    httpx._config.DEFAULT_TIMEOUT_CONFIG.write = timeout

    # 在进程范围内设置系统级代理
    proxies = {}
    if isinstance(proxy, str):
        for n in ["http", "https", "all"]:
            proxies[n + "_proxy"] = proxy
    elif isinstance(proxy, dict):
        for n in ["http", "https", "all"]:
            if p := proxy.get(n):
                proxies[n + "_proxy"] = p
            elif p := proxy.get(n + "_proxy"):
                proxies[n + "_proxy"] = p

    for k, v in proxies.items():
        os.environ[k] = v

    # set host to bypass proxy
    no_proxy = [
        x.strip() for x in os.environ.get("no_proxy", "").split(",") if x.strip()
    ]
    no_proxy += [
        # do not use proxy for locahost
        "http://127.0.0.1",
        "http://localhost",
    ]
    # do not use proxy for user deployed fastchat servers
    for x in unused_proxies:
        host = ":".join(x.split(":")[:2])
        if host not in no_proxy:
            no_proxy.append(host)
    os.environ["NO_PROXY"] = ",".join(no_proxy)

    def _get_proxies():
        return proxies

    import urllib.request

    urllib.request.getproxies = _get_proxies


def safe_save(filename, data):
    with open(filename, 'wb') as f:
        # 获取排他锁（阻塞直到获取）
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            np.save(f, data)
        finally:
            # 释放锁
            fcntl.flock(f, fcntl.LOCK_UN)

def safe_load(filename):
    with open(filename, 'rb') as f:
        # 获取共享锁（允许其他进程读取，但阻止写入）
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return np.load(f, allow_pickle=True)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

@cached(TTLCache(1, 1800))  # 经过测试，缓存的token可以使用，目前每30分钟刷新一次
def del_older_files(directory, older_days=30):
    cutoff_time = time.time() - (older_days * 24 * 60 * 60)  # 将天数转换为秒
    for root, dirs, files in os.walk(directory, topdown=False):
        for name in files:
            file_path = os.path.join(root, name)
            mtime = os.path.getmtime(file_path)
            if mtime < cutoff_time:
                os.remove(file_path)

        for name in dirs:
            dir_path = os.path.join(root, name)
            if not os.listdir(dir_path):
                os.rmdir(dir_path)
            else:
                del_older_files(dir_path)
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)