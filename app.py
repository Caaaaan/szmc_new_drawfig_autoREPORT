"""
接触网检测数据分析报告 Web 服务
内网多用户访问，上传 Excel + defect_report → 自动生成检测报告
"""
import os
import re
import sys
import uuid
import json
import shutil
import threading
import subprocess
import zipfile
from datetime import datetime
from io import BytesIO

from flask import Flask, request, session, render_template, send_file, jsonify, redirect, url_for

# 将项目根目录加入 sys.path，以便导入各脚本
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import main as pipeline_main
import export_top10_tables
import generate_table2_1
import generate_table2_2_3
import generate_summary_tables

# ============================================================
# 配置
# ============================================================
DATA_ROOT = "E:/catenary_service/tasks"
UPLOAD_ROOT = "E:/catenary_service/uploads"

# 需要从项目根目录复制到每个任务目录的静态文件
COPY_FILES = [
    "report_template_all.html",
    "Variable_placeholder.md",
    "station.json",
    "more_info.json",
    "prompt_report.md",
    "logo.png",
]

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "w102-report-system-default-secret")

# ============================================================
# IP 白名单 — 仅允许列表中的 IP 访问
# ============================================================
ALLOWED_IPS = {
    "127.0.0.1",
    "10.10.17.208",
    "10.10.17.206",
    "10.10.17.207",
    "10.10.17.240",
    # 在此添加更多允许的 IP
}


def get_user_ip() -> str:
    """获取当前请求的用户 IP，用作用户标识。"""
    return request.remote_addr or "unknown"


@app.before_request
def ip_whitelist():
    remote_ip = request.remote_addr
    if not remote_ip or remote_ip not in ALLOWED_IPS:
        app.logger.warning(f"拒绝未授权 IP 访问: {remote_ip}")
        return jsonify({"error": "Access denied: unauthorized IP address"}), 403

# ============================================================
# 任务管理（内存字典）
# ============================================================
tasks: dict = {}  # task_id -> dict(...)
tasks_lock = threading.Lock()

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_INTERMEDIATE = "intermediate"  # Step 1 完成，等待用户确认继续


def set_task(task_id: str, **kwargs):
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id].update(kwargs)
        else:
            tasks[task_id] = kwargs


def get_task(task_id: str):
    with tasks_lock:
        return tasks.get(task_id)


def get_user_tasks(ip: str) -> list:
    """获取某个 IP 的所有任务，按时间倒序。"""
    with tasks_lock:
        user_tasks = [
            {"task_id": tid, **t}
            for tid, t in tasks.items()
            if t.get("ip") == ip
        ]
    user_tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return user_tasks


# ============================================================
# 流水线执行
# ============================================================
# 每步的 progress 值和消息
_STEP_DEFS = [
    (10, "步骤 1/7: 生成图表..."),
    (25, "步骤 2/7: 生成 Top-10 数据表..."),
    (40, "步骤 3/7: 生成几何参数缺陷统计表..."),
    (55, "步骤 4/7: 生成缺陷汇总表..."),
    (65, "步骤 5/7: 生成拉出值/站点汇总统计表..."),
    (80, "步骤 6/7: AI 生成分析报告..."),
    (95, "步骤 7/7: 生成 PDF 报告..."),
]


