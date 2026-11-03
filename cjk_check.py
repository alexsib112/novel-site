import sqlite3, os, json, re
os.chdir(r'C:\Users\allfa\shared-workspace\projects\novel-site')
c = sqlite3.connect('novelfull.db')
rows = c.execute("SELECT num, content_ru FROM chapters WHERE slug='battle-through-the-heavens' AND status='translated'").fetchall()
c.close()
cjk = []
for num, ru in rows:
    found = re.findall(r'[\u4e00-\u9fff]+', ru or '')
    if found:
        cjk.append({'num': num, 'count': len(found), 'samples': found[:5]})
with open('cjk.json', 'w', encoding='utf-8') as f:
    json.dump({'chapters': len(cjk), 'items': cjk[:40]}, f, ensure_ascii=False, indent=2)
print('глав с иероглифами:', len(cjk))
for x in cjk[:15]:
    print(x['num'], x['samples'])
