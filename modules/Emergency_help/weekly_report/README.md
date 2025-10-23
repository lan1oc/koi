# 周报生成模块

这是一个完整的工作周报自动生成模块，通过分析系统文件活动记录，自动生成工作周报。

## 📁 模块结构

```
weekly_report/
├── __init__.py                    # 模块初始化文件
├── weekly_report_generator.py     # 周报生成器核心逻辑
├── weekly_report_ui.py           # 周报生成UI组件
├── integration_helper.py         # 集成助手
└── README.md                     # 本文件
```

## 🚀 功能特性

### 📊 智能文件分析 (WeeklyReportGenerator)
- ✅ 从Windows注册表获取最近文件记录
- ✅ 从最近文件夹获取文件活动
- ✅ 智能识别工作相关文件
- ✅ 自动提取企业名称
- ✅ 工作类型分类统计
- ✅ 支持多种时间范围统计
- ✅ 生成详细或简要报告

### 🎨 现代化界面 (WeeklyReportUI)
- ✅ 直观的配置面板
- ✅ 实时状态显示
- ✅ 美观的结果展示
- ✅ 响应式布局设计
- ✅ 多线程处理，界面不卡顿

### 🔧 集成支持 (IntegrationHelper)
- ✅ 简单的集成接口
- ✅ 完全模块化设计
- ✅ 与主程序无缝集成

## 📦 依赖要求

```bash
PySide6>=6.0.0
```

## 🔧 使用方法

### 1. 基础使用

```python
from modules.Emergency_help.weekly_report import WeeklyReportGenerator

# 创建周报生成器
generator = WeeklyReportGenerator()

# 生成本周工作日报告
report = generator.generate_report()
print(report)

# 生成最近7天的详细报告
detailed_report = generator.generate_report(days=7, detailed=True)
print(detailed_report)
```

### 2. UI界面使用

```python
from modules.Emergency_help.weekly_report import WeeklyReportUI
from PySide6.QtWidgets import QApplication
import sys

# 创建应用程序
app = QApplication(sys.argv)

# 创建周报UI
weekly_ui = WeeklyReportUI()
weekly_ui.setWindowTitle("周报生成器")
weekly_ui.resize(1000, 700)
weekly_ui.show()

# 运行应用程序
sys.exit(app.exec())
```

### 3. 集成到主程序

```python
from modules.Emergency_help.weekly_report.integration_helper import integrate_weekly_report_to_emergency_help

# 在创建江湖救急标签页时集成
class MainWindow(QMainWindow):
    def create_emergency_tools_tab(self):
        # 创建江湖救急主标签页
        emergency_widget = QWidget()
        emergency_layout = QVBoxLayout(emergency_widget)
        
        # 创建子标签页
        emergency_tabs = QTabWidget()
        
        # 集成周报生成功能
        self.weekly_report_ui = integrate_weekly_report_to_emergency_help(emergency_tabs)
        
        # 添加其他功能标签页...
        
        emergency_layout.addWidget(emergency_tabs)
        self.tab_widget.addTab(emergency_widget, "🆘 江湖救急")
```

## 📋 API文档

### WeeklyReportGenerator

#### 主要方法
- `generate_report(days=None, detailed=False)` - 生成工作周报
  - `days`: 统计天数，None表示本周工作日
  - `detailed`: 是否生成详细报告
  - 返回: 生成的周报内容字符串

#### 私有方法
- `_collect_file_activities(start_date, end_date)` - 收集文件活动记录
- `_get_recent_files_from_registry()` - 从注册表获取最近文件
- `_get_recent_files_from_folder()` - 从最近文件夹获取文件
- `_analyze_work_content(file_records)` - 分析工作内容
- `_generate_report_content(date_range, analysis, detailed, file_records)` - 生成报告内容

### WeeklyReportUI

#### 主要方法
- `generate_weekly_report()` - 生成工作周报
- `clear_weekly_report()` - 清空周报结果
- `update_report_progress(message)` - 更新生成进度
- `on_report_completed(report)` - 报告生成完成回调

#### UI组件
- `report_range_combo` - 时间范围选择下拉框
- `report_type_combo` - 报告类型选择下拉框
- `weekly_report_result` - 结果显示文本框
- `report_status_label` - 状态显示标签

### IntegrationHelper

#### 集成函数
- `create_weekly_report_tab(parent_tab_widget)` - 创建周报生成选项卡
- `integrate_weekly_report_to_emergency_help(emergency_help_tabs)` - 集成到江湖救急
- `add_weekly_report_methods_to_main_window(main_window)` - 添加方法到主窗口

