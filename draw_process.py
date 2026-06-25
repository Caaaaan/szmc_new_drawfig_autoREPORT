import matplotlib
matplotlib.use('Agg')  # 非交互式后端，线程安全，必须在 import pyplot 之前设置

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import os
import json
from typing import Dict, List, Tuple, Optional
import numpy as np
import re

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 常量定义
# ============================================================
HARDPOINT_THRESHOLD = 7 * 10  # 硬点阈值，单位：m/s² (7g, g=10m/s²)
PRESSURE_HIGH_THRESHOLD = 130  # 接触压力上限阈值，单位：N
PRESSURE_LOW_THRESHOLD = 100  # 接触压力下限阈值，单位：N
PRESSURE_MIN_VALID = 10  # 接触压力最低有效值，<=此值视为接触异常，不纳入统计
WEAR_WIDTH_THRESHOLD = 8  # 磨耗宽度阈值，单位：mm
HEIGHT_MAX_THRESHOLD = 4400  # 导高上限阈值，单位：mm（11号线/5号线导高>=4400mm不纳入统计）

# 导高差值区间定义（前开后闭）
HEIGHT_DIFF_BINS = [0, 4, 6, 8, 10, 12, 15, 101]
HEIGHT_DIFF_LABELS = ['0-4', '4-6', '6-8', '8-10', '10-12', '12-15', '15-100']

# 磨耗宽度区间定义（前开后闭）
WEAR_WIDTH_BINS = [8, 10, 12, 14, float('inf')]
WEAR_WIDTH_LABELS = ['8-10mm', '10-12mm', '12-14mm', '>14mm']

# 拉出值区间定义
PULLOUT_RANGE_START = -250
PULLOUT_RANGE_END = 250
PULLOUT_BIN_WIDTH = 10

PULLOUT_BIN_EDGES = list(range(PULLOUT_RANGE_START, PULLOUT_RANGE_END + 1, PULLOUT_BIN_WIDTH))
PULLOUT_BIN_LABELS = [f'{PULLOUT_BIN_EDGES[i]}-{PULLOUT_BIN_EDGES[i + 1]}'
                      for i in range(len(PULLOUT_BIN_EDGES) - 1)]
PULLOUT_BIN_LABELS = ['小于-250'] + PULLOUT_BIN_LABELS + ['大于250']
PULLOUT_BINS = [-float('inf')] + PULLOUT_BIN_EDGES + [float('inf')]

STATION_JSON_PATH = "./station.json"


# ============================================================
# 站区顺序数据加载
# ============================================================
def load_station_data(json_path: str = "station.json") -> Dict[str, List[str]]:
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            station_data = json.load(f)
        return station_data
    except FileNotFoundError:
        print(f"警告: 未找到站区顺序文件 {json_path}，将使用空字典")
        return {}
    except json.JSONDecodeError as e:
        print(f"警告: 站区顺序文件 {json_path} JSON解析错误: {e}，将使用空字典")
        return {}


STATION_DATA = load_station_data(STATION_JSON_PATH)


def get_station_order(line_name: str, line_type: str) -> Optional[List[str]]:
    key = f"{line_name}-{line_type}"
    if key in STATION_DATA:
        return STATION_DATA[key]
    # 尝试模糊匹配：数据中的线名可能包含 station.json 中线名的前缀
    for skey in STATION_DATA:
        if skey.startswith(line_name + '-') or line_name.startswith(skey.split('-')[0]):
            if skey.endswith('-' + line_type):
                print(f"模糊匹配: 数据线名'{line_name}' -> station.json键'{skey}'")
                return STATION_DATA[skey]
    print(f"警告: 未找到线名'{line_name}'行别'{line_type}'的站区顺序数据")
    return None


# ============================================================
# 辅助函数
# ============================================================
def _extract_month_label(filename: str) -> str:
    """从文件名中提取月份标签，如 '2026年03月'"""
    match = re.search(r'(\d{4}年\d{1,2}月)', filename)
    if match:
        return match.group(1)
    return filename[:20]


def _get_month_color_map(file_info_list: List[Dict]) -> Dict[str, str]:
    """为每个唯一月份分配颜色"""
    months = []
    for fi in file_info_list:
        month = _extract_month_label(fi['filename'])
        if month not in months:
            months.append(month)
    cmap = plt.cm.tab20(np.linspace(0, 0.7, max(len(months), 1)))
    return {month: cmap[i] for i, month in enumerate(months)}


