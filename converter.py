import pandas as pd
import sys
import re

# ================= 配置区域 =================
# 如果 Scopus 中只有年份，默认补充的日期
DEFAULT_DATE_SUFFIX = "-01-01" 
# ===========================================

def clean_name_keep_full(name_str):
    """
    清洗名字，去除 ID，保留全名。
    输入: "Chuang, Cheng-Hsun (57200334448)"
    输出: "Chuang, Cheng-Hsun"
    """
    if pd.isna(name_str): return ""
    # 去掉括号及里面的数字
    return re.sub(r'\s*\(\d+\)', '', str(name_str)).strip()

def parse_affiliations_to_dict(aff_str):
    """
    将 Scopus 的 Affiliations 列解析为 {机构文本: 序号} 的字典
    Scopus 的 Affiliations 通常用 "; " 分隔
    """
    if pd.isna(aff_str): return {}, []
    
    # Scopus 的机构列表通常是用分号分隔的
    # 注意：有时候机构名称内部也有分号（极少），这里假设用 "; " 分割
    aff_list = [a.strip() for a in str(aff_str).split(';') if a.strip()]
    
    aff_dict = {}
    master_list = []
    
    for idx, aff in enumerate(aff_list):
        # 序号从 1 开始
        real_index = idx + 1
        aff_dict[aff] = real_index
        master_list.append(aff)
        
    return aff_dict, master_list

def match_author_affiliations(auth_entry, aff_dict, master_aff_list):
    """
    确定某个作者属于哪些机构序号。
    auth_entry: "Chuang C.-H., Institute of Molecular Medicine..."
    aff_dict: {机构名: 序号}
    """
    indices = []
    
    # 策略：遍历所有主机构名，看它是否包含在这个作者的条目字符串中
    for aff_name in master_aff_list:
        # 使用精确包含检查
        if aff_name in auth_entry:
            indices.append(aff_dict[aff_name])
            
    # 如果没匹配到（可能是拼写差异），尝试模糊匹配或留空
    # 这里排序 indices 保证 (1,2) 而不是 (2,1)
    return sorted(list(set(indices)))

def get_author_name_from_entry(auth_entry):
    """
    从 "Chuang C.-H., Institute..." 中提取 "Chuang C.-H."
    """
    if ',' in auth_entry:
        # Scopus 格式通常是 Last, F.M., Dept... 
        # 我们假设前两个逗号之间的是名字，或者第一个逗号前是姓，但这很难拆。
        # 这里我们主要依靠 'Author full names' 列来获取名字，这里只用作辅助匹配。
        # 简单处理：取第一个逗号前的内容作为 key 之一，但更可靠的是使用 Author full names 列的顺序。
        pass
    return auth_entry.split(',')[0] # 仅供参考

