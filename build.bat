@echo off
chcp 65001 >nul
echo ========================================
echo KOI 应用程序编译脚本
echo ========================================
echo.

REM 检查是否安装了 PyInstaller
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [错误] 未安装 PyInstaller
    echo 正在安装 PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

echo [1/4] 清理旧的编译文件...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "koi.exe" del /q "koi.exe"
echo 清理完成

echo.
echo [2/4] 检查依赖...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [警告] 部分依赖安装失败,继续编译...
)

echo.
echo [3/4] 开始编译 (单可执行文件模式)...
echo 这可能需要几分钟时间,请耐心等待...
pyinstaller --clean koi.spec

if errorlevel 1 (
    echo.
    echo [错误] 编译失败!
    echo 请检查错误信息并修复后重试
    pause
    exit /b 1
)

echo.
echo [4/4] 复制必要文件到输出目录...
REM 单文件模式下,exe 在 dist 目录
if exist "dist\koi.exe" (
    echo 复制 koi.exe 到当前目录...
    copy "dist\koi.exe" "koi.exe" >nul
    
    REM 创建发布目录
    if not exist "release" mkdir "release"
    
    echo 复制到 release 目录...
    copy "dist\koi.exe" "release\koi.exe" >nul
    copy "config.json" "release\config.json" >nul
    copy "1.ico" "release\1.ico" >nul
    
    REM 复制模板文件夹
    if exist "Report_Template" (
        echo 复制报告模板...
        xcopy "Report_Template" "release\Report_Template\" /E /I /Y >nul
    )
    
    if exist "modules\data_processing\templates" (
        echo 复制数据处理模板...
        xcopy "modules\data_processing\templates" "release\modules\data_processing\templates\" /E /I /Y >nul
    )
    
    echo.
    echo ========================================
    echo 编译成功!
    echo ========================================
    echo.
    echo 输出文件:
    echo   - 可执行文件: release\koi.exe
    echo   - 配置文件: release\config.json
    echo   - 图标文件: release\1.ico
    echo   - 报告模板: release\Report_Template\
    echo   - 数据处理模板: release\modules\data_processing\templates\
    echo.
    echo 注意: 
    echo   1. 首次运行时,程序会解压到临时目录,可能需要几秒钟
    echo   2. 启动动画会在独立进程中运行,确保流畅体验
    echo   3. 请将 release 目录下的所有文件一起分发
    echo.
) else (
    echo [错误] 未找到编译输出文件!
    pause
    exit /b 1
)

pause
