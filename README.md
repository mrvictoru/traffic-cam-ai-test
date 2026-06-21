# traffic-cam-ai-test
This repo is to test taking live traffic cam and outputting useful traffic information

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

## Docker Support

You can run the pipeline in a Docker container on both Windows and Linux systems. The only requirement is to have Docker installed.

### Using Docker Directly

Build the image:

```bash
docker build -t macau-feed .
```

Run the pipeline with default options:

```bash
docker run macau-feed
```

Run with custom options:

```bash
docker run macau-feed --limit 5
docker run macau-feed --pretty --limit 10
```

Run the tests inside the container:

```bash
docker run macau-feed python -m unittest discover -s tests -q
```

### Using Docker Compose

The easiest way to run the pipeline is with Docker Compose:

```bash
docker-compose up
```

This will build the image and run the pipeline with default settings.

To pass custom arguments, edit the `docker-compose.yml` file and uncomment/modify the `command` line in the `macau-feed` service, then run:

```bash
docker-compose up --build
```

To run tests with Docker Compose, edit `docker-compose.yml` to replace the command with:

```yaml
command: ["python", "-m", "unittest", "discover", "-s", "tests", "-q"]
```

Then run:

```bash
docker-compose up --build
```
