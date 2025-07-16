import os
import json
import pandas as pd
import plotly.express as px
from backend.monitor import LOG_FILE, DATA_DIR
from backend.export import REPORTS_DIR

def generate_trend_plot(url):
    """Generate a Plotly trend plot for posts and keywords."""
    try:
        # Load monitoring log
        log_data = {}
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                log_data = json.load(f).get(url, {})

        # Load scan data
        scans = log_data.get("scans", [])
        if not scans:
            return None

        df = pd.DataFrame(scans)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')

        # Create a line plot for posts and keywords
        fig = px.line(df, x='timestamp', y=['post_count', 'keyword_count'],
                      title=f"Post and Keyword Trends for {url}",
                      labels={'value': 'Count', 'variable': 'Metric'},
                      hover_data=['changes_length', 'backlink_count'])
        fig.update_layout(
            xaxis_title="Timestamp",
            yaxis_title="Count",
            legend_title="Metric",
            hovermode="x unified"
        )
        return fig
    except Exception as e:
        print(f"Error generating trend plot for {url}: {e}")
        return None