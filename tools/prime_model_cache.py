from __future__ import annotations

import argparse
from pathlib import Path

from trafficcam.config import settings


def prime_yolo_cache() -> None:
    from ultralytics import YOLO

    Path(settings.vision_yolo_weights_dir).mkdir(parents=True, exist_ok=True)
    model = YOLO(settings.vision_yolo_model_name)
    print(f"Primed YOLO model: {model.ckpt_path or settings.vision_yolo_model_name}")
    print(f"YOLO cache dir: {settings.vision_yolo_weights_dir}")


def prime_owlvit_cache() -> None:
    from transformers import pipeline

    Path(settings.huggingface_cache_dir).mkdir(parents=True, exist_ok=True)
    pipeline(
        "zero-shot-object-detection",
        model=settings.vision_model_name,
        device=settings.vision_device,
        model_kwargs={"cache_dir": settings.huggingface_cache_dir},
    )
    print(f"Primed owlvit model: {settings.vision_model_name}")
    print(f"HF cache dir: {settings.huggingface_cache_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prime on-disk model caches for Docker runs")
    parser.add_argument(
        "--backend",
        choices=["yolo", "owlvit", "all"],
        default="yolo",
        help="Which model cache(s) to prime",
    )
    args = parser.parse_args()

    if args.backend in {"yolo", "all"}:
        prime_yolo_cache()
    if args.backend in {"owlvit", "all"}:
        prime_owlvit_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