def _get_bar_positions(n_categories: int, n_groups: int, group_idx: int,
                       total_width: float = 0.8):
    """计算分组柱状图的 x 位置"""
    single_width = total_width / n_groups
    offset = (group_idx - n_groups / 2 + 0.5) * single_width
    return np.arange(n_categories) + offset, single_width


def _ensure_output_dir(path: str):
    """确保输出目录存在"""
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d)


def _build_full_station_list(file_info_list: List[Dict], ordered_stations: List[str]) -> List[str]:
    """构建完整站区列表：ordered_stations + 数据中额外出现的站区"""
    extra = set()
    for fi in file_info_list:
        df = fi['df']
        if '站区' in df.columns:
            for s in df['站区'].unique():
                if s not in ordered_stations and isinstance(s, str):
                    extra.add(s)
    return ordered_stations + sorted(extra)


def _build_station_series(counts: pd.Series, full_stations: List[str]) -> pd.Series:
    """将站区计数映射到完整站区列表上，缺失的填0"""
    result = pd.Series(0, index=full_stations)
    for st, cnt in counts.items():
        if st in result.index:
            result[st] = cnt
        else:
            result[st] = cnt
    return result


def _get_hardpoint_mask(df: pd.DataFrame) -> pd.Series:
    """返回硬点1或硬点2 > 7g 的布尔掩码"""
    hardpoint_cols = ['硬点1(m/s²)', '硬点2(m/s²)']
    available = [c for c in hardpoint_cols if c in df.columns]
    mask = pd.Series(False, index=df.index)
    for col in available:
        series = pd.to_numeric(df[col], errors='coerce')
        mask = mask | (series > HARDPOINT_THRESHOLD)
    return mask


def _get_pressure_mask(df: pd.DataFrame) -> pd.Series:
    """返回接触压力 > PRESSURE_HIGH_THRESHOLD 或 10N < 压力 < PRESSURE_LOW_THRESHOLD 的布尔掩码"""
    pressure_col = None
    for candidate in ['压力和(N)', '压力和']:
        if candidate in df.columns:
            pressure_col = candidate
            break
    if pressure_col is None:
        return pd.Series(False, index=df.index)
    pressure = pd.to_numeric(df[pressure_col], errors='coerce')
    return (pressure > PRESSURE_HIGH_THRESHOLD) | ((pressure > PRESSURE_MIN_VALID) & (pressure < PRESSURE_LOW_THRESHOLD))


def _get_pullout_bin_counts(series: pd.Series, mask: pd.Series = None) -> pd.Series:
    """按拉出值区间统计数量，可选先应用掩码"""
    if mask is not None:
        series = series[mask]
    cut = pd.cut(series, bins=PULLOUT_BINS, labels=PULLOUT_BIN_LABELS, right=False)
    dist = cut.value_counts().sort_index()
    for label in PULLOUT_BIN_LABELS:
        if label not in dist.index:
            dist[label] = 0
    return dist.sort_index()


# ============================================================
# Graph 1: 硬点月度对比图（上下行在一张图）
# ============================================================
def plot_graph1_hardpoint_monthly_comparison(all_file_infos: List[Dict],
                                              output_path: str) -> None:
    """
    对所有月份硬点值超限数据点数量进行统计，柱状图，上下行对比画在一张图上。

    Parameters
    ----------
    all_file_infos : List[Dict]
        所有文件的 file_info 列表
    output_path : str
        输出图片路径
    """
    if not all_file_infos:
        return

    # 按 (月份, 行别) 统计硬点超限数量
    records = []
    for fi in all_file_infos:
        df = fi['df']
        month = _extract_month_label(fi['filename'])
        direction = fi['line_type']
        mask = _get_hardpoint_mask(df)
        count = mask.sum()
        records.append({'月份': month, '行别': direction, '硬点超限数量': count})

    summary_df = pd.DataFrame(records)

    # 透视：行=月份，列=行别
    pivot = summary_df.pivot_table(values='硬点超限数量', index='月份', columns='行别',
                                   aggfunc='sum', fill_value=0)

    months = list(pivot.index)
    directions = list(pivot.columns)

    if not months or not directions:
        print("警告: graph_1 没有足够的数据")
        return

    # 颜色映射
    dir_colors = {'上行': '#4472C4', '下行': '#ED7D31'}

    fig, ax = plt.subplots(figsize=(10, 6))
    n_months = len(months)
    n_dirs = len(directions)

    for i, d in enumerate(directions):
        vals = [pivot.loc[m, d] if d in pivot.columns else 0 for m in months]
        xpos, width = _get_bar_positions(n_months, n_dirs, i, total_width=0.8)
        color = dir_colors.get(d, plt.cm.tab20(i))
        bars = ax.bar(xpos, vals, width, label=d, color=color, alpha=0.85)
        all_vals = [pivot.loc[m, d2] if d2 in pivot.columns else 0 for d2 in directions for m in months]
        y_max = max(all_vals) if all_vals else 1
        for x, v in zip(xpos, vals):
            if v > 0:
                ax.text(x, v + y_max * 0.02, str(int(v)), ha='center', va='bottom',
                        fontsize=9, weight='bold')

    ax.set_xlabel('月份', fontsize=12)
    ax.set_ylabel(f'硬点>{int(HARDPOINT_THRESHOLD/10)}g的数据点数量', fontsize=12)
    ax.set_title(f'各月份硬点值超限数据点数量对比（上下行）(>{int(HARDPOINT_THRESHOLD/10)}g)', fontsize=14)
    ax.set_xticks(range(n_months))
    ax.set_xticklabels(months, rotation=0)
    ax.legend(title='行别', loc='best', fontsize=10)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.5, which='major', axis='y')
    ax.grid(True, alpha=0.2, which='minor', axis='y', linestyle='--')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.tight_layout()
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 1 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    summary_df.to_excel(excel_path, index=False)
    print(f"Graph 1 Excel 已保存至: {excel_path}")


