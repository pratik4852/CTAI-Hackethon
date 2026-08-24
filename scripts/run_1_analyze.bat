@echo off
REM Analyze the full dataset -> outputs/analysis (counts, class maps, plots)
cd /d "%~dp0.."
set DATASET=E:\CTA Dataset\CTD Dataset
python -m src.analysis.analyze_dataset --dataset "%DATASET%" --out outputs\analysis
pause
