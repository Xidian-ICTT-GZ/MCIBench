"""Execute input-only adapters in the real existing eight-language sandbox."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.lab import portable_judging as judging
from local.harness import runner
from local.harness.identity import image_digest

IDENTITIES={
    'python3':'def solve(data): return data',
    'javascript':'function solve(data) { return data; }',
    'cpp':'Mci solve(Mci data) { return data; }',
    'c':'Mci* solve(Mci* data) { return data; }',
    'java':'class Solution { public Object solve(Map<String,Object> data) { return data; } }',
    'csharp':'class Solution { public object Solve(System.Text.Json.JsonElement data) { return data; } }',
    'golang':'func solve(data map[string]interface{}) interface{} {return data}',
    'rust':'fn solve(data: Mci) -> Mci { data }',
}


def main():
    ap=argparse.ArgumentParser(__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--languages',nargs='*',choices=IDENTITIES,default=list(IDENTITIES))
    args=ap.parse_args();runner.DOCKER_IMAGE=image_digest();rows=[]
    sample={'ints':[-2147483648,0,2147483647],'nested':[None,False,True,[],{}],
            'text':'null\u0000\u0001\t\n 中文 😀 \\"','fraction':1.25}
    def run(label,language,data):
        result=judging.execute(0,language,IDENTITIES[language],[{'args':data,'expected':data}])
        row={'label':label,'language':language,'verdict':result};rows.append(row)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps({'image':runner.DOCKER_IMAGE,'checks':rows},ensure_ascii=False,indent=2),encoding='utf8')
        print(label,language,result['ac_status'],flush=True)
        if result['ac_status']!='Accepted':raise SystemExit(1)
    for language in args.languages:run('nested JSON roundtrip',language,sample)
    if 'java' in args.languages:
        run('large array and string beyond javac constant/method limits','java',{'array':list(range(20000)),'text':'中文😀'*20000})
    if 'javascript' in args.languages:
        for expression,expected in (('Infinity',None),('NaN',None),('[undefined]',[None]),('new Date(0)','1970-01-01T00:00:00.000Z')):
            result=judging.execute(0,'javascript','function solve(data){return '+expression+'}',[{'args':{},'expected':expected}])
            rows.append({'label':'reject lossy JSON conversion: '+expression,'language':'javascript','verdict':result})
            args.output.write_text(json.dumps({'image':runner.DOCKER_IMAGE,'checks':rows},ensure_ascii=False,indent=2),encoding='utf8')
            print('lossy JSON',expression,result['ac_status'],flush=True)
            if result['ac_status']!='Runtime Error':raise SystemExit(1)


if __name__=='__main__':main()