# ============================================================
# Graph 2: 硬点按拉出值区间 — 柱状图（每行别一张图）
# ============================================================
def plot_graph2_hardpoint_by_pullout(file_info_list: List[Dict],
                                      output_path: str) -> None:
    """
    以拉出值分布区间为横坐标，硬点值超限数据点数量为纵坐标，
    柱状图，不同月份不同颜色。

    Parameters
    ----------
    file_info_list : List[Dict]
        同一线路和行别的文件信息列表
    output_path : str
        输出图片路径
    """
    if not file_info_list:
        return

    line_name = file_info_list[0]['line_name']
    line_type = file_info_list[0]['line_type']
    color_map = _get_month_color_map(file_info_list)
    month_labels = sorted(color_map.keys())
    n_months = len(month_labels)

    # 为每个文件统计拉出值区间硬点超限数量
    data_by_month = {}
    for fi in file_info_list:
        month = _extract_month_label(fi['filename'])
        df = fi['df']
        pullout_col = '拉出值(mm)'
        if pullout_col not in df.columns:
            continue
        pullout = pd.to_numeric(df[pullout_col], errors='coerce')
        mask = _get_hardpoint_mask(df)
        dist = _get_pullout_bin_counts(pullout, mask)
        data_by_month[month] = dist

    if not data_by_month:
        print("警告: graph_2 没有有效数据")
        return

    bin_labels = PULLOUT_BIN_LABELS
    n_bins = len(bin_labels)

    fig, ax = plt.subplots(figsize=(18, 7))

    for i, month in enumerate(month_labels):
        if month not in data_by_month:
            continue
        vals = [data_by_month[month].get(lbl, 0) for lbl in bin_labels]
        xpos, width = _get_bar_positions(n_bins, n_months, i, total_width=0.9)
        bars = ax.bar(xpos, vals, width, label=month, color=color_map[month], alpha=0.85)
        for x, v in zip(xpos, vals):
            if v > 0:
                ax.text(x, v + max(max(vals) if vals else 0, 1) * 0.02, str(int(v)),
                        ha='center', va='bottom', fontsize=7, weight='bold')

    ax.set_xlabel('拉出值区间(mm)', fontsize=12)
    ax.set_ylabel(f'硬点>{int(HARDPOINT_THRESHOLD/10)}g的数据点数量', fontsize=12)
    ax.set_title(f'{line_name} {line_type}\n按拉出值区间统计硬点大于{int(HARDPOINT_THRESHOLD/10)}g的数据点数量', fontsize=14)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(bin_labels, rotation=45, ha='right', fontsize=8)
    ax.legend(title='月份', loc='best', fontsize=9)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.5, which='major', axis='y')
    ax.grid(True, alpha=0.2, which='minor', axis='y', linestyle='--')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.tight_layout()
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 2 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    excel_data = pd.DataFrame(data_by_month).T
    excel_data.columns = bin_labels
    excel_data.to_excel(excel_path, index=True)
    print(f"Graph 2 Excel 已保存至: {excel_path}")


