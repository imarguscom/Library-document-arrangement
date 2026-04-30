import pandas as pd

file1 = "/Users/wyh/Desktop/Library-document-arrangement/samples/scopus-1.csv"
file2 = "/Users/wyh/Desktop/Library-document-arrangement/samples/scopus-2.csv"
out = "scopus.csv"

df1 = pd.read_csv(file1, dtype=str)
df2 = pd.read_csv(file2, dtype=str)

# 去掉列名两侧空格/隐藏字符，避免“看起来一样其实不一样”
df1.columns = df1.columns.str.strip().str.replace("\ufeff", "")
df2.columns = df2.columns.str.strip().str.replace("\ufeff", "")

# 校验列名完全一致（顺序也一致）
if list(df1.columns) != list(df2.columns):
    raise ValueError("两文件表头不一致（列名或顺序不同），请先对齐。")

merged = pd.concat([df1, df2], ignore_index=True)
merged.to_csv(out, index=False, encoding="utf-8-sig")
print("OK ->", out)