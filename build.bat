@echo off
chcp 65001 >nul
echo ========================================
echo         koi 打包脚本
echo ========================================
echo.

:: 检查 Python 环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确保已安装并添加到 PATH
    pause
    exit /b 1
)

:: 检查 PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 PyInstaller...
    pip install pyinstaller
)

:: 清理旧的构建文件
echo [1/3] 清理旧的构建文件...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

:: 开始打包
echo [2/3] 开始打包（这可能需要几分钟）...
echo.
pyinstaller koi.spec --noconfirm

:: 检查结果
if exist "dist\koi.exe" (
    echo.
    echo ========================================
    echo [3/3] 打包成功！
    echo.
    echo 输出文件: dist\koi.exe
    echo ========================================
    
    :: 复制额外文件到 dist 目录
    echo.
    echo 正在复制配置文件...
    copy "config.json" "dist\" >nul 2>&1
    copy "1.ico" "dist\" >nul 2>&1
    xcopy "Report_Template" "dist\Report_Template\" /E /I /Q >nul 2>&1
    
    echo 完成！
) else (
    echo.
    echo [错误] 打包失败，请检查错误信息
)

echo.
pause