# ============================================================
# Graph 3: 硬点按站区 — 柱状图（每行别一张图）
# ============================================================
def plot_graph3_hardpoint_by_station(file_info_list: List[Dict],
                                      output_path: str) -> None:
    """
    以站区名为横坐标，硬点值超限数据点数量为纵坐标，
    柱状图，不同月份不同颜色。

    Parameters
    ----------
    file_info_list : List[Dict]
        同一线路和行别的文件信息列表
    output_path : str
        输出图片路径
    """
    if not file_info_list:
        return

    line_name = file_info_list[0]['line_name']
    line_type = file_info_list[0]['line_type']

    ordered_stations = get_station_order(line_name, line_type)
    if ordered_stations is None:
        ordered_stations = []

    full_stations = _build_full_station_list(file_info_list, ordered_stations)

    color_map = _get_month_color_map(file_info_list)
    month_labels = sorted(color_map.keys())
    n_months = len(month_labels)

    # 为每个文件统计各站区硬点超限数量
    data_by_month = {}
    for fi in file_info_list:
        month = _extract_month_label(fi['filename'])
        df = fi['df']
        mask = _get_hardpoint_mask(df)
        counts = df.loc[mask, '站区'].value_counts()
        data_by_month[month] = _build_station_series(counts, full_stations)

    if not data_by_month or not full_stations:
        print("警告: graph_3 没有有效数据")
        return

    n_stations = len(full_stations)

    fig, ax = plt.subplots(figsize=(16, 7))

    for i, month in enumerate(month_labels):
        if month not in data_by_month:
            continue
        vals = [data_by_month[month].get(st, 0) for st in full_stations]
        xpos, width = _get_bar_positions(n_stations, n_months, i, total_width=0.9)
        ax.bar(xpos, vals, width, label=month, color=color_map[month], alpha=0.85)
        for x, v in zip(xpos, vals):
            if v > 0:
                ax.text(x, v + max(max(vals) if vals else 0, 1) * 0.02, str(int(v)),
                        ha='center', va='bottom', fontsize=7, weight='bold')

    ax.set_xlabel('站区名', fontsize=12)
    ax.set_ylabel(f'硬点>{int(HARDPOINT_THRESHOLD/10)}g的数据点数量', fontsize=12)
    ax.set_title(f'{line_name} {line_type}\n各站区硬点大于{int(HARDPOINT_THRESHOLD/10)}g的数据点数量统计', fontsize=14)
    ax.set_xticks(range(n_stations))
    ax.set_xticklabels(full_stations, rotation=45, ha='right', fontsize=8)
    ax.legend(title='月份', loc='best', fontsize=9)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.5, which='major', axis='y')
    ax.grid(True, alpha=0.2, which='minor', axis='y', linestyle='--')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.tight_layout()
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 3 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    excel_data = pd.DataFrame(data_by_month).T
    excel_data.columns = full_stations
    excel_data.to_excel(excel_path, index=True)
    print(f"Graph 3 Excel 已保存至: {excel_path}")


# ============================================================
# Graph 4: 拉出值分布统计
# ============================================================
def plot_graph4_pullout_distribution(file_info_list: List[Dict],
                                      output_path: str) -> None:
    """
    对拉出值分布进行统计，按区间统计落在各区间的数量。

    Parameters
    ----------
    file_info_list : List[Dict]
        同一线路和行别的文件信息列表
    output_path : str
        输出图片路径
    """
    if not file_info_list:
        return

    line_name = file_info_list[0]['line_name']
    line_type = file_info_list[0]['line_type']
    color_map = _get_month_color_map(file_info_list)
    month_labels = sorted(color_map.keys())

    bin_labels = PULLOUT_BIN_LABELS
    n_bins = len(bin_labels)

    data_by_month = {}
    for fi in file_info_list:
        month = _extract_month_label(fi['filename'])
        df = fi['df']
        pullout_col = '拉出值(mm)'
        if pullout_col not in df.columns:
            continue
        pullout = pd.to_numeric(df[pullout_col], errors='coerce')
        dist = _get_pullout_bin_counts(pullout)
        data_by_month[month] = dist

    if not data_by_month:
        print("警告: graph_4 没有有效数据")
        return

    fig, ax = plt.subplots(figsize=(16, 7))

    for month in month_labels:
        if month not in data_by_month:
            continue
        vals = [data_by_month[month].get(lbl, 0) for lbl in bin_labels]
        ax.plot(range(n_bins), vals, marker='o', linewidth=2, markersize=5,
                color=color_map[month], alpha=0.8, label=month)
        for x, y in zip(range(n_bins), vals):
            if y > 0:
                ax.text(x, y + max(vals) * 0.01, str(int(y)), ha='center', va='bottom',
                        fontsize=7, color=color_map[month], weight='bold')

    ax.set_xlabel('拉出值区间(mm)', fontsize=12)
    ax.set_ylabel('数据点数量', fontsize=12)
    ax.set_title(f'{line_name} {line_type}\n拉出值分布统计', fontsize=14)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(bin_labels, rotation=45, ha='right', fontsize=8)
    ax.legend(title='月份', loc='best', fontsize=9)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.5, which='major')
    ax.grid(True, alpha=0.2, which='minor', linestyle='--')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.tight_layout()
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 4 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    excel_data = pd.DataFrame(data_by_month).T
    excel_data.columns = bin_labels
    excel_data.to_excel(excel_path, index=True)
    print(f"Graph 4 Excel 已保存至: {excel_path}")


