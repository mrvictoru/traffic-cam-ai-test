$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repositoryRoot

$sourceFrames = @(
    "output\camera109-sunday-afternoon-20260927\burst-03\cam_109\frame_001.jpg",
    "output\camera109-sunday-afternoon-20260927-1546\burst-02\cam_109\frame_001.jpg"
)
foreach ($path in $sourceFrames) {
    if (-not (Test-Path $path)) {
        throw "Required retained camera 109 frames are missing: $path"
    }
}

$gpuProbe = docker run --rm --gpus all nvcr.io/nvidia/deepstream:7.1-triton-multiarch nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
if ($LASTEXITCODE -ne 0) {
    throw "Docker cannot access an NVIDIA GPU. TrafficCamNet test was not started."
}
$gpuProbe

docker compose --profile capture run --rm --no-deps --entrypoint bash live-capture /app/tools/trafficcamnet-test/prepare-clips.sh
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare camera 109 test clips."
}

docker compose -f docker-compose.trafficcamnet.yml --profile trafficcamnet run --rm trafficcamnet-test
if ($LASTEXITCODE -ne 0) {
    throw "TrafficCamNet test container failed."
}
