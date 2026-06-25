@echo off
cd /d "%~dp0"

if not exist "E:\catenary_service\tasks" mkdir "E:\catenary_service\tasks"
if not exist "E:\catenary_service\uploads" mkdir "E:\catenary_service\uploads"

echo ========================================
echo Catenary Report Service
echo http://10.10.17.208:8920
echo Press Ctrl+C to stop
echo ========================================

python app.py --host=10.10.17.208 --port=8920
pause
