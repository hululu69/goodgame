import os
import time
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib import colors
import html
import re
from urllib.parse import urlparse

REPORTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'reports'))
os.makedirs(REPORTS_DIR, exist_ok=True)

def sanitize_diff(changes):
    """Sanitizes diff content for display in PDF."""
    if not changes or not changes.strip():
        return "No content changes detected since the last scan."

    sanitized = []
    # Skip diff headers and only show actual changes
    for line in changes.splitlines():
        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
            continue
        # Limit line length to avoid issues with very long lines in PDF
        if len(line) > 200:
            line = line[:200] + "..."
        sanitized.append(line)

    if not sanitized:
        return "No meaningful content changes detected."

    return '\n'.join(sanitized[:100]) # Limit to first 100 lines of sanitized diff

def generate_pdf_report(url, keywords, changes, archive_path, additional_results=None):
    """
    Generates a PDF report summarizing monitoring activities.
    """
    print(f"Generating PDF report for {url}")
    additional_results = additional_results or []
    
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    safe_url_name = re.sub(r'[^a-zA-Z0-9_.-]', '', urlparse(url).netloc)
    report_path = os.path.join(REPORTS_DIR, f"{safe_url_name}_{timestamp}_report.pdf")

    doc = SimpleDocTemplate(report_path, pagesize=A4)
    styles = getSampleStyleSheet()
    
    # --- FIX: Check if styles exist before adding them ---
    if 'Justify' not in styles:
        styles.add(ParagraphStyle(name='Justify', alignment=TA_LEFT))
    if 'Code' not in styles:
        styles.add(ParagraphStyle(name='Code', fontName='Courier', fontSize=8, leading=9, textColor=colors.black))

    story = []

    # Title
    story.append(Paragraph(f"Dark Web Monitoring Report for: {url}", styles['h1']))
    story.append(Spacer(1, 12))

    # Summary
    story.append(Paragraph(f"Report Date: {time.ctime()}", styles['Normal']))
    story.append(Paragraph(f"Monitored URL: {url}", styles['Normal']))
    story.append(Paragraph(f"Keywords Monitored: {', '.join(keywords) if keywords else 'None'}", styles['Normal']))
    story.append(Spacer(1, 12))

    # Detected Changes
    story.append(Paragraph("Detected Changes (Sanitized Diff)", styles['h2']))
    sanitized_changes = sanitize_diff(changes)
    if sanitized_changes.startswith("No"):
        story.append(Paragraph(sanitized_changes, styles['Justify']))
    else:
        formatted_changes = ""
        for line in sanitized_changes.splitlines():
            if line.startswith('+'):
                line = f'<font color=\"green\">{html.escape(line)}</font>'
            elif line.startswith('-'):
                line = f'<font color=\"red\">{html.escape(line)}</font>'
            else:
                line = html.escape(line)
            formatted_changes += line + '<br/>'
        story.append(Paragraph(formatted_changes, styles['Code']))
    story.append(Spacer(1, 12))

    # Additional Links Scanned (Backlinks)
    story.append(Paragraph("Additional Links Scanned (Backlinks with Keyword Hits)", styles['h2']))
    if additional_results:
        for result in additional_results:
            story.append(Paragraph(f"URL: <font color=\"blue\"><u>{result['url']}</u></font>", styles['Normal']))
            story.append(Paragraph(f"Keywords Found: {', '.join(result['found_keywords'])}", styles['Normal']))
            story.append(Paragraph(f"Anchor Text Snippet: {result['text'][:100]}...", styles['Normal']))
            story.append(Spacer(1, 8))
    else:
        story.append(Paragraph("No additional links with keywords found during this scan.", styles['Justify']))
    story.append(Spacer(1, 12))
    
    try:
        doc.build(story)
        print(f"PDF report generated and saved to: {report_path}")
        return report_path
    except Exception as e:
        print(f"Failed to generate PDF report for {url}: {e}")
        return None