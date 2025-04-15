# -*- coding: utf-8 -*-
import os
from easydict import EasyDict as edict

base_config = edict()
base_config.LOG_PATH = os.path.join(os.path.dirname(__file__), "log")
if not os.path.exists(base_config.LOG_PATH):
    os.mkdir(base_config.LOG_PATH)

# ============= data_file_path ===========#
base_config.workers = 1
base_config.port = 8562
base_config.host = "0.0.0.0"
base_config.MAX_PAGES = 50
base_config.MIN_CTX = 100
base_config.MAX_CTX = 20000
base_config.MAX_SIZE = 50  # 最大文件大小20m
