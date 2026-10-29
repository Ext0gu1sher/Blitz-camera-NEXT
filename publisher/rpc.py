"""Single-request stdin/stdout bridge for the native studio (no web server)."""
import argparse
import json
from pathlib import Path
import sys

from .store import Studio
from .master import read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--defaults',type=Path)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError('请求过大。')
        request = json.loads(raw)
        if not isinstance(request,dict) or not isinstance(request.get('value',{}),dict): raise ValueError('请求格式无效。')
        defaults = read_json(args.defaults) if args.defaults and args.defaults.exists() else {}
        for name in ('key_path','trust_path','output_dir','recipe_path','master_hint'):
            if defaults.get(name) and not Path(defaults[name]).is_absolute():
                defaults[name] = str((args.defaults.resolve().parent/defaults[name]).resolve())
        result = Studio(args.data,defaults).dispatch(request['action'],request.get('value',{}))
        value = {'ok':True,'result':result}
    except Exception as exc:
        value = {'ok':False,'error':str(exc)}
    sys.stdout.buffer.write(json.dumps(value,ensure_ascii=False).encode('utf-8'))


if __name__=='__main__': main()
