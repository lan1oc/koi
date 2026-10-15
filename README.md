# Koi - 多功能信息收集与处理工具
# 2026-9-23 更新
rust重构后端，提升性能，修复一些bug
# 闲来无事
老是碰到大量重复性的工作，想着让ai写个工具能够简化一下我的操作，并且也结合了以前写的一些工具，集成了一下

## 项目简介

Koi 是一款 Windows 桌面工具，把信息查询、表格处理、Word/PDF 处理和 AI 测试放在一起，减少日常重复操作。当前版本为 **4.0.0**，使用 Tauri 前端和 Rust 后端。

## 主要功能

| 模块 | 能做什么 |
| --- | --- |
| 信息收集 | 天眼查、爱企查查询与企业分类；FOFA、Hunter、Quake 资产查询；微步威胁情报查询 |
| 数据处理 | Excel/CSV/TXT 字段提取、数据填充、字段映射、模板管理 |
| 文档处理 | Word/PDF 转换、PDF 预览和选页提取、合并、压缩，以及通报处理 |
| AI 测试 | 模型配置与连接测试、会话工作台、模型规划、工具执行、证据展示和断点继续 |
| 江湖救急 | 根据通报目录和日期生成周报 |

左侧功能导航展开时保持原有尺寸，需要更大的工作区时可以收起。AI 工作台的会话列表、执行侧栏也可以分别展开和收起。

## 下载和使用