# ============================================================
# Graph 5: 导高坡度变化 — 饼状图
# ============================================================
def plot_graph5_height_diff_pie(file_info_list: List[Dict],
                                 output_path: str) -> None:
    """
    按"站区+杆号"分组，计算导高最大值-最小值，落入差值区间，
    饼状图显示各区间比例和个数。仅使用最新月份的数据。

    Parameters
    ----------
    file_info_list : List[Dict]
        同一线路和行别的文件信息列表
    output_path : str
        输出图片路径
    """
    if not file_info_list:
        return

    line_name = file_info_list[0]['line_name']
    line_type = file_info_list[0]['line_type']

    # 仅使用最新月份数据
    latest_month = max(_extract_month_label(fi['filename']) for fi in file_info_list)
    latest_fi_list = [fi for fi in file_info_list
                      if _extract_month_label(fi['filename']) == latest_month]

    _is_line_11 = "11号线" in line_name or "5号线" in line_name
    all_diffs = []
    for fi in latest_fi_list:
        df = fi['df']
        height_col = '导高(mm)'
        if height_col not in df.columns:
            continue
        # 11号线/5号线仅统计导高 < 4400mm 的数据点
        if _is_line_11:
            df = df[df[height_col] < HEIGHT_MAX_THRESHOLD]
        # 按"站区+杆号"分组
        grouped = df.groupby(df['站区'].astype(str) + '_' + df['杆号'].astype(str))
        height_range = grouped[height_col].agg(['max', 'min'])
        diffs = height_range['max'] - height_range['min']
        all_diffs.extend(diffs.dropna().tolist())

    if not all_diffs:
        print("警告: graph_5 没有有效数据")
        return

    # 分箱统计
    diff_series = pd.Series(all_diffs)
    binned = pd.cut(diff_series, bins=HEIGHT_DIFF_BINS, labels=HEIGHT_DIFF_LABELS,
                    right=True)
    counts = binned.value_counts().sort_index()
    # 确保所有区间都存在
    for lbl in HEIGHT_DIFF_LABELS:
        if lbl not in counts.index:
            counts[lbl] = 0
    counts = counts.sort_index()

    # 过滤掉数量为0的区间
    non_zero = counts[counts > 0]

    if len(non_zero) == 0:
        print("警告: graph_5 所有区间数量为0")
        return

    fig, ax = plt.subplots(figsize=(12, 7))
    colors = plt.cm.Set3(np.linspace(0, 1, len(non_zero)))

    *_, autotexts = ax.pie(
        non_zero.values,
        labels=None,
        autopct='%1.1f%%',
        startangle=90,
        colors=colors,
        pctdistance=0.6,
        wedgeprops=dict(edgecolor='white', linewidth=2),
    )
    for t in autotexts:
        t.set_fontsize(9)

    total = non_zero.values.sum()
    legend_labels = []
    for lbl, cnt in zip(non_zero.index, non_zero.values):
        pct = cnt / total * 100
        legend_labels.append(f'{lbl}mm     {int(cnt):>5}个    {pct:>5.1f}%')

    from matplotlib.patches import Patch
    legend_handles = [Patch(facecolor=c, edgecolor='gray', linewidth=0.5) for c in colors]

    ax.legend(
        legend_handles, legend_labels,
        title='  导高差值区间      数量      占比',
        loc='center left',
        bbox_to_anchor=(1, 0, 0.5, 1),
        fontsize=10,
        title_fontsize=11,
        labelspacing=0.8,
        handlelength=1.2,
        handleheight=1.0,
        borderpad=0.8,
    )

    ax.set_title(f'{line_name} {line_type}  {latest_month}\n导高差值分布（站区+杆号分组 max-min）', fontsize=14, pad=15)

    plt.tight_layout(rect=[0, 0, 0.72, 1])
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 5 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    excel_data = pd.DataFrame({'区间': counts.index, '数量': counts.values,
                                '占比': counts.values / counts.values.sum()})
    excel_data.to_excel(excel_path, index=False)
    print(f"Graph 5 Excel 已保存至: {excel_path}")


