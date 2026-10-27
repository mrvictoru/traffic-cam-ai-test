#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/data/trafficcamnet-test/videos

make_clip() {
    local source_root="$1"
    local burst="$2"
    local clip="$3"
    ffmpeg -hide_banner -loglevel error -y \
        -framerate 5 \
        -start_number 1 \
        -i "${source_root}/burst-${burst}/cam_109/frame_%03d.jpg" \
        -frames:v 30 \
        -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p \
        "/app/data/trafficcamnet-test/videos/${clip}.mp4"
}

make_clip /app/output/camera109-sunday-afternoon-20260927 03 window1_burst03
make_clip /app/output/camera109-sunday-afternoon-20260927 05 window1_burst05
make_clip /app/output/camera109-sunday-afternoon-20260927 06 window1_burst06
make_clip /app/output/camera109-sunday-afternoon-20260927 09 window1_burst09
make_clip /app/output/camera109-sunday-afternoon-20260927 13 window1_burst13
make_clip /app/output/camera109-sunday-afternoon-20260927 15 window1_burst15
make_clip /app/output/camera109-sunday-afternoon-20260927-1546 02 window2_burst02
make_clip /app/output/camera109-sunday-afternoon-20260927-1546 11 window2_burst11
make_clip /app/output/camera109-sunday-afternoon-20260927-1546 12 window2_burst12
make_clip /app/output/camera109-sunday-afternoon-20260927-1546 17 window2_burst17
make_clip /app/output/camera109-sunday-afternoon-20260927-1546 18 window2_burst18
make_clip /app/output/camera109-sunday-afternoon-20260927-1546 20 window2_burst20

printf 'Prepared %s clips\n' "$(find /app/data/trafficcamnet-test/videos -maxdepth 1 -name '*.mp4' | wc -l)"
