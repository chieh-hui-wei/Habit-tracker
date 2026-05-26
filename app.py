import gradio as gr
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
from google.cloud import bigquery
from google.api_core.exceptions import NotFound
from google.oauth2 import service_account
import uuid
from zoneinfo import ZoneInfo

# ----------------------
# BIGQUERY SETUP
# ----------------------
# Configuration (Recommended: set these as environment variables)
PROJECT_ID = os.environ.get("BQ_PROJECT_ID", "vm-20260413")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "habit")
TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.habit_logs"
credentials_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

credentials = service_account.Credentials.from_service_account_file(
    credentials_path
)

client = bigquery.Client(project=PROJECT_ID, credentials=credentials)


def setup_bigquery():
    """Initializes dataset and table with partitioning and clustering."""
    # Ensure dataset exists
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "asia-east1"  # or your preferred region
        client.create_dataset(dataset)
        print(f"Created dataset {DATASET_ID}")

    # Ensure table exists with optimization
    try:
        client.get_table(TABLE_ID)
    except NotFound:
        schema = [
            bigquery.SchemaField(
                "id", "STRING"
            ),  # Manual ID or use TIMESTAMP for uniqueness
            bigquery.SchemaField("habit_name", "STRING"),
            bigquery.SchemaField("start_time", "TIMESTAMP"),
            bigquery.SchemaField("end_time", "TIMESTAMP"),
            bigquery.SchemaField("duration_second", "INTEGER"),
        ]
        table = bigquery.Table(TABLE_ID, schema=schema)

        # OPTIMIZATION: Partitioning by start_time (reduces scan cost for date filters)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field="start_time"
        )

        # OPTIMIZATION: Clustering by habit_name (optimizes GROUP BY and habit filters)
        table.clustering_fields = ["habit_name"]

        client.create_table(table)
        print(f"Created table {TABLE_ID} with partitioning and clustering.")


setup_bigquery()

# ----------------------
# STATE
# ----------------------
current_session = {}


# ----------------------
# CORE FUNCTIONS
# ----------------------
def start_habit(habit_name, detail):
    global current_session

    start_time = datetime.now(ZoneInfo("Asia/Taipei"))

    current_session = {
        "habit_name": habit_name,
        "start_time": start_time,
        "detail": detail,
    }

    return f"Started: {habit_name} at {start_time.strftime('%Y-%m-%d %H:%M:%S')}"


