import urllib.request as u
import re

req = u.Request('https://www.dsat.gov.mo/dsat/realtime_core4.aspx?lang=tc&cam_id=122', headers={'User-Agent': 'Mozilla/5.0'})
html = u.urlopen(req, timeout=30).read().decode('utf-8', 'replace')
print(html[:12000])
print('---STREAM-LIKE---')
print(re.findall(r'https?://[^"\'\s>]+', html)[:100])