# ============================================================
# Graph 6: 接触压力超限按站区统计 — 折线图（每行别一张图）
# ============================================================
def plot_graph6_pressure_by_station(file_info_list: List[Dict],
                                     output_path: str) -> None:
    """
    按站区统计接触压力超限（高于上限，或介于最低有效值与下限之间）的数据点数量，折线图，不同月份不同颜色。
    <=10N 视为接触异常，不纳入统计。

    Parameters
    ----------
    file_info_list : List[Dict]
        同一线路和行别的文件信息列表
    output_path : str
        输出图片路径
    """
    if not file_info_list:
        return

    line_name = file_info_list[0]['line_name']
    line_type = file_info_list[0]['line_type']

    ordered_stations = get_station_order(line_name, line_type)
    if ordered_stations is None:
        ordered_stations = []

    full_stations = _build_full_station_list(file_info_list, ordered_stations)

    color_map = _get_month_color_map(file_info_list)
    month_labels = sorted(color_map.keys())

    data_by_month = {}
    for fi in file_info_list:
        month = _extract_month_label(fi['filename'])
        df = fi['df']
        mask = _get_pressure_mask(df)
        counts = df.loc[mask, '站区'].value_counts()
        data_by_month[month] = _build_station_series(counts, full_stations)

    if not data_by_month or not full_stations:
        print("警告: graph_6 没有有效数据")
        return

    n_stations = len(full_stations)

    fig, ax = plt.subplots(figsize=(16, 7))

    for month in month_labels:
        if month not in data_by_month:
            continue
        vals = [data_by_month[month].get(st, 0) for st in full_stations]
        ax.plot(range(n_stations), vals, marker='o', linewidth=2, markersize=5,
                color=color_map[month], alpha=0.8, label=month)
        for x, y in zip(range(n_stations), vals):
            if y > 0:
                ax.text(x, y + max(vals) * 0.01 if max(vals) > 0 else 1,
                        str(int(y)), ha='center', va='bottom',
                        fontsize=7, color=color_map[month], weight='bold')

    ax.set_xlabel('站区名', fontsize=12)
    ax.set_ylabel(f'压力>{PRESSURE_HIGH_THRESHOLD}N 或 {PRESSURE_MIN_VALID}N<压力<{PRESSURE_LOW_THRESHOLD}N 的数据点数量', fontsize=12)
    ax.set_title(f'{line_name} {line_type}\n各站区压力>{PRESSURE_HIGH_THRESHOLD}N 或 {PRESSURE_MIN_VALID}N<压力<{PRESSURE_LOW_THRESHOLD}N 的数据点数量统计', fontsize=14)
    ax.set_xticks(range(n_stations))
    ax.set_xticklabels(full_stations, rotation=45, ha='right', fontsize=8)
    ax.legend(title='月份', loc='best', fontsize=9)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.5, which='major')
    ax.grid(True, alpha=0.2, which='minor', linestyle='--')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.tight_layout()
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 6 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    excel_data = pd.DataFrame(data_by_month).T
    excel_data.columns = full_stations
    excel_data.to_excel(excel_path, index=True)
    print(f"Graph 6 Excel 已保存至: {excel_path}")