def run_pipeline(task_id: str, task_dir: str, params: dict, start_step: int = 1):
    """后台线程执行的完整流水线。start_step 用于断点续跑，默认从第1步开始。"""
    try:
        original_data_dir = os.path.join(task_dir, "original_data")
        defect_report_dir = os.path.join(task_dir, "defect_report")
        output_fig_dir = os.path.join(task_dir, "output_fig")
        output_excel_dir = os.path.join(task_dir, "output_excel")
        station_json_path = os.path.join(task_dir, "station.json")

        def step_progress(n: int):
            """设置当前步骤的 progress 和 message。"""
            prog, msg = _STEP_DEFS[n - 1]
            set_task(task_id, progress=prog, message=msg)

        def step_done(n: int):
            """标记第 n 步完成。"""
            set_task(task_id, last_step=n)

        output_filename = _get_report_filename(task_dir, params.get('line_number'))
        output_html = os.path.join(task_dir, output_filename)

        # ---- Step 1: main.py 出图 ----
        if start_step <= 1:
            step_progress(1)
            pipeline_main.run_pipeline(
                data_dir=original_data_dir,
                output_fig_dir=output_fig_dir,
                output_excel_dir=output_excel_dir,
                station_json_path=station_json_path,
                line_number=params.get("line_number", ""),
            )
            step_done(1)

            # 如果是全新任务（非续跑），Step 1 后暂停等待用户确认
            if start_step == 1:
                _set_intermediate_state(task_id, task_dir)
                return

        # ---- Step 2: export_top10_tables ----
        if start_step <= 2:
            step_progress(2)
            export_top10_tables.run_latest_files(
                data_dir=original_data_dir,
                output_dir=output_excel_dir,
                line_number=params.get("line_number", ""),
            )
            step_done(2)

        # ---- Step 3: generate_table2_1 ----
        if start_step <= 3:
            step_progress(3)
            generate_table2_1.run(
                data_dir=original_data_dir,
                output_dir=output_excel_dir,
                line_number=params.get("line_number", ""),
            )
            step_done(3)

        # ---- Step 4: generate_table2_2_3 ----
        if start_step <= 4:
            step_progress(4)
            generate_table2_2_3.run(
                data_dir=defect_report_dir,
                output_dir=output_excel_dir,
            )
            step_done(4)

        # ---- Step 5: generate_summary_tables ----
        if start_step <= 5:
            step_progress(5)
            generate_summary_tables.run(
                data_dir=original_data_dir,
                output_dir=output_excel_dir,
                station_json_path=station_json_path,
                line_number=params.get("line_number", ""),
            )
            step_done(5)

        # ---- Step 6: Claude CLI 生成报告 ----
        if start_step <= 6:
            step_progress(6)
            claude_success = _run_claude(task_dir, output_html, params, params.get("line_number"))

            if not claude_success:
                set_task(task_id, status=STATUS_FAILED, progress=80,
                         message="Claude CLI 调用失败，请点击「续跑」重试",
                         error="Claude CLI returned non-zero exit code")
                return

            step_done(6)

        # ---- Step 7: HTML → PDF ----
        if start_step <= 7:
            step_progress(7)
            output_pdf = output_html.replace(".html", ".pdf")
            pdf_success = _convert_html_to_pdf(output_html, output_pdf)

            if pdf_success:
                set_task(task_id, status=STATUS_DONE, progress=100,
                         message="报告生成完毕！",
                         output_path=output_html,
                         output_pdf_path=output_pdf,
                         last_step=7)
            else:
                # PDF 转换失败不阻塞，HTML 报告仍然可用
                set_task(task_id, status=STATUS_DONE, progress=100,
                         message="报告生成完毕（PDF 转换失败，可下载 HTML）",
                         output_path=output_html,
                         last_step=7)
        else:
            # start_step > 7 表示所有步骤已完成，直接标记完成
            if os.path.exists(output_html) and os.path.getsize(output_html) > 1000:
                output_pdf = output_html.replace(".html", ".pdf")
                pdf_exists = os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 1000
                set_task(task_id, status=STATUS_DONE, progress=100,
                         message="报告生成完毕！",
                         output_path=output_html,
                         output_pdf_path=output_pdf if pdf_exists else None,
                         last_step=7)
            else:
                set_task(task_id, status=STATUS_FAILED, progress=90,
                         message="报告文件丢失，请点击「续跑」重新生成",
                         error="output.html not found")

    except Exception as e:
        set_task(task_id, status=STATUS_FAILED, progress=0,
                 message=f"流水线执行失败: {str(e)}",
                 error=str(e))


def _set_intermediate_state(task_id: str, task_dir: str):
    """Step 1 完成后，收集中间结果并设置 intermediate 状态。"""
    output_fig_dir = os.path.join(task_dir, "output_fig")
    output_excel_dir = os.path.join(task_dir, "output_excel")

    # 收集生成的图表列表
    figures = sorted(
        [f for f in os.listdir(output_fig_dir) if f.endswith(".png")]
    ) if os.path.isdir(output_fig_dir) else []

    # 收集生成的 Excel 列表
    excels = sorted(
        [f for f in os.listdir(output_excel_dir) if f.endswith(".xlsx")]
    ) if os.path.isdir(output_excel_dir) else []

    set_task(task_id,
             status=STATUS_INTERMEDIATE,
             progress=15,
             message="Step 1 完成 — 图表已生成，请确认后继续",
             last_step=1,
             figures=figures,
             excels=excels)


# Claude CLI 的完整路径（Windows npm 全局安装位置）
# 可通过 `where claude` (bash) 或 `npm root -g` 确认
CLAUDE_CLI_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming")),
    "npm", "claude.cmd",
)

