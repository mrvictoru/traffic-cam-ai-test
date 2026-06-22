from urllib.request import Request, urlopen
from macau_dsat_feed import build_feed_snapshot, extract_camera_entries

index_url = 'https://www.dsat.gov.mo/dsat/realtime.aspx'
req = Request(index_url, headers={'User-Agent': 'Mozilla/5.0'})
with urlopen(req, timeout=30) as response:
    html = response.read().decode('utf-8', 'replace')

print('index_len', len(html))
print('camera_matches', len(extract_camera_entries(html, index_url)))
print('first_five', [(c.cam_id, c.detail_url) for c in extract_camera_entries(html, index_url)[:5]])

snapshot = build_feed_snapshot(index_url=index_url)
print('snapshot_count', snapshot['camera_count'])
for camera in snapshot['cameras'][:5]:
    print(camera['cam_id'], camera['detail_url'], camera['stream_urls'][:5], camera.get('fetch_error'))
