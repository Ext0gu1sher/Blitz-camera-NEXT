"""Hidden portable entry; errors remain accessible without a console window."""
from pathlib import Path
import os
import sys
import traceback


def main():
    root = Path(os.environ['BLITZCAM_DATA_ROOT']).resolve()
    output = root/'output'
    output.mkdir(parents=True, exist_ok=True)
    with (output/'desktop-service.log').open('a', encoding='utf-8', buffering=1) as log:
        sys.stdout = sys.stderr = log
        try:
            from blitzcam.__main__ import main as cli
            return cli(['desktop', *sys.argv[1:]])
        except BaseException:
            traceback.print_exc()
            return 2


if __name__ == '__main__':
    raise SystemExit(main())