# ============================================================
# Graph 7: 磨耗宽度分布 — 折线图（每行别一张图）
# ============================================================
def plot_graph7_wear_width_distribution(file_info_list: List[Dict],
                                         output_path: str) -> None:
    """
    磨耗宽度处于 8-10,10-12,12-14,>14mm 四个区间统计，
    折线图，不同月份不同颜色。

    Parameters
    ----------
    file_info_list : List[Dict]
        同一线路和行别的文件信息列表
    output_path : str
        输出图片路径
    """
    if not file_info_list:
        return

    line_name = file_info_list[0]['line_name']
    line_type = file_info_list[0]['line_type']
    color_map = _get_month_color_map(file_info_list)
    month_labels = sorted(color_map.keys())

    wear_col = '磨耗宽度(mm)'
    bin_labels = WEAR_WIDTH_LABELS
    n_bins = len(bin_labels)

    data_by_month = {}
    _is_line_11 = "11号线" in line_name or "5号线" in line_name
    for fi in file_info_list:
        month = _extract_month_label(fi['filename'])
        df = fi['df']
        if wear_col not in df.columns:
            continue
        # 11号线/5号线仅统计导高 < 4400mm 的数据点
        if _is_line_11 and '导高(mm)' in df.columns:
            df = df[df['导高(mm)'] < HEIGHT_MAX_THRESHOLD]
        wear = pd.to_numeric(df[wear_col], errors='coerce')
        # 只统计磨耗宽度 >= 8mm 的
        wear_ge8 = wear[wear >= WEAR_WIDTH_THRESHOLD]
        binned = pd.cut(wear_ge8, bins=WEAR_WIDTH_BINS, labels=bin_labels, right=True)
        dist = binned.value_counts().sort_index()
        for lbl in bin_labels:
            if lbl not in dist.index:
                dist[lbl] = 0
        data_by_month[month] = dist.sort_index()

    if not data_by_month:
        print("警告: graph_7 没有有效数据")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    for month in month_labels:
        if month not in data_by_month:
            continue
        vals = [data_by_month[month].get(lbl, 0) for lbl in bin_labels]
        ax.plot(range(n_bins), vals, marker='o', linewidth=2, markersize=6,
                color=color_map[month], alpha=0.8, label=month)
        for x, y in zip(range(n_bins), vals):
            if y > 0:
                ax.text(x, y + max(vals) * 0.02 if max(vals) > 0 else 1,
                        str(int(y)), ha='center', va='bottom',
                        fontsize=9, color=color_map[month], weight='bold')

    ax.set_xlabel('磨耗宽度区间', fontsize=12)
    ax.set_ylabel('数据点数量', fontsize=12)
    ax.set_title(f'{line_name} {line_type}\n磨耗宽度分布统计（>={WEAR_WIDTH_THRESHOLD}mm）', fontsize=14)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(bin_labels, rotation=0)
    ax.legend(title='月份', loc='best', fontsize=9)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.5, which='major')
    ax.grid(True, alpha=0.2, which='minor', linestyle='--')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.tight_layout()
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 7 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    excel_data = pd.DataFrame(data_by_month).T
    excel_data.columns = bin_labels
    excel_data.to_excel(excel_path, index=True)
    print(f"Graph 7 Excel 已保存至: {excel_path}")


# ============================================================
# Graph 8: 磨耗宽度>8mm 按站区统计 — 柱状图（每行别一张图）
# ============================================================
def plot_graph8_wear_width_by_station(file_info_list: List[Dict],
                                       output_path: str) -> None:
    """
    按站区统计磨耗宽度>8mm的数据点数量，柱状图，不同月份不同颜色。

    Parameters
    ----------
    file_info_list : List[Dict]
        同一线路和行别的文件信息列表
    output_path : str
        输出图片路径
    """
    if not file_info_list:
        return

    line_name = file_info_list[0]['line_name']
    line_type = file_info_list[0]['line_type']

    ordered_stations = get_station_order(line_name, line_type)
    if ordered_stations is None:
        ordered_stations = []

    full_stations = _build_full_station_list(file_info_list, ordered_stations)

    color_map = _get_month_color_map(file_info_list)
    month_labels = sorted(color_map.keys())
    n_months = len(month_labels)

    wear_col = '磨耗宽度(mm)'
    _is_line_11 = "11号线" in line_name or "5号线" in line_name
    data_by_month = {}
    for fi in file_info_list:
        month = _extract_month_label(fi['filename'])
        df = fi['df']
        if wear_col not in df.columns:
            continue
        # 11号线/5号线仅统计导高 < 4400mm 的数据点
        if _is_line_11 and '导高(mm)' in df.columns:
            df = df[df['导高(mm)'] < HEIGHT_MAX_THRESHOLD]
        wear = pd.to_numeric(df[wear_col], errors='coerce')
        mask = wear > WEAR_WIDTH_THRESHOLD
        counts = df.loc[mask, '站区'].value_counts()
        data_by_month[month] = _build_station_series(counts, full_stations)

    if not data_by_month or not full_stations:
        print("警告: graph_8 没有有效数据")
        return

    n_stations = len(full_stations)

    fig, ax = plt.subplots(figsize=(16, 7))

    for i, month in enumerate(month_labels):
        if month not in data_by_month:
            continue
        vals = [data_by_month[month].get(st, 0) for st in full_stations]
        xpos, width = _get_bar_positions(n_stations, n_months, i, total_width=0.9)
        ax.bar(xpos, vals, width, label=month, color=color_map[month], alpha=0.85)
        for x, v in zip(xpos, vals):
            if v > 0:
                ax.text(x, v + max(max(vals) if vals else 0, 1) * 0.02, str(int(v)),
                        ha='center', va='bottom', fontsize=7, weight='bold')

    ax.set_xlabel('站区名', fontsize=12)
    ax.set_ylabel(f'磨耗宽度>{WEAR_WIDTH_THRESHOLD}mm的数据点数量', fontsize=12)
    ax.set_title(f'{line_name} {line_type}\n各站区磨耗宽度大于{WEAR_WIDTH_THRESHOLD}mm的数据点数量统计', fontsize=14)
    ax.set_xticks(range(n_stations))
    ax.set_xticklabels(full_stations, rotation=45, ha='right', fontsize=8)
    ax.legend(title='月份', loc='best', fontsize=9)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.5, which='major', axis='y')
    ax.grid(True, alpha=0.2, which='minor', axis='y', linestyle='--')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.tight_layout()
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 8 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    excel_data = pd.DataFrame(data_by_month).T
    excel_data.columns = full_stations
    excel_data.to_excel(excel_path, index=True)
    print(f"Graph 8 Excel 已保存至: {excel_path}")


