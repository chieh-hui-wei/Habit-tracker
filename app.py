import gradio as gr
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import json
import uuid
import threading
from zoneinfo import ZoneInfo
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from google.cloud import bigquery
from google.api_core.exceptions import NotFound
from google.oauth2 import service_account

from garmin_integration import sync_garmin_activities
from timevest_service import TimeVestService

load_dotenv()

# ----------------------
# BIGQUERY SETUP
# ----------------------
PROJECT_ID = os.environ.get("BQ_PROJECT_ID", "").strip('"').strip("'")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "").strip('"').strip("'")
TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.habit_logs"
credentials_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '').strip('"').strip("'")

credentials = service_account.Credentials.from_service_account_file(credentials_path)
client = bigquery.Client(project=PROJECT_ID, credentials=credentials)

def setup_bigquery():
    """Initializes dataset and table with partitioning and clustering."""
    # Ensure dataset exists
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "asia-east1"
        client.create_dataset(dataset)
        print(f"Created dataset {DATASET_ID}")

    # Ensure table exists with optimization
    try:
        client.get_table(TABLE_ID)
    except NotFound:
        schema = [
            bigquery.SchemaField("id", "STRING"),
            bigquery.SchemaField("habit_name", "STRING"),
            bigquery.SchemaField("start_time", "TIMESTAMP"),
            bigquery.SchemaField("end_time", "TIMESTAMP"),
            bigquery.SchemaField("duration_second", "INTEGER"),
            bigquery.SchemaField("detail", "STRING"),
        ]
        table = bigquery.Table(TABLE_ID, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field="start_time"
        )
        table.clustering_fields = ["habit_name"]
        client.create_table(table)
        print(f"Created table {TABLE_ID} with partitioning and clustering.")

setup_bigquery()

# Initialize timeVest Service
service = TimeVestService(client, TABLE_ID)
service.upgrade_schema()
service.check_and_generate_monthly_summaries()

# ----------------------
# HTML BUILDERS
# ----------------------
def get_icon_svg(icon_name, color="#475569"):
    svgs = {
        "book.fill": f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="display: inline-block; vertical-align: middle;"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/><path d="M6 6h10M6 10h10"/></svg>',
        "guitars.fill": f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="display: inline-block; vertical-align: middle;"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
        "dumbbell.fill": f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="display: inline-block; vertical-align: middle;"><path d="m6.5 6.5 11 11"/><path d="m21 21-1-1"/><path d="m3 3 1 1"/><path d="m18 22 4-4"/><path d="m2 6 4-4"/><path d="m3 10 7-7"/><path d="m14 21 7-7"/></svg>',
        "figure.run": f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="display: inline-block; vertical-align: middle;"><path d="M18 6h.01M6 18h.01M12 12h.01M21 21l-4.3-4.3M4.3 4.3L21 21M3 3l18 18"/></svg>',
        "laptopcomputer": f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="display: inline-block; vertical-align: middle;"><rect width="18" height="12" x="3" y="4" rx="2" ry="2"/><line x1="2" x2="22" y1="20" y2="20"/><line x1="5" x2="19" y1="16" y2="16"/></svg>',
    }
    return svgs.get(icon_name, "")

def get_banner_html(year_str="全部", month_str="全部"):
    year = int(year_str) if year_str != "全部" else None
    month = int(month_str) if month_str != "全部" else None
    
    stats = service.get_portfolio_summary(year=year, month=month)
    total = stats["total_hours"]
    today = stats["today_hours"]
    streak = stats["streak_days"]
    
    h = int(total)
    m = int((total - h) * 60)
    
    total_formatted = f"<span class='monospace-num' style='font-size: 46px; color: #B48A2C;'>{h}</span><span style='font-size: 20px; color: #475569; margin-left: 2px; margin-right: 6px;'>h</span><span class='monospace-num' style='font-size: 46px; color: #B48A2C;'>{m:02d}</span><span style='font-size: 20px; color: #475569; margin-left: 2px;'>m</span>"
    
    if year or month:
        left_box_label = "投入天數"
        left_box_val = f"{stats['active_days']} 天"
    else:
        left_box_label = "連續天數"
        left_box_val = f"{streak} 天"
    
    return f"""
        <div style='text-align: center; padding: 1.5rem 0;'>
            <div style='color: #475569; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase;'>專注資產總額</div>
            <div style='margin-top: 5px; display: inline-flex; align-items: baseline;'>
                {total_formatted}
            </div>
            
            <div style='display: flex; justify-content: center; gap: 16px; margin-top: 20px;'>
                <div style='background: #F1F5F9; padding: 10px 20px; border-radius: 12px; border: 1px solid rgba(200, 157, 69, 0.3); text-align: center; min-width: 90px;'>
                    <div style='color: #B48A2C; font-size: 16px; font-weight: 700; font-family: monospace;'>{left_box_val}</div>
                    <div style='color: #475569; font-size: 10px;'>{left_box_label}</div>
                </div>
                <div style='background: #F1F5F9; padding: 10px 20px; border-radius: 12px; border: 1px solid rgba(200, 157, 69, 0.3); text-align: center; min-width: 90px;'>
                    <div style='color: #B48A2C; font-size: 16px; font-weight: 700; font-family: monospace;'>{today:.1f}h</div>
                    <div style='color: #475569; font-size: 10px;'>今日收益</div>
                </div>
            </div>
        </div>
    """

