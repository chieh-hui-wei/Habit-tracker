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
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from garmin_integration import sync_garmin_activities

load_dotenv()

# ----------------------
# BIGQUERY SETUP
# ----------------------
# Configuration (Recommended: set these as environment variables)
PROJECT_ID = os.environ.get("BQ_PROJECT_ID")
DATASET_ID = os.environ.get("BQ_DATASET_ID")
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
            bigquery.SchemaField("detail", "STRING"),
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
# HABIT LIST MANAGEMENT
# ----------------------
HABITS_FILE = "habits.json"
DEFAULT_HABITS = ["閱讀", "吉他", "健身", "烏克麗麗", "冥想", "走路", "讀經文"]


def load_habits():
    import json
    if os.path.exists(HABITS_FILE):
        try:
            with open(HABITS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_HABITS
    else:
        try:
            with open(HABITS_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_HABITS, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
        return DEFAULT_HABITS


def save_habits(habits):
    import json
    try:
        with open(HABITS_FILE, "w", encoding="utf-8") as f:
            json.dump(habits, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Error saving habits: {e}")


def add_habit_fn(new_habit):
    new_habit = new_habit.strip()
    if not new_habit:
        current = load_habits()
        return (
            gr.Dropdown(choices=current),
            gr.Dropdown(choices=current),
            "",
            "❌ Habit name cannot be empty.",
        )

    habits = load_habits()
    if new_habit in habits:
        return (
            gr.Dropdown(choices=habits),
            gr.Dropdown(choices=habits),
            "",
            "⚠️ Habit already exists in the list.",
        )

    habits.append(new_habit)
    save_habits(habits)
    return (
        gr.Dropdown(choices=habits, value=new_habit),
        gr.Dropdown(choices=habits),
        "",
        f"✅ Successfully added habit: '{new_habit}'",
    )


def delete_habit_fn(habit_to_delete):
    if not habit_to_delete:
        current = load_habits()
        return (
            gr.Dropdown(choices=current),
            gr.Dropdown(choices=current),
            "❌ Please select a habit to delete.",
        )

    habits = load_habits()
    if habit_to_delete not in habits:
        return (
            gr.Dropdown(choices=habits),
            gr.Dropdown(choices=habits),
            f"❌ Habit '{habit_to_delete}' not found.",
        )

    habits.remove(habit_to_delete)
    save_habits(habits)
    return (
        gr.Dropdown(choices=habits, value=None),
        gr.Dropdown(choices=habits, value=None),
        f"🗑️ Successfully deleted habit: '{habit_to_delete}'",
    )


# ----------------------
# UI
# ----------------------
custom_css = """
.header-container {
    background: linear-gradient(135deg, #6366f1 0%, #3b82f6 100%);
    padding: 2.5rem 2rem;
    border-radius: 16px;
    text-align: center;
    color: white;
    box-shadow: 0 10px 25px rgba(59, 130, 246, 0.15);
    margin-bottom: 2rem;
}
.header-container h1 {
    font-size: 2.6rem;
    font-weight: 800;
    margin: 0 0 0.5rem 0;
    letter-spacing: -0.5px;
    color: #ffffff;
}
.header-container p {
    font-size: 1.1rem;
    opacity: 0.9;
    margin: 0;
    font-weight: 400;
}
.custom-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
    border: 1px solid #e2e8f0;
    margin-bottom: 1.5rem !important;
}
.dark .custom-card {
    background: #1e293b;
    border-color: #334155;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
}
"""

theme = gr.themes.Soft(
    primary_hue="indigo",
    secondary_hue="blue",
    neutral_hue="slate",
    font=[gr.themes.GoogleFont("Outfit"), "sans-serif"],
).set(
    button_primary_background_fill="linear-gradient(90deg, #6366f1, #3b82f6)",
    button_primary_background_fill_hover="linear-gradient(90deg, #4f46e5, #2563eb)",
    button_primary_text_color="white",
    block_title_text_weight="600",
    block_border_width="1px",
    block_shadow="0 4px 6px -1px rgba(0, 0, 0, 0.05)",
)

with gr.Blocks(theme=theme, css=custom_css) as app:
    gr.HTML(
        """
        <div class="header-container">
            <h1>🧠 Habit Tracker</h1>
            <p>Track your daily habits, visualize your dedication, and build a better version of yourself.</p>
        </div>
        """
    )

    initial_habits = load_habits()

    with gr.Row(equal_height=False):
        # LEFT COLUMN: Log Current Activity & Track Automatically
        with gr.Column(scale=2, min_width=350):
            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### 📍 Log Current Activity")
                habit_input = gr.Dropdown(
                    choices=initial_habits,
                    label="Habit Name",
                    value=initial_habits[0] if initial_habits else None,
                    interactive=True
                )
                detail = gr.Textbox(
                    label="Detail",
                    placeholder="e.g. Book name, workout muscle, song...",
                )

            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### ⏱️ Track Automatically")
                with gr.Row():
                    start_btn = gr.Button("▶️ Start Session", variant="primary")
                    stop_btn = gr.Button("⏹️ Stop & Save", variant="stop")

            with gr.Group(elem_classes="custom-card"):
                gr.Markdown("### ✍️ Manual Entry")
                manual_start = gr.Textbox(
                    label="Start Time",
                    placeholder="YYYY-MM-DD HH:MM",
                )
                manual_end = gr.Textbox(
                    label="End Time",
                    placeholder="YYYY-MM-DD HH:MM",
                )
                manual_submit = gr.Button("📥 Submit Manual Entry", variant="secondary")

            status = gr.Textbox(
                label="System Status",
                value="System idle...",
                interactive=False
            )

        # RIGHT COLUMN: Report & Logs & Settings
        with gr.Column(scale=3, min_width=450):
            with gr.Tabs():
                with gr.TabItem("📊 Report Chart"):
                    with gr.Group(elem_classes="custom-card"):
                        gr.Markdown("### 📈 Time Spent Visualization")
                        with gr.Row():
                            period = gr.Radio(
                                choices=["week", "month"],
                                value="week",
                                label="Time Period",
                                interactive=True
                            )
                            plot_btn = gr.Button("🔄 Generate Chart", variant="primary")
                        plot_output = gr.Plot(label="Time Distribution")

                with gr.TabItem("📋 Detailed Logs"):
                    with gr.Group(elem_classes="custom-card"):
                        gr.Markdown("### 🕒 Recently Logged Habits")
                        load_btn = gr.Button("🔄 Refresh Logs Table", variant="primary")
                        table = gr.Dataframe(interactive=False)

                with gr.TabItem("⚙️ Habit List Settings"):
                    with gr.Group(elem_classes="custom-card"):
                        gr.Markdown("### 🛠️ Add or Remove Habit Options")
                        with gr.Row():
                            with gr.Column():
                                new_habit_input = gr.Textbox(
                                    label="Add New Habit Option",
                                    placeholder="e.g. 寫程式, 慢跑, 瑜伽...",
                                )
                                add_habit_btn = gr.Button("➕ Add to List", variant="primary")
                            with gr.Column():
                                delete_habit_dropdown = gr.Dropdown(
                                    choices=initial_habits,
                                    label="Select Habit to Remove",
                                )
                                delete_habit_btn = gr.Button("🗑️ Remove from List", variant="stop")
                        manage_status = gr.Markdown()

    # Event handlers
    start_btn.click(start_habit, inputs=[habit_input, detail], outputs=status)
    stop_btn.click(stop_habit, outputs=status)

    manual_submit.click(
        fn=insert_manual_habit,
        inputs=[habit_input, detail, manual_start, manual_end],
        outputs=status,
    )

    add_habit_btn.click(
        fn=add_habit_fn,
        inputs=[new_habit_input],
        outputs=[habit_input, delete_habit_dropdown, new_habit_input, manage_status],
    )

    delete_habit_btn.click(
        fn=delete_habit_fn,
        inputs=[delete_habit_dropdown],
        outputs=[habit_input, delete_habit_dropdown, manage_status],
    )

    load_btn.click(load_data, outputs=table)
    plot_btn.click(fn=plot_report, inputs=period, outputs=plot_output)

# ----------------------
# RUN
# ----------------------
app.launch(server_name="0.0.0.0")