# ============================================================
# Graph 9: 磨耗宽度>8mm 按拉出值区间 — 柱状图（每行别一张图）
# ============================================================
def plot_graph9_wear_width_by_pullout(file_info_list: List[Dict],
                                       output_path: str) -> None:
    """
    按拉出值区间统计磨耗宽度>8mm的数据点数量，柱状图，不同月份不同颜色。

    Parameters
    ----------
    file_info_list : List[Dict]
        同一线路和行别的文件信息列表
    output_path : str
        输出图片路径
    """
    if not file_info_list:
        return

    line_name = file_info_list[0]['line_name']
    line_type = file_info_list[0]['line_type']
    color_map = _get_month_color_map(file_info_list)
    month_labels = sorted(color_map.keys())
    n_months = len(month_labels)

    wear_col = '磨耗宽度(mm)'
    pullout_col = '拉出值(mm)'
    bin_labels = PULLOUT_BIN_LABELS
    n_bins = len(bin_labels)

    data_by_month = {}
    _is_line_11 = "11号线" in line_name or "5号线" in line_name
    for fi in file_info_list:
        month = _extract_month_label(fi['filename'])
        df = fi['df']
        if wear_col not in df.columns or pullout_col not in df.columns:
            continue
        # 11号线/5号线仅统计导高 < 4400mm 的数据点
        if _is_line_11 and '导高(mm)' in df.columns:
            df = df[df['导高(mm)'] < HEIGHT_MAX_THRESHOLD]
        wear = pd.to_numeric(df[wear_col], errors='coerce')
        pullout = pd.to_numeric(df[pullout_col], errors='coerce')
        mask = wear > WEAR_WIDTH_THRESHOLD
        dist = _get_pullout_bin_counts(pullout, mask)
        data_by_month[month] = dist

    if not data_by_month:
        print("警告: graph_9 没有有效数据")
        return

    fig, ax = plt.subplots(figsize=(18, 7))

    for i, month in enumerate(month_labels):
        if month not in data_by_month:
            continue
        vals = [data_by_month[month].get(lbl, 0) for lbl in bin_labels]
        xpos, width = _get_bar_positions(n_bins, n_months, i, total_width=0.9)
        ax.bar(xpos, vals, width, label=month, color=color_map[month], alpha=0.85)
        for x, v in zip(xpos, vals):
            if v > 0:
                ax.text(x, v + max(max(vals) if vals else 0, 1) * 0.02, str(int(v)),
                        ha='center', va='bottom', fontsize=7, weight='bold')

    ax.set_xlabel('拉出值区间(mm)', fontsize=12)
    ax.set_ylabel(f'磨耗宽度>{WEAR_WIDTH_THRESHOLD}mm的数据点数量', fontsize=12)
    ax.set_title(f'{line_name} {line_type}\n按拉出值区间统计磨耗宽度大于{WEAR_WIDTH_THRESHOLD}mm的数据点数量', fontsize=14)
    ax.set_xticks(range(n_bins))
    ax.set_xticklabels(bin_labels, rotation=45, ha='right', fontsize=8)
    ax.legend(title='月份', loc='best', fontsize=9)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.5, which='major', axis='y')
    ax.grid(True, alpha=0.2, which='minor', axis='y', linestyle='--')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

    plt.tight_layout()
    _ensure_output_dir(output_path)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Graph 9 已保存至: {output_path}")

    # 输出 Excel
    excel_path = output_path.replace('output_fig', 'output_excel').replace('.png', '.xlsx')
    _ensure_output_dir(excel_path)
    excel_data = pd.DataFrame(data_by_month).T
    excel_data.columns = bin_labels
    excel_data.to_excel(excel_path, index=True)
    print(f"Graph 9 Excel 已保存至: {excel_path}")