def get_allocation_html(year_str="全部", month_str="全部"):
    year = int(year_str) if year_str != "全部" else None
    month = int(month_str) if month_str != "全部" else None
    
    allocations = service.get_allocation(year=year, month=month)
    if not allocations:
        return "<div style='color: #475569; font-size: 13px; text-align: center; padding: 20px;'>尚無投入數據以進行配置分析</div>"
    
    allocations = sorted(allocations, key=lambda x: x["percentage"], reverse=True)
    
    bar_rows_html = ""
    for item in allocations:
        pct_val = item["percentage"] * 100
        inv = next((i for i in service.investments if i["name"] == item['name']), None)
        icon_svg = get_icon_svg(inv["icon"], item['color']) if inv else ""
        bar_rows_html += f"""
            <div style='margin-bottom: 8px;'>
                <div style='display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 3px;'>
                    <div style='display: flex; align-items: center; gap: 6px;'>
                        {icon_svg}
                        <span style='color: #0F172A; font-weight: 500;'>{item['name']}</span>
                    </div>
                    <span style='color: #B48A2C; font-family: monospace; font-weight: 700;'>{item['hours']:.1f}h ({pct_val:.0f}%)</span>
                </div>
                <div style='width: 100%; height: 8px; background-color: #E2E8F0; border-radius: 4px; overflow: hidden;'>
                    <div style='width: {pct_val}%; height: 100%; background-color: {item['color']}; border-radius: 4px;'></div>
                </div>
            </div>
        """
        
    return f"""
        <div style='display: flex; flex-direction: column; max-height: 180px; overflow-y: auto; padding-right: 4px;'>
            <div style='color: #475569; font-size: 11px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 8px;'>時間資產配置比例</div>
            {bar_rows_html}
        </div>
    """

def get_statement_html():
    stats = service.get_portfolio_summary()
    allocations = service.get_allocation()
    total = stats["total_hours"]
    streak = stats["streak_days"]

    h = int(total)
    m = int((total - h) * 60)

    distribution = sorted(allocations, key=lambda x: x["hours"], reverse=True)
    top_inv = distribution[0]["name"] if distribution else "無"

    detail_rows = ""
    for item in distribution:
        inv = next((i for i in service.investments if i["name"] == item["name"]), None)
        icon_svg = get_icon_svg(inv["icon"], item["color"]) if inv else ""
        detail_rows += (
            "<div style='display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px;'>"
            "<div style='display: flex; align-items: center; gap: 5px;'>"
            f"{icon_svg}"
            f"<span style='color: #0F172A;'>{item['name']}</span>"
            "</div>"
            f"<span style='color: #475569; font-family: monospace;'>{item['hours']:.1f}h ({item['percentage']*100:.0f}%)</span>"
            "</div>"
        )

    # Build quantified results section
    quant_sections = ""
    for inv in service.investments:
        if not inv.get("item_label"):
            continue
        label = inv["item_label"]
        icon_svg = get_icon_svg(inv["icon"], inv["color"])
        completed_items = service.get_items(inv_id=inv["id"], status="completed")
        inprogress_items = service.get_items(inv_id=inv["id"], status="inProgress")

        if not completed_items and not inprogress_items:
            continue

        item_rows = ""
        if completed_items:
            names = "、".join([f"《{it['name']}》" for it in completed_items])
            item_rows += (
                "<div style='display:flex;align-items:center;gap:6px;margin-bottom:6px;'>"
                f"<span style='background:#DCFCE7;color:#166534;font-size:10px;font-weight:700;"
                f"padding:2px 7px;border-radius:99px;'>✓ 已完成 {len(completed_items)} 項</span>"
                f"<span style='color:#64748B;font-size:11px;overflow:hidden;text-overflow:ellipsis;"
                f"white-space:nowrap;max-width:200px;' title='{names}'>{names}</span>"
                "</div>"
            )

        for it in inprogress_items:
            prog = it.get("progress", 0.0)
            ptype = inv.get("progress_type", "none")
            inv_color = inv["color"]
            if ptype == "pages" and it.get("total"):
                tot = it["total"]
                cur = prog * tot
                label_val = f"{cur:.0f} / {tot:.0f} 頁"
                pct_w = min(prog * 100, 100)
            elif ptype == "percentage":
                label_val = f"{prog * 100:.0f}%"
                pct_w = min(prog * 100, 100)
            else:
                label_val = ""
                pct_w = 0

            progress_bar = ""
            if ptype != "none" and pct_w > 0:
                progress_bar = (
                    "<div style='width:100%;height:5px;background:#E2E8F0;border-radius:3px;"
                    "overflow:hidden;margin-top:3px;'>"
                    f"<div style='width:{pct_w:.1f}%;height:100%;background:{inv_color};border-radius:3px;'></div>"
                    "</div>"
                )

            right_part = (
                f"<span style='color:{inv_color};font-family:monospace;font-size:11px;font-weight:700;'>{label_val}</span>"
                if label_val else ""
            )
            item_rows += (
                "<div style='margin-bottom:8px;'>"
                "<div style='display:flex;justify-content:space-between;font-size:12px;'>"
                f"<span style='color:#0F172A;'>《{it['name']}》</span>"
                f"{right_part}"
                "</div>"
                f"{progress_bar}"
                "</div>"
            )

        quant_sections += (
            "<div style='margin-bottom:12px;'>"
            "<div style='display:flex;align-items:center;gap:5px;margin-bottom:6px;'>"
            f"{icon_svg}"
            f"<span style='color:#0F172A;font-size:12px;font-weight:600;'>{inv['name']}</span>"
            f"<span style='color:#94A3B8;font-size:11px;'>— {label}</span>"
            "</div>"
            f"{item_rows}"
            "</div>"
        )

    quant_block = ""
    if quant_sections:
        quant_block = (
            "<div style='border-top: 1px dashed #CBD5E1; margin: 16px 0;'></div>"
            "<div style='display: flex; flex-direction: column; gap: 4px;'>"
            "<div style='color: #475569; font-size: 11px; font-weight: 700; font-family: monospace;"
            "letter-spacing: 1px; margin-bottom: 8px;'>成果量化明細</div>"
            f"{quant_sections}"
            "</div>"
        )

    date_str = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M")

    return (
        "<div style='background: #F8FAFC; border-radius: 18px; padding: 24px;"
        "border: 1px solid rgba(200, 157, 69, 0.35); max-width: 420px; margin: 0 auto;"
        "box-shadow: 0 10px 30px rgba(0,0,0,0.08);'>"
        "<div style='text-align: center;'>"
        "<div style='color: #B48A2C; font-size: 13px; font-weight: 700; font-family: monospace;"
        "letter-spacing: 2px;'>TIMEVEST STATEMENT</div>"
        "<div style='color: #0F172A; font-size: 18px; font-weight: 800; margin-top: 4px;'>"
        "個人自我投資對帳單</div>"
        "</div>"
        "<div style='border-top: 1px dashed #CBD5E1; margin: 16px 0;'></div>"
        "<div style='display: flex; flex-direction: column; gap: 10px;'>"
        f"<div style='display:flex;justify-content:space-between;font-size:12px;'>"
        f"<span style='color:#475569;'>結算時間</span>"
        f"<span style='color:#0F172A;font-family:monospace;'>{date_str}</span></div>"
        f"<div style='display:flex;justify-content:space-between;font-size:12px;'>"
        f"<span style='color:#475569;'>累積投資總時數</span>"
        f"<span style='color:#B48A2C;font-weight:700;font-family:monospace;'>{h}h {m}m</span></div>"
        f"<div style='display:flex;justify-content:space-between;font-size:12px;'>"
        f"<span style='color:#475569;'>持續投資天數</span>"
        f"<span style='color:#0F172A;font-family:monospace;'>{streak} 天</span></div>"
        f"<div style='display:flex;justify-content:space-between;font-size:12px;'>"
        f"<span style='color:#475569;'>增值最多項目</span>"
        f"<span style='color:#B48A2C;font-weight:700;'>{top_inv}</span></div>"
        "</div>"
        "<div style='border-top: 1px dashed #CBD5E1; margin: 16px 0;'></div>"
        "<div style='display: flex; flex-direction: column; gap: 8px;'>"
        "<div style='color: #475569; font-size: 11px; font-weight: 700; font-family: monospace;"
        "letter-spacing: 1px; margin-bottom: 4px;'>資產分佈明細</div>"
        f"{detail_rows}"
        "</div>"
        f"{quant_block}"
        "<div style='border-top: 1px dashed #CBD5E1; margin: 16px 0;'></div>"
        "<div style='text-align: center; display: flex; flex-direction: column; gap: 4px;'>"
        "<div style='color: #B48A2C; font-size: 11px; font-style: italic; font-weight: 500;'>"
        "\u201c\u6642\u9593\u662f\u552f\u4e00\u7121\u6cd5\u88ab\u5265\u5955\u7684\u771f\u5be6\u8cc7\u7522\u3002\u201d</div>"
        "<div style='color: #475569; font-size: 8px; font-weight: 700; font-family: monospace;"
        "letter-spacing: 2px;'>時光投資委員會認證印記</div>"
        "</div>"
        "</div>"
    )

