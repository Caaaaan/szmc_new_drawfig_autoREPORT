# 描述整个自动化报告的流程
1. 运行main.py
2. 对original_data下最新两个日期的excel文件 运行export_top10_tables.py
   格式：D:\ProgramData\anaconda3\python.exe export_top10_tables.py "original_data\全线路原始数据_深圳地铁7号线_SZDTW102_上行_2026年05月11日 00时45分.xlsx"
3. 运行generate_table2_1.py
4. 运行generate_table2_2_3.py
5. prompt：以report_template_all.html为模板，根据html中占位符位置和图片路径路径位置进行修改，生成一份检测报告。
    1. 占位符解释参考Variable_placeholder.md
    2. 图片路径为output_fig下的图片，生成的报告中使用的图片和模板的graphx（x代表数字）对应
    3. 生成的报告命名为{{LINE_NUMBER}}号线{{MONTH}}月份检测数据分析报告.html
    4. 所有数据表达必须有数据依据，不可随意编造，同时注意**单位统一**
    5. 根据占位符一步步进行修改，先生成模板检测报告，然后慢慢一个个占位符填入，图像路径修改，避免上下文过长导致信息遗忘
    6. 插入的数据，描述，符合html语法规范，使整个模板和谐
    7. 不要生成冗余的字眼，例如“上行”而不是“上行业”
