from pathlib import Path
import tempfile

import pandas as pd

try:
    import streamlit as st
except ModuleNotFoundError:  # Allows import/compile checks before Streamlit is installed.
    st = None

from converter import run_conversion


SUPPORTED_DATA_TYPES = ["xlsx", "xls", "csv", "txt"]
SUPPORTED_CONFIG_TYPES = ["xlsx", "xls", "csv"]


def _save_uploaded_file(uploaded_file, directory: Path) -> str:
    path = directory / uploaded_file.name
    path.write_bytes(uploaded_file.getbuffer())
    return str(path)


def _read_preview_frames(output_path: str):
    xl = pd.ExcelFile(output_path)
    frames = {}
    for sheet in ["全部数据", "期刊论文", "会议论文", "校外成果", "待确认", "需补邮箱"]:
        if sheet in xl.sheet_names:
            frames[sheet] = pd.read_excel(output_path, sheet_name=sheet, dtype=str, nrows=100)
    return frames


def _sheet_metric(frames, sheet_name):
    frame = frames.get(sheet_name)
    return 0 if frame is None else len(frame)


def main():
    if st is None:
        raise RuntimeError("Streamlit is not installed. Install dependencies with `python3 -m pip install -r requirements.txt`.")

    st.set_page_config(page_title="文献数据合并与博文阁导入工具", layout="wide")
    st.title("文献数据合并与博文阁导入工具")
    st.write(
        "本校成果通常来自三大数据库前台本校检索下载。"
        "校外成果通常来自本校学者 Author ID/API 采集，导入博文阁时需要匹配本校学者邮箱并补全作品认领。"
        "未匹配到的记录会进入待确认。"
        "默认优先使用 src/博文阁用户别名表.xlsx；若上传别名表，本次上传文件优先；若正式别名表不存在，则回退到其他别名来源。"
    )

    data_files = st.file_uploader(
        "上传 Scopus、WOS、EI 等导出文件",
        type=SUPPORTED_DATA_TYPES,
        accept_multiple_files=True,
    )

    achievement_type = st.radio("成果类型", ["本校成果", "校外成果"], horizontal=True)
    mode = "local" if achievement_type == "本校成果" else "external"

    with st.expander("可选配置文件", expanded=False):
        account_file = st.file_uploader("账户表", type=SUPPORTED_CONFIG_TYPES, key="account")
        article_library_file = st.file_uploader("文章库", type=SUPPORTED_CONFIG_TYPES, key="article")
        alias_file = st.file_uploader(
            "学者别名表（推荐正式博文阁别名表：别名、姓名、邮箱；兼容旧 scholar_author_name_forms.xlsx 格式）",
            type=SUPPORTED_CONFIG_TYPES,
            key="alias",
        )

    scopus_api_key = st.text_input(
        "Scopus API Key（可选，留空则跳过 Scopus 学科补充）",
        type="password",
        value="",
    )

    if st.button("开始处理", type="primary"):
        if not data_files:
            st.error("请至少上传一个数据文件。")
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_paths = [_save_uploaded_file(file, tmp) for file in data_files]
            account_path = _save_uploaded_file(account_file, tmp) if account_file else None
            article_path = _save_uploaded_file(article_library_file, tmp) if article_library_file else None
            alias_path = _save_uploaded_file(alias_file, tmp) if alias_file else None
            output_path = tmp / "博文阁导入_文献数据合并.xlsx"

            with st.spinner("正在处理文件..."):
                try:
                    stats = run_conversion(
                        input_paths,
                        str(output_path),
                        mode,
                        accounts_path=account_path,
                        article_library_path=article_path,
                        alias_path=alias_path,
                        scopus_api_key=scopus_api_key.strip() or None,
                    )
                except Exception as exc:
                    st.exception(exc)
                    return

            frames = _read_preview_frames(str(output_path))
            all_df = pd.read_excel(output_path, sheet_name="全部数据", dtype=str)
            external_df = pd.read_excel(output_path, sheet_name="校外成果", dtype=str)
            wos_record_count = 0
            wos_source_count = 0
            if not all_df.empty:
                wos_record_count = all_df.get("WOS记录号", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum()
                wos_source_count = all_df.get("来源库", pd.Series(dtype=str)).fillna("").astype(str).str.contains("WOS", case=False, na=False).sum()
            email_nonempty = 0
            claim_nonempty = 0
            if not external_df.empty:
                email_nonempty = external_df.get("本校学者邮箱", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum()
                claim_nonempty = external_df.get("作品认领", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum()

            st.success("处理完成")
            st.caption("本次处理文件：" + "；".join(file.name for file in data_files))
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("全部数据", stats["total"])
            c2.metric("本校成果", stats["local"])
            c3.metric("校外成果", stats["external_ready"])
            c4.metric("待确认", stats["pending"])
            c5, c6, c7 = st.columns(3)
            c5.metric("需补邮箱", stats["missing_email"])
            c6.metric("校外邮箱非空", int(email_nonempty))
            c7.metric("校外作品认领非空", int(claim_nonempty))
            c8, c9, c10 = st.columns(3)
            c8.metric("alias 总数", stats.get("alias_count", 0))
            c9.metric("冲突 alias", stats.get("conflict_alias_count", 0))
            c10.metric("匹配到邮箱的校外成果", int(email_nonempty))
            c11, c12 = st.columns(2)
            c11.metric("来源库含 WOS", int(wos_source_count))
            c12.metric("WOS记录号非空", int(wos_record_count))
            st.caption(f"当前使用的别名来源：{stats.get('alias_path') or '未找到；已回退到账户表/文章库等来源'}")

            preview_sheet_names = ["全部数据", "期刊论文", "会议论文", "校外成果", "待确认", "需补邮箱"]
            tabs = st.tabs(preview_sheet_names)
            for tab, sheet_name in zip(tabs, preview_sheet_names):
                with tab:
                    frame = frames.get(sheet_name)
                    if frame is None or frame.empty:
                        st.info("无记录")
                    else:
                        st.dataframe(frame, use_container_width=True)

            st.download_button(
                "下载博文阁导入 Excel",
                data=output_path.read_bytes(),
                file_name="博文阁导入_文献数据合并.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            st.download_button(
                "下载全部数据 CSV",
                data=all_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="博文阁导入_全部数据.csv",
                mime="text/csv",
            )


if __name__ == "__main__":
    main()