def get_milestone_list_html(m_type=None, start_date=None, end_date=None):
    filtered = service.milestones
    if m_type:
        filtered = [m for m in filtered if m["type"] == m_type]
        
    if start_date and end_date:
        filtered = [
            m for m in filtered 
            if start_date <= m["date_unlocked"][:10] <= end_date
        ]
        
    filtered = sorted(filtered, key=lambda x: x["date_unlocked"], reverse=True)
    
    if not filtered:
        return "<div style='color: #475569; text-align: center; padding: 30px;'>尚無收益記錄</div>"
        
    html = "<div style='display: flex; flex-direction: column; gap: 14px; position: relative; padding-left: 20px; border-left: 1px solid rgba(200, 157, 69, 0.25);'>"
    for item in filtered:
        m_color = "#B48A2C"
        if item["type"] == "completion":
            m_color = "#2EE59D"
        elif item["type"] == "monthlyAchievement":
            m_color = "#0D9488"
            
        html += f"""
            <div style='position: relative; background: #F8FAFC; padding: 14px; border-radius: 12px; border: 1px solid rgba(200, 157, 69, 0.15);'>
                <!-- Timeline dot -->
                <span style='position: absolute; left: -25px; top: 20px; width: 8px; height: 8px; border-radius: 50%; background: {m_color}; box-shadow: 0 0 8px {m_color};'></span>
                
                <div style='display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #475569;'>
                    <span>{item['date_unlocked'][:16].replace('T', ' ')}</span>
                </div>
                <div style='color: #0F172A; font-weight: 700; font-size: 14px; margin-top: 5px;'>{item['title']}</div>
                <div style='color: #475569; font-size: 12px; margin-top: 4px;'>{item['description']}</div>
            </div>
        """
    html += "</div>"
    return html

def get_items_summary_html(inv_id, status):
    items = service.get_items(inv_id=inv_id, status=status)
    if not items:
        return "<div style='color: #475569; text-align: center; padding: 20px;'>無此狀態項目</div>"
        
    html = "<div style='display: flex; flex-direction: column; gap: 12px;'>"
    for item in items:
        pct = item["progress"] * 100
        html += f"""
            <div style='background: #F8FAFC; padding: 14px; border-radius: 12px; border: 1px solid rgba(200, 157, 69, 0.15); display: flex; justify-content: space-between; align-items: center;'>
                <div>
                    <div style='color: #0F172A; font-weight: 700; font-size: 14px;'>{item['name']}</div>
                    <div style='color: #475569; font-size: 11px; margin-top: 2px;'>狀態：{item['status']}</div>
                </div>
                <div style='text-align: right;'>
                    <span style='color: #B48A2C; font-family: monospace; font-size: 16px; font-weight: 700;'>{pct:.0f}%</span>
                    <div style='width: 80px; height: 4px; background: rgba(148, 163, 184, 0.3); border-radius: 2px; overflow: hidden; margin-top: 4px;'>
                        <div style='width: {pct}%; height: 100%; background: #B48A2C;'></div>
                    </div>
                </div>
            </div>
        """
    html += "</div>"
    return html

