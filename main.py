"""
主程序：批量读入 original_data 中的 Excel 数据，调用 draw_process 绘图。
"""
import os
import re
import pandas as pd
from draw_process import (
    plot_graph1_hardpoint_monthly_comparison,
    plot_graph2_hardpoint_by_pullout,
    plot_graph3_hardpoint_by_station,
    plot_graph4_pullout_distribution,
    plot_graph5_height_diff_pie,
    plot_graph6_pressure_by_station,
    plot_graph7_wear_width_distribution,
    plot_graph8_wear_width_by_station,
    plot_graph9_wear_width_by_pullout,
    _ensure_output_dir,
)


def parse_filename(filename: str, direction: str = None) -> dict:
    """
    从文件名中解析线名、日期。方向由调用方显式传入（来自子目录名），
    不再从文件名解析。direction=None 时回退到从文件名 parts[3] 解析（兼容旧任务）。

    文件名格式: 全线路原始数据_{线名}_{车号}_{行别}_{日期}.xlsx
    """
    name_no_ext = filename.replace('.xlsx', '')
    parts = name_no_ext.split('_')
    # parts[0] = '全线路原始数据'
    # parts[1] = 线名 (如 '深圳地铁5号线')
    # parts[2] = 车号 (如 'SZDTW102')
    # parts[3] = 行别 (如 '上行' or '下行') — 仅回退模式使用
    # parts[4:] = 日期 (如 '2026年03月16日 00时07分')
    if len(parts) < 5:
        return None
    line_name = parts[1]
    if direction is None:
        direction = parts[3]  # 回退：从文件名解析
    date_str = '_'.join(parts[4:])
    return {
        'line_name': line_name,
        'direction': direction,
        'date_str': date_str,
    }


def load_all_files(data_dir: str = "original_data") -> list:
    """
    加载 original_data 目录下所有 Excel 文件，返回 file_info 列表。
    优先从 上行/下行 子目录加载（方向由子目录名确定）；
    子目录不存在时回退到 flat 目录 + 文件名解析（兼容旧任务）。
    """
    file_infos = []
    if not os.path.isdir(data_dir):
        print(f"错误: 数据目录 '{data_dir}' 不存在")
        return file_infos

    up_dir = os.path.join(data_dir, "上行")
    down_dir = os.path.join(data_dir, "下行")

    if os.path.isdir(up_dir) and os.path.isdir(down_dir):
        # 新模式：子目录编码方向
        scan_plan = [(up_dir, "上行"), (down_dir, "下行")]
    else:
        # 回退模式：flat 目录，方向从文件名解析
        scan_plan = [(data_dir, None)]

    for scan_dir, known_direction in scan_plan:
        if not os.path.isdir(scan_dir):
            continue
        for fname in sorted(os.listdir(scan_dir)):
            if not fname.endswith('.xlsx'):
                continue
            info = parse_filename(fname, direction=known_direction)
            if info is None:
                print(f"警告: 无法解析文件名 '{fname}'，跳过")
                continue

            filepath = os.path.join(scan_dir, fname)
            try:
                df = pd.read_excel(filepath)
            except Exception as e:
                print(f"错误: 读取文件 '{fname}' 失败: {e}")
                continue

            # Drop trailing/padding rows where 站区 is NaN
            before = len(df)
            df = df.dropna(subset=['站区'])
            if len(df) < before:
                print(f"  已过滤 {before - len(df)} 行无效数据（站区为空）")

            file_infos.append({
                'df': df,
                'filename': fname,
                'filepath': filepath,
                'line_name': info['line_name'],
                'line_type': info['direction'],
                'date_str': info['date_str'],
            })
            print(f"已加载: {fname} (线名={info['line_name']}, 行别={info['direction']})")

    return file_infos


def group_by_line_and_direction(file_infos: list) -> dict:
    """按 (线名, 行别) 分组"""
    groups = {}
    for fi in file_infos:
        key = (fi['line_name'], fi['line_type'])
        if key not in groups:
            groups[key] = []
        groups[key].append(fi)
    return groups


