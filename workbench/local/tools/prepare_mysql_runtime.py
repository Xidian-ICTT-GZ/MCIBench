"""Prepare a pinned, separate MySQL lab runtime without changing local-judge."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.lab.mysql_runtime import CLIENT,CLIENT_SHA256,CONFIG,FLAGS

URL='https://files.pythonhosted.org/packages/7c/4c/ad33b92b9864cbde84f259d5df035a6447f91891f5be77788e2a3892bce3/pymysql-1.1.2-py3-none-any.whl'
# Pin the linux/amd64 manifest, rather than a partly cached multiarch index.
IMAGE='docker.io/library/mysql@sha256:65ce0889751900d2dd5fc5aa5a5fb59073d401fc43df2eae6bd6afb18e7626dd'


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--pull',action='store_true');args=ap.parse_args()
    if args.pull:subprocess.run(['docker','pull',IMAGE],check=True,**FLAGS)
    info=json.loads(subprocess.check_output(['docker','image','inspect',IMAGE],**FLAGS))[0]
    if IMAGE.removeprefix('docker.io/library/') not in info['RepoDigests']:raise ValueError('MySQL image repository digest mismatch')
    image=IMAGE
    if info['Architecture']!='amd64' or info['Os']!='linux':raise ValueError('Unexpected MySQL image platform')
    version=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','mysqld',image,'--version'],**FLAGS).decode()
    if not re.search(r'\b8\.0\.36\b',version):raise ValueError('Unexpected MySQL version')
    if not CLIENT.is_file() or hashlib.sha256(CLIENT.read_bytes()).hexdigest()!=CLIENT_SHA256:
        data=urllib.request.urlopen(URL,timeout=30).read()
        if hashlib.sha256(data).hexdigest()!=CLIENT_SHA256:raise ValueError('Client download fingerprint mismatch')
        CLIENT.parent.mkdir(parents=True,exist_ok=True);CLIENT.write_bytes(data)
    row={'image':image,'mysql_version':'8.0.36','client':'PyMySQL 1.1.2','client_sha256':CLIENT_SHA256,
         'client_url':URL,'client_license':'MIT','mysql_source':'https://github.com/docker-library/mysql','mysql_license':'GPL-2.0'}
    CONFIG.write_text(json.dumps(row,indent=2)+'\n',encoding='utf8')
    print(json.dumps(row,indent=2))


if __name__=='__main__':main()
