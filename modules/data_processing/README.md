# 数据处理模块

这是一个完整的数据处理模块，提供Excel文件处理、字段提取、数据填充、模板管理等功能。

## 📁 模块结构

```
data_processing/
├── __init__.py              # 模块初始化文件
├── excel_processor.py       # Excel文件处理器
├── field_extractor.py       # 字段提取器
├── data_filler.py          # 数据填充器
├── template_manager.py      # 模板管理器
├── data_processor_ui.py     # 数据处理UI组件
├── integration_helper.py    # 集成助手
└── README.md               # 本文件
```

## 🚀 功能特性

### 📊 Excel文件处理 (ExcelProcessor)
- ✅ 读取Excel文件 (.xlsx, .xls)
- ✅ 获取工作表名称列表
- ✅ 提取表头信息
- ✅ 数据预览和统计
- ✅ 写入Excel文件
- ✅ 文件验证
- ✅ 数据类型转换
- ✅ 数据清洗

### 🔍 字段提取 (FieldExtractor)
- ✅ 从Excel文件中提取指定字段
- ✅ 预览提取结果
- ✅ 获取可用字段列表
- ✅ 模式匹配提取（支持通配符）
- ✅ 批量提取
- ✅ 字段统计和描述

### 🔄 数据填充 (DataFiller)
- ✅ 使用模板填充数据
- ✅ 从文本文件填充模板
- ✅ 预览填充结果
- ✅ 自动字段映射
- ✅ 字段映射验证
- ✅ 批量填充
- ✅ 相似度计算

### 📝 模板管理 (TemplateManager)
- ✅ 创建、编辑、删除模板
- ✅ 模板导入导出
- ✅ 模板搜索
- ✅ 使用统计
- ✅ 默认模板
- ✅ 模板验证

### 🎨 图形界面 (DataProcessorUI)
- ✅ 现代化UI设计
- ✅ 多选项卡布局
- ✅ 实时预览
- ✅ 进度显示
- ✅ 错误处理
- ✅ 文件拖拽支持

## 📦 安装依赖

```bash
pip install pandas openpyxl PySide6
```

## 🔧 使用方法

### 1. 基础使用

```python
from modules.data_processing import ExcelProcessor, FieldExtractor, DataFiller

# Excel文件处理
excel_processor = ExcelProcessor()
df = excel_processor.read_excel('data.xlsx')
headers = excel_processor.get_headers('data.xlsx')

# 字段提取
field_extractor = FieldExtractor()
result = field_extractor.extract_fields(
    source_file='data.xlsx',
    selected_fields=['姓名', '年龄', '邮箱'],
    output_file='extracted.xlsx'
)

# 数据填充
data_filler = DataFiller()
result = data_filler.fill_template(
    source_file='source.xlsx',
    template_file='template.xlsx',
    field_mapping={'姓名': 'name', '年龄': 'age'},
    output_file='filled.xlsx'
)
```

### 2. 模板管理

```python
from modules.data_processing import TemplateManager

# 创建模板管理器
template_manager = TemplateManager()

# 创建新模板
result = template_manager.create_template(
    name='用户信息模板',
    description='用于处理用户信息的模板',
    field_mapping={'姓名': 'name', '年龄': 'age', '邮箱': 'email'}
)

# 列出所有模板
templates = template_manager.list_templates()

# 使用模板
template = template_manager.use_template('template_id')
```

### 3. UI集成

```python
from modules.data_processing import DataProcessorUI
from modules.data_processing.integration_helper import integrate_data_processing_to_main_window

# 方法1：直接使用UI组件
data_ui = DataProcessorUI()
data_ui.show()

# 方法2：集成到现有主窗口
integrate_data_processing_to_main_window(main_window)
```

## 🎯 集成到主程序

在 `fool_tools.py` 中集成数据处理功能：

```python
# 1. 导入集成助手
from modules.data_processing.integration_helper import integrate_data_processing_to_main_window

# 2. 在主窗口初始化时调用
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
        # 集成数据处理功能
        integrate_data_processing_to_main_window(self)
    
    def setup_ui(self):
        # 创建主选项卡控件
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)
        
        # 其他UI设置...
```

## 📋 API文档

### ExcelProcessor