# 如果以上路径不存在，则回退到裸命令 "claude"（适用于已加入 PATH 的情况）
CLAUDE_CLI_CMD = CLAUDE_CLI_PATH if os.path.exists(CLAUDE_CLI_PATH) else "claude"


def _build_claude_md(params: dict, output_filename: str, line_number: str = None) -> str:
    """构建 CLAUDE.md 内容（系统级指令，Claude Code 启动时自动加载）。"""
    user_params = ""
    if line_number:
        user_params += f"\n- 线路号 (LINE_NUMBER): {line_number}"
    if params.get("who_you_are"):
        user_params += f"\n- 分析人员姓名 (who_you_are): {params['who_you_are']}"
    if params.get("start_end"):
        user_params += f"\n- 始末区间: {params['start_end']}"
    if params.get("stat_pullout_irregular_count"):
        user_params += f"\n- 拉出值不平顺处数量: {params['stat_pullout_irregular_count']}"
    if params.get("stat_pullout_irregular_dec"):
        user_params += f"\n- 拉出值不平顺变化描述: {params['stat_pullout_irregular_dec']}"

    return f"""# 接触网检测数据分析报告 — 自动生成

你是地铁接触网检测数据分析专家。当前目录下有以下资源，用于生成一份完整的 HTML 检测报告：

- report_template_all.html — HTML 模板，包含 {{占位符}} 待替换
- Variable_placeholder.md — 占位符含义说明
- output_excel/ — 步骤1-5生成的中间数据 Excel
- output_fig/ — 步骤1生成的图表 PNG
- original_data/ — 用户上传的原始数据文件

## 核心规则

1. **唯一交付物是 {output_filename}** — 必须生成此文件才算完成任务
2. **消除所有 {{{{占位符}}}}** — 用正则检查，零残留才能停
3. **禁止交互** — 不用 AskUserQuestion，不等待确认
4. **这是要执行的任务，不是要你写 prompt 模板** — 直接动手做

## 执行步骤

### A. 读取数据源
- 读 report_template_all.html 了解模板和占位符
- 读 Variable_placeholder.md
- 列 output_excel/ 所有文件，逐个读 .xlsx
- 列 output_fig/ 所有图片
- 列 original_data/ 所有文件，从文件名解析：线路号、月份、车号、检测日期

### B. 解析参数
LINE_NUMBER 已由系统提供（见上方用户参数），直接使用。MONTH, Vehicle_NUMBER, DATE_TEST, ALL_FILE_DATE 从 original_data/ 文件名提取。
DATE_TODAY=当前日期，START_END 从 station.json 或下方用户参数获取。
who_you_are 从下方用户参数获取，填入 {{{{who_you_are}}}} 占位符。
{user_params}

### C. 填充表格占位符
- {{{{table2_1}}}} — 读 table2_1.xlsx，生成 HTML table（caption="表 2-1 接触网检测几何参数缺陷分类统计表"）
- {{{{table2_2}}}} — 读 table2_2.xlsx（序号|缺陷等级|确认缺陷数量，最后行合计）
- {{{{table2_3}}}} — 读 table2_3.xlsx（序号|缺陷位置|缺陷描述|缺陷级别|汇总）
- {{{{HARDPOINT_DATA}}}} — 读 HARDPOINT_DATA_UP/DOWN.xlsx，生成表4-1/4-2
- {{{{HEIGHT_DIFF_DATA}}}} — 读 HEIGHT_DIFF_DATA_UP/DOWN.xlsx，生成表4-3/4-4
- {{{{PRESSURE_OVERLIMIT_TABLE}}}} — 读 PRESSURE_OVERLIMIT_TABLE_UP/DOWN.xlsx，生成表4-5/4-6
- {{{{WEAR_WIDTH_DATA}}}} — 读 WEAR_WIDTH_DATA_UP/DOWN.xlsx，生成表4-7/4-8

### D. 填充描述占位符
- {{{{DEFECT_DES}}}} — 汇总 table2_2/2_3："本次任务发现缺陷X处，其中一级X项，二级X项，三级X项，主要集中在XXX，详见表2-2。"
- {{{{HARDPOINT_STATIC_DES1}}}} — 从 graph1 描述各月硬点变化趋势，变化<50轻微/50-100略微/>100明显
- {{{{HARDPOINT_STATIC_DES2}}}} — 从 graph3 描述硬点集中站区top3、上下行最大硬点值及位置
- {{{{PULLOUT_STATIC_DES1}}}} — 从 graph4 描述拉出值分布、碳滑板磨耗风险、各月波动
- {{{{HEIGHT_DIFF_DES}}}} — 从 graph5 描述导高高差>10mm数量/风险、各月>8mm占比变化
- {{{{PRESSURE_DES}}}} — 从 graph6 描述各月接触压力超限变化%、集中站区、最大压力值位置
- {{{{WEAR_WIDTH_DES1}}}} — 从 graph7 描述各月磨耗区间数量变化
- {{{{WEAR_WIDTH_DES2}}}} — 从 graph9 描述不同拉出值位置磨耗分布
- {{{{WEAR_WIDTH_DES3}}}} — 从 graph8 描述不同站区磨耗数量/变化趋势

### E. 修正图片路径 → 保存为 {output_filename} → 用正则检查 → 有残留继续改 → 无残留才完成

## 规范
- 单位：硬点=g, 压力=N, 磨耗=mm, 导高=mm
- "上行业"→"上行"，变化<50"轻微"/50-100"略微"/>100"明显"
- 所有数字从 Excel 来，找不到填"待补充"
"""


