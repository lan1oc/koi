# Koi - 多功能信息收集与处理工具
# 2026-9-23 更新
rust重构后端，提升性能，修复一些bug
# 闲来无事
老是碰到大量重复性的工作，想着让ai写个工具能够简化一下我的操作，并且也结合了以前写的一些工具，集成了一下

## 项目简介

Koi 是一个集成了多种功能的桌面应用程序，主要用于信息收集、威胁情报分析、文档处理等安全相关工作。

## 主要功能

### 🔍 信息收集
- **威胁情报查询**：支持 IP、域名、文件哈希等威胁情报查询
- **企业信息查询**：集成多个企业信息查询平台
- **资产映射**：网络资产发现和映射功能

### 📄 文档处理
- **文档转换**：Word 转 PDF、PDF 提取等
- **报告重写**：通报内容重写功能

网信办的“开始处理”在五阶段和 PDF 校验全部成功后，将改写通报恢复为原始文件名，并替换原件；失败时保留原件和断点。此前生成的 `改写-` 文件也会在再次处理、转换 PDF 或清理时恢复原名，已分配编号不重复增加。

“PDF转换与过程文件清理”区域支持递归转换所选目录中的通报、授权委托书和责令整改 Word，校验新 PDF 后才删除对应 Word。“删除过程文件”会先列出可删除的 `.koi_notice_process_state.json`、`.koi-original-<SHA256>.docx` 和受管工作副本；确认后删除，正式文档、PDF 和处置模板保留。未完成或产物缺失的任务会保留恢复文件。

PDF 处理的提取输出路径可以留空，默认保存到输入 PDF 所在目录；多文件选页合并使用第一个输入文件的目录，并生成带 `_extract_` 或 `_merged_pages` 后缀的文件，不覆盖输入 PDF。

### 🛠️ 数据处理
- **Excel 处理**：数据填充、字段提取等
- **模板管理**：支持自定义数据处理模板

### 🚨 应急响应
- **周报生成**：自动化周报生成工具

## 安装和使用

### 环境要求
- Node.js 20+
- Rust stable
- Windows x64；动态探针使用随应用锁定的 CPython 运行时，不依赖系统 Python
- 动态探针的可选第三方包只接受 `probe-wheels.lock.json` 中锁定的 PyPI 官方二进制 wheel；当前只批准 `idna 3.10`。源码包不会在宿主机上构建，也不会回退到 `pip`。
- 7z/RAR 使用 NanaZip 7.0.1832.0 的 Microsoft Marketplace 签名 x64 MSIX；运行时文件必须与签名包内条目逐字节一致。详情见 [7-Zip 兼容运行时信任模型](docs/archive-runtime-trust.md)。

### 安装步骤

1. 克隆项目
```bash
git clone https://github.com/lan1oc/koi.git
cd koi
```

2. 安装前端依赖
```bash
cd tauri-ui
npm install
```

3. 配置设置
自动生成config.json

4. 运行程序
```bash
npm run tauri dev
```

或者直接通过编译吧
```bash
./build_release.ps1
```
or
```bash
./build_release.cmd
```

### 构建说明

开发调试时，在项目根目录执行：

```powershell
cd tauri-ui
npm ci
npm run tauri dev
```

