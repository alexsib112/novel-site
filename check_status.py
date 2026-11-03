import sqlite3
import sys

db = r'C:\Users\allfa\shared-workspace\projects\novel-site\novelfull.db'
conn = sqlite3.connect(db)
c = conn.cursor()

c.execute('SELECT COUNT(*) FROM chapters')
total = c.fetchone()[0]
print(f'Total chapters: {total}')

c.execute("SELECT COUNT(*) FROM chapters WHERE translation IS NOT NULL AND translation != ''")
translated = c.fetchone()[0]
print(f'Translated: {translated}')

c.execute('SELECT chapter_num, title FROM chapters WHERE translation IS NOT NULL AND translation != "" ORDER BY chapter_num LIMIT 5')
print('Translated samples:')
for r in c.fetchall():
    title = r[1][:60] if r[1] else '(no title)'
    print(f'  #{r[0]}: {title}')

c.execute('SELECT name, chapters_total FROM novels LIMIT 5')
for r in c.fetchall():
    print(f'Novel: {r[0]}, total_chapters: {r[1]}')

conn.close()