## 🎯 工作原理

### 文件收集机制
1. **注册表扫描**: 从Office应用程序的MRU（Most Recently Used）记录中获取最近文件
2. **系统文件夹**: 扫描Windows最近文件夹中的快捷方式
3. **时间过滤**: 根据指定时间范围过滤文件记录
4. **去重处理**: 合并重复的文件记录

### 智能分析算法
1. **关键词匹配**: 使用预定义的工作关键词识别工作相关文件
2. **企业名称提取**: 通过正则表达式提取文件名中的企业信息
3. **工作类型分类**: 根据文件名特征自动分类工作类型
4. **统计分析**: 生成各种维度的统计信息

### 报告生成流程
1. **数据收集**: 收集指定时间范围内的文件活动
2. **内容分析**: 分析文件内容，提取工作信息
3. **报告组装**: 按照模板格式组装最终报告
4. **格式化输出**: 生成Markdown格式的周报内容

## 🔍 配置选项

### 时间范围选项
- **本周工作日**: 从本周一到今天
- **最近3天**: 最近3天的文件活动
- **最近7天**: 最近一周的文件活动
- **最近14天**: 最近两周的文件活动
- **最近30天**: 最近一个月的文件活动

### 报告类型
- **简要报告**: 包含基本统计和主要工作内容
- **详细报告**: 包含完整的文件列表和详细分析

## 🛠️ 自定义扩展

### 添加新的工作关键词

```python
# 在WeeklyReportGenerator.__init__中修改
self.work_keywords = [
    '漏洞', '扫描', '渗透', '测试', '安全', '评估', '报告', '检测',
    '修复', '加固', '防护', '监控', '审计', '合规', '风险',
    'vulnerability', 'scan', 'penetration', 'test', 'security',
    'assessment', 'report', 'detection', 'fix', 'hardening',
    # 添加新的关键词
    '新关键词1', '新关键词2'
]
```

### 自定义企业名称匹配规则

```python
# 在WeeklyReportGenerator.__init__中修改
self.company_patterns = [
    r'([\u4e00-\u9fa5]+(?:公司|集团|企业|科技|网络|信息|系统|软件|技术))',
    r'([A-Za-z]+(?:\s+(?:Inc|Corp|Ltd|Co|Company|Group|Tech|Technology)))',
    # 添加新的匹配规则
    r'新的正则表达式规则'
]
```

### 自定义工作类型分类

```python
# 在_analyze_work_content方法中修改work_types字典
analysis['work_types'] = {
    '漏洞扫描': 0,
    '渗透测试': 0,
    '安全评估': 0,
    '报告编写': 0,
    '新工作类型': 0,  # 添加新的工作类型
    '其他': 0
}
```

## 📈 性能优化

### 文件扫描优化
- 使用多线程处理，避免界面卡顿
- 智能缓存机制，减少重复扫描
- 异常处理，确保程序稳定性

### 内存使用优化
- 流式处理大量文件记录
- 及时释放不需要的数据
- 优化数据结构，减少内存占用

## 🐛 故障排除

### 常见问题

1. **无法获取文件记录**
   - 检查Windows用户权限
   - 确认Office应用程序已安装
   - 检查注册表访问权限

2. **生成的报告为空**
   - 检查时间范围设置
   - 确认工作关键词配置
   - 检查文件活动是否在指定时间内

3. **界面卡顿**
   - 确认使用了多线程处理
   - 检查文件数量是否过多
   - 优化扫描范围

### 调试模式

```python
import logging

# 启用调试日志
logging.basicConfig(level=logging.DEBUG)

# 创建生成器
generator = WeeklyReportGenerator()
report = generator.generate_report()
```

## 📝 更新日志

### v1.0.0 (2025-01-22)
- ✅ 初始版本发布
- ✅ 完整的周报生成功能
- ✅ 现代化UI界面
- ✅ 模块化架构设计
- ✅ 集成助手支持

## 🤝 贡献指南

欢迎提交Issue和Pull Request来改进这个模块！

### 开发环境设置

```bash
# 安装依赖
pip install PySide6

# 运行测试
python weekly_report_ui.py
```

### 代码规范
- 遵循PEP 8代码风格
- 添加适当的注释和文档字符串
- 编写单元测试

---

*周报生成模块 v1.0.0 - 让工作汇报更简单！*