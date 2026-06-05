@echo off
echo ============================================
echo   Photo Studio - Орнату
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ҚАТЕ] Python орнатылмаған! python.org-тан жүктеп ал.
    pause
    exit /b 1
)

echo [1/3] Python табылды
echo.

REM Install dependencies
echo [2/3] Кітапханалар орнатылуда... (opencv ~50MB, бірнеше мин)
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ҚАТЕ] Орнату сәтсіз. pip жұмыс істей ме?
    pause
    exit /b 1
)

echo.
echo [3/3] .env файлын дайындау...
if not exist .env (
    copy .env.example .env
    echo .env файлы жасалды - API кілттерін енгіз!
) else (
    echo .env файлы бар - OK
)

echo.
echo ============================================
echo   Дайын! start.bat iске қос
echo   .env файлына API кілттерін ұмытпа!
echo ============================================
pause
