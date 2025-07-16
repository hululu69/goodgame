import pandas as pd
import time
import os

REPORTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'reports')
os.makedirs(REPORTS_DIR, exist_ok=True)

def export_to_csv(url, changes, keywords, additional_results=None, summary=None):
    """
    Exports monitoring data to a CSV file.
    Can handle individual scan data or summary data.
    """
    if summary:
        # Export summary data
        data = []
        for site in summary.get('monitored_sites', []):
            data.append({
                "timestamp": time.ctime(),
                "url": site['url'],
                "last_scraped": site.get('last_scraped', 'N/A'),
                "last_changed": site.get('last_changed', 'N/A'),
                "status": site.get('status', 'N/A'),
                "keywords": ', '.join(site.get('keywords', [])),
                "changes_length": site.get('changes_length', 0),
                "keyword_count": site.get('keyword_count', 0),
                "backlink_count": site.get('backlink_count', 0)
            })
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"monitoring_summary_{timestamp}.csv"
        log_file = os.path.join(REPORTS_DIR, filename)
        
        df = pd.DataFrame(data)
        df.to_csv(log_file, index=False, encoding='utf-8-sig')
        print(f"Summary data exported to {log_file}")
        return log_file
    else:
        # Export individual scan data
        additional_results = additional_results or []
        data = [{
            "timestamp": time.ctime(),
            "url": url,
            "keywords_found": ", ".join(keywords),
            "change_summary": changes[:500].replace('\n', ' ').replace('\r', ' '), # Sanitize changes for CSV
            "additional_links_keywords": "; ".join([f"{r['url']}: {', '.join(r['found_keywords'])}" for r in additional_results]),
            "post_count": len([r for r in additional_results if r.get("post_keywords")]) # Assuming 'post_keywords' might be in future 'additional_results'
        }]
        
        # Create individual CSV file for this scan
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_url = url.replace('/', '_').replace(':', '_').replace('?', '_')[:50]
        filename = f"scan_{safe_url}_{timestamp}.csv"
        log_file = os.path.join(REPORTS_DIR, filename)

        df = pd.DataFrame(data)
        df.to_csv(log_file, index=False, encoding='utf-8-sig')
        print(f"Data for {url} exported to {log_file}")
        return log_file