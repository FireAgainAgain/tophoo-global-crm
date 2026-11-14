"""Build three accent themes from the compiled canonical workbench stylesheet.

Run after changing interface colors. Only color declarations are emitted;
layout, white surfaces, and semantic warning/error/success colors stay intact.
Uses the Python standard library only.
"""
from pathlib import Path
import colorsys
import re

ROOT = Path(__file__).resolve().parents[1]
SCOPE = 'html[data-ui-theme="green"]'
HUE = 155 / 360
ACCENT = re.compile(r'active|selected|primary|focus|checked|logo-mark|link|submit|save|convert-button|accent', re.I)
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")
SEMANTIC = re.compile(r"success|danger|delete|error|warning|approved|rejected|completed|healthy|verified|passed|failed|cancelled|comm-status|lead-summary-dot|mic-product-status|mic-editor-status|mic-label-summary|is-published|\bgrade-[a-fx]\b", re.I)


def recolor(match, prop="", selector="") :
    value = match.group()
    if value.startswith('#'):
        digits = value[1:]
        if len(digits) in (3, 4):
            digits = ''.join(char * 2 for char in digits)
        if len(digits) not in (6, 8):
            return value
        rgb = [int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        alpha = digits[6:]
    else:
        numbers = re.findall(r"[\d.]+", value)
        if len(numbers) not in (3, 4):
            return value
        rgb = [float(number) / 255 for number in numbers[:3]]
        alpha = None
    hue, light, saturation = colorsys.rgb_to_hls(*rgb)
    if not (75 <= hue * 360 <= 180 and saturation > .025):
        return value
    # Neutral surfaces and text stay identical across themes. Accent is
    # reserved for controls, links and selection, never semantic states.
    accented = bool(ACCENT.search(selector)) or prop in {'--primary', '--primary-hover', 'accent-color', 'caret-color'}
    if prop.startswith('--text') or prop in {'--bg', '--sidebar', '--card', '--border', '--border-light'}:
        accented = False
    neutral = (light > .8 and not accented) or (prop in {'color', '-webkit-text-fill-color'} and not accented) or ('border' in prop and not accented)
    if neutral:
        saturation = min(saturation, .045)
        hue = 220 / 360
    else:
        hue = HUE
        saturation = min(saturation, .64)
    converted = [round(channel * 255) for channel in colorsys.hls_to_rgb(hue, light, saturation)]
    if alpha is not None:
        return '#' + ''.join(f'{channel:02x}' for channel in converted) + alpha
    return ('rgba(' + ','.join(map(str, converted)) + ',' + numbers[3] + ')') if len(numbers) == 4 else ('rgb(' + ','.join(map(str, converted)) + ')')


def split_selectors(value):
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif char == ',' and not depth:
            yield value[start:index].strip()
            start = index + 1
    yield value[start:].strip()


def blocks(css):
    """Walk nested blocks, respecting quoted strings and escaped characters."""
    start, index = 0, 0
    while index < len(css):
        opening = css.find('{', index)
        if opening < 0:
            return
        heading = css[start:opening].strip()
        depth, quote, escaped = 1, '', False
        index = opening + 1
        while index < len(css) and depth:
            char = css[index]
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif quote:
                if char == quote:
                    quote = ''
            elif char in '\"\'':
                quote = char
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
            index += 1
        yield heading, css[opening + 1:index - 1]
        start = index


def scoped(selector):
    if selector.startswith(':root'):
        return selector.replace(':root', SCOPE, 1)
    if re.match(r'html(?=[\s.:#\[]|$)', selector):
        return SCOPE + selector[4:]
    return SCOPE + ' ' + selector


def overrides(css):
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    result = []
    for heading, content in blocks(css):
        if heading.startswith(('@media', '@supports', '@layer')):
            nested = overrides(content)
            if nested:
                result.append(heading + '{\n' + nested + '\n}')
        elif not heading.startswith('@'):
            selectors = [selector for selector in split_selectors(heading) if selector]
            if not selectors:
                continue
            for selector in selectors:
                declarations = []
                for declaration in content.split(';'):
                    if 'url(' in declaration:
                        continue
                    prop = declaration.partition(':')[0].strip()
                    if not re.fullmatch(r'color|background(?:-color|-image|-clip)?|-webkit-background-clip|-webkit-text-fill-color|border(?:-(?:top|right|bottom|left))?(?:-color)?|box-shadow|text-shadow|outline(?:-color)?|fill|stroke|caret-color|accent-color', prop) and not (prop.startswith('--') and COLOR.search(declaration)):
                        continue
                    # Repeat unchanged white text too, so scoped accent rules
                    # cannot override the original primary-button foreground.
                    converted = declaration if SEMANTIC.search(selector) or SEMANTIC.search(prop) else COLOR.sub(lambda match: recolor(match, prop, selector), declaration)
                    declarations.append(converted.strip())
                if declarations:
                    result.append(scoped(selector) + '{' + ';'.join(declarations) + '}')
    return '\n'.join(result)


def main():
    index = (ROOT / 'app/templates/index.html').read_text(encoding='utf-8')
    sources = []
    for href in re.findall(r'<link[^>]+href="(/static/css/[^"?]+)', index):
        if href.endswith(('/ui-themes.css', '/appearance.css')):
            continue
        sources.append((href, (ROOT / 'app' / href.removeprefix('/')).read_text(encoding='utf-8')))
    global SCOPE, HUE
    output = ['/* Generated by scripts/build_ui_themes.py. Shared neutral surfaces; semantic colors preserved. */']
    palettes = {'green': (155, '#16754f', '#105d3d', '#eaf5ef'), 'blue': (217, '#2563b9', '#1d4f94', '#edf3fc'), 'purple': (262, '#7151b5', '#593b95', '#f2eef9')}
    for theme, (hue, primary, hover, soft) in palettes.items():
        SCOPE = f'html[data-ui-theme="{theme}"]'
        HUE = hue / 360
        for name, css in sources:
            converted = overrides(css)
            if converted:
                output.extend(['/* ' + theme + ': ' + name + ' */', converted])
        tokens = f'--primary:{primary};--primary-hover:{hover};--accent-soft:{soft};--bg:#f6f7f9;--sidebar:#fff;--card:#fff;--text:#253044;--text-secondary:#566174;--text-muted:#748095;--border:#e0e4eb;--border-light:#eef0f4;--success:#16754f;--danger:#dc2626'
        output.append(f'{SCOPE},{SCOPE} body[data-workspace="crm"]' + '{' + tokens + '}')
    target = ROOT / 'app/static/css/ui-themes.css'
    target.write_text('\n'.join(output), encoding='utf-8')
    print(f'Built {target.name}: {target.stat().st_size} bytes')


if __name__ == '__main__':
    main()
