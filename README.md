# traffic-cam-ai-test
This repo is to test taking live traffic cam and outputing useful traffic information

## Macau DSAT live feed pipeline

This repository now includes a small Python pipeline that:

1. fetches the Macau DSAT realtime index page at `https://www.dsat.gov.mo/dsat/realtime.aspx`
2. discovers camera detail pages such as `realtime_core.aspx?...&cam_id=...`
3. fetches each detail page and extracts live `.m3u8`, `image.aspx`, or snapshot image URLs
4. emits a JSON snapshot of the discovered feeds

Run it with:

```bash
python macau_dsat_feed.py --pretty
```

Useful options:

- `--limit 5` to only print the first few cameras
- `--index-url <url>` to point the pipeline at a different DSAT index page or a local fixture

Run the tests with:

```bash
python -m unittest discover -s tests -q
```
