"""
根据输入的 Excel 原始数据，生成 4 个 top-10 统计 Excel 表格。

输入：original_data 目录下的任意一个 Excel 文件路径
输出：output_excel/ 目录下生成 4 个 Excel 文件，文件名自动识别上行/下行。
"""

import os
import re
import sys
import pandas as pd


def detect_direction(df: pd.DataFrame, filepath: str, known_direction: str = None) -> str:
    """检测上行/下行。
    优先使用显式传入的 known_direction；否则回退到 '行别' 列检测。
    （已移除文件名检测——方向由子目录结构提供。）
    """
    if known_direction is not None:
        return known_direction
    # 回退：从 '行别' 列检测
    if "行别" in df.columns:
        vals = df["行别"].dropna().unique()
        if len(vals) > 0:
            v = str(vals[0])
            if "上" in v:
                return "UP"
            if "下" in v:
                return "DOWN"
    return "UP"


def export_hardpoint_data(df: pd.DataFrame, output_dir: str, direction: str):
    """
    Excel1: 按 硬点2(g) 降序，取前10，杆号互不相同。
    列：站区、公里标、杆号、硬点1(g)、硬点2(g)
    """
    col_map = {
        "硬点1(m/s²)": "硬点1(m/s²)",
        "硬点2(m/s²)": "硬点2(m/s²)",
        "站区": "站区",
        "公里标": "公里标",
        "杆号": "杆号",
    }
    for c in col_map:
        if c not in df.columns:
            print(f"  警告: 缺少列 '{c}'，跳过 HARDPOINT_DATA")
            return

    df_work = df.dropna(subset=["硬点2(m/s²)"]).copy()
    df_work = df_work.sort_values("硬点2(m/s²)", ascending=False)
    df_work = df_work.drop_duplicates(subset=["杆号"])
    df_work = df_work.head(10)

    # 将硬点1和硬点2从 m/s² 转换为 g
    df_work["硬点1(g)"] = df_work["硬点1(m/s²)"] / 9.8
    df_work["硬点2(g)"] = df_work["硬点2(m/s²)"] / 9.8

    keep_cols = ["站区", "公里标", "杆号", "硬点1(g)", "硬点2(g)"]
    result = df_work[keep_cols].reset_index(drop=True)

    fname = f"HARDPOINT_DATA_{direction}.xlsx"
    outpath = os.path.join(output_dir, fname)
    result.to_excel(outpath, index=False)
    print(f"  已生成: {fname} ({len(result)} 行)")


def _parse_range(pattern: str) -> list:
    """解析范围模式如 'LC25-29~19'，返回所有杆号子串列表。"""
    left, right = pattern.split("~")
    last_dash = left.rfind("-")
    prefix = left[:last_dash + 1]
    start_num = int(left[last_dash + 1:])
    end_num = int(right)
    start_str = left[last_dash + 1:]
    width = len(start_str)

    step = 1 if start_num <= end_num else -1
    result = []
    for i in range(start_num, end_num + step, step):
        result.append(f"{prefix}{i:0{width}d}")
    return result


def _build_exclusion_set(direction: str) -> set:
    """构建 Excel2 中需要排除的杆号子串集合。"""
    if direction == "UP":
        ranges = ["LC25-29~19", "LC13-02~10", "LC11-01~13", "LC01-01~10"]
        singles = ["LC004", "LC110", "LC001"]
    else:
        ranges = ["RC02-01~10", "RC12-05~13", "RC14-01~10", "RC26-24~30"]
        singles = ["RC004"]

    excluded = set(singles)
    for r in ranges:
        excluded.update(_parse_range(r))
    return excluded


def export_height_diff_data(df: pd.DataFrame, output_dir: str, direction: str, filepath: str = ""):
    """
    Excel2: 按 站区+杆号 分组，取组内 导高(mm) 最大/最小值，高差=最大-最小。
        按高差降序，取前10，杆号互不相同。
    列：站区、公里标、杆号、最大导高、最小导高、高差
    杆号过滤仅当输入文件为"11号线"时生效。
    """
    if "导高(mm)" not in df.columns:
        print("  警告: 缺少列 '导高(mm)'，跳过 HEIGHT_DIFF_DATA")
        return

    df_work = df.dropna(subset=["导高(mm)"]).copy()

    # 11号线/5号线仅统计导高 < 4400mm 的数据点
    if "11号线" in filepath or "5号线" in filepath:
        df_work = df_work[df_work["导高(mm)"] < 4400]

    grouped = df_work.groupby(["站区", "杆号"], as_index=False).agg(
        公里标=("公里标", "first"),
        最大导高=("导高(mm)", "max"),
        最小导高=("导高(mm)", "min"),
    )
    grouped["高差"] = grouped["最大导高"] - grouped["最小导高"]
    grouped = grouped[grouped["高差"] <= 30]
    grouped = grouped.sort_values("高差", ascending=False)
    grouped = grouped.drop_duplicates(subset=["杆号"])

    # 杆号过滤仅对11号线生效
    if "11号线" in filepath:
        exclusion_set = _build_exclusion_set(direction)
        grouped = grouped[~grouped["杆号"].apply(
            lambda x: any(ex in str(x) for ex in exclusion_set)
        )]

    grouped = grouped.head(10)

    keep_cols = ["站区", "公里标", "杆号", "最大导高", "最小导高", "高差"]
    result = grouped[keep_cols].reset_index(drop=True)

    fname = f"HEIGHT_DIFF_DATA_{direction}.xlsx"
    outpath = os.path.join(output_dir, fname)
    result.to_excel(outpath, index=False)
    print(f"  已生成: {fname} ({len(result)} 行)")


