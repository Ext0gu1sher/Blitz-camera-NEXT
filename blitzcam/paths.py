"""Keep application resources separate from portable, writable user data."""
import os
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get('BLITZCAM_DATA_ROOT', RESOURCE_ROOT)).resolve()
OUTPUT = DATA_ROOT / 'output'
