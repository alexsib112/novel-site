import sqlite3, os
os.chdir(r'C:\Users\allfa\shared-workspace\projects\novel-site')
c = sqlite3.connect('novelfull.db')
c.execute("UPDATE books SET title='Расколотая битвой синева небес' WHERE slug='battle-through-the-heavens'")
c.commit()
c.close()
print('DB исправлена')