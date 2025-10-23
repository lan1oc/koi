# Koi - 多功能信息收集与处理工具

## 项目简介

Koi 是一个集成了多种功能的桌面应用程序，主要用于信息收集、威胁情报分析、文档处理等安全相关工作。

## 主要功能

### 🔍 信息收集
- **威胁情报查询**：支持 IP、域名、文件哈希等威胁情报查询
- **企业信息查询**：集成多个企业信息查询平台
- **资产映射**：网络资产发现和映射功能

### 📄 文档处理
- **文档转换**：Word 转 PDF、PDF 提取等
- **报告重写**：智能报告内容重写功能

### 🛠️ 数据处理
- **Excel 处理**：数据填充、字段提取等
- **模板管理**：支持自定义数据处理模板

### 🚨 应急响应
- **周报生成**：自动化周报生成工具

## 安装和使用

### 环境要求
- Python 3.8+
- PyQt6
- 其他依赖见 `requirements.txt`

### 安装步骤

1. 克隆项目
```bash
git clone <your-repo-url>
cd wow
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置设置
```bash
# 复制配置模板
cp config_template.json config.json
# 编辑 config.json 添加你的 API 密钥
```

4. 运行程序
```bash
python koi.py
```

## 配置说明

程序需要配置各种 API 密钥才能正常工作：

- **Hunter API**：用于网络资产查询
- **Quake API**：用于网络空间测绘
- **FOFA API**：用于网络资产搜索
- **威胁情报 API**：用于威胁情报查询
- **企业查询 Cookie**：用于企业信息查询

请参考 `config_template.json` 文件进行配置。

## 项目结构

```
├── koi.py                 # 主程序入口
├── config_template.json   # 配置文件模板
├── requirements.txt       # Python 依赖
├── modules/              # 功能模块
│   ├── Information_Gathering/  # 信息收集模块
│   ├── Document_Processing/    # 文档处理模块
│   ├── data_processing/        # 数据处理模块
│   ├── Emergency_help/         # 应急响应模块
│   ├── ui/                    # 用户界面
│   ├── config/               # 配置管理
│   └── utils/                # 工具函数
└── script/               # 独立脚本
```

## 注意事项

⚠️ **安全提醒**：
- 请勿将包含 API 密钥的 `config.json` 文件提交到版本控制系统
- 建议定期更换 API 密钥
- 使用前请确保遵守相关 API 的使用条款

## 许可证

本项目仅供学习和研究使用，请勿用于非法用途。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进项目。

## 更新日志

- v1.0: 初始版本，集成基础功能模块