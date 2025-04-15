import asyncio
import multiprocessing
import os
import sys


# 设置numexpr最大线程数，默认为CPU核心数
try:
    import numexpr

    n_cores = numexpr.utils.detect_number_of_cores()
    os.environ["NUMEXPR_MAX_THREADS"] = str(n_cores)
except:
    pass


def run_api_server():
    import uvicorn
    sys.path.append(os.path.dirname(__file__))
    from config import base_config
    from server_tools.server_utils import set_httpx_config
    set_httpx_config()

    uvicorn.run(app="server_tools.server_router:app", host=base_config.host, port=base_config.port,
                workers=base_config.workers)


def main():
    # 添加这行代码
    cwd = os.getcwd()
    sys.path.append(cwd)
    multiprocessing.freeze_support()
    if sys.version_info < (3, 10):
        loop = asyncio.get_event_loop()
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()

        asyncio.set_event_loop(loop)
    loop.run_until_complete(run_api_server())


if __name__ == "__main__":
    main()