#### 主要方法
- `read_excel(file_path, sheet_name=None)` - 读取Excel文件
- `get_headers(file_path, sheet_name=None)` - 获取表头
- `get_data_preview(file_path, sheet_name=None, rows=5)` - 获取数据预览
- `write_excel(data, file_path, sheet_name='Sheet1')` - 写入Excel文件
- `validate_file(file_path)` - 验证文件

### FieldExtractor

#### 主要方法
- `extract_fields(source_file, selected_fields, output_file=None)` - 提取字段
- `preview_extraction(source_file, selected_fields, preview_rows=10)` - 预览提取
- `get_available_fields(source_file)` - 获取可用字段
- `extract_by_pattern(source_file, field_patterns)` - 模式匹配提取
- `batch_extract(extraction_configs)` - 批量提取

### DataFiller

#### 主要方法
- `fill_template(source_file, template_file, field_mapping, output_file)` - 填充模板
- `fill_from_text(source_file, template_file, field_mapping, output_file)` - 从文本填充
- `preview_filling(source_file, template_file, field_mapping)` - 预览填充
- `auto_map_fields(source_file, template_file)` - 自动映射字段
- `batch_fill(fill_configs)` - 批量填充

### TemplateManager

#### 主要方法
- `create_template(name, description, field_mapping)` - 创建模板
- `update_template(template_id, **kwargs)` - 更新模板
- `delete_template(template_id)` - 删除模板
- `get_template(template_id)` - 获取模板
- `list_templates(filter_format=None)` - 列出模板
- `export_template(template_id, export_path)` - 导出模板
- `import_template(import_path)` - 导入模板
- `search_templates(keyword)` - 搜索模板

## 🔍 示例场景

### 场景1：暴露面数据处理

```python
# 1. 从FOFA导出的Excel文件中提取关键字段
field_extractor = FieldExtractor()
result = field_extractor.extract_fields(
    source_file='fofa_export.xlsx',
    selected_fields=['IP', '端口', '协议', '标题', '国家'],
    output_file='extracted_exposure.xlsx'
)

# 2. 使用暴露面收集模板填充标准格式
data_filler = DataFiller()
template_manager = TemplateManager()

# 获取暴露面模板
template = template_manager.get_template_by_name('暴露面收集模板')

# 填充数据
result = data_filler.fill_template(
    source_file='extracted_exposure.xlsx',
    template_file='exposure_template.xlsx',
    field_mapping=template['field_mapping'],
    output_file='final_exposure_report.xlsx'
)
```

### 场景2：批量数据处理

```python
# 批量处理多个文件
extraction_configs = [
    {
        'source_file': 'file1.xlsx',
        'selected_fields': ['姓名', '邮箱'],
        'output_file': 'output1.xlsx'
    },
    {
        'source_file': 'file2.xlsx',
        'selected_fields': ['姓名', '邮箱'],
        'output_file': 'output2.xlsx'
    }
]

results = field_extractor.batch_extract(extraction_configs)
```

## 🛠️ 扩展开发

### 添加新的数据处理器

1. 在 `data_processing` 目录下创建新的处理器文件
2. 继承基础处理器类或实现标准接口
3. 在 `__init__.py` 中导出新的处理器
4. 在UI中添加对应的界面组件

### 自定义模板

```python
# 创建自定义模板
custom_template = {
    'name': '自定义模板',
    'description': '用于特定场景的模板',
    'field_mapping': {
        '目标字段1': '源字段1',
        '目标字段2': '源字段2'
    },
    'metadata': {
        'category': 'custom',
        'tags': ['自定义', '特殊用途']
    }
}

template_manager.create_template(**custom_template)
```

## 🐛 故障排除

### 常见问题

1. **文件读取失败**
   - 检查文件路径是否正确
   - 确认文件格式是否支持
   - 验证文件是否损坏

2. **字段映射错误**
   - 检查源文件和模板文件的字段名称
   - 确认字段映射关系是否正确
   - 使用预览功能验证映射结果

3. **UI显示异常**
   - 确认PySide6版本兼容性
   - 检查系统字体设置
   - 重启应用程序

### 日志调试

```python
import logging

# 启用调试日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('modules.data_processing')
```

## 📈 性能优化

- 大文件处理时使用分块读取
- 启用pandas的优化选项
- 合理设置内存使用限制
- 使用多线程处理批量任务

## 🔒 安全注意事项

- 验证输入文件的安全性
- 限制文件大小和处理时间
- 避免执行不安全的代码
- 保护敏感数据

## 📄 许可证

本模块遵循项目主许可证。

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个模块！