def _run_pipeline_inner(data_dir: str, output_fig_dir: str, output_excel_dir: str,
                        line_number: str = ""):
    """内部：执行完整流水线（已确保输出目录存在，data_dir 已验证）。
    line_number: 从 welcome.html 用户交互获得的线路号，如 "11号线"、"5号线"。"""
    all_files = load_all_files(data_dir)
    if not all_files:
        print("错误: 未加载到任何数据文件，程序退出")
        return

    print(f"\n共加载 {len(all_files)} 个数据文件")

    # Graph 1: 月度硬点对比图（所有文件，上下行在同一张图）
    print("\n" + "=" * 60)
    print("生成 Graph 1: 硬点月度对比图")
    print("=" * 60)
    plot_graph1_hardpoint_monthly_comparison(
        all_files,
        os.path.join(output_fig_dir, "graph1_hardpoint_monthly_comparison.png"),
    )

    # 按 (线名, 行别) 分组
    groups = group_by_line_and_direction(all_files)
    print(f"\n共 {len(groups)} 个线路-行别分组")

    for (line_name, line_type), file_list in groups.items():
        print("\n" + "=" * 60)
        print(f"处理分组: {line_name} - {line_type} ({len(file_list)} 个文件)")
        print("=" * 60)

        # 构造安全的文件名前缀
        safe_name = f"{line_name}_{line_type}".replace('/', '_').replace(' ', '_')

        # Graph 2: 硬点按拉出值区间（柱状图）
        print("\n生成 Graph 2: 硬点按拉出值区间")
        plot_graph2_hardpoint_by_pullout(
            file_list,
            os.path.join(output_fig_dir, f"graph2_hardpoint_by_pullout_{safe_name}.png"),
        )

        # Graph 3: 硬点按站区（柱状图）
        print("\n生成 Graph 3: 硬点按站区")
        plot_graph3_hardpoint_by_station(
            file_list,
            os.path.join(output_fig_dir, f"graph3_hardpoint_by_station_{safe_name}.png"),
            line_number=line_number,
        )

        # Graph 4: 拉出值分布
        print("\n生成 Graph 4: 拉出值分布")
        plot_graph4_pullout_distribution(
            file_list,
            os.path.join(output_fig_dir, f"graph4_pullout_distribution_{safe_name}.png"),
        )

        # Graph 5: 导高差值饼状图
        print("\n生成 Graph 5: 导高差值饼状图")
        plot_graph5_height_diff_pie(
            file_list,
            os.path.join(output_fig_dir, f"graph5_height_diff_pie_{safe_name}.png"),
            line_number=line_number,
        )

        # Graph 6: 压力按站区（折线图）
        print("\n生成 Graph 6: 压力按站区")
        plot_graph6_pressure_by_station(
            file_list,
            os.path.join(output_fig_dir, f"graph6_pressure_by_station_{safe_name}.png"),
            line_number=line_number,
        )

        # Graph 7: 磨耗宽度分布（折线图）
        print("\n生成 Graph 7: 磨耗宽度分布")
        plot_graph7_wear_width_distribution(
            file_list,
            os.path.join(output_fig_dir, f"graph7_wear_width_distribution_{safe_name}.png"),
            line_number=line_number,
        )

        # Graph 8: 磨耗宽度按站区（柱状图）
        print("\n生成 Graph 8: 磨耗宽度按站区")
        plot_graph8_wear_width_by_station(
            file_list,
            os.path.join(output_fig_dir, f"graph8_wear_width_by_station_{safe_name}.png"),
            line_number=line_number,
        )

        # Graph 9: 磨耗宽度按拉出值区间（柱状图）
        print("\n生成 Graph 9: 磨耗宽度按拉出值区间")
        plot_graph9_wear_width_by_pullout(
            file_list,
            os.path.join(output_fig_dir, f"graph9_wear_width_by_pullout_{safe_name}.png"),
            line_number=line_number,
        )

    print("\n" + "=" * 60)
    print("所有图形生成完毕！")
    print(f"图片保存在 {output_fig_dir}/ 目录")
    print(f"Excel 统计结果保存在 {output_excel_dir}/ 目录")
    print("=" * 60)


def run_pipeline(data_dir: str = "original_data",
                 output_fig_dir: str = "output_fig",
                 output_excel_dir: str = "output_excel",
                 station_json_path: str = "station.json",
                 line_number: str = ""):
    """流水线入口（供 Web 服务调用，所有路径均已参数化）。
    line_number: 从 welcome.html 用户交互获得的线路号，如 "11号线"。

    与 CLI 模式 main() 的区别：路径可重定向到任意任务目录，
    确保多用户并发时互不干扰。
    """
    import draw_process

    # 更新 draw_process 中的 station.json 路径
    # （所有任务共用同一个 station.json 副本，内容相同，所以并发安全）
    draw_process.STATION_JSON_PATH = station_json_path
    draw_process.STATION_DATA = draw_process.load_station_data(station_json_path)

    # 确保输出目录存在
    for d in [output_fig_dir, output_excel_dir]:
        if not os.path.exists(d):
            os.makedirs(d)

    _run_pipeline_inner(data_dir, output_fig_dir, output_excel_dir, line_number=line_number)


def main():
    _run_pipeline_inner("original_data", "output_fig", "output_excel")


if __name__ == "__main__":
    main()
