import sqlite3, os, re
os.chdir(r'C:\Users\allfa\shared-workspace\projects\novel-site')
c = sqlite3.connect('novelfull.db')
rows = c.execute("SELECT num, title_ru FROM chapters WHERE slug='battle-through-the-heavens' AND status='translated' ORDER BY num").fetchall()
latin = [(n,t) for n,t in rows if re.search(r'[A-Za-z]', t or '')]
starts_glava = [(n,t) for n,t in rows if (t or '').startswith('Глава')]
long_titles = [(n,t) for n,t in rows if len(t or '') > 90]
print('всего:', len(rows))
print('с латиницей:', len(latin), latin[:10])
print('начинаются с "Глава":', len(starts_glava), starts_glava[:10])
print('длиннее 90 симв.:', len(long_titles), long_titles[:5])
print('\nпримеры:')
for n,t in rows[:3] + rows[820:823] + rows[-3:]:
    print(n, '|', t)
c.close()
