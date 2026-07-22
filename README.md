# Library Document Arrangement

文献数据清洗、合并与博文阁导入工具。项目面向高校科研管理场景，把 Scopus、Web of Science、EI Compendex 和已整理的机构库成果表统一转换为可导入 CSpace / 博文阁的标准 Excel。

## 项目亮点

- 支持 Scopus、Web of Science、EI、机构库期刊论文表等多源数据导入
- 自动识别来源库，统一映射为中文成果字段
- 按 DOI 规范化、合并和去重，保留 Scopus / WOS / EI 标识
- 支持“本校成果”和“校外成果”两种处理模式
- 使用学者别名、英文名、发文名和邮箱表辅助匹配本校学者
- 校外成果模式下可生成或补全 `作品认领`
- 输出多 sheet Excel，便于导入前复核
- 提供桌面 GUI、Streamlit 网页版和命令行三种入口

## 适用场景

这个工具适合处理以下任务：

- 将三大数据库导出的成果记录转换为博文阁导入格式
- 合并 Scopus 和 WOS 中重复收录的同一篇论文
- 批量整理本校成果、校外成果或作者 Author ID/API 采集成果
- 检查成果归属、学者邮箱、作品认领字段是否可导入
- 为科研管理、成果认领和数据治理生成可审计的中间表

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 启动桌面版

```bash
python3 ui.py
```

桌面版适合日常使用，支持选择多个 Excel/CSV/TXT 文件，并在界面中选择本校或校外成果模式。

### 3. 启动网页版

```bash
streamlit run web_app.py
```

网页版适合临时演示和共享处理流程，支持上传文件、预览处理统计并下载结果。

### 4. 命令行处理

```bash
python3 converter.py outputs/result.xlsx --local samples/scopus.csv samples/sci_test.xls
```

校外成果模式：

```bash
python3 converter.py outputs/external_result.xlsx --external input_scopus.csv input_wos.xls
```

指定账户表、文章库或别名表：

```bash
python3 converter.py outputs/result.xlsx --external \
  --accounts src/user20260515085525.xlsx \
  --article-library "src/香港中文大学（深圳）-期刊论文[_所有] (1)0430.xlsx" \
  --aliases src/博文阁用户别名表.xlsx \
  input.xlsx
```

## 输入数据

程序会根据表头和文件名自动识别输入来源：

| 来源 | 识别依据 | 常见格式 |
| --- | --- | --- |
| Scopus | 存在 `EID`，文件名包含 `scopus`，或存在 `Authors with affiliations` / `带归属机构的作者` | `.csv`, `.xlsx` |
| Web of Science | 存在 `UT (Unique WOS ID)`、`Web of Science Record` 或 `UT` | `.xls`, `.xlsx`, `.txt` |
| EI Compendex | 存在 `Accession number` 和 `Classification code` | `.csv`, `.xlsx` |
| 机构库成果表 | 已整理为中文字段，如 `题名`、`作者`、`DOI` 等 | `.xlsx` |

推荐保留原始导出表头，不要手动改列名。程序会做常见字段别名兼容。

## 输出结果

默认输出一个多 sheet `.xlsx`，包含：

| Sheet | 用途 |
| --- | --- |
| `全部数据` | 所有成功合并且有 DOI 的成果 |
| `期刊论文` | 非会议、非综述的论文记录 |
| `会议论文` | 会议、proceedings、workshop 等记录 |
| `综述论文` | Review 类型记录 |
| `本校成果` | 本校成果模式或判定为本校的记录 |
| `校外成果` | 校外成果模式下已匹配邮箱、可进入认领流程的记录 |
| `待确认` | 学者匹配不明确或别名冲突的记录 |
| `需补邮箱` | 命中本校学者但缺少可用邮箱的记录 |

核心输出字段包括：

- 题名、作者、第一作者、通讯作者、作者单位
- 发表日期、发表期刊、卷号、期号、页码
- DOI、URL、来源库、收录类别
- WOS 记录号、EI 入藏号、SCOPUS_ID、SCOPUSEID
- Scopus 学科分类、被引次数、影响因子
- 数据归属、归属依据、本校学者匹配、本校学者邮箱、学者匹配依据
- 校外成果模式下的 `作品认领`

## 数据处理流程

1. 读取输入文件，清理 BOM、空白和异常表头。
2. 识别数据来源：Scopus、WOS、EI 或机构库成果表。
3. 将不同来源字段映射到统一中文字段。
4. 标准化 DOI，并以 DOI 作为主键合并重复记录。
5. 合并来源库、收录类别、数据库记录号和引用指标。
6. 根据本校/校外模式补充数据归属字段。
7. 在校外成果模式下，使用别名表、账户表和文章库匹配本校学者邮箱。
8. 生成多 sheet Excel，便于导入前人工复核。

## 学者别名与邮箱匹配

系统会优先使用正式别名表：

```text
src/博文阁用户别名表.xlsx
```

推荐格式：

| 别名 | 姓名 | 邮箱 |
| --- | --- | --- |
| Zhang Peng | 张鹏 | zhangpeng@cuhk.edu.cn |
| ZHANG, Peng | 张鹏 | zhangpeng@cuhk.edu.cn |

默认别名来源优先级：

1. 命令行或网页端显式传入的别名表
2. `src/博文阁用户别名表.xlsx`
3. `src/scholar_aliases.xlsx`
4. `src/scholar_author_name_forms.xlsx`
5. 账户表
6. 文章库推断出的发文名

同一别名对应多个学者或邮箱时，系统不会自动裁决，会把记录放入 `待确认`。

## Scopus 学科补充

桌面版和网页版支持可选填写 Scopus API Key。填写后，程序会基于 DOI 或 SCOPUSEID 调用 Elsevier Abstract API，补充 `Scopus学科分类`。

不填写 API Key 时，主流程仍可正常清洗、合并和导出，只是跳过学科补充。

## 项目结构

```text
Library-document-arrangement/
├── converter.py                  # 命令行入口与核心转换流程
├── ui.py                         # 桌面 GUI 入口
├── web_app.py                    # Streamlit 网页版入口
├── claim_mapping.py              # 发文名、姓名、邮箱和作品认领映射
├── scope_rules.py                # 本校/校外归属与学者别名匹配规则
├── scopus_subject_updater.py     # 独立 Scopus 学科补充脚本
├── samples/                      # 示例输入数据
├── src/                          # 默认账户表、别名表和机构库数据
├── tests/                        # 自动化测试
├── static_app/                   # 静态展示页面
└── README.md
```

## 测试

```bash
pytest
```

如果只想检查核心转换和归属逻辑：

```bash
pytest tests/test_converter.py tests/test_scope_rules.py
```

## 注意事项

- 当前主流程以 DOI 作为合并主键，没有 DOI 的记录不会进入最终导出。
- 校外成果的 `作品认领` 质量依赖别名表、账户表和文章库的完整性。
- 单位关键词只作为辅助证据，不直接替代人工确认。
- Scopus API Key 只用于补充学科分类，不影响基础转换流程。
- 真实业务数据可能包含个人信息和机构内部数据，公开仓库前建议移除或脱敏 `src/`、`outputs/` 中的敏感文件。

## 后续计划

- 抽象 `ui.py` 和 `converter.py` 的重复处理流程，减少维护成本
- 支持无 DOI 记录按题名、年份、期刊进行备用去重
- 增强 `待确认` 记录的人工校对和回写能力
- 增加更多真实样例的自动化测试
- 优化 Scopus / WOS / EI 不同导出版本的字段兼容性

## License

当前仓库未声明开源许可证。公开发布前请根据项目用途补充合适的 License。
