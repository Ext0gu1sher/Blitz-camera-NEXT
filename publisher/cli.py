"""Machine-readable adapter production workflow for future maintenance."""
import argparse
import json
from pathlib import Path
from .master import create_master, inspect_master
from .issuance import issue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    make = sub.add_parser('make'); make.add_argument('--recipe',type=Path,required=True); make.add_argument('--output',type=Path,required=True)
    inspect = sub.add_parser('inspect'); inspect.add_argument('master',type=Path)
    batch = sub.add_parser('issue')
    for name in ('master','output','key','trust'): batch.add_argument('--'+name,type=Path,required=True)
    batch.add_argument('--configs',type=Path,nargs='+',required=True)
    args = parser.parse_args()
    if args.command=='make': result=create_master(args.recipe,args.output)
    elif args.command=='inspect': result=inspect_master(args.master)
    else: result=issue(args.master,args.configs,args.output,args.key,args.trust)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