def stop_habit():
    global current_session

    if not current_session:
        return "No active session"

    end_time = datetime.now(ZoneInfo("Asia/Taipei"))
    start_time = current_session["start_time"]
    duration = int((end_time - start_time).total_seconds())

    rows_to_insert = [
        {
            "id": str(uuid.uuid4()),
            "habit_name": current_session["habit_name"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "detail": current_session["detail"],
            "duration_second": duration,
        }
    ]

    errors = client.insert_rows_json(TABLE_ID, rows_to_insert)
    if errors:
        return f"Error inserting data: {errors}"

    current_session = {}

    duration = int((end_time - start_time).total_seconds())

    return (
        f"Stopped: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Duration: {format_duration(duration)}"
    )


# ----------------------
# VIEW DATA
# ----------------------
def load_data():
    # Optimization: Filter by last 7 days + limit to reduce scan volume
    now = datetime.now()
    start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    query = f"""
        SELECT habit_name, start_time, end_time, duration_second , detail
        FROM `{TABLE_ID}` 
        WHERE start_time >= '{start_date}'
        ORDER BY start_time DESC 
        LIMIT 10
    """
    df = client.query(query).to_dataframe()

    if df.empty:
        return df

    # convert seconds → human readable
    def fmt(sec):
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60

        parts = []
        if h > 0:
            parts.append(f"{h}h")
        if m > 0:
            parts.append(f"{m}m")
        parts.append(f"{s}s")
        return " ".join(parts)

    df["duration"] = df["duration_second"].apply(fmt)

    return df


# ----------------------
# ANALYTICS
# ----------------------
def get_report(period=None):
    now = datetime.now()
    where_clause = ""

    # OPTIMIZATION: SQL-level filtering so we don't scan the whole table
    if period == "week":
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        where_clause = f"WHERE start_time >= '{start_date}'"
    elif period == "month":
        start_date = now.replace(day=1).strftime("%Y-%m-%d")
        where_clause = f"WHERE start_time >= '{start_date}'"

    query = f"""
        SELECT habit_name, SUM(duration_second) as total_duration, COUNT(*) as count
        FROM `{TABLE_ID}`
        {where_clause}
        GROUP BY habit_name
        ORDER BY total_duration DESC
    """
    df = client.query(query).to_dataframe()

    if df.empty:
        return df

    # -----------------------------
    # Format duration
    # -----------------------------
    def fmt(sec):
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60

        parts = []
        if h > 0:
            parts.append(f"{h}h")
        if m > 0:
            parts.append(f"{m}m")
        parts.append(f"{s}s")

        return " ".join(parts)

    df["total_time"] = df["total_duration"].apply(fmt)

    # -----------------------------
    # Sort
    # -----------------------------
    df = df.sort_values("total_duration", ascending=False)

    # -----------------------------
    # Final output
    # -----------------------------
    return df[["habit_name", "count", "total_time"]]


def plot_report(period):
    #plt.rcParams['font.family'] = 'sans-serif'
    #plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei']
    plt.rcParams['axes.unicode_minus'] = False
    # Specify the path to WenQuanYi Zen Hei font
    font_path = (
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"  # Update the path if necessary
    )
    import matplotlib.font_manager as fm

    # Create a FontProperties object
    prop = fm.FontProperties(fname=font_path)
    
    # Set global font family to WenQuanYi Zen Hei
    plt.rcParams["font.family"] = prop.get_name()
    
    now = datetime.now()
    where_clause = ""

    # OPTIMIZATION: SQL-level filtering
    if period == "week":
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        where_clause = f"WHERE start_time >= '{start_date}'"
    elif period == "month":
        start_date = now.replace(day=1).strftime("%Y-%m-%d")
        where_clause = f"WHERE start_time >= '{start_date}'"

    query = f"""
        SELECT habit_name, SUM(duration_second) as total_duration
        FROM `{TABLE_ID}`
        {where_clause}
        GROUP BY habit_name
    """
    result = client.query(query).to_dataframe()

    if result.empty:
        return None

    # convert to hours
    result["hours"] = result["total_duration"] / 3600
    result = result.sort_values("hours", ascending=False)

    # -----------------------------
    # Plot
    # -----------------------------
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.bar(result["habit_name"], result["hours"], color="skyblue", width=0.3)

    ax.set_title(f"Habit Time ({period})")
    ax.set_xlabel("Habit")
    ax.set_ylabel("Hours")

    # labels
    for i, h in enumerate(result["hours"]):
        ax.text(i, h, f"{h:.1f}h", ha="center")

    plt.tight_layout()

    return fig


def format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if hours > 0:
        parts.append(f"{hours} hr")
    if minutes > 0:
        parts.append(f"{minutes} min")
    parts.append(f"{secs} sec")

    return " ".join(parts)


def insert_manual_habit(habit_name, detail, start_str, end_str):
    try:
        start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
        end_time = datetime.strptime(end_str, "%Y-%m-%d %H:%M")

        duration = int((end_time - start_time).total_seconds())

        if duration < 0:
            return "❌ End time must be after start time"

        row = {
            "id": str(uuid.uuid4()),
            "habit_name": habit_name,
            "detail": detail,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_second": duration,
        }

        errors = client.insert_rows_json(TABLE_ID, [row])

        if errors:
            return f"❌ Error: {errors}"

        return "✅ Inserted successfully"

    except Exception as e:
        return f"❌ Invalid input: {e}"


# ----------------------
# UI
# ----------------------
with gr.Blocks() as app:
    gr.Markdown("# 🧠 Habit Tracker")

    with gr.Row():
        habit_input = gr.Dropdown(
            choices=["健身", "閱讀", "烏克麗麗", "吉他", "冥想", "走路"],
            label="Habit Name",
        )
        detail = gr.Textbox(label="Detail (書名/訓練部位/歌曲)")
    with gr.Row():
        with gr.Column():
            gr.Markdown("## Track automatically")
            with gr.Row():
                with gr.Column():
                    start_btn = gr.Button("Start")
                    stop_btn = gr.Button("Stop")
        with gr.Column():
            gr.Markdown("## Manual Entry")
            with gr.Row():
                manual_start = gr.Textbox(label="Start Time (YYYY-MM-DD HH:MM)")
                manual_end = gr.Textbox(label="End Time (YYYY-MM-DD HH:MM)")

            manual_submit = gr.Button("Submit")

    status = gr.Textbox(label="Status")

    start_btn.click(start_habit, inputs=[habit_input, detail], outputs=status)
    stop_btn.click(stop_habit, outputs=status)

    manual_submit.click(
        fn=insert_manual_habit,
        inputs=[habit_input, detail, manual_start, manual_end],
        outputs=status,
    )

    gr.Markdown("## 📋 Logs")
    load_btn = gr.Button("Refresh Logs")
    table = gr.Dataframe()

    load_btn.click(load_data, outputs=table)

    gr.Markdown("## 📊 Report")
    period = gr.Radio(["week", "month"], value="week")
    # report_btn = gr.Button("Generate Report")
    # report_table = gr.Dataframe()

    # report_btn.click(get_report, inputs=period, outputs=report_table)

    plot_btn = gr.Button("📊 Show Report Chart")
    plot_output = gr.Plot()

    plot_btn.click(fn=plot_report, inputs=period, outputs=plot_output)

# ----------------------
# RUN
# ----------------------
app.launch(server_name="0.0.0.0")