生成正式 Windows x64 成品时，回到项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1 -Verify
```

正式构建要求 Git 工作树干净，并会执行 97 条命令契约、Rust handler、97 条命令行为矩阵、运行时锁、前端、便携包和 NSIS 门禁。默认输出目录是 `dist-tauri\4.0.0`，不会把用户可见成品写到 D 盘或其他临时目录。构建完成后，成品位于：

- `dist-tauri\4.0.0\koi-v4.0.0-windows-x64-portable.zip`
- `dist-tauri\4.0.0\koi-v4.0.0-windows-x64-setup.exe`
- `dist-tauri\4.0.0\SHA256SUMS`
- `dist-tauri\4.0.0\supply-chain.json`

如果当前工作树有本地改动，请先提交需要进入发布版本的代码；也可以按照 [KOI 4.0.0 发布流程](docs/release-4.0.0.md) 创建干净的 detached worktree 后再构建。不要把包含 `config.json`、会话、断点、Cookie 或浏览器 profile 的用户数据复制进发布目录。

构建后可使用成品自检验证完整运行时。`--data-dir` 必须是绝对路径，并且目录开始时为空：

```powershell
$selfTestData = Join-Path $env:TEMP ("koi-self-test-" + [guid]::NewGuid().ToString("N"))
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
& .\dist-tauri\4.0.0\koi\koi.exe --self-test --data-dir $selfTestData
```

自检输出中的 `ok` 应为 `true`，并应报告 97 条契约命令和 97 个 Rust handler。重新构建时可以删除 `dist-tauri\4.0.0`，脚本会重新生成；前端依赖可用 `npm ci` 恢复。

### 全功能一致性门禁

`contracts\backend-behavior-matrix.v1.json` 是 97 条后端命令的机器可读行为矩阵。旧版 `v3.1.4` 是功能能力和工作流基线，不要求 Rust 放弃更安全或更可靠的实现；矩阵把结果分为：

- `equivalent`：规范化时间、临时路径和随机 ID 后与旧版等价。
- `improved`：功能与工作流保留，同时使用 DPAPI 脱敏、带令牌的 WebSocket、持久化 generation、迟到结果丢弃等 Rust 增强。
- `security-exception`：保留工具 ID 和工作流，但拒绝恢复不受限的 `sqlmap.py`、宿主 Python 或明文秘密。

日常构建只需运行 `build_release.cmd -Verify`，它会自动执行矩阵验证。也可以单独验证：

```powershell
cd tauri-ui
npm.cmd run verify:backend-contract -- --strict-rust
npm.cmd run verify:behavior-matrix
```

只有在重新审计旧版行为时才需要系统 Python 和独立的干净旧版目录。开发捕获器固定拒绝非 `f059eacf18de2bc2c888d901d257a59cbe8e12ca`、脏工作树和包含秘密的输出；捕获器与 Rust 行协议驱动器不会进入生产包：

```powershell
cd tauri-ui\src-tauri
cargo build --locked --example backend_protocol_driver
cd ..\..
node tauri-ui\scripts\capture-python-oracle.mjs --oracle-root C:\path\to\clean-v3.1.4
cd tauri-ui
npm.cmd run generate:behavior-matrix
npm.cmd run verify:behavior-matrix
```

## 配置说明

程序需要配置各种 API 密钥才能正常工作：

- **Hunter API**：用于网络资产查询
- **Quake API**：用于网络空间测绘
- **FOFA API**：用于网络资产搜索
- **微步 API**：用于威胁情报查询
- **企业查询 Cookie**：用于企业信息查询（天眼查、爱企查）


# 信息收集
## 企业查询
### 天眼查
可粘贴 Cookie，也可在查询遇到登录/风控时使用应用打开的站点隔离 WebView2 登录窗口。天眼查与爱企查使用不同的浏览器 profile；Rust 只提取对应站点的 Cookie。
![](docs/readme-images/02-enterprise-tyc.png)
批量最多能查多少还不知道，最多的的是，一次性查了77家，然后没被ban
![](docs/readme-images/02-enterprise-tyc.png)
### 爱企查
可粘贴 Cookie，也可使用站点隔离 WebView2 登录窗口。
能查地址、注册号、备案号、资产主域名、员工联系方式（不保真，就是爱企查那边更多手机号的信息）
![](docs/readme-images/03-enterprise-aiqicha.png)

## 资产测绘
如下
![](docs/readme-images/06-assets-fofa.png)

## 威胁情报
根据微步的api写的，但是比较鸡肋，md基本有用的功能都不让你免费用
### ip信誉
界面如下
![](docs/readme-images/09-threat-ip.png)

### 域名失陷检测

如下

![域名失陷检测结果](docs/readme-images/10-threat-domain.png)

### 文件分析

#### 哈希查询

界面如下

![哈希查询界面](docs/readme-images/11-threat-file.png)



#### 文件上传

界面如下

![文件上传界面](docs/readme-images/11-threat-file.png)

查询结果

![文件上传查询结果](docs/readme-images/11-threat-file.png)

打开报告

![文件上传报告](docs/readme-images/11-threat-file.png)

详情

![文件上传详情](docs/readme-images/11-threat-file.png)
# 数据处理
## 字段提取
测试文件如下
![](自研/Pasted%20image%2020251022101956.png)
选择文件后，会识别分隔符，如果识别不到可以手动设置，然后自动读取表头信息
![](自研/Pasted%20image%2020251022101916.png)
比如提取url和公司
![](自研/Pasted%20image%2020251022103311.png)
文件如下
![](自研/Pasted%20image%2020251022103329.png)
## 数据填充
这个功能就是服务于前面的，提取后的数据填充到对应的模板上面
源文件就是提取后的数据文件，然后再选个模板文件
比如模板文件是这样
![](自研/Pasted%20image%2020251022104731.png)
选好文件后，然后要选择映射
![](自研/Pasted%20image%2020251022110341.png)
然后点启用映射就行，映射情况如下
![](自研/Pasted%20image%2020251022111732.png)
开始填充
![](自研/Pasted%20image%2020251022111806.png)
填充好之后
![](自研/Pasted%20image%2020251022112715.png)
![](自研/Pasted%20image%2020251022112257.png)
## 模板管理
这个就是之前数据填充那边，将映射关系保存为模板之后查看的地方
界面如下
![](自研/Pasted%20image%2020251022112953.png)
模板信息
![](自研/Pasted%20image%2020251022112936.png)
# 江湖救急
## 周报生成
界面长这样
![](docs/readme-images/18-emergency-weekly.png)
运行结果
![](docs/readme-images/18-emergency-weekly.png)

# 文档处理
## 通报改写（自用）
按照流程然后写成工具自动化改写了
有时候会遇到一些bug，成因是com接口调用繁忙，上一次调用的句柄还未释放，然后就已经到下个通报改写的调用了，就会造成图片插入失败
![](docs/readme-images/16-document-office-tools.png)
但其实影响不是不大，毕竟本身这个操作就是需要我手动微调的，不过也分两种情况
1. 文档里没有插入设置为`浮于文字上方`的盖章样式图片
2. 插入了但没保存，打开后要另存为才行，如下图所示
![](docs/readme-images/16-document-office-tools.png)
然后就是微调完，点击转换pdf的按钮，那个就是专门转换通报的
![](docs/readme-images/17-document-retest.png)
## word转pdf
界面如下
![](docs/readme-images/14-document-conversion.png)
## pdf提取
提取pdf用的，界面如下
![](docs/readme-images/15-document-pdf-extract.png)
预览
![](docs/readme-images/15-document-pdf-extract.png)

# 2026-6-6 更新
新增测试agent
# 2026-5-21 更新
前端用tauri重构，非常丝滑，然后布局细微优化重构
# 2026-1-22 功能更新
爱企查模块新增cookie获取机制，直接查询，会检测是否有cookie，或者cookie是否可用，然后启动浏览器扫码登录获取cookie
# 2025-12-29 功能更新
分组功能优化，添加标签页可视化更改
# 2025-12-17 功能更新
pdf转换bug修复、pdf提取功能优化，启动动画优化逻辑
# 2025-11-23 功能更新
加了启动动画，ui也更新了下，gemini3pro太通人性了，太会设计了😋
# 2025-11-3 功能更新
天眼查模块新增cookie获取机制，直接查询，会检测是否有cookie，或者cookie是否可用，然后启动浏览器扫码登录获取cookie