def process_row(row):
    """
    处理单行数据，返回处理后的字典
    """
    # 1. 准备机构主表
    aff_str = row.get('Affiliations', '')
    aff_dict, master_aff_list = parse_affiliations_to_dict(aff_str)
    
    # 2. 准备作者列表（全名）
    full_names_str = row.get('Author full names', '')
    if pd.isna(full_names_str):
        full_names = []
    else:
        full_names = [clean_name_keep_full(x) for x in str(full_names_str).split(';')]
    
    # 3. 准备带有机构信息的作者字串，用于匹配序号
    auth_with_aff_str = row.get('Authors with affiliations', '')
    if pd.isna(auth_with_aff_str):
        auth_entries = []
    else:
        # Scopus 用分号分隔不同作者
        auth_entries = str(auth_with_aff_str).split(';')
    
    # 结果容器
    formatted_authors = [] # 存放 "Name(1,2)"
    first_author_affs = "" 
    corr_author_affs = ""
    
    # 4. 遍历作者并匹配
    # 我们假设 full_names 和 auth_entries 的顺序是一致的（通常是）
    
    # 建立一个临时映射：姓名 -> [序号列表]
    author_index_map = {} 
    
    for i in range(len(full_names)):
        name = full_names[i]
        
        # 尝试从 auth_entries 找到对应的条目
        # 如果 auth_entries 数量和 full_names 一样，直接对应
        indices = []
        if i < len(auth_entries):
            entry = auth_entries[i]
            indices = match_author_affiliations(entry, aff_dict, master_aff_list)
        
        # 保存映射供后面查找通讯作者用
        author_index_map[name] = indices
        
        # 格式化: Name(1,2)
        if indices:
            indices_str = ",".join(map(str, indices))
            formatted_authors.append(f"{name}({indices_str})")
        else:
            # 如果没有匹配到机构，就不加括号
            formatted_authors.append(name)
            
    # 5. 生成最终的“作者”列
    authors_column = ";".join(formatted_authors)
    
    # 6. 生成“第一作者单位”
    # 第一作者即 full_names[0]
    if len(full_names) > 0:
        first_indices = author_index_map.get(full_names[0], [])
        # 获取对应的机构文本
        first_aff_texts = [aff for aff, idx in aff_dict.items() if idx in first_indices]
        first_author_affs = "; ".join(first_aff_texts)
        
    # 7. 生成“通讯作者单位”
    # 从 Correspondence Address 提取名字
    corr_str = row.get('Correspondence Address', '')
    corr_name = ""
    if not pd.isna(corr_str):
        # 格式通常是 "Lee, M.-L.; Dept..."
        # 取第一个分号前的作为名字
        possible_name_part = str(corr_str).split(';')[0].strip()
        
        # 这是一个缩写名 (Lee, M.-L.)，我们需要在 full_names (Lee, Meng-Lin) 中找到它
        # 进行简单的模糊匹配
        best_match = None
        
        # 1. 尝试完全匹配
        if possible_name_part in author_index_map:
            best_match = possible_name_part
        else:
            # 2. 尝试匹配姓 (Last name)
            # 假设格式是 "Last, First"
            last_name = possible_name_part.split(',')[0].strip()
            for full_n in full_names:
                if full_n.startswith(last_name):
                    best_match = full_n
                    break
        
        if best_match and best_match in author_index_map:
            corr_indices = author_index_map[best_match]
            corr_aff_texts = [aff for aff, idx in aff_dict.items() if idx in corr_indices]
            corr_author_affs = "; ".join(corr_aff_texts)
        else:
            # 如果匹配失败，回退到使用 Correspondence Address 中的地址部分
            # 这里的逻辑是：如果找不到对应的人和机构序号，就直接把通讯地址里的地址部分填进去
            parts = str(corr_str).split(';')
            if len(parts) > 1:
                # 排除 email
                addr_parts = [p.strip() for p in parts[1:] if 'email:' not in p.lower()]
                corr_author_affs = "; ".join(addr_parts)
            else:
                corr_author_affs = str(corr_str)

    # 8. 处理日期
    year = str(row.get('Year', ''))
    # 如果 CSV 里没有具体的 Date 列，我们只能用 Year 拼凑，或者不做修改
    # 用户要求 YYYY-MM-DD
    # 检查是否有 Source 列可能包含日期（Scopus 有时混在 Source 里）
    # 但根据提供的 CSV，只有 Year。
    if year and len(year) == 4:
        date_column = f"{year}{DEFAULT_DATE_SUFFIX}"
    else:
        date_column = year

    return {
        '题名': row.get('Title', ''),
        '其他题名': '',
        '作者': authors_column,
        '第一作者单位': first_author_affs,
        '通讯作者单位': corr_author_affs,
        '发表日期': date_column,
        '发表期刊': row.get('Source title', '')
    }

def main(input_file, output_file):
    try:
        df = pd.read_csv(input_file, sep=None, engine='python')
        # 清洗列名
        df.columns = df.columns.str.strip()
        
        results = []
        for index, row in df.iterrows():
            results.append(process_row(row))
            
        output_df = pd.DataFrame(results)
        
        # 确保列顺序
        target_cols = ['题名', '其他题名', '作者', '第一作者单位', '通讯作者单位', '发表日期', '发表期刊']
        output_df = output_df[target_cols]
        
        output_df.to_excel(output_file, index=False)
        print(f"转换成功！输出文件: {output_file}")
        print(f"处理行数: {len(output_df)}")
        print("注意：由于 Scopus CSV 源文件通常只包含年份(Year)，日期已默认设置为 YYYY-01-01。")
        
    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    input_csv = "samples/scopus-2.csv"
    output_xlsx = "output_pro.xlsx"
    
    if len(sys.argv) > 1: input_csv = sys.argv[1]
    if len(sys.argv) > 2: output_xlsx = sys.argv[2]
    
    main(input_csv, output_xlsx)