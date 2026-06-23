from urllib.request import Request, urlopen
import re

req = Request('https://www.dsat.gov.mo/dsat/realtime.aspx', headers={'User-Agent': 'Mozilla/5.0'})
html = urlopen(req, timeout=30).read().decode('utf-8', 'replace')
print('length', len(html))
for m in re.finditer(r'cam_id=\d+', html, flags=re.I):
    start = max(0, m.start() - 1000)
    end = min(len(html), m.end() + 2000)
    snippet = html[start:end].replace('\n', ' ')
    print('---MATCH---')
    print(snippet)
    print()
    break
