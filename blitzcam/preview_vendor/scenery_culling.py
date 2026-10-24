"""Forward-pass culling from the client's material files, without a YAML runtime."""
import re


def material_scalars(text):
    """Read scalar paths from DAVA's indented mapping subset.

    Keep pass/preset boundaries: a ShadowMap override must not affect Forward,
    and a disabled AlphaTest preset must not make an opaque wall two-sided.
    """
    stack, values = [], {}
    for line in text.splitlines():
        match = re.match(r'^( *)([\w.]+)\s*:\s*(.*?)\s*$', line)
        if not match:
            continue
        indent, key, value = len(match[1]), match[2], match[3].split(' #', 1)[0].strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = tuple(k for _, k in stack) + (key,)
        if value:
            values[path] = value.strip('"\'')
        else:
            stack.append((indent, key))
    return values


class ClientCullModes:
    def __init__(self, game_data, decode):
        self.base, self.decode, self.cache = game_data/'Materials', decode, {}

    def material(self, fx, depth=0):
        name = (fx or '').rsplit('/', 1)[-1]
        if not name or depth > 4:
            return {}
        if name not in self.cache:
            values = {}
            for path in (self.base/(name+'.dvpl'), self.base/name):
                if path.is_file():
                    raw = path.read_bytes()
                    values = material_scalars((self.decode(raw) if path.suffix == '.dvpl' else raw).decode('utf-8', 'replace'))
                    break
            # Match the highest available client quality, not a union of passes
            # or quality levels (which would enable unrelated NONE overrides).
            refs = {p[-1]: v for p, v in values.items() if p[0] == 'MaterialTemplate'}
            for quality in ('ULTRA', 'ULTRA_HIGH', 'HIGH', 'MEDIUM', 'LOW'):
                if quality in refs:
                    values = self.material(refs[quality], depth+1)
                    break
            self.cache[name] = values
        return self.cache[name]

    def resolve(self, desc):
        custom = desc.get('customCullMode')
        if type(custom) is int and custom in (0, 1, 2):
            return custom
        values = self.material(desc.get('fxName'))
        mode = None
        roots = [('Material',)] + [('Material', 'Presets', name)
                 for name, enabled in (desc.get('presets') or {}).items() if enabled]
        for root in roots:
            for scope in (root, root+('Passes', 'Forward')):
                value = values.get(scope+('RenderState', 'cullMode'))
                if value in ('NONE', 'FACE_FRONT', 'FACE_BACK'):
                    mode = {'NONE': 0, 'FACE_FRONT': 1, 'FACE_BACK': 2}[value]
        return mode
