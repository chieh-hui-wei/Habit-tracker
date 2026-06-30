import os
import json
import uuid
import datetime
from zoneinfo import ZoneInfo
from google.cloud import bigquery
from google.api_core.exceptions import NotFound
import pandas as pd


# JSON database files
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
INVESTMENTS_FILE = os.path.join(DATA_DIR, "investments.json")
ITEMS_FILE = os.path.join(DATA_DIR, "items.json")
MILESTONES_FILE = os.path.join(DATA_DIR, "milestones.json")

# Default seed data matching SwiftUI project
DEFAULT_INVESTMENTS = [
    {
        "id": "e2b65900-1111-2222-3333-444455556666",
        "name": "日常閱讀",
        "icon": "book.fill",
        "color": "#E2B659",
        "item_label": "書籍",
        "progress_type": "pages",
        "total_duration": 0
    }
]

# Helper functions to load/save JSON
def load_json(file_path, default_data):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
        return default_data
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return default_data

def save_json(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Error saving {file_path}: {e}")

# Service class for database & metadata
class TimeVestService:
    def __init__(self, bq_client, table_id):
        self.bq_client = bq_client
        self.table_id = table_id
        
        # Load local configs
        self.investments = load_json(INVESTMENTS_FILE, DEFAULT_INVESTMENTS)
        self.items = load_json(ITEMS_FILE, [])
        self.milestones = load_json(MILESTONES_FILE, [])

    def upgrade_schema(self):
        """Checks and adds item tracking columns to BigQuery schema if they don't exist."""
        try:
            table = self.bq_client.get_table(self.table_id)
            existing_names = {field.name for field in table.schema}
            new_fields = []
            
            if "item_name" not in existing_names:
                new_fields.append(bigquery.SchemaField("item_name", "STRING"))
            if "progress_snapshot" not in existing_names:
                new_fields.append(bigquery.SchemaField("progress_snapshot", "FLOAT"))
            if "total_pages" not in existing_names:
                new_fields.append(bigquery.SchemaField("total_pages", "FLOAT"))
                
            if new_fields:
                table.schema = table.schema + new_fields
                self.bq_client.update_table(table, ["schema"])
                print("BigQuery schema upgraded with item tracking fields successfully.")
        except Exception as e:
            print(f"Warning: BigQuery schema upgrade check failed: {e}")

    # --- Investments ---
    def get_investments(self):
        return self.investments

    def add_investment(self, name, icon, color, item_label=None, progress_type="none"):
        new_inv = {
            "id": str(uuid.uuid4()),
            "name": name,
            "icon": icon,
            "color": color,
            "item_label": item_label if item_label else None,
            "progress_type": progress_type,
            "total_duration": 0
        }
        self.investments.append(new_inv)
        save_json(INVESTMENTS_FILE, self.investments)
        return new_inv

    def delete_investment(self, inv_id):
        self.investments = [inv for inv in self.investments if inv["id"] != inv_id]
        save_json(INVESTMENTS_FILE, self.investments)
        # Cascade deletion to items
        self.items = [item for item in self.items if item["investment_id"] != inv_id]
        save_json(ITEMS_FILE, self.items)

    # --- Items ---
    def get_items(self, inv_id=None, status=None):
        items_list = self.items
        if inv_id:
            items_list = [item for item in items_list if item["investment_id"] == inv_id]
        if status:
            items_list = [item for item in items_list if item["status"] == status]
        return items_list

    def add_item(self, inv_id, name, total=None):
        new_item = {
            "id": str(uuid.uuid4()),
            "investment_id": inv_id,
            "name": name,
            "total": total,
            "progress": 0.0,
            "status": "inProgress", # inProgress, completed, paused
            "created_at": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
        }
        self.items.append(new_item)
        save_json(ITEMS_FILE, self.items)
        return new_item

    def set_item_status(self, item_id, status):
        for item in self.items:
            if item["id"] == item_id:
                item["status"] = status
                break
        save_json(ITEMS_FILE, self.items)

    def delete_item(self, item_id):
        self.items = [item for item in self.items if item["id"] != item_id]
        save_json(ITEMS_FILE, self.items)

    # --- Activities & Milestone triggers ---
    def log_activity(self, inv_id, item_id, duration_seconds, detail, start_time, end_time, progress_snapshot=None):
        # 1. Insert to BigQuery
        inv = next((i for i in self.investments if i["id"] == inv_id), None)
        item = next((it for it in self.items if it["id"] == item_id), None) if item_id else None
        
        row_id = str(uuid.uuid4())
        rows_to_insert = [
            {
                "id": row_id,
                "habit_name": inv["name"] if inv else "未知",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_second": duration_seconds,
                "detail": detail,
                "item_name": item["name"] if item else None,
                "progress_snapshot": progress_snapshot,
                "total_pages": item["total"] if item else None
            }
        ]
        
        errors = self.bq_client.insert_rows_json(self.table_id, rows_to_insert)
        if errors:
            print(f"Error logging to BQ: {errors}")
            return False, f"BigQuery error: {errors}"

        # 2. Update item progress locally
        prev_progress = 0.0
        if item and progress_snapshot is not None:
            prev_progress = item["progress"]
            item["progress"] = min(progress_snapshot, 1.0)
            if item["progress"] >= 1.0 and prev_progress < 1.0:
                item["status"] = "completed"
            save_json(ITEMS_FILE, self.items)

        # 3. Check and unlock Milestones
        new_milestones = self.check_milestones(inv, item, prev_progress, duration_seconds)
        
        return True, new_milestones

    def check_milestones(self, inv, item, prev_progress, new_duration):
        newly_unlocked = []
        now_str = datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
        
        # A. Completion Milestone
        if item and item["progress"] >= 1.0 and prev_progress < 1.0:
            m = {
                "id": str(uuid.uuid4()),
                "title": f"項目結清：《{item['name']}》",
                "description": f"《{item['name']}》已成功轉化為個人專注資產！",
                "type": "completion",
                "investment_id": inv["id"] if inv else None,
                "date_unlocked": now_str
            }
            self.milestones.append(m)
            newly_unlocked.append(m)

        # B. Month-end summary checks (run dynamically based on BQ logs)
        # We save milestones locally to cache them
        save_json(MILESTONES_FILE, self.milestones)
        return newly_unlocked

    # --- Stats & Query Summaries ---
    def get_portfolio_summary(self, year=None, month=None):
        # We query BigQuery for overall stats to avoid drift
        where_clause = "WHERE 1=1"
        if year:
            where_clause += f" AND EXTRACT(YEAR FROM start_time) = {year}"
        if month:
            where_clause += f" AND EXTRACT(MONTH FROM start_time) = {month}"

        query = f"""
            SELECT SUM(duration_second) as total_sec, COUNT(DISTINCT DATE(start_time)) as active_days
            FROM `{self.table_id}`
            {where_clause}
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            val = df['total_sec'].iloc[0]
            if val is None or pd.isna(val):
                total_hours = 0.0
            else:
                total_hours = float(val) / 3600.0
            
            # calculate active days as simple streak or count
            active_val = df['active_days'].iloc[0]
            if active_val is None or pd.isna(active_val):
                active_days = 0
            else:
                active_days = int(active_val)
        except Exception as e:
            print(f"BQ query failed: {e}")
            total_hours = 0.0
            active_days = 0

        # Calculate streak (consecutive days including today)
        streak = self.calculate_streak()

        # Calculate today's duration
        today_start = datetime.datetime.now(ZoneInfo("Asia/Taipei")).replace(hour=0, minute=0, second=0, microsecond=0)
        query_today = f"""
            SELECT SUM(duration_second) as today_sec
            FROM `{self.table_id}`
            WHERE start_time >= '{today_start.isoformat()}'
        """
        try:
            df_today = self.bq_client.query(query_today).to_dataframe()
            val_today = df_today['today_sec'].iloc[0]
            if val_today is None or pd.isna(val_today):
                today_hours = 0.0
            else:
                today_hours = float(val_today) / 3600.0
        except Exception as e:
            print(f"BQ query today failed: {e}")
            today_hours = 0.0

        return {
            "total_hours": total_hours,
            "today_hours": today_hours,
            "streak_days": streak,
            "active_days": active_days
        }

    def calculate_streak(self):
        query = f"""
            SELECT DISTINCT DATE(start_time) as date
            FROM `{self.table_id}`
            ORDER BY date DESC
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            if df.empty:
                return 0
            dates = [datetime.datetime.strptime(str(d), "%Y-%m-%d").date() for d in df['date']]
            
            today = datetime.date.today()
            yesterday = today - datetime.timedelta(days=1)
            
            if dates[0] != today and dates[0] != yesterday:
                return 0
                
            streak = 1
            for i in range(len(dates) - 1):
                diff = dates[i] - dates[i+1]
                if diff.days == 1:
                    streak += 1
                elif diff.days > 1:
                    break
            return streak
        except Exception as e:
            print(f"Streak calculation failed: {e}")
            return 0

    def get_allocation(self, year=None, month=None):
        where_clause = "WHERE 1=1"
        if year:
            where_clause += f" AND EXTRACT(YEAR FROM start_time) = {year}"
        if month:
            where_clause += f" AND EXTRACT(MONTH FROM start_time) = {month}"

        query = f"""
            SELECT habit_name, SUM(duration_second) as total_sec
            FROM `{self.table_id}`
            {where_clause}
            GROUP BY habit_name
        """
        allocations = []
        try:
            df = self.bq_client.query(query).to_dataframe()
            total_sec = float(df['total_sec'].sum())
            if total_sec > 0:
                for _, row in df.iterrows():
                    inv = next((i for i in self.investments if i["name"] == row['habit_name']), None)
                    pct = float(row['total_sec']) / total_sec
                    allocations.append({
                        "name": row['habit_name'],
                        "hours": float(row['total_sec']) / 3600.0,
                        "percentage": pct,
                        "color": inv["color"] if inv else "#94A3B8"
                    })
        except Exception as e:
            print(f"Allocation calculation failed: {e}")
        return allocations

    def check_and_generate_monthly_summaries(self):
        """Automatically checks BQ for monthly summaries, clears old duplicates, and creates rich quantified summaries."""
        # 1. Clear existing automatically generated monthlyAchievement milestones to prevent duplicates
        self.milestones = [m for m in self.milestones if m.get("type") != "monthlyAchievement"]

        # 2. Check completed items milestones (成果型) from items.json
        for item in self.items:
            if item.get("status") == "completed":
                inv = next((i for i in self.investments if i["id"] == item["investment_id"]), None)
                milestone_title = f"項目結清：《{item['name']}》"
                if not any(m["title"] == milestone_title for m in self.milestones):
                    label = inv["item_label"] if inv and inv["item_label"] else "項目"
                    m = {
                        "id": str(uuid.uuid4()),
                        "title": milestone_title,
                        "description": f"卓越的成果！你已成功結算【{inv['name'] if inv else '自我投資'}】中的 {label}——《{item['name']}》！",
                        "type": "completion",
                        "investment_id": item["investment_id"],
                        "date_unlocked": item.get("completed_at", datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat())
                    }
                    self.milestones.append(m)

        query = f"""
            SELECT 
                FORMAT_TIMESTAMP('%Y-%m', start_time) as month,
                habit_name,
                item_name,
                detail,
                MAX(progress_snapshot) as max_prog,
                SUM(duration_second) as duration_sec
            FROM `{self.table_id}`
            GROUP BY month, habit_name, item_name, detail
            ORDER BY month DESC
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            if df.empty:
                return

            import collections
            by_month = collections.defaultdict(list)
            for _, row in df.iterrows():
                by_month[row['month']].append(row)

            def get_unit_by_label(label):
                if not label:
                    return "個"
                if "書" in label:
                    return "本"
                if "曲" in label:
                    return "首"
                if "課" in label:
                    return "門"
                if "運" in label or "健身" in label:
                    return "次"
                return "項"

            def normalize_habit_name(name):
                if "閱讀" in name:
                    return "閱讀"
                if "健身" in name or "Gym" in name or "Strength" in name:
                    return "健身"
                if "吉他" in name:
                    return "吉他"
                return name

            for month_str, rows in sorted(by_month.items(), reverse=True):
                total_sec = sum(r['duration_sec'] for r in rows)
                total_hours = total_sec / 3600.0

                habit_groups = collections.defaultdict(list)
                for r in rows:
                    norm_name = normalize_habit_name(r['habit_name'])
                    habit_groups[norm_name].append(r)

                desc_parts = [f"在 {month_str} 中，你累計向自我專注投資了 {total_hours:.1f} 小時，穩步增值你的時間資產。"]

                for habit_name, r_list in habit_groups.items():
                    inv = next((i for i in self.investments if i["name"] == habit_name), None)
                    if habit_name == "吉他" and not inv:
                        inv = {"name": "吉他", "item_label": "曲目", "progress_type": "percentage"}

                    if not inv or not inv.get("item_label"):
                        sub_sec = sum(r['duration_sec'] for r in r_list)
                        desc_parts.append(f"• {habit_name}：投入 {sub_sec/3600.0:.1f} 小時。")
                        continue

                    label = inv["item_label"]
                    unit = get_unit_by_label(label)

                    completed_items = []
                    inprogress_items = []

                    for r in r_list:
                        it_name = r['item_name'] or r['detail']
                        if not it_name or any(keyword in it_name for keyword in ["投入", "北歐時間", "Garmin", "準備投資"]):
                            continue

                        is_completed = False
                        if r['max_prog'] is not None and float(r['max_prog']) >= 1.0:
                            is_completed = True

                        if is_completed:
                            completed_items.append(it_name)
                        else:
                            inprogress_items.append(it_name)

                    sub_sec = sum(r['duration_sec'] for r in r_list)
                    habit_desc = f"• {habit_name}：投入 {sub_sec/3600.0:.1f} 小時"

                    detail_pieces = []
                    if completed_items:
                        detail_pieces.append(f"已完成 {len(completed_items)} {unit}{label}（{', '.join(completed_items)}）")
                    if inprogress_items:
                        detail_pieces.append(f"投入 {len(inprogress_items)} {unit}{label}（{', '.join(inprogress_items)}）")

                    if detail_pieces:
                        habit_desc += "，" + "；".join(detail_pieces) + "。"
                    else:
                        habit_desc += "。"

                    desc_parts.append(habit_desc)

                description = "\n".join(desc_parts)

                m = {
                    "id": str(uuid.uuid4()),
                    "title": f"📊 {month_str} 資產月報",
                    "description": description,
                    "type": "monthlyAchievement",
                    "investment_id": None,
                    "date_unlocked": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
                }
                self.milestones.append(m)

            self.milestones.sort(key=lambda x: x["date_unlocked"], reverse=True)
            save_json(MILESTONES_FILE, self.milestones)
        except Exception as e:
            print(f"Monthly summary engine failed: {e}")

    def get_activities_by_range(self, start_date, end_date, habit_name):
        query = f"""
            SELECT id, start_time, habit_name, detail, item_name, progress_snapshot, total_pages, duration_second
            FROM `{self.table_id}`
            WHERE DATE(start_time) >= '{start_date}' AND DATE(start_time) <= '{end_date}'
              AND habit_name = '{habit_name}'
            ORDER BY start_time DESC
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            # Clean up NaN / NaT for JSON serialization
            df = df.where(pd.notnull(df), None)
            # Convert start_time timestamp to string
            df['start_time'] = df['start_time'].apply(lambda x: str(x) if x else None)
            return df.to_dict('records')
        except Exception as e:
            print(f"Error fetching activities: {e}")
            return []

    def update_historical_activity(self, row_id, start_date, item_name, progress_snapshot, total_pages, detail):
        prog_sql = f"{progress_snapshot}" if progress_snapshot is not None else "NULL"
        tot_sql = f"{total_pages}" if total_pages is not None else "NULL"
        item_sql = f"'{item_name}'" if item_name else "NULL"
        detail_sql = f"'{detail}'" if detail else "NULL"

        query = f"""
            UPDATE `{self.table_id}`
            SET item_name = {item_sql},
                progress_snapshot = {prog_sql},
                total_pages = {tot_sql},
                detail = {detail_sql}
            WHERE id = '{row_id}' AND DATE(start_time) = '{start_date}'
        """
        try:
            query_job = self.bq_client.query(query)
            query_job.result()
            return True, "歷史紀錄已成功更新！"
        except Exception as e:
            print(f"Error updating BQ row: {e}")
            return False, f"更新失敗：{e}"
