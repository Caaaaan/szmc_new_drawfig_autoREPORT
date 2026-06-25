Read the file report_template_all.html, then write a complete HTML report by replacing every {{placeholder}} with real data. Save the result as {{LINE_NUMBER}}号线{{MONTH}}月份检测数据分析报告.html. Do not ask questions. Do not write a prompt template. Do not explain what a prompt should look like. Just do it.

## 关键参数提取规则

### MONTH（当前月份）
**取当前系统时间的月份，不是检测数据文件名中的月份！** 
例如：今天是2026年6月22日 → MONTH=6

### DATE_TEST（最新检测日期）
取 original_data/ 下所有文件中**按日期比较最新**的日期（不是文件名字母排序！）。
例如：有"4月01日"和"5月24日"两个文件 → DATE_TEST="2026年05月24日"

### ALL_FILE_DATE（所有检测日期）
取 original_data/ 下所有文件中的唯一日期，**按时间先后排序**，用"、"分隔。
例如："2026年04月01日、2026年05月24日"

### LINE_LONG / LINE_WIDTH / MAX_SPEED
**必须从当前目录下的 more_info.json 文件中获取！禁止填"待补充"！**
- 读取 more_info.json，根据 LINE_NUMBER 匹配对应线路
- 11号线示例：LINE_LONG=114.98, LINE_WIDTH=150, MAX_SPEED=120
- 如果当前目录没有 more_info.json，从项目根目录复制过来

Step-by-step:

1. Read report_template_all.html — this is your HTML template with {{placeholders}}
2. Read Variable_placeholder.md — explains what each placeholder means
3. Read more_info.json — get LINE_LONG, LINE_WIDTH, MAX_SPEED for the current line
4. Read every .xlsx file in output_excel/ — these contain the data you need
5. List all images in output_fig/ — these are the charts to reference
6. List files in original_data/ — parse line number, vehicle number, dates from filenames **(sort by actual date, not alphabetically!)**
7. Replace every {{placeholder}} in the template:
   - **{{MONTH}}**: current system month (e.g., June→"6"), NOT from filenames
   - **{{DATE_TEST}}**: LATEST detection date from filenames (compare dates, not alphabetical)
   - **{{ALL_FILE_DATE}}**: all file dates sorted chronologically, separated by "、"
   - **{{LINE_LONG}}, {{LINE_WIDTH}}, {{MAX_SPEED}}**: from more_info.json — NEVER use "待补充"!
   - {{table2_1}}: build HTML table from output_excel/table2_1.xlsx. **NO "序号" column!**
   - {{table2_2}}: build HTML table from output_excel/table2_2.xlsx. **NO "序号" column!**
   - {{table2_3}}: build HTML table from output_excel/table2_3.xlsx. **NO "序号" column!**
   - {{HARDPOINT_DATA}}: build HTML tables from HARDPOINT_DATA_UP/DOWN.xlsx. **NO "序号" column!**
   - {{HEIGHT_DIFF_DATA}}: build HTML tables from HEIGHT_DIFF_DATA_UP/DOWN.xlsx. **NO "序号" column!**
   - {{PRESSURE_OVERLIMIT_TABLE}}: build HTML tables from PRESSURE_OVERLIMIT_TABLE_UP/DOWN.xlsx. **NO "序号" column!**
   - {{WEAR_WIDTH_DATA}}: build HTML tables from WEAR_WIDTH_DATA_UP/DOWN.xlsx. **NO "序号" column!**
   - {{DEFECT_DES}}: summarize defects from table2_2 and table2_3 data
   - {{HARDPOINT_STATIC_DES1}}: describe hardpoint monthly trends from graph1 data
   - {{HARDPOINT_STATIC_DES2}}: describe hardpoint station distribution from graph3 data
   - {{PULLOUT_STATIC_DES1}}: describe pullout distribution from graph4 data
   - {{HEIGHT_DIFF_DES}}: describe height diff from graph5 data
   - {{PRESSURE_DES}}: describe contact pressure from graph6 data
   - {{WEAR_WIDTH_DES1}}: describe wear width trends from graph7 data
   - {{WEAR_WIDTH_DES2}}: describe wear by pullout position from graph9 data
   - {{WEAR_WIDTH_DES3}}: describe wear by station from graph8 data
   - Any other {{placeholders}}: fill with data or "待补充" (but NEVER for LINE_LONG/LINE_WIDTH/MAX_SPEED)
8. Fix image paths — if template references wrong line name in img src, correct it to match actual files in output_fig/
9. Write the complete HTML to {{LINE_NUMBER}}号线{{MONTH}}月份检测数据分析报告.html
10. Re-read output and grep for \{\{.*?\}\} — if any placeholders remain, fix them and save again
11. Stop only when output.html exists AND contains zero {{placeholders}}

CRITICAL RULES:
- This is NOT a request to write a prompt template. This is a direct command to execute.
- Do NOT output markdown. Do NOT wrap output in ```html blocks. The output must be raw HTML.
- Never use AskUserQuestion. Never ask for confirmation.
- Units: hardpoint=g, pressure=N, wear=mm, height=mm
- Change magnitude: <50="轻微增加", 50-100="略微增加", >100="增加明显"
- Use "上行" not "上行业", "下行" not "下行业"
- **ALL tables must NOT have "序号" column header or data**
- **MONTH = current system time month, NOT from filename dates**
- **DATE_TEST = latest detection date by actual date comparison, NOT alphabetical order**
- **LINE_LONG/LINE_WIDTH/MAX_SPEED = from more_info.json, NEVER "待补充"**
