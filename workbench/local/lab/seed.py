"""Explicitly import the project's existing Qwen API connection without logging secrets."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

from local.common import REPO_ROOT
from local.lab.storage import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--existing-qwen', action='store_true', required=True)
    args = parser.parse_args()
    path = REPO_ROOT / 'SFT/MCIBench/Submit_Trans/run_T_api_baseline_Qwen3-8B_dmx_cand5.ps1'
    text = path.read_text(encoding='utf-8-sig')
    found = re.search(r'\$env:LLM_API_KEY\s*=\s*[\"\x27]([^\"\x27]+)[\"\x27]', text, re.I)
    if not found:
        raise SystemExit('现有配置没有可导入的 LLM_API_KEY；请在页面配置模型')
    store = Store(args.data.resolve())
    existing = {p['model_name'] for p in store.profiles()}
    for name in ('qwen3-8b-free', 'qwen3-1.7b-free'):
        if name in existing:
            continue
        store.save_profile({'name': name.replace('-free', ''), 'model_name': name,
                            'api_url': 'https://www.dmxapi.cn/v1/chat/completions',
                            'api_key': found.group(1), 'enable_thinking': False, 'enabled': True, 'max_tokens': 4096})
        print('Imported model:', name)


if __name__ == '__main__':
    main()
