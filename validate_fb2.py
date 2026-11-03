import xml.etree.ElementTree as ET, os, sys
p = r'C:\Users\allfa\shared-workspace\projects\novel-site\output\battle-through-the-heavens.fb2'
tree = ET.parse(p)
root = tree.getroot()
ns = {'f': 'http://www.gribuser.ru/xml/fictionbook/2.0'}
secs = root.findall('.//f:body/f:section', ns)
title = root.find('.//f:title-info/f:book-title', ns).text
print('XML OK')
print('book-title:', title)
print('sections:', len(secs))
print('first section title:', secs[0].find('f:title/f:p', ns).text)
print('paras in first:', len(secs[0].findall('f:p', ns)))
print('size MB:', round(os.path.getsize(p)/1024/1024, 2))