# ----------------------
# STATE
# ----------------------
timer_state = {
    "is_active": False,
    "is_paused": False,
    "start_time": None,
    "accumulated": 0,
    "elapsed": 0,
    "inv_id": None,
    "item_id": None
}

# ----------------------
# GRADIO EVENT HANDLERS
# ----------------------
def start_timer(inv_name, item_name):
    global timer_state
    
    inv = next((i for i in service.investments if i["name"] == inv_name), None)
    if not inv:
        return "請選擇有效的投資帳戶"
        
    item = None
    if inv["item_label"] and item_name:
        item = next((it for it in service.items if it["name"] == item_name), None)
        
    timer_state["is_active"] = True
    timer_state["is_paused"] = False
    timer_state["start_time"] = datetime.now(ZoneInfo("Asia/Taipei"))
    timer_state["accumulated"] = 0
    timer_state["elapsed"] = 0
    timer_state["inv_id"] = inv["id"]
    timer_state["item_id"] = item["id"] if item else None
    
    item_label_str = f"▹《{item['name']}》" if item else ""
    return f"正在投資至 ── {inv['name']} {item_label_str}"

def get_stopwatch_html(time_str):
    return f"<div style='text-align: center; font-size: 3rem; font-weight: 800; font-family: monospace; color: #B48A2C; padding: 1rem 0;'>{time_str}</div>"

def tick_timer():
    global timer_state
    if timer_state["is_active"] and not timer_state["is_paused"]:
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        delta = int((now - timer_state["start_time"]).total_seconds())
        timer_state["elapsed"] = timer_state["accumulated"] + delta
        
    h = timer_state["elapsed"] // 3600
    m = (timer_state["elapsed"] % 3600) // 60
    s = timer_state["elapsed"] % 60
    
    if h > 0:
        return get_stopwatch_html(f"{h:02d}:{m:02d}:{s:02d}")
    return get_stopwatch_html(f"{m:02d}:{s:02d}")

def pause_resume_timer():
    global timer_state
    if not timer_state["is_active"]:
        return "No active session", "暫停"
        
    if timer_state["is_paused"]:
        timer_state["start_time"] = datetime.now(ZoneInfo("Asia/Taipei"))
        timer_state["is_paused"] = False
        return "繼續注入時間中...", "暫停"
    else:
        timer_state["is_paused"] = True
        if timer_state["start_time"]:
            delta = int((datetime.now(ZoneInfo("Asia/Taipei")) - timer_state["start_time"]).total_seconds())
            timer_state["accumulated"] += delta
        timer_state["start_time"] = None
        return "暫停中", "繼續"

def check_timer_settle_fields():
    global timer_state
    if not timer_state["is_active"]:
        return gr.update(visible=False), gr.update(visible=False)
        
    inv = next((i for i in service.investments if i["id"] == timer_state["inv_id"]), None)
    if inv and inv["progress_type"] != "none" and timer_state["item_id"]:
        if inv["progress_type"] == "pages":
            return gr.update(visible=True, value=""), gr.update(visible=True, value="300")
        elif inv["progress_type"] == "percentage":
            return gr.update(visible=True, value="0"), gr.update(visible=False)
    return gr.update(visible=False), gr.update(visible=False)

def settle_timer(progress_val, total_val, remarks):
    global timer_state
    if not timer_state["is_active"]:
        return "無進行中的計時會話"
        
    # calculate total elapsed
    if not timer_state["is_paused"] and timer_state["start_time"]:
        delta = int((datetime.now(ZoneInfo("Asia/Taipei")) - timer_state["start_time"]).total_seconds())
        timer_state["elapsed"] = timer_state["accumulated"] + delta
        
    duration = timer_state["elapsed"]
    if duration <= 0:
        duration = 1 # min 1 sec
        
    inv = next((i for i in service.investments if i["id"] == timer_state["inv_id"]), None)
    
    progress_snapshot = None
    if inv and inv["progress_type"] != "none" and timer_state["item_id"]:
        try:
            if inv["progress_type"] == "pages":
                cur = float(progress_val)
                tot = float(total_val)
                if tot > 0:
                    progress_snapshot = min(cur / tot, 1.0)
                    # update item total pages limit
                    for it in service.items:
                        if it["id"] == timer_state["item_id"]:
                            it["total"] = tot
            elif inv["progress_type"] == "percentage":
                progress_snapshot = min(float(progress_val) / 100.0, 1.0)
        except Exception:
            pass

    start_t = datetime.now(ZoneInfo("Asia/Taipei")) - timedelta(seconds=duration)
    end_t = datetime.now(ZoneInfo("Asia/Taipei"))
    
    success, ms_list = service.log_activity(
        inv_id=timer_state["inv_id"],
        item_id=timer_state["item_id"],
        duration_seconds=duration,
        detail=remarks if remarks else "專注投入",
        start_time=start_t,
        end_time=end_t,
        progress_snapshot=progress_snapshot
    )
    
    timer_state["is_active"] = False
    timer_state["is_paused"] = False
    
    msg = f"成功結算投入 {duration // 60} 分鐘！"
    if ms_list:
        msg += "\n解鎖里程碑！" + "\n".join([item["title"] for item in ms_list])
    return msg

def discard_timer():
    global timer_state
    timer_state["is_active"] = False
    timer_state["is_paused"] = False
    return "已放棄本次投入"

def get_investment_choices():
    icon_map = {
        "book.fill": "📖",
        "guitars.fill": "🎸",
        "dumbbell.fill": "🏋️",
        "figure.run": "🏃",
        "laptopcomputer": "💻"
    }
    choices = []
    for i in service.investments:
        emoji = icon_map.get(i["icon"], "💼")
        choices.append((f"{emoji} {i['name']}", i["name"]))
    return choices

# Settings / Actions
def add_new_investment_option(name, icon, color, progress_type, item_label):
    if not name.strip():
        return gr.update(choices=get_investment_choices()), "帳戶名稱不能為空"
    service.add_investment(name.strip(), icon, color, item_label.strip(), progress_type)
    return gr.update(choices=get_investment_choices()), f"已成功開立新投資帳戶：{name}"

