import os, re

def process_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Matches: text-[var(--lq-text-bright)] -> text-lq-text-bright
    # Also handles bg, border, fill, stroke
    pattern = r'(text|bg|border|fill|stroke)-\[var\(--(lq-[a-zA-Z0-9-]+)\)\]'
    new_content = re.sub(pattern, r'\1-\2', content)
    
    if content != new_content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {path}")

for root, dirs, files in os.walk('src'):
    for file in files:
        if file.endswith(('.tsx', '.ts')):
            process_file(os.path.join(root, file))
