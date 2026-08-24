@echo off
REM Train YOLOv8 on the tiled dataset. Set device to your GPU id (e.g. 0) or cpu.
cd /d "%~dp0.."
python -m src.train.train_yolo --data data\yolo\dataset.yaml --model yolov8s.pt --imgsz 1280 --epochs 100 --batch 8 --device 0 --name mep_combined
pause