def delete_investment_option(name):
    inv = next((i for i in service.investments if i["name"] == name), None)
    if not inv:
        return gr.update(choices=get_investment_choices()), "找不到要刪除的帳戶"
    service.delete_investment(inv["id"])
    return gr.update(choices=get_investment_choices()), f"已刪除帳戶及其所有項目：{name}"

def add_new_item_option(inv_name, name, total_val):
    inv = next((i for i in service.investments if i["name"] == inv_name), None)
    if not inv:
        return "請先選擇投資帳戶"
    if not name.strip():
        return "請輸入項目名稱"
    tot = None
    if inv["progress_type"] == "pages" and total_val:
        try:
            tot = float(total_val)
        except:
            pass
    service.add_item(inv["id"], name.strip(), tot)
    return f"已新增項目：{name}"

def update_item_status_option(item_name, status):
    item = next((i for i in service.items if i["name"] == item_name), None)
    if not item:
        return "找不到指定項目"
    service.set_item_status(item["id"], status)
    return f"項目狀態已更新為：{status}"

def dynamic_update_items_dropdown(inv_name):
    inv = next((i for i in service.investments if i["name"] == inv_name), None)
    if not inv or not inv["item_label"]:
        return gr.update(choices=[], visible=False, label="項目")
    items = service.get_items(inv_id=inv["id"], status="inProgress")
    return gr.update(choices=[it["name"] for it in items], visible=True, label=inv["item_label"])

def get_timer_item_panel_state(inv_name):
    """Returns (item_dropdown update, warning_html update, quick_add_group update, quick_add_label) """
    inv = next((i for i in service.investments if i["name"] == inv_name), None)
    if not inv or not inv["item_label"]:
        return (
            gr.update(choices=[], visible=False, label="項目"),
            gr.update(visible=False),
            gr.update(visible=False),
            inv["item_label"] if inv and inv["item_label"] else "項目"
        )
    label = inv["item_label"]
    items = service.get_items(inv_id=inv["id"], status="inProgress")
    if items:
        return (
            gr.update(choices=[it["name"] for it in items], visible=True, label=f"選擇{label}"),
            gr.update(visible=False),
            gr.update(visible=False),
            label
        )
    else:
        return (
            gr.update(choices=[], visible=False, label=f"選擇{label}"),
            gr.update(visible=True, value=f"<div style='display:flex;align-items:center;gap:8px;padding:10px 14px;background:#FFF7ED;border:1px solid #FDBA74;border-radius:10px;font-size:13px;color:#92400E;'>⚠️ 目前無進行中的{label}，請先新增。</div>"),
            gr.update(visible=True),
            label
        )

def dynamic_update_all_items_dropdown():
    return gr.update(choices=[it["name"] for it in service.items])

# ----------------------
# Gradio Theme & Custom CSS
# ----------------------
custom_css = """
:root, body, .gradio-container {
    background-color: #FFFFFF !important;
    color: #0F172A !important;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Outfit", sans-serif !important;
    
    /* Gradio Theme CSS Variable Overrides */
    --body-background-fill: #FFFFFF !important;
    --background-fill-primary: #FFFFFF !important;
    --background-fill-secondary: #F8FAFC !important;
    --border-color-accent: #C89D45 !important;
    --border-color-primary: rgba(200, 157, 69, 0.2) !important;
    --block-background-fill: #F8FAFC !important;
    --block-border-color: rgba(200, 157, 69, 0.2) !important;
    --block-border-width: 1px !important;
    --input-background-fill: #FFFFFF !important;
    --input-border-color: rgba(148, 163, 184, 0.5) !important;
    --button-primary-background-fill: linear-gradient(90deg, #E2B659, #C89D45) !important;
    --button-primary-background-fill-hover: linear-gradient(90deg, #C89D45, #A37E30) !important;
    --button-primary-text-color: #FFFFFF !important;
    --button-secondary-background-fill: #F1F5F9 !important;
    --button-secondary-border-color: rgba(148, 163, 184, 0.5) !important;
    --button-secondary-text-color: #0F172A !important;
}

/* Force light backgrounds on all container-like components */
.custom-card, .gr-group, .gr-box, .gr-form, .block, .panel, .form {
    background-color: #F8FAFC !important;
    background: #F8FAFC !important;
    border: 1px solid rgba(200, 157, 69, 0.2) !important;
    border-radius: 16px !important;
    color: #0F172A !important;
}

/* Force light style on inputs, textboxes and dropdowns (excluding radios/checkboxes) */
input:not([type="radio"]):not([type="checkbox"]), select, textarea, .gr-input, .gr-input-label, .select-wrap, .dropdown, .choices__inner, .choices__list {
    background-color: #FFFFFF !important;
    background: #FFFFFF !important;
    color: #0F172A !important;
    border-color: rgba(148, 163, 184, 0.5) !important;
}

/* Checked radio selector inner dot fix */
input[type="radio"]:checked {
    background-color: #C89D45 !important;
    border-color: #C89D45 !important;
    background-image: radial-gradient(circle, #FFFFFF 35%, transparent 40%) !important;
}

/* Fix text and label colors */
span, label, p, .gr-text, .gr-input-label, .block-title, .section-title {
    color: #475569 !important;
}

.monospace-num {
    font-family: 'SF Pro Display', 'Courier New', monospace !important;
    font-weight: 700 !important;
    color: #C89D45 !important;
}

/* Style navigation tabs */
.tabs {
    border-bottom: 1px solid rgba(148, 163, 184, 0.3) !important;
    background: #FFFFFF !important;
}
.tab-nav button {
    color: #475569 !important;
    border-bottom: 2px solid transparent !important;
    font-weight: 600 !important;
}
.tab-nav button.selected {
    color: #C89D45 !important;
    border-bottom-color: #C89D45 !important;
    background: transparent !important;
}
.gr-button-primary {
    background: linear-gradient(90deg, #E2B659, #C89D45) !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 25px !important;
    box-shadow: 0 4px 15px rgba(226, 182, 89, 0.2) !important;
}
.gr-button-secondary {
    background: #F1F5F9 !important;
    color: #0F172A !important;
    border: 1px solid rgba(148, 163, 184, 0.5) !important;
    border-radius: 25px !important;
}
.gr-button-stop {
    background: #EF4444 !important;
    color: #FFFFFF !important;
    border-radius: 25px !important;
}
"""