def export_pressure_overlimit_table(df: pd.DataFrame, output_dir: str, direction: str):
    """
    Excel3: 按 压力和(N) 降序，取前10，杆号互不相同。
    列：站区、公里标、杆号、压力
    """
    pressure_col = None
    for candidate in ['压力和(N)', '压力和']:
        if candidate in df.columns:
            pressure_col = candidate
            break
    if pressure_col is None:
        print("  警告: 缺少压力列，跳过 PRESSURE_OVERLIMIT_TABLE")
        return

    df_work = df.dropna(subset=[pressure_col]).copy()
    df_work = df_work.sort_values(pressure_col, ascending=False)
    df_work = df_work[df_work[pressure_col] >= 130]
    df_work = df_work.drop_duplicates(subset=["杆号"])
    df_work = df_work.head(10)

    result = df_work[["站区", "公里标", "杆号", pressure_col]].reset_index(drop=True)
    result = result.rename(columns={pressure_col: "压力"})

    fname = f"PRESSURE_OVERLIMIT_TABLE_{direction}.xlsx"
    outpath = os.path.join(output_dir, fname)
    result.to_excel(outpath, index=False)
    print(f"  已生成: {fname} ({len(result)} 行)")


def export_wear_width_data(df: pd.DataFrame, output_dir: str, direction: str, filepath: str = ""):
    """
    Excel4: 按 磨耗宽度(mm) 降序，取前10，杆号互不相同。
    列：站区、公里标、杆号、磨耗宽度
    导高超过4400mm的不参与筛选，对11号线/5号线生效。
    """
    if "磨耗宽度(mm)" not in df.columns:
        print("  警告: 缺少列 '磨耗宽度(mm)'，跳过 WEAR_WIDTH_DATA")
        return

    df_work = df.dropna(subset=["磨耗宽度(mm)"]).copy()

    # 导高过滤：导高>=4400mm的不参与筛选，对11号线/5号线生效
    if ("11号线" in filepath or "5号线" in filepath) and "导高(mm)" in df_work.columns:
        before = len(df_work)
        df_work = df_work[df_work["导高(mm)"] < 4400]
        print(f"  Excel4 导高过滤: 排除 {before - len(df_work)} 行（导高>=4400mm）")

    df_work = df_work.sort_values("磨耗宽度(mm)", ascending=False)
    df_work = df_work.drop_duplicates(subset=["杆号"])
    df_work = df_work.head(10)

    keep_cols = ["站区", "公里标", "杆号", "磨耗宽度(mm)"]
    result = df_work[keep_cols].reset_index(drop=True)

    fname = f"WEAR_WIDTH_DATA_{direction}.xlsx"
    outpath = os.path.join(output_dir, fname)
    result.to_excel(outpath, index=False)
    print(f"  已生成: {fname} ({len(result)} 行)")


def process_excel(filepath: str, output_dir: str = "output_excel", direction: str = None):
    """主处理函数：读取 Excel，生成 4 个 top-10 表格。
    direction: "UP" or "DOWN"，若为 None 则回退检测。
    """
    if not os.path.exists(filepath):
        print(f"错误: 文件不存在 - {filepath}")
        return

    print(f"读取文件: {filepath}")
    df = pd.read_excel(filepath)
    before = len(df)
    df = df.dropna(subset=['站区'])
    if len(df) < before:
        print(f"  已过滤 {before - len(df)} 行无效数据（站区为空）")
    print(f"  数据量: {len(df)} 行, {len(df.columns)} 列")

    direction = detect_direction(df, filepath, known_direction=direction)
    print(f"  识别行别: {'上行' if direction == 'UP' else '下行'}")

    os.makedirs(output_dir, exist_ok=True)

    print("\n生成 top-10 表格...")
    export_hardpoint_data(df, output_dir, direction)
    export_height_diff_data(df, output_dir, direction, filepath)
    export_pressure_overlimit_table(df, output_dir, direction)
    export_wear_width_data(df, output_dir, direction, filepath)

    print(f"\n全部完成，输出目录: {output_dir}/")