def _convert_html_to_pdf(html_path: str, pdf_path: str) -> bool:
    """使用 Playwright (Chromium) 将 HTML 报告转换为 PDF。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[PDF] playwright 未安装，跳过 PDF 转换")
        return False

    try:
        abs_html_path = os.path.abspath(html_path).replace("\\", "/")
        file_url = f"file:///{abs_html_path}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(file_url, wait_until="networkidle", timeout=30000)
            page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"},
            )
            browser.close()

        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
            print(f"[PDF] 生成成功: {pdf_path} ({os.path.getsize(pdf_path)} bytes)")
            return True
        else:
            print("[PDF] PDF 文件生成失败或为空")
            return False

    except Exception as e:
        print(f"[PDF] 转换失败: {e}")
        return False


def _run_claude(task_dir: str, output_path: str, params: dict, line_number: str = None) -> bool:
    """调用 Claude CLI 生成报告。"""
    # 解析输出文件名
    output_basename = os.path.basename(output_path)

    # 将详细指令写入 CLAUDE.md（Claude Code 启动时自动读取为系统指令）
    claude_md_path = os.path.join(task_dir, "CLAUDE.md")
    claude_md_content = _build_claude_md(params, output_basename, line_number)
    with open(claude_md_path, "w", encoding="utf-8") as f:
        f.write(claude_md_content)

    # -p 只传简短命令，详细指令在 CLAUDE.md 中
    short_prompt = (
        f"Generate {output_basename} now: read report_template_all.html, "
        "replace every {{placeholder}} with real data from output_excel/*.xlsx files, "
        f"save as {output_basename}. Start by reading the template."
    )

    try:
        result = subprocess.run(
            [
                CLAUDE_CLI_CMD,
                "-p", short_prompt,
                "--permission-mode", "bypassPermissions",
                "--output-format", "text",
                "--max-turns", "50",
            ],
            cwd=task_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,  # 10 分钟超时
            env={**os.environ, "NO_COLOR": "1"},
        )

        print(f"[Claude CLI] returncode={result.returncode}")
        if result.stdout:
            print(f"[Claude CLI] stdout (前500字符): {result.stdout[:500]}")
        if result.stderr:
            print(f"[Claude CLI] stderr: {result.stderr[:1000]}")

        # 检查 output.html 是否生成
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True
        else:
            # 尝试从 stdout 中提取 HTML
            if result.stdout and "<!DOCTYPE html>" in result.stdout:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(result.stdout)
                return True
            return False

    except subprocess.TimeoutExpired:
        print("[Claude CLI] 超时")
        return False
    except FileNotFoundError:
        print("[Claude CLI] 未找到 claude 命令")
        return False


# ============================================================
# 路由 — 页面
# ============================================================
@app.route("/", methods=["GET", "POST"])
def welcome():
    """欢迎/登录页面：选择线路号、输入姓名后进入系统。"""
    if request.method == "POST":
        line_number = request.form.get("line_number", "").strip()
        who_you_are = request.form.get("who_you_are", "").strip()
        if not line_number:
            return render_template("welcome.html", error="请选择线路号")
        if not who_you_are:
            return render_template("welcome.html", error="请输入分析人员姓名")
        session["line_number"] = line_number
        session["who_you_are"] = who_you_are
        return redirect(url_for("upload_page"))
    return render_template("welcome.html")


@app.route("/upload")
def upload_page():
    """主页面：上传检测数据、填写参数、提交生成报告任务。"""
    ip = get_user_ip()
    user_tasks = get_user_tasks(ip)
    who_you_are = session.get("who_you_are", "")
    line_number = session.get("line_number", "")
    return render_template("upload.html", user_ip=ip, user_tasks=user_tasks,
                           who_you_are=who_you_are, line_number=line_number)


@app.route("/static/logo.png")
def serve_logo():
    """提供 logo 静态文件。"""
    logo_path = os.path.join(PROJECT_ROOT, "logo.png")
    if os.path.exists(logo_path):
        return send_file(logo_path)
    return "", 404


@app.route("/static/assistant-character.png")
def serve_assistant_character():
    """提供交互助手角色贴图。"""
    character_path = os.path.join(PROJECT_ROOT, "assets", "assistant-character.png")
    if os.path.exists(character_path):
        return send_file(character_path)
    return "", 404


@app.route("/static/rail-tech-hero.png")
def serve_rail_tech_hero():
    """提供浅色科技轨道列车主视觉。"""
    hero_path = os.path.join(PROJECT_ROOT, "assets", "rail-tech-hero.png")
    if os.path.exists(hero_path):
        return send_file(hero_path)
    return "", 404


@app.route("/status/<task_id>")
def status_page(task_id):
    t, err = _verify_task_owner(task_id)
    if not t:
        return err
    return render_template("status.html", task_id=task_id, task=t)


# ============================================================
# 路由 — API
# ============================================================
@app.route("/api/tasks", methods=["POST"])
def create_task():
    """创建新任务，上传文件。"""
    ip = get_user_ip()
    task_id = uuid.uuid4().hex[:12]
    task_dir = os.path.join(DATA_ROOT, ip, task_id)

    # 创建任务目录（含上下行子目录）
    for sub in ["original_data", "defect_report", "output_fig", "output_excel"]:
        os.makedirs(os.path.join(task_dir, sub), exist_ok=True)
    os.makedirs(os.path.join(task_dir, "original_data", "上行"), exist_ok=True)
    os.makedirs(os.path.join(task_dir, "original_data", "下行"), exist_ok=True)

    # 保存上行 Excel 文件到 original_data/上行/
    for f in request.files.getlist("excel_files_up"):
        if f.filename and f.filename.endswith(".xlsx"):
            f.save(os.path.join(task_dir, "original_data", "上行", f.filename))

    # 保存下行 Excel 文件到 original_data/下行/
    for f in request.files.getlist("excel_files_down"):
        if f.filename and f.filename.endswith(".xlsx"):
            f.save(os.path.join(task_dir, "original_data", "下行", f.filename))

    # 保存上传的 defect_report 文件
    defect_files = request.files.getlist("defect_files")
    has_defect = False
    for f in defect_files:
        if f.filename:
            f.save(os.path.join(task_dir, "defect_report", f.filename))
            has_defect = True

    # 如果用户没有另外上传 defect report，尝试从 E 盘默认位置复制
    # （用户可能提前放在 uploads 目录下）
    if not has_defect:
        default_defect_dir = os.path.join(UPLOAD_ROOT, "defect_report")
        if os.path.isdir(default_defect_dir):
            for fname in os.listdir(default_defect_dir):
                src = os.path.join(default_defect_dir, fname)
                dst = os.path.join(task_dir, "defect_report", fname)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)

    # 复制模板等静态文件到任务目录
    for fname in COPY_FILES:
        src = os.path.join(PROJECT_ROOT, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(task_dir, fname))

    # 提取用户参数（含欢迎页面登录时填写的分析人员姓名和线路号）
    params = {
        "line_number": session.get("line_number", "").strip(),
        "start_end": request.form.get("start_end", "").strip(),
        "stat_pullout_irregular_count": request.form.get("stat_pullout_irregular_count", "").strip(),
        "stat_pullout_irregular_dec": request.form.get("stat_pullout_irregular_dec", "").strip(),
        "who_you_are": session.get("who_you_are", "").strip(),
    }

    # 验证必要文件（统计上下行子目录）
    def _count_xlsx(dir_path):
        if not os.path.isdir(dir_path):
            return 0
        return len([f for f in os.listdir(dir_path) if f.endswith(".xlsx")])

    excel_count = (_count_xlsx(os.path.join(task_dir, "original_data", "上行"))
                   + _count_xlsx(os.path.join(task_dir, "original_data", "下行")))
    if excel_count == 0:
        # 清理空目录
        shutil.rmtree(task_dir, ignore_errors=True)
        return jsonify({"error": "请至少上传一个 Excel 数据文件（上行或下行）"}), 400

    # 初始化任务状态
    set_task(task_id, status=STATUS_PENDING, progress=0,
             message="任务已创建，开始执行...",
             created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             output_path=None, output_pdf_path=None, error=None, ip=ip, task_dir=task_dir,
             last_step=0, params=params)

    # 启动后台线程执行流水线
    thread = threading.Thread(target=run_pipeline, args=(task_id, task_dir, params), daemon=True)
    thread.start()

    return jsonify({"task_id": task_id, "redirect": url_for("status_page", task_id=task_id)})


@app.route("/api/tasks/<task_id>")
def api_task_status(task_id):
    """查询任务状态（JSON，供前端轮询）。"""
    t, err = _verify_task_owner(task_id)
    if not t:
        return jsonify({"error": err[0]}), err[1]
    resp = {
        "task_id": task_id,
        "status": t.get("status"),
        "progress": t.get("progress", 0),
        "message": t.get("message", ""),
        "error": t.get("error"),
        "created_at": t.get("created_at"),
        "last_step": t.get("last_step", 0),
    }
    # intermediate 状态时返回中间文件列表，前端无需额外请求
    if t.get("status") == STATUS_INTERMEDIATE:
        resp["figures"] = t.get("figures", [])
        resp["excels"] = t.get("excels", [])
    return jsonify(resp)


@app.route("/api/tasks/<task_id>/resume", methods=["POST"])
def resume_task(task_id):
    """断点续跑：从上次失败/中间状态的步骤继续执行流水线。"""
    t, err = _verify_task_owner(task_id)
    if not t:
        return jsonify({"error": err[0]}), err[1]

    if t.get("status") not in (STATUS_FAILED, STATUS_INTERMEDIATE):
        return jsonify({"error": "只有失败或待确认的任务才能续跑"}), 400

    last_step = t.get("last_step", 0)
    if last_step >= 7:
        return jsonify({"error": "所有步骤已完成，无需续跑"}), 400

    start_step = last_step + 1
    task_dir = t.get("task_dir")
    params = t.get("params", {})

    set_task(task_id, status=STATUS_RUNNING,
             progress=_STEP_DEFS[start_step - 1][0],
             message=f"断点续跑：从第 {start_step}/7 步开始...",
             error=None)

    thread = threading.Thread(
        target=run_pipeline,
        args=(task_id, task_dir, params, start_step),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "task_id": task_id,
        "start_step": start_step,
        "message": f"已从第 {start_step}/7 步开始续跑",
    })


@app.route("/api/tasks/<task_id>/continue", methods=["POST"])
def continue_task(task_id):
    """中间状态确认继续：从 Step 2 继续执行流水线。"""
    t, err = _verify_task_owner(task_id)
    if not t:
        return jsonify({"error": err[0]}), err[1]

    if t.get("status") != STATUS_INTERMEDIATE:
        return jsonify({"error": "只有待确认状态的任务才能继续"}), 400

    task_dir = t.get("task_dir")
    params = t.get("params", {})
    start_step = 2  # 固定从 Step 2 开始

    set_task(task_id, status=STATUS_RUNNING,
             progress=_STEP_DEFS[start_step - 1][0],
             message=f"用户确认继续：从第 {start_step}/7 步开始...",
             error=None)

    thread = threading.Thread(
        target=run_pipeline,
        args=(task_id, task_dir, params, start_step),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "task_id": task_id,
        "start_step": start_step,
        "message": f"已从第 {start_step}/7 步开始继续执行",
    })


@app.route("/api/tasks/<task_id>/figures/<filename>")
def serve_figure(task_id, filename):
    """查看任务生成的图表图片（用于 <img> 显示）。"""
    t, err = _verify_task_owner(task_id)
    if not t:
        return jsonify({"error": err[0]}), err[1]
    # 安全检查：防止路径穿越
    if ".." in filename or "/" in filename or "\\" in filename:
        return "Invalid filename", 400
    task_dir = t.get("task_dir")
    fig_path = os.path.join(task_dir, "output_fig", filename)
    if not os.path.isfile(fig_path):
        return "File not found", 404
    return send_file(fig_path, mimetype="image/png")


@app.route("/api/tasks/<task_id>/intermediate")
def api_intermediate_files(task_id):
    """返回中间结果文件列表（图表 + Excel）。"""
    t, err = _verify_task_owner(task_id)
    if not t:
        return jsonify({"error": err[0]}), err[1]
    return jsonify({
        "figures": t.get("figures", []),
        "excels": t.get("excels", []),
    })


# ============================================================
# 路由 — 下载
# ============================================================
def _verify_task_owner(task_id: str):
    """验证当前 IP 是否拥有该任务，返回 (task_dict, error_msg)。"""
    ip = get_user_ip()
    t = get_task(task_id)
    if not t:
        return None, ("任务不存在", 404)
    if t.get("ip") != ip:
        return None, ("无权访问此任务", 403)
    return t, None


@app.route("/api/tasks/<task_id>/download/report")
def download_report(task_id):
    t, err = _verify_task_owner(task_id)
    if not t:
        return err
    if t.get("status") != STATUS_DONE:
        return "报告尚未生成", 404
    output_path = t.get("output_path")
    if not output_path or not os.path.exists(output_path):
        return "报告文件不存在", 404
    return send_file(output_path, as_attachment=True,
                     download_name=os.path.basename(output_path))


@app.route("/api/tasks/<task_id>/download/pdf")
def download_pdf(task_id):
    t, err = _verify_task_owner(task_id)
    if not t:
        return err
    if t.get("status") != STATUS_DONE:
        return "报告尚未生成", 404
    pdf_path = t.get("output_pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        return "PDF 文件不存在（可能转换失败）", 404
    return send_file(pdf_path, as_attachment=True,
                     download_name=os.path.basename(pdf_path))


@app.route("/api/tasks/<task_id>/download/excel")
def download_excel(task_id):
    t, err = _verify_task_owner(task_id)
    if not t:
        return err
    task_dir = t.get("task_dir")
    excel_dir = os.path.join(task_dir, "output_excel")
    if not os.path.isdir(excel_dir):
        return "Excel 目录不存在", 404
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(excel_dir):
            fpath = os.path.join(excel_dir, fname)
            if os.path.isfile(fpath):
                zf.write(fpath, fname)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{task_id}_output_excel.zip")


@app.route("/api/tasks/<task_id>/download/figures")
def download_figures(task_id):
    t, err = _verify_task_owner(task_id)
    if not t:
        return err
    task_dir = t.get("task_dir")
    fig_dir = os.path.join(task_dir, "output_fig")
    if not os.path.isdir(fig_dir):
        return "图片目录不存在", 404
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in os.listdir(fig_dir):
            fpath = os.path.join(fig_dir, fname)
            if os.path.isfile(fpath):
                zf.write(fpath, fname)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{task_id}_output_fig.zip")


# ============================================================
# 工具函数
# ============================================================

def _iter_original_files(original_dir: str):
    """遍历 original_data 下所有 .xlsx 文件。
    优先从 上行/下行 子目录读取；子目录不存在时回退到 flat 目录（兼容旧任务）。
    """
    up_dir = os.path.join(original_dir, "上行")
    down_dir = os.path.join(original_dir, "下行")
    if os.path.isdir(up_dir) and os.path.isdir(down_dir):
        for sub in (up_dir, down_dir):
            for fname in sorted(os.listdir(sub)):
                if fname.endswith(".xlsx"):
                    yield fname
    else:
        for fname in sorted(os.listdir(original_dir)):
            if fname.endswith(".xlsx"):
                yield fname


def _get_report_filename(task_dir: str, line_number: str = None) -> str:
    """使用用户选择的线路号 + 文件名中的月份，生成报告文件名。

    示例: "11号线5月份检测数据分析报告.html"
    优先使用 line_number 参数；无参数时回退到从文件名解析（兼容 CLI 模式）。
    """
    original_dir = os.path.join(task_dir, "original_data")
    if not os.path.isdir(original_dir):
        return "output.html"

    # 从文件名提取月份（遍历子目录）
    month = ""
    for fname in _iter_original_files(original_dir):
        name_no_ext = fname.replace(".xlsx", "")
        parts = name_no_ext.split("_")
        if len(parts) >= 5:
            date_str = parts[4]
            month_match = re.search(r"(\d+)月", date_str)
            month = month_match.group(1) if month_match else ""
        break

    if line_number and month:
        return f"{line_number}{month}月份检测数据分析报告.html"

    # 回退：从文件名解析（兼容 CLI 模式无 line_number 的情况）
    for fname in _iter_original_files(original_dir):
        # 文件名格式: 全线路原始数据_{线名}_{车号}_{行别}_{日期}.xlsx
        # 线名如 "深圳地铁11号线"，日期如 "2026年05月16日 00时07分"
        name_no_ext = fname.replace(".xlsx", "")
        parts = name_no_ext.split("_")
        if len(parts) >= 5:
            line_name = parts[1]  # "深圳地铁11号线"
            # 提取线路号
            line_match = re.search(r"(\d+)号线", line_name)
            line_num = line_match.group(1) if line_match else ""
            if line_num and month:
                return f"{line_num}号线{month}月份检测数据分析报告.html"
        break  # 只看第一个文件即可

    return "output.html"


# ============================================================
# 模块化测试 — 独立运行单个步骤（CLI 模式）
# ============================================================

def run_step(task_dir: str, step: int, params: dict = None):
    """独立运行单个步骤。不依赖 Flask 任务管理系统。

    用法示例:
        python app.py --step 1 --task-dir E:/catenary_service/tasks/10.10.17.208/abc123
        python app.py --step 6 --task-dir E:/catenary_service/tasks/10.10.17.208/abc123
    """
    if params is None:
        params = {}

    line_number = params.get("line_number", "")

    original_data_dir = os.path.join(task_dir, "original_data")
    defect_report_dir = os.path.join(task_dir, "defect_report")
    output_fig_dir = os.path.join(task_dir, "output_fig")
    output_excel_dir = os.path.join(task_dir, "output_excel")
    station_json_path = os.path.join(task_dir, "station.json")

    step_funcs = {
        1: lambda: pipeline_main.run_pipeline(
            data_dir=original_data_dir,
            output_fig_dir=output_fig_dir,
            output_excel_dir=output_excel_dir,
            station_json_path=station_json_path,
            line_number=line_number,
        ),
        2: lambda: export_top10_tables.run_latest_files(
            data_dir=original_data_dir,
            output_dir=output_excel_dir,
            line_number=line_number,
        ),
        3: lambda: generate_table2_1.run(
            data_dir=original_data_dir,
            output_dir=output_excel_dir,
            line_number=line_number,
        ),
        4: lambda: generate_table2_2_3.run(
            data_dir=defect_report_dir,
            output_dir=output_excel_dir,
        ),
        5: lambda: generate_summary_tables.run(
            data_dir=original_data_dir,
            output_dir=output_excel_dir,
            station_json_path=station_json_path,
            line_number=line_number,
        ),
        6: lambda: _run_claude(
            task_dir,
            os.path.join(task_dir, _get_report_filename(task_dir, line_number)),
            params,
            line_number,
        ),
        7: lambda: _convert_html_to_pdf(
            os.path.join(task_dir, _get_report_filename(task_dir, line_number)),
            os.path.join(task_dir, _get_report_filename(task_dir, line_number).replace(".html", ".pdf")),
        ),
    }

    if step not in step_funcs:
        print(f"无效步骤: {step}，有效范围: 1-7")
        return False

    print(f"\n{'='*60}")
    print(f"  执行第 {step}/7 步")
    print(f"  任务目录: {task_dir}")
    print(f"{'='*60}\n")

    step_funcs[step]()
    print(f"\n第 {step}/7 步执行完成。")
    return True


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="接触网检测数据分析报告服务")
    parser.add_argument("--host", default="10.10.17.208")
    parser.add_argument("--port", type=int, default=8920)
    parser.add_argument("--debug", action="store_true")

    # 模块化测试参数
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5, 6, 7],
                        help="仅运行指定步骤（不启动 Web 服务）")
    parser.add_argument("--task-dir", help="任务目录路径（配合 --step 使用）")
    parser.add_argument("--start-end", default="", help="始末区间参数（配合 --step 6）")
    parser.add_argument("--pullout-count", default="", help="拉出值不平顺处数量（配合 --step 6）")
    parser.add_argument("--pullout-dec", default="", help="拉出值不平顺变化描述（配合 --step 6）")

    args = parser.parse_args()

    # ---- 模块化测试模式 ----
    if args.step is not None:
        if not args.task_dir:
            print("错误: --task-dir 参数必须指定（配合 --step 使用）")
            sys.exit(1)
        if not os.path.isdir(args.task_dir):
            print(f"错误: 任务目录不存在: {args.task_dir}")
            sys.exit(1)

        params = {
            "start_end": args.start_end,
            "stat_pullout_irregular_count": args.pullout_count,
            "stat_pullout_irregular_dec": args.pullout_dec,
        }
        success = run_step(args.task_dir, args.step, params)
        sys.exit(0 if success else 1)

    # ---- Web 服务模式 ----
    print(f"Catenary Report Service: http://{args.host}:{args.port}")
    if args.debug:
        app.run(host=args.host, port=args.port, debug=True)
    else:
        from waitress import serve
        serve(app, host=args.host, port=args.port)
