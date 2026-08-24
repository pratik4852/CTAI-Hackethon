@echo off
REM Render + tile + convert COCO -> YOLO dataset (combined mech+elec model)
cd /d "%~dp0.."
set DATASET=E:\CTA Dataset\CTD Dataset
python -m src.data_prep.coco_to_yolo --dataset "%DATASET%" --out data\yolo --mode combined --tile 1280 --overlap 0.2
pause
