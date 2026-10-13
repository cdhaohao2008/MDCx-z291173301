with open('mdcx/views/MDCx.py', 'r', encoding='utf-8') as f:
    content = f.read()
start = content.find('textBrowser_about.setHtml')
end = content.find('</body></html>', start)
html_block = content[start:end+len('</body></html>')]
import re
matches = re.findall(r'font-size:[^";]*', html_block)
print('Matches:', matches)
