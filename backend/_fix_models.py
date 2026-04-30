"""
_fix_models.py — Patch models.py for SQLite test compatibility.

Fixes:
  1. NOW() -> CURRENT_TIMESTAMP (SQLite has no NOW())
  2. gen_random_uuid() -> '' server_default; rely on Python uuid4 default
"""

import pathlib, re

f = pathlib.Path("db/models.py")
txt = f.read_text()

# Fix 1: NOW() -> CURRENT_TIMESTAMP
count1 = txt.count('text("NOW()")')
txt = txt.replace('text("NOW()")', 'text("CURRENT_TIMESTAMP")')
print(f"Fix 1 NOW(): {count1} replacements")

# Fix 2: gen_random_uuid() server_default -> Python-side uuid4 default
# Replace: server_default=text("gen_random_uuid()")
# With:    default=lambda: str(__import__('uuid').uuid4())
count2 = txt.count('server_default=text("gen_random_uuid()")')
txt = txt.replace(
    'server_default=text("gen_random_uuid()")', 'default=lambda: str(__import__("uuid").uuid4())'
)
print(f"Fix 2 gen_random_uuid(): {count2} replacements")

f.write_text(txt)
print("models.py written.")
