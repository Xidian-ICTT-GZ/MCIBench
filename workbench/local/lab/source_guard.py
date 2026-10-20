"""Prevent a long-lived worker from signing on-disk code it has not loaded."""
import hashlib
from pathlib import Path

_loaded={}


def register(filename):
    path=Path(filename).resolve()
    _loaded.setdefault(path,hashlib.sha256(path.read_bytes()).hexdigest())


def check():
    for path,digest in tuple(_loaded.items()):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('判题流程源码已改变，当前任务保留结果；请重启服务后复制任务重试：'+path.name)


register(__file__)
