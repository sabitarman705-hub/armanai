@echo off
echo ============================================
echo   Photo Studio iске қосылуда...
echo   http://localhost:5000  бетін аш
echo ============================================
echo.

if not exist .env (
    echo [ЕСКЕРТУ] .env файлы жоқ! setup.bat iске қос.
    pause
)

start "" http://localhost:5000
python app.py
pause
