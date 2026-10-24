"""Convert the supplied artwork to Windows icon sizes without changing its design."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'blitzcam/desktop/assets'
SIZES = (16, 24, 32, 48, 64, 128, 256)


def build():
    with Image.open(ASSETS/'BlitzCamera.png') as source:
        if source.width != source.height:
            raise ValueError('Application icon artwork must be square')
        artwork = source.convert('RGBA')
    if artwork.getchannel('A').getextrema()[0] != 0:
        raise ValueError('Application icon artwork must have a transparent background')
    target = ASSETS/'BlitzCamera.ico'
    artwork.save(target, format='ICO', sizes=[(size, size) for size in SIZES])
    with Image.open(target) as result:
        assert result.ico.sizes() == {(size, size) for size in SIZES}
        for size in result.ico.sizes():
            frame = result.ico.getimage(size).convert('RGBA')
            assert frame.getpixel((0, 0))[3] == 0, 'Icon corner must remain transparent'
    print(target)
    return target


if __name__ == '__main__':
    build()