推荐从 [GitHub Releases](https://github.com/lan1oc/koi/releases) 下载 Windows x64 版本：

- **便携版**：解压后运行 `koi\koi.exe`，保留解压目录中的 `koi`、`koi-data` 和 `koi-portable.marker`，保持原有目录结构。
- **安装版**：运行 `koi-v4.0.0-windows-x64-setup.exe`，按提示安装。

运行成品不需要安装 Node.js、Rust 或系统 Python。Word 自动转换和依赖 Word 排版的流程需要本机安装 Microsoft Word。程序使用随包提供的 PDFium、归档运行时和隔离探针运行时。

### 配置和数据保存

首次启动会初始化配置和数据库。各功能使用的凭据在对应页面配置：

- FOFA：账号邮箱与 API Key。
- Hunter、Quake、微步：对应平台的 API Key。
- 天眼查、爱企查：对应站点的 Cookie；需要登录时可使用站点隔离的登录窗口。
- AI 测试：在“模型与工具”中配置 Provider、Base URL、Model 和 API Key，并点击“测试模型”。

程序界面只显示凭据是否已配置，已保存的敏感值使用 Windows DPAPI 保护。保存配置时，密钥输入留空会保留原值；需要删除时使用明确的清除选项。

便携版的配置、企业数据库、会话、计数器和模板保存在 `koi-data`。安装版默认使用 `%LOCALAPPDATA%\Koi`。升级前应备份数据；替换程序文件时保留用户数据目录，不要直接删除整个发布目录。

## 信息收集

### 企业查询

#### 天眼查

输入企业名称进行单项查询，也可以导入企业名单批量查询。查询结果按企业展示，可以查看详细信息并导出。遇到登录或验证要求时，按页面提示使用站点隔离的登录窗口。

![天眼查：单项与批量查询、登录配置和企业结果区域](docs/readme-images/03-enterprise-tyc.png)

#### 爱企查

支持企业名称查询、批量文件查询、企业基础信息和平台提供的联系方式等明细。天眼查与爱企查使用不同的登录数据目录；可用字段取决于接口、账号权限和 Cookie 状态。

![爱企查：企业查询及独立登录配置](docs/readme-images/04-enterprise-aiqicha.png)

#### 企业分类

按分组维护企业名单，支持全局搜索、分组与企业重命名、增删，以及把企业移动到其他分组。下面的分组和企业名均为独立数据库中的演示数据。

![企业分类：分组、企业搜索和名单维护](docs/readme-images/05-enterprise-classification.png)

### 资产查询

支持 FOFA、Hunter、Quake 单平台查询和统一查询。查询前填写对应平台配置，结果可查看结构化列表、明细并导出文本；查询数量、字段和频率受平台账号额度影响。下面展示各平台的当前查询界面与示例语法。

#### 统一查询

勾选参与查询的平台，输入条件或选择批量查询文件，在同一处查看各平台返回的资产。

![统一资产查询：平台选择、查询条件与结果列表](docs/readme-images/06-assets-unified.png)

#### FOFA

配置邮箱与 API Key，按 FOFA 语法查询；“查看语法”提供字段和示例。

![FOFA：配置、查询语句和分页设置](docs/readme-images/07-assets-fofa.png)

#### Hunter

使用 Hunter API Key，设置查询语句、页码和数量。

![Hunter：独立平台查询界面](docs/readme-images/08-assets-hunter.png)

#### Quake

使用 Quake API Key，按 Quake 支持的语法查询资产。

![Quake：独立平台查询界面](docs/readme-images/09-assets-quake.png)

### 威胁情报

使用微步 API 查询 IP 信誉、域名失陷情况和文件信息。结果支持列表、明细与平台报告链接；不同接口的可用范围以账号权限为准。

#### IP 信誉

输入 IP 地址查询信誉和相关威胁信息，也可以切换批量查询方式。

![微步 IP 信誉：查询条件和结果区域](docs/readme-images/10-threat-ip.png)

#### 域名失陷检测

输入域名查询失陷相关信息，在结果区查看返回的明细。

![域名失陷检测：域名输入和结果区域](docs/readme-images/11-threat-domain.png)

#### 文件哈希查询

选择文件报告或多引擎检测，填写 SHA256、SHA1、MD5 或 scan_id 查询已有分析结果。

![文件分析：哈希类型、报告查询与多引擎检测](docs/readme-images/12-threat-file-hash.png)

#### 文件上传分析

切换到“文件上传分析”后选择样本、沙箱类型和运行时间。执行上传会把所选文件发送到微步平台；下图展示操作界面。

![文件上传分析：文件选择与沙箱参数](docs/readme-images/13-threat-file-upload.png)

## 数据处理

### 字段提取

选择 Excel、CSV 或文本文件后，程序读取表头并尝试识别分隔符；必要时可以手动指定分隔符。选中需要的字段后提取，先在右侧预览，填写输出路径后可以保存结果。

下图由桌面版使用的前端连接真实 Rust 后端，处理演示 CSV 并提取“企业”和“网址”两列。结果只写入独立演示目录，截图中的文件路径已遮挡。

![字段提取：读取表头、选择字段并预览实际输出](docs/readme-images/01-field-extraction.png)

### 数据填充

将源数据字段映射到 Excel 目标模板，可以使用自动映射或逐项调整映射。下面使用两行合成 CSV 和独立的 Excel 模板实际完成填充。

先选择源文件和目标模板，程序分别读取两边的表头。

![数据填充：选择源数据和目标 Excel 模板](docs/readme-images/14-data-filling-inputs.png)

设置“源字段 → 目标字段”的对应关系，例如把“企业”填入“单位”、把“网址”填入“资产地址”；字段名称不同也可以手动映射。

![自定义字段映射：逐项设置源字段与目标字段](docs/readme-images/15-data-field-mapping.png)

应用映射后先预览，检查列和内容是否对应。

![填充预览：字段映射和两行实际演示数据](docs/readme-images/16-data-filling-preview.png)

点击“开始填充”选择输出文件，完成后可打开生成的 Excel。示例实际写入两行数据，结果保存在独立演示目录。

![数据填充完成：处理进度、映射与输出预览](docs/readme-images/17-data-filling-complete.png)

### 模板管理

常用的映射可以在填充页“保存为模板”，之后直接选用。模板管理支持查看、创建、编辑、导入和导出。

![模板管理：已保存的演示模板和常用操作](docs/readme-images/18-template-management.png)

查看模板时可以核对说明、源数据格式、目标模板和字段映射关系。

![模板详情：说明、格式与保存的字段映射](docs/readme-images/19-template-detail.png)

## AI 测试

### 模型与工具

可以保存和切换不同的模型配置，支持 OpenAI 兼容服务、Anthropic 及多个国内模型服务。建议先测试连接，再进入工作台执行任务。

- **上下文窗口**：用于估算可携带的原文、历史消息和工具证据量。
- **最大输出 Tokens**：单次模型回答的输出预算，可设置为 128–1,000,000；实际可用上限以所选模型和服务为准。大上下文不等于同样大的单次输出。
- **等待与停止**：模型生成不再受固定的 180/240 秒总时限阻断，等待时可以停止。连接失败、服务端限制或额度错误仍会显示具体原因。
- **工具检测**：检测和安装由应用管理的工具；动态 Python 探针使用隔离运行时，不依赖系统 Python。

下图使用独立复制的真实配置进行连接测试，截图已遮挡 API 地址和密钥。

![模型与工具：隔离真实配置的连接测试](docs/readme-images/02-model-tools.png)

### 工作台

通过会话描述任务，模型根据已有信息决定直接答复或调用工具。执行过程会展示当前文件进度、工具参数、实际结果和需要继续处理的事项。

- 推理思考、模型答复、执行安排和证据判定分别展示，答复支持 Markdown 排版，界面不展示原始响应 JSON。
- 流式内容在同一条记录中更新，避免被重复事件去重丢弃。
- 长任务保留会话和文件检查点；停止、刷新或重启后，可以使用“继续”恢复已有进度。
- 继续时复用已保存的证据；已经完成的文件不会仅凭数字进度被重做或跳过。
- 模型调用失败、证据不足或工具执行失败会明确显示；不会把这些情况直接当作验证成功。

使用自动审批时，任务仍受原目标范围、工具权限和请求预算约束。第三方库缺失时可下载兼容的 wheel 及依赖；需要从源码构建的依赖走独立审批和隔离构建流程。

下面的工作台截图使用隔离的真实模型配置，实际生成了一段普通的数据与文档功能介绍。模型答复以 Markdown 排版，思考内容单独显示。

![AI 工作台：真实模型答复、思考记录与执行侧栏](docs/readme-images/25-ai-workbench.png)

需要集中阅读时，可以分别收起功能导航、会话列表和执行侧栏；再次展开后恢复原有尺寸。

![工作台折叠视图：为完整模型答复留出阅读空间](docs/readme-images/26-ai-workbench-collapsed.png)

## 文档处理

### 文档转换

#### Word 转 PDF

选择单个 Word 或文件夹，设置输出目录；可以递归处理子目录、跳过模板和指定关键词，并在下方查看转换进度与日志。依赖 Word 排版的转换需要本机安装 Microsoft Word。

![Word 转 PDF：输入输出、递归与覆盖等转换选项](docs/readme-images/20-document-conversion.png)

#### PDF 转 Word

切换转换方向后选择 PDF 和输出目录，转换完成后可打开本次结果。不同方向的输入文件和选项独立更新。

![PDF 转 Word：转换方向与 PDF 输入设置](docs/readme-images/21-pdf-to-word.png)

### PDF 处理

#### 预览和选页

选择一个或多个 PDF，点击“加载预览”查看页面缩略图。可以点击页面选择，也可以输入页码范围。下图实际加载了三页演示 PDF，选择其中的第 1、3 页。

![PDF 页面预览：三页中选择第 1、3 页](docs/readme-images/22-pdf-preview-selection.png)

#### 提取与合并

点击“开始提取”生成新 PDF。单文件按页提取，多文件可以把选中的页面合并输出。示例已实际生成两页 PDF，并保留三页原文件。

![PDF 提取结果：两页导出完成与实际处理进度](docs/readme-images/23-pdf-extraction-result.png)

提取输出路径可以留空，默认保存在输入文件所在目录；多文件合并使用第一个输入文件的目录。默认输出使用独立文件名，避免覆盖输入 PDF。

#### 文件压缩

切换到“文件压缩”，添加文件后选择标准或强力压缩，设置输出目录并处理。右侧显示待压缩文件队列。

![PDF 文件压缩：压缩方式、输出目录与队列](docs/readme-images/24-pdf-compression.png)

### 通报处理

通报处理按目录组织分类、改写、责令整改、处置文件和 PDF 转换。界面会显示阶段进度和失败原因，并保存断点用于继续处理。

- ZIP、7z、RAR 先解压，验证产物并保存断点后再清理对应压缩包；解压失败保留源包。
- 改写、编号和产物校验成功后再完成原文件名恢复与替换；失败时保留原件和恢复记录。
- 只有有改写来源标记、且抄送字段为空或为占位符的通报，才会在分类后补全抄送；已有抄送和普通文档保持原样。
- 确认图片使用可手动调整的浮动图片；自动定位不到时使用第二页回退，并保存结果。
- 不生成授权委托书。

“PDF 转换与过程文件清理”会先验证新 PDF，再处理对应 Word；删除过程文件前列出候选。正式文档、PDF、模板及仍需恢复的文件应保留。

## 江湖救急

周报生成可以选择漏洞通报、事件通报目录和报告日期。生成前核对目录与日期范围，生成后再检查报告内容。

周报模块的当前界面如下，包含目录、报告日期和结果区域。

![周报生成界面：目录、日期和结果区域](docs/readme-images/27-weekly-interface.png)

## 从源码运行

### 开发环境

- Windows x64。
- Node.js 22.16.0、锁定的 npm 依赖。
- Rust 1.95.0（与 GitHub Actions 一致），以及 rustfmt、Clippy。
- Microsoft C++ 编译工具和 Windows SDK。

克隆项目并安装前端依赖：

```powershell
git clone https://github.com/lan1oc/koi.git
cd koi
```

进入前端目录运行开发版。调试版要求显式指定独立的临时数据目录：

```powershell
$env:KOI_USER_DATA_DIR = Join-Path $env:TEMP ('koi-dev-' + [guid]::NewGuid().ToString('N'))
cd tauri-ui
npm ci
npm run tauri dev
```

### 本地构建

在项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
```
构建脚本会检测 MSVC 和 Windows SDK，并尝试加载已安装的工具。缺失时按脚本流程下载并验证官方依赖；`-SkipInstall` 可禁止自动安装。

### 正式发布与检查

正式发布使用干净、已提交的源码：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1 -StrictRelease -Verify
```

单独运行常用检查：

```powershell
cd tauri-ui\src-tauri
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --workspace --lib --tests -- --test-threads=1
cd ..
npm run verify:backend-contract -- --strict-rust
npm run verify:behavior-matrix
npm run test:release-gates
npm run build
npm run test:e2e
```
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
