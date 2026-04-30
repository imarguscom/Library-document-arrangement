# Library-document-arrangement

将从 Scopus、Web of Science (WOS)、EI Compendex 等学术数据库检索导出的多源异构文献列表，自动进行数据清洗、融合去重，并通过异步调用外部 API 增强元数据，最终转换为图书馆 **CSpace 批量导入模板（期刊论文）** 所需的 `.xls` 格式。

## 功能

- **多源异构数据解析**：自动识别 WOS、Scopus、EI 的不同表头与特征，对含 UTF-8 BOM 及非标准引号的异常 CSV 文件实现高容错降级读取。
- **数据融合与清洗**：基于 DOI 及外部标识符实现无状态的确定性去重合并；利用正则提取并规范化复杂的作者单位序列及关联关系；统一规范化多语言字段与日期格式。
- **外部 API 集成与容错控制**：
  - 接入 Scopus Abstract API 获取 XML 格式数据并解析学科分类。
  - 实现基础的**服务治理机制**：针对外部接口的限流及超时问题，内置了并发控制（Sleep限速）、异常捕获及 404 死链跳过处理，防止单点故障阻塞整体流程。
- **前后端分离与异步任务**：通过 CustomTkinter 构建图形交互界面，利用 Python `threading` 实现底层 IO 任务与 UI 渲染解耦；通过覆写 `sys.stdout` 实现日志的实时反向输出，保证极佳的用户交互体验。

## 字段映射

| 数据源提取字段合并     | CSpace 字段（中文）    | CSpace 内部键                          |
|------------------------|------------------------|----------------------------------------|
| Title                  | 题名                   | dc.title                               |
| Author full names      | 作者（格式化）         | dc.contributor.author                  |
| Author full names[0]   | 第一作者               | dc.contributor.firstauthor             |
| Source title           | 来源期刊               | dc.source.journal                      |
| Year                   | 年份                   | dc.date.issued                         |
| Volume                 | 卷                     | dc.description.volume                  |
| Issue                  | 期                     | dc.description.issue                   |
| Art. No.               | 文章编号               | dc.identifier.articlenumber            |
| Page start             | 起始页                 | dc.description.startpage               |
| Page end               | 结束页                 | dc.description.endpage                 |
| Page count             | 页数                   | dc.description.pagecount               |
| DOI                    | DOI                    | dc.identifier.doi                      |
| Cited by               | 被引次数               | dc.description.citedby                 |
| Document Type          | 文献类型               | dc.type                                |
| Publication Stage      | 出版阶段               | dc.description.publicationstage        |
| Source                 | 数据来源               | dc.source                              |
| EID                    | 资源标识符             | dc.identifier.eid                      |
| Scopus学科分类         | 学科分类               | dc.subject.classification              |

> 通讯作者、作者机构、摘要、关键词等复杂字段已通过代码实现智能剥离与匹配，直接输出。

## 环境要求

- Python 3.10+
- Pandas, Requests, CustomTkinter

## 安装与运行

### 方式一：GUI 客户端（推荐）
```bash
# 安装依赖后直接运行界面
pip install pandas requests customtkinter openpyxl
python ui_app.py
```

### 方式二：命令行调用（向下兼容）
```bash
python converter.py <合并输出的.xlsx> <输入文件1> <输入文件2> ...
```

## 数据导出步骤说明

1. 在数据库搜索结果页面，勾选需要导出的文献。
2. 点击 **Export** -> 选择 **CSV / Excel**。
3. 在导出选项中确保一键全选所有信息（包含引文、摘要及附属信息）。
4. （针对 Scopus）文件编码选 **UTF-8**，字段分隔符选 **Tab**。
5. 运行本工具进行一键清洗与合并。

## 项目结构

```text
Library-document-arrangement/
├── ui_app.py                  # 主程序入口：GUI 视图层与业务逻辑调度的全栈整合
├── converter.py               # 底层核心逻辑：多源数据清洗、正则解析与合并规则
├── scopus_subject_updater.py  # 外部集成：Scopus Abstract API 请求与 XML 解析模块
├── requirements.txt           # Python 依赖
└── README.md                  # 项目文档
```