def _parse_date_from_filename(fname: str) -> str:
    """从文件名中提取日期字符串 YYYY年MM月DD日"""
    m = re.search(r"(\d{4}年\d{2}月\d{2}日)", fname)
    return m.group(1) if m else ""


def _find_latest_files(data_dir: str) -> tuple:
    """找到 data_dir 下最新日期的文件路径列表及方向映射。
    优先扫描 上行/下行 子目录；子目录不存在时回退到 flat 目录（兼容旧任务）。

    Returns: (filepaths, date_str, direction_map)
        filepaths: list of absolute paths
        date_str: 'YYYY年MM月DD日'
        direction_map: dict mapping filepath -> "UP" or "DOWN"
    """
    up_dir = os.path.join(data_dir, "上行")
    down_dir = os.path.join(data_dir, "下行")

    if os.path.isdir(up_dir) and os.path.isdir(down_dir):
        # 新模式：子目录编码方向
        scan_plan = [(up_dir, "UP"), (down_dir, "DOWN")]
    else:
        # 回退模式：flat 目录
        scan_plan = [(data_dir, None)]

    all_files = []
    direction_map = {}
    for scan_dir, known_dir in scan_plan:
        if not os.path.isdir(scan_dir):
            continue
        for f in sorted(os.listdir(scan_dir)):
            if not f.endswith(".xlsx"):
                continue
            d = _parse_date_from_filename(f)
            if d:
                fp = os.path.join(scan_dir, f)
                all_files.append((d, fp))
                if known_dir is not None:
                    direction_map[fp] = known_dir
                else:
                    # 回退：从文件名推断
                    direction_map[fp] = "UP" if "上行" in f else ("DOWN" if "下行" in f else "UP")

    if not all_files:
        raise FileNotFoundError(f"在 {data_dir} 中未找到 Excel 文件")

    # 按日期分组，取最新
    dated = {}
    for d, fp in all_files:
        dated.setdefault(d, []).append(fp)

    latest_date = max(dated.keys())
    latest_files = dated[latest_date]
    print(f"最新数据日期: {latest_date}，文件: {[os.path.basename(f) for f in latest_files]}")
    return latest_files, latest_date, direction_map


def _scan_files_with_direction(data_dir: str) -> list:
    """扫描 data_dir 下所有 Excel 文件，返回 (filepath, direction) 列表。
    优先扫描 上行/下行 子目录；子目录不存在时回退到 flat 目录。
    """
    up_dir = os.path.join(data_dir, "上行")
    down_dir = os.path.join(data_dir, "下行")

    if os.path.isdir(up_dir) and os.path.isdir(down_dir):
        scan_plan = [(up_dir, "UP"), (down_dir, "DOWN")]
    else:
        scan_plan = [(data_dir, None)]

    result = []
    for scan_dir, known_dir in scan_plan:
        if not os.path.isdir(scan_dir):
            continue
        for fname in sorted(os.listdir(scan_dir)):
            if fname.endswith(".xlsx"):
                if known_dir is not None:
                    direction = known_dir
                else:
                    # 回退：从文件名推断
                    direction = "UP" if "上行" in fname else ("DOWN" if "下行" in fname else "UP")
                result.append((os.path.join(scan_dir, fname), direction))
    return result


def run_latest_files(data_dir: str, output_dir: str = "output_excel"):
    """供 Web 服务调用：处理 data_dir 中最新日期的所有文件。"""
    filepaths, date_str, direction_map = _find_latest_files(data_dir)
    for fp in filepaths:
        process_excel(fp, output_dir, direction=direction_map.get(fp))


def run(data_dir: str, output_dir: str = "output_excel"):
    """供 Web 服务调用：处理 data_dir 中所有 Excel 文件。"""
    if not os.path.isdir(data_dir):
        print(f"错误: 数据目录 '{data_dir}' 不存在")
        return

    files_with_dir = _scan_files_with_direction(data_dir)
    if not files_with_dir:
        print(f"警告: {data_dir} 中未找到 Excel 文件")
        return

    for fp, direction in files_with_dir:
        process_excel(fp, output_dir, direction=direction)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python export_top10_tables.py <excel文件路径>")
        print("示例: python export_top10_tables.py original_data/全线路原始数据_深圳地铁5号线_SZDTW102_上行_2026年04月18日 00时06分.xlsx")
        sys.exit(1)

    process_excel(sys.argv[1])
