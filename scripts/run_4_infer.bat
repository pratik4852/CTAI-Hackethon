@echo off
REM Run detection + counting on the test drawings -> outputs/detections
cd /d "%~dp0.."
set DATASET=E:\CTA Dataset\CTD Dataset
set WEIGHTS=outputs\runs\mep_combined\weights\best.pt

python -m src.infer.predict_sheet --weights "%WEIGHTS%" --classes data\yolo\classes.json --pdf "%DATASET%\testing\mechanical\mechanical.pdf" --out outputs\detections --conf 0.25
python -m src.infer.predict_sheet --weights "%WEIGHTS%" --classes data\yolo\classes.json --pdf "%DATASET%\testing\mechanical\METRO_P1_MECH_BL5.1.pdf" --out outputs\detections --conf 0.25
python -m src.infer.predict_sheet --weights "%WEIGHTS%" --classes data\yolo\classes.json --pdf "%DATASET%\testing\electrical\Sheets_selected_Electrical_2026-08-07_11-28-36am.pdf" --out outputs\detections --conf 0.25
pause
