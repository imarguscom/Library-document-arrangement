# Library-document-arrangement

将从 Scopus 等学术数据库检索导出的 CSV 文献列表，自动整理转换为图书馆 **CSpace 批量导入模板（期刊论文）** 所需的 `.xls` 格式。

## 功能特性

- 读取 Scopus 导出的制表符分隔 CSV 文件（含 UTF-8 BOM）
- 自动清理作者全名（去除 Scopus 作者 ID）
- 提取第一作者字段
- 生成符合 CSpace 两行表头规范的 `.xls` 文件
- 输出文件名格式：`CSpace批量导入模板_期刊论文_YYYYMMDD.xls`

## 字段映射

| Scopus 字段            | CSpace 字段（中文）    | CSpace 内部键                          |
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
| Open Access            | 开放获取               | dc.rights.accessrights                 |
| Source                 | 数据来源               | dc.source                              |
| EID                    | 资源标识符             | dc.identifier.eid                      |
| Link                   | 链接                   | dc.identifier.uri                      |

> 通讯作者、作者机构、摘要、关键词、ISSN 等字段在 Scopus 导出中不包含，留空供人工填写。

## 环境要求

- Python 3.10+

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

```bash
python converter.py <Scopus导出CSV文件> [输出目录]
```

### 示例

```bash
# 使用示例文件，输出到当前目录
python converter.py samples/sample_scopus_input.csv

# 指定输出目录
python converter.py samples/sample_scopus_input.csv ./output
```

输出示例：

```
Output written to: ./CSpace批量导入模板_期刊论文_20260309.xls
```

## Scopus 导出步骤

1. 在 Scopus 搜索结果页面，勾选需要导出的文献
2. 点击 **Export** → 选择 **CSV**
3. 在导出选项中确保一键全选所有信息
4. 文件编码选 **UTF-8**，字段分隔符选 **Tab**
5. 下载 `.csv` 文件后运行本工具转换

## 运行测试

```bash
python -m pytest tests/ -v
```

## 项目结构

```
Library-document-arrangement/
├── converter.py               # 主转换脚本
├── requirements.txt           # Python 依赖
├── samples/
│   └── sample_scopus_input.csv   # Scopus 导出示例文件
└── tests/
    └── test_converter.py      # 单元测试
```