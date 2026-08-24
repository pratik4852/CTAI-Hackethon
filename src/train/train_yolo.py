"""
Train a YOLOv8 detector on the tiled MEP dataset.

Run (after src.data_prep.coco_to_yolo has produced dataset.yaml):
  python -m src.train.train_yolo \
      --data data/yolo/dataset.yaml --model yolov8s.pt \
      --imgsz 1280 --epochs 100 --batch 8 --name mep_combined

Notes:
  - imgsz should match the tile size used in data prep (default 1280).
  - Small symbols benefit from a larger imgsz and more epochs; start with
    yolov8s and move to yolov8m if you have GPU headroom.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def train(data: str, model: str = "yolov8s.pt", imgsz: int = 1280,
          epochs: int = 100, batch: int = 8, device: str = None,
          project: str = "outputs/runs", name: str = "mep",
          patience: int = 25, resume: bool = False) -> None:
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Install ultralytics:  pip install ultralytics") from exc

    yolo = YOLO(model)
    yolo.train(
        data=str(Path(data).resolve()),
        imgsz=imgsz,
        epochs=epochs,
        batch=batch,
        device=device,
        project=project,
        name=name,
        patience=patience,
        resume=resume,
        # Symbols are line-art; keep photometric aug mild, geometry moderate.
        hsv_h=0.0, hsv_s=0.1, hsv_v=0.2,
        degrees=0.0, translate=0.05, scale=0.2, shear=0.0,
        fliplr=0.0, flipud=0.0,     # drawings have canonical orientation
        mosaic=1.0, close_mosaic=10,
        cos_lr=True,
        verbose=True,
    )
    best = Path(project) / name / "weights" / "best.pt"
    print(f"[train] done. Best weights: {best}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Train YOLOv8 on tiled MEP data")
    ap.add_argument("--data", required=True, help="path to dataset.yaml")
    ap.add_argument("--model", default="yolov8s.pt")
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default=None, help="e.g. 0 for GPU 0, or cpu")
    ap.add_argument("--project", default="outputs/runs")
    ap.add_argument("--name", default="mep")
    ap.add_argument("--patience", type=int, default=25)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    train(args.data, args.model, args.imgsz, args.epochs, args.batch,
          args.device, args.project, args.name, args.patience, args.resume)


if __name__ == "__main__":
    main()
