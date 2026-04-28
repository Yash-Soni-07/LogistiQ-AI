import pathlib, re

for f in sorted(pathlib.Path('tests/integration').glob('*.py')):
    txt = f.read_text()
    urls = re.findall(r'''["'](/[a-zA-Z0-9_/{}.-]+)["']''', txt)
    unique = sorted(set(u for u in urls if u.startswith('/') and u != '/'))
    if unique:
        print(f.name, '->', unique)