theme = gr.themes.Soft(
    primary_hue="amber",
    secondary_hue="amber",
    neutral_hue="slate"
)

with gr.Blocks(theme=theme, css=custom_css, title="時光投資簿 timeVest") as app:
    # Force light theme class
    gr.HTML("<script>document.querySelector('body').classList.remove('dark');</script>")
    
    gr.HTML(
        """
        <div style='text-align: center; padding: 1rem 0; background: linear-gradient(135deg, #F8FAFC 0%, #E2E8F0 100%); border-bottom: 1px solid rgba(200, 157, 69, 0.3);'>
            <h1 style='color: #B48A2C; font-size: 1.8rem; font-weight: 800; margin: 0; letter-spacing: -0.5px;'>時光投資簿 timeVest</h1>
            <p style='color: #475569; font-size: 0.95rem; margin-top: 3px; font-weight: 400;'>Don't just track habits. Build your time assets.</p>
        </div>
        """
    )

    # Top Stats Dashboard Row
    with gr.Row(elem_classes="custom-card", equal_height=True):
        with gr.Column(scale=4):
            banner_view = gr.HTML(value=get_banner_html())
        with gr.Column(scale=6):
            allocation_view = gr.HTML(value=get_allocation_html())
        with gr.Column(scale=2, min_width=150):
            year_dropdown = gr.Dropdown(choices=["全部", "2026", "2025", "2024"], value="全部", label="選擇年份", interactive=True)
            month_dropdown = gr.Dropdown(choices=["全部", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"], value="全部", label="選擇月份", interactive=True)

    with gr.Tabs():
        # Tab 1: Circular Stopwatch Tracking Card (timer section)
        with gr.TabItem("專注計時"):
            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### 專注時間注入")

                # --- Account selector ---
                invest_dropdown = gr.Dropdown(
                    choices=get_investment_choices(),
                    label="選擇投資帳戶",
                    value=service.investments[0]["name"] if service.investments else None,
                    interactive=True
                )

                # --- Item selector (shown only when account has item_label) ---
                # Compute initial state
                _init_inv = service.investments[0] if service.investments else None
                _init_items = service.get_items(inv_id=_init_inv["id"], status="inProgress") if (_init_inv and _init_inv["item_label"]) else []
                _init_has_label = bool(_init_inv and _init_inv["item_label"])
                _init_label = _init_inv["item_label"] if _init_has_label else "項目"

                item_dropdown = gr.Dropdown(
                    choices=[it["name"] for it in _init_items] if _init_items else [],
                    label=f"選擇{_init_label}" if _init_has_label else "項目",
                    visible=_init_has_label and bool(_init_items),
                    interactive=True
                )

                # Warning: account has item_label but no in-progress items
                timer_item_warning = gr.HTML(
                    value=f"<div style='display:flex;align-items:center;gap:8px;padding:10px 14px;background:#FFF7ED;border:1px solid #FDBA74;border-radius:10px;font-size:13px;color:#92400E;'>⚠️ 目前無進行中的{_init_label}，請先新增。</div>" if (_init_has_label and not _init_items) else "",
                    visible=_init_has_label and not bool(_init_items)
                )

                # Inline quick-add (appears when no items)
                with gr.Group(visible=_init_has_label and not bool(_init_items)) as timer_quick_add_group:
                    with gr.Row():
                        timer_quick_item_name = gr.Textbox(label=f"新增{_init_label}", placeholder=f"輸入{_init_label}名稱…", scale=4)
                        timer_quick_add_btn = gr.Button("＋ 新增", variant="secondary", scale=1)

                # Action timer state
                stopwatch_display = gr.HTML(value=get_stopwatch_html("00:00"))
                timer_msg = gr.Textbox(label="當前狀態", value="準備投資", interactive=False)

                # Dynamic inputs during timer or settlement
                with gr.Group(visible=True) as settle_panel:
                    gr.Markdown("#### 結算投入進度")
                    settle_progress = gr.Textbox(label="當前進度 (頁數 / 百分比)", visible=False, placeholder="例如: 180 或 45")
                    settle_total = gr.Textbox(label="總頁數", visible=False, placeholder="例如: 300")
                    remarks = gr.Textbox(label="備忘備註", placeholder="寫下本次投入的重點...")

                with gr.Row():
                    start_btn = gr.Button("開始注入", variant="primary")
                    pause_btn = gr.Button("暫停", variant="secondary")
                    settle_btn = gr.Button("結算入帳", variant="stop")
                    discard_btn = gr.Button("放棄本次", variant="secondary")

                # Hidden Timer for tick
                stopwatch_trigger = gr.Timer(active=False, value=1)

        # Tab 2: Manual Entry
        with gr.TabItem("手動記錄"):
            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### 手動記錄投入")
                manual_invest_dropdown = gr.Dropdown(
                    choices=get_investment_choices(),
                    label="選擇投資帳戶",
                    value=service.investments[0]["name"] if service.investments else None
                )
                
                # Check initial items for default selection
                init_choices = []
                init_visible = False
                init_label = "項目"
                if service.investments:
                    default_inv = service.investments[0]
                    if default_inv["item_label"]:
                        init_choices = [it["name"] for it in service.get_items(inv_id=default_inv["id"], status="inProgress")]
                        init_visible = True
                        init_label = default_inv["item_label"]
                        
                manual_item_dropdown = gr.Dropdown(choices=init_choices, visible=init_visible, label=init_label)
                
                manual_start = gr.Textbox(label="開始時間 (YYYY-MM-DD HH:MM)", placeholder="例如: 2026-06-29 14:00")
                manual_end = gr.Textbox(label="結束時間 (YYYY-MM-DD HH:MM)", placeholder="例如: 2026-06-29 15:30")
                manual_remarks = gr.Textbox(label="投入備忘")
                manual_submit = gr.Button("手動入帳", variant="secondary")

        # Tab 3: Project Items management
        with gr.TabItem("項目管理"):
            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### 項目追蹤看板")
                with gr.Row():
                    items_inv_dropdown = gr.Dropdown(
                        choices=get_investment_choices(),
                        label="選擇投資帳戶",
                        value=service.investments[0]["name"] if service.investments else None
                    )
                    items_status_radio = gr.Radio(
                        choices=["inProgress", "completed", "paused"],
                        value="inProgress",
                        label="項目狀態"
                    )
                items_refresh_btn = gr.Button("整理列表", variant="secondary")
                items_display_html = gr.HTML()

            # Inline creator
            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### 新增追蹤項目")
                new_item_name = gr.Textbox(label="項目名稱", placeholder="如: 《深度工作力》")
                new_item_total = gr.Textbox(label="總頁數 (若無則不填)", placeholder="例如: 300")
                new_item_btn = gr.Button("建立新項目", variant="secondary")
                new_item_status = gr.Markdown()

        # Tab 4: Yields Timeline (Milestones & Reports)
        with gr.TabItem("投資收益"):
            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### 成果與報告")
                yields_tab_selector = gr.Radio(
                    choices=["成果匯報", "成果報告"],
                    value="成果匯報",
                    label="收益報告分類"
                )
                
                # Date filter for monthly summaries
                with gr.Row(visible=False) as report_date_row:
                    start_date_picker = gr.Textbox(label="開始日期 (YYYY-MM-DD)", value=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"))
                    end_date_picker = gr.Textbox(label="結束日期 (YYYY-MM-DD)", value=datetime.now().strftime("%Y-%m-%d"))
                
                yields_refresh_btn = gr.Button("整理報告", variant="secondary")
                yields_display_html = gr.HTML()

        # Tab 5: Spotify-Wrapped style Financial Statement
        with gr.TabItem("時光對帳單"):
            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### 自律對帳結算")
                statement_generate_btn = gr.Button("產生時光對帳單", variant="primary")
                statement_display_html = gr.HTML()

        # Tab 6: Account settings
        with gr.TabItem("帳戶管理"):
            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### 投資帳戶增刪")
                new_inv_name = gr.Textbox(label="帳戶名稱", placeholder="例如: 日常閱讀")
                new_inv_icon = gr.Dropdown(
                    choices=[
                        ("📖 書本 (book.fill)", "book.fill"),
                        ("🎸 吉他 (guitars.fill)", "guitars.fill"),
                        ("🏋️ 啞鈴 (dumbbell.fill)", "dumbbell.fill"),
                        ("🏃 跑步 (figure.run)", "figure.run"),
                        ("💻 電腦 (laptopcomputer)", "laptopcomputer")
                    ],
                    value="book.fill",
                    label="圖示"
                )
                new_inv_color = gr.ColorPicker(value="#E2B659", label="代表顏色")
                new_inv_prog = gr.Radio(choices=["pages", "percentage", "none"], value="none", label="進度模式")
                new_inv_label = gr.Textbox(label="項目標籤 (如: 書籍, 曲目, 課程) 空白則為時間累積型")
                
                add_inv_btn = gr.Button("開立新投資帳戶", variant="primary")
                
                delete_inv_dropdown = gr.Dropdown(
                    choices=get_investment_choices(),
                    label="選擇要銷戶的帳戶"
                )
                delete_inv_btn = gr.Button("銷戶並清空項目", variant="stop")
                
                settings_status = gr.Markdown()

    # Event handlers: Dropdown linkages
    invest_dropdown.change(
        fn=get_timer_item_panel_state,
        inputs=[invest_dropdown],
        outputs=[item_dropdown, timer_item_warning, timer_quick_add_group, timer_quick_item_name]
    )

    # Inline quick-add item from the Focus Timer tab
    def timer_quick_add_item(inv_name, item_name):
        inv = next((i for i in service.investments if i["name"] == inv_name), None)
        if not inv or not item_name.strip():
            return gr.update(), gr.update(), gr.update(), ""
        service.add_item(inv["id"], item_name.strip(), None)
        items = service.get_items(inv_id=inv["id"], status="inProgress")
        label = inv["item_label"] or "項目"
        return (
            gr.update(choices=[it["name"] for it in items], visible=True, label=f"選擇{label}"),
            gr.update(visible=False),
            gr.update(visible=False),
            ""
        )

    timer_quick_add_btn.click(
        fn=timer_quick_add_item,
        inputs=[invest_dropdown, timer_quick_item_name],
        outputs=[item_dropdown, timer_item_warning, timer_quick_add_group, timer_quick_item_name]
    )

    manual_invest_dropdown.change(
        fn=dynamic_update_items_dropdown,
        inputs=[manual_invest_dropdown],
        outputs=[manual_item_dropdown]
    )

    # Timer actions
    start_btn.click(
        fn=start_timer,
        inputs=[invest_dropdown, item_dropdown],
        outputs=[timer_msg]
    ).then(
        fn=lambda: gr.update(active=True),
        outputs=[stopwatch_trigger]
    )

    stopwatch_trigger.tick(
        fn=tick_timer,
        outputs=[stopwatch_display]
    )

    pause_btn.click(
        fn=pause_resume_timer,
        outputs=[timer_msg, pause_btn]
    )

    settle_btn.click(
        fn=check_timer_settle_fields,
        outputs=[settle_progress, settle_total]
    )

    # Confirm settle
    def complete_settle_workflow(progress_val, total_val, remarks_val, year_val, month_val):
        msg = settle_timer(progress_val, total_val, remarks_val)
        banner = get_banner_html(year_val, month_val)
        alloc = get_allocation_html(year_val, month_val)
        return msg, banner, alloc, gr.update(active=False), gr.update(visible=False), gr.update(visible=False), get_stopwatch_html("00:00"), "準備投資"

    settle_btn.click(
        fn=complete_settle_workflow,
        inputs=[settle_progress, settle_total, remarks, year_dropdown, month_dropdown],
        outputs=[timer_msg, banner_view, allocation_view, stopwatch_trigger, settle_progress, settle_total, stopwatch_display, timer_msg]
    )

    discard_btn.click(
        fn=discard_timer,
        outputs=[timer_msg]
    ).then(
        fn=lambda: (gr.update(active=False), get_stopwatch_html("00:00"), "準備投資"),
        outputs=[stopwatch_trigger, stopwatch_display, timer_msg]
    )

    # Refresh dashboard
    def update_dashboard(year, month):
        banner = get_banner_html(year, month)
        alloc = get_allocation_html(year, month)
        return banner, alloc

    year_dropdown.change(
        fn=update_dashboard,
        inputs=[year_dropdown, month_dropdown],
        outputs=[banner_view, allocation_view]
    )
    month_dropdown.change(
        fn=update_dashboard,
        inputs=[year_dropdown, month_dropdown],
        outputs=[banner_view, allocation_view]
    )

    # Manual entry
    def run_manual_entry(inv_name, item_name, start_s, end_s, rems):
        inv = next((i for i in service.investments if i["name"] == inv_name), None)
        if not inv:
            return "請選擇帳戶"
        item = None
        if inv["item_label"] and item_name:
            item = next((it for it in service.items if it["name"] == item_name), None)
            
        try:
            start_t = datetime.strptime(start_s.strip(), "%Y-%m-%d %H:%M")
            end_t = datetime.strptime(end_s.strip(), "%Y-%m-%d %H:%M")
            duration = int((end_t - start_t).total_seconds())
            if duration <= 0:
                return "結束時間必須晚於開始時間"
        except Exception as e:
            return f"時間格式錯誤: {e}"
            
        success, ms_list = service.log_activity(
            inv_id=inv["id"],
            item_id=item["id"] if item else None,
            duration_seconds=duration,
            detail=rems if rems else "手動記錄投入",
            start_time=start_t,
            end_time=end_t
        )
        msg = "手動登錄成功！"
        if ms_list:
            msg += "\n解鎖里程碑！" + "\n".join([item["title"] for item in ms_list])
        return msg

    manual_submit.click(
        fn=run_manual_entry,
        inputs=[manual_invest_dropdown, manual_item_dropdown, manual_start, manual_end, manual_remarks],
        outputs=[timer_msg]
    )

    # Tab 1 actions: Items List
    def refresh_items_view(inv_name, status):
        inv = next((i for i in service.investments if i["name"] == inv_name), None)
        if not inv:
            return "<div style='color: #475569; text-align: center; padding: 20px;'>請選擇帳戶</div>"
        return get_items_summary_html(inv["id"], status)

    items_refresh_btn.click(
        fn=refresh_items_view,
        inputs=[items_inv_dropdown, items_status_radio],
        outputs=[items_display_html]
    )

    new_item_btn.click(
        fn=add_new_item_option,
        inputs=[items_inv_dropdown, new_item_name, new_item_total],
        outputs=[new_item_status]
    ).then(
        fn=dynamic_update_all_items_dropdown,
        outputs=[item_dropdown]
    )

    # Tab 2 actions: Yields
    def toggle_yields_date_pickers(tab):
        if tab == "成果報告":
            return gr.update(visible=True)
        return gr.update(visible=False)

    yields_tab_selector.change(
        fn=toggle_yields_date_pickers,
        inputs=[yields_tab_selector],
        outputs=[report_date_row]
    )

    def generate_yields_report(tab, start_d, end_d):
        if tab == "成果匯報":
            return get_milestone_list_html(m_type="completion")
        else:
            return get_milestone_list_html(m_type="monthlyAchievement", start_date=start_d.strip(), end_date=end_d.strip())

    yields_refresh_btn.click(
        fn=generate_yields_report,
        inputs=[yields_tab_selector, start_date_picker, end_date_picker],
        outputs=[yields_display_html]
    )

    # Tab 3 actions: Wrapped Statement
    statement_generate_btn.click(
        fn=get_statement_html,
        outputs=[statement_display_html]
    )

    # Tab 4 actions: Settings
    add_inv_btn.click(
        fn=add_new_investment_option,
        inputs=[new_inv_name, new_inv_icon, new_inv_color, new_inv_prog, new_inv_label],
        outputs=[invest_dropdown, settings_status]
    ).then(
        fn=lambda: (
            gr.update(choices=get_investment_choices()),
            gr.update(choices=get_investment_choices()),
            gr.update(choices=get_investment_choices())
        ),
        outputs=[delete_inv_dropdown, items_inv_dropdown, manual_invest_dropdown]
    )

    delete_inv_btn.click(
        fn=delete_investment_option,
        inputs=[delete_inv_dropdown],
        outputs=[invest_dropdown, settings_status]
    ).then(
        fn=lambda: (
            gr.update(choices=get_investment_choices()),
            gr.update(choices=get_investment_choices()),
            gr.update(choices=get_investment_choices())
        ),
        outputs=[delete_inv_dropdown, items_inv_dropdown, manual_invest_dropdown]
    )

# Background initial Garmin Sync
def run_initial_sync():
    try:
        print("Starting initial Garmin sync in background...")
        status = sync_garmin_activities(client, TABLE_ID)
        print(f"Garmin Sync complete: {status}")
    except Exception as e:
        print(f"Garmin sync failed: {e}")

threading.Thread(target=run_initial_sync, daemon=True).start()

app.launch(server_name="0.0.0.0")
