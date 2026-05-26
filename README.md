# 🧠 Habit Tracker

A personal habit tracker built with **Gradio** and **Google BigQuery**. It features a modern two-column SaaS analytics layout, dynamic habit choices management with local persistence, automatic session timing, manual time logging, and beautiful Matplotlib analytics charts.

---

## Features
### Flexible Choice Management
* **Dynamic Editing**: Easily add or delete habits directly from the web browser under the **Habit List Settings** tab.
* **Persistent Storage**: Dynamic changes are persisted locally in `habits.json` and synchronized across all dropdowns instantly.

### BigQuery Performance Architecture
* **Daily Partitioning**: Optimized BigQuery schema partitioned on `start_time` to dramatically reduce query costs over large historical sets.
* **Clustering by Habit**: Clustered on `habit_name` to make group-by aggregations and habit-specific searches ultra-fast.
* **Buffered Insertion**: Handled via rapid JSON streaming insertions.

---

## Getting Started

### Prerequisites

* **Python 3.10+**
* **Google Cloud Platform (GCP) Project** with BigQuery enabled and a service account key JSON file.
* **System Fonts**: To display Matplotlib charts correctly with Chinese text:
  * Ubuntu/Debian: `sudo apt install fonts-wqy-zenhei fonts-wqy-microhei`

---

### Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/chieh-hui-wei/Habit-tracker.git
   cd Habit-tracker
   ```

2. **Install Dependencies**:
   You can run the provided installer or install them manually:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Set up your GCP BigQuery configurations (e.g. in your `.env` or shell profile):
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your GCP credentials.

---

## Usage

### Running the App

Start the server using Python:
```bash
python3 app.py
```
Open the local URL printed in your terminal (usually `http://127.0.0.1:7860`).

### Dashboard Guide

1. **Start Tracking automatically**:
   Select a habit from the dropdown (e.g., `健身`), add any details (e.g., `Leg Day`), and click **Start Session**. When you are finished, click **Stop & Save** to automatically compute the duration and log it to BigQuery.
2. **Submit Manual Entries**:
   Input a start time and end time matching `YYYY-MM-DD HH:MM` and click **Submit Manual Entry**.
3. **Customize your Habits list**:
   Navigate to the **Habit List Settings** tab. Use the left column to add new habits (e.g., `寫程式`), or the right dropdown to remove choices you no longer need.
4. **View Logs & Charts**:
   Under the **Report Chart** tab, select a timeframe (week/month) and click **Generate Chart** to update the Matplotlib time distribution. Check the **Detailed Logs** tab to view your raw log history.

---

## License

This project is licensed under the [MIT License](LICENSE).
