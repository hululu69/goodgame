import time
import os
import re
from difflib import unified_diff
from bs4 import BeautifulSoup
from selectolax.parser import HTMLParser
import hashlib
from backend.scraper import scrape_and_save
from backend.alert import alert_user
from backend.export import export_to_csv
from backend.pdf_report import generate_pdf_report
import json
import numpy as np
from urllib.parse import urljoin
import sqlite3
import logging
from datetime import datetime
from backend.llm_analyzer import analyze_with_llm
from backend.vector_store import add_to_vector_store

# --- Configuration ---
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'store')
LOG_FILE = os.path.join(DATA_DIR, "monitoring_log.json")
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'urls.db')
ARCHIVE_DIR = os.path.join(DATA_DIR, 'archive')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def init_db():
    """
    Initializes the SQLite database.
    Checks for and adds new columns to the urls table if they are missing.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create the table if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            keywords TEXT,
            last_scraped TEXT,
            last_changed TEXT,
            status TEXT
        )
    ''')

    # Check for and add new columns to support login functionality
    cursor.execute("PRAGMA table_info(urls)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'login_url' not in columns:
        cursor.execute('ALTER TABLE urls ADD COLUMN login_url TEXT')
        logging.info("Added 'login_url' column to the database.")
    if 'login_payload' not in columns:
        cursor.execute('ALTER TABLE urls ADD COLUMN login_payload TEXT')
        logging.info("Added 'login_payload' column to the database.")
    if 'last_scraped' not in columns:
        cursor.execute('ALTER TABLE urls ADD COLUMN last_scraped TEXT') 
        logging.info("Added 'last_scraped' column to the database.")
    if 'last_changed' not in columns:
        cursor.execute('ALTER TABLE urls ADD COLUMN last_changed TEXT')
        logging.info("Added 'last_changed' column to the database.")    
    if 'status' not in columns:
        cursor.execute('ALTER TABLE urls ADD COLUMN status TEXT')
        logging.info("Added 'status' column to the database.")
    if 'alias' not in columns:
        cursor.execute('ALTER TABLE urls ADD COLUMN alias TEXT')
        logging.info("Added 'alias' column to the database.")
    
    conn.commit()
    conn.close()

def get_clean_text(html_content):
    """Extracts clean text from HTML content."""
    soup = BeautifulSoup(html_content, 'lxml')
    for script_or_style in soup(['script', 'style']):
        script_or_style.extract()
    text = soup.get_text(separator=' ', strip=True)
    return text

def check_keywords(text_content, keywords):
    """Enhanced keyword checking with better pattern matching."""
    if not keywords or not text_content:
        return []
    
    found = []
    text_lower = text_content.lower()
    
    for kw in keywords:
        kw_lower = kw.lower()
        # Check for exact word boundaries
        if re.search(r'\b' + re.escape(kw_lower) + r'\b', text_lower):
            found.append(kw)
        # Also check for partial matches in compound words
        elif kw_lower in text_lower and len(kw_lower) > 3:
            found.append(kw)
    
    return found

def enumerate_backlinks(html_content, base_url, keywords):
    """Extracts backlinks and checks for keywords in their anchor text."""
    parser = HTMLParser(html_content)
    links_data = []
    for node in parser.css('a'):
        href = node.attrs.get('href')
        if href:
            full_url = urljoin(base_url, href)
            if full_url.startswith(('http://', 'https://', 'onion://')):
                link_text = node.text(strip=True)
                found_kw = check_keywords(link_text, keywords)
                if found_kw:
                    links_data.append({'url': full_url, 'text': link_text, 'found_keywords': found_kw})
    return links_data

def extract_forum_posts(html_content):
    """
    Enhanced extraction of structured post data from HTML using multiple strategies.
    """
    posts = []
    parser = HTMLParser(html_content)
    
    # Strategy 1: Enhanced forum/marketplace selectors
    post_selectors = {
        'container': [
            'div.post', 'article.message', 'li.post', 'div.thread-post', 'div.comment',
            'div.message', 'div.topic', 'div.entry', 'div.item', 'div.listing',
            'tr.row', 'div.post-wrapper', 'div.forum-post', 'div.thread-item',
            'div[class*="post"]', 'div[class*="message"]', 'div[class*="comment"]',
            'div[class*="thread"]', 'div[class*="topic"]', 'div[class*="entry"]'
        ],
        'author': [
            '.author', '.username', 'a[data-user-id]', '.user-name', '.comment-author',
            '.poster', '.by', '.member', '.user', '.name', '.creator',
            'span[class*="author"]', 'span[class*="user"]', 'a[class*="user"]',
            'div[class*="author"]', 'div[class*="user"]'
        ],
        'content': [
            '.post-body', '.message-content', '.entry-content', '.post-content', '.comment-body',
            '.content', '.text', '.body', '.description', '.message', '.post-text',
            'div[class*="content"]', 'div[class*="body"]', 'div[class*="text"]',
            'p', 'div.text', 'span.text'
        ],
        'title': [
            '.post-title', '.thread-title', 'h1', 'h2', 'h3', 'h4', '.title',
            '.subject', '.heading', '.header', 'div[class*="title"]',
            'span[class*="title"]', 'a[class*="title"]'
        ]
    }

    # Strategy 1: Try structured extraction
    for container_selector in post_selectors['container']:
        post_elements = parser.css(container_selector)
        if post_elements:
            for post_el in post_elements:
                post_data = {}
                
                # Extract author
                author = "Unknown"
                for author_selector in post_selectors['author']:
                    author_node = post_el.css_first(author_selector)
                    if author_node:
                        author = author_node.text(strip=True)
                        if author:
                            break
                post_data['author'] = author

                # Extract content
                content = ""
                for content_selector in post_selectors['content']:
                    content_node = post_el.css_first(content_selector)
                    if content_node:
                        content = content_node.text(strip=True)
                        if content and len(content) > 20:  # Only accept substantial content
                            break
                
                # If no content found in specific selectors, try the whole element
                if not content or len(content) < 20:
                    content = post_el.text(strip=True)
                
                post_data['content'] = content if content else "No content found"

                # Extract title
                title = ""
                for title_selector in post_selectors['title']:
                    title_node = post_el.css_first(title_selector)
                    if title_node:
                        title = title_node.text(strip=True)
                        if title:
                            break
                
                # If no title found, try to extract from content (first line)
                if not title and content:
                    first_line = content.split('\n')[0].strip()
                    if len(first_line) < 100:  # Reasonable title length
                        title = first_line
                
                post_data['title'] = title if title else "No title found"
                
                # Add to list if content is substantial
                if post_data['content'] != "No content found" and len(post_data['content']) > 20:
                    posts.append(post_data)
            
            if posts:
                logging.info(f"Extracted {len(posts)} posts using container selector '{container_selector}'")
                break
    
    # Strategy 2: Fallback - Extract from common text blocks
    if not posts:
        # Try to extract from paragraphs and divs with substantial text
        text_elements = parser.css('p, div')
        potential_posts = []
        
        for element in text_elements:
            text = element.text(strip=True)
            if text and len(text) > 50:  # Substantial text content
                # Try to find author in nearby elements
                author = "Unknown"
                parent = element.parent
                if parent:
                    for auth_sel in post_selectors['author']:
                        auth_node = parent.css_first(auth_sel)
                        if auth_node:
                            author = auth_node.text(strip=True)
                            if author:
                                break
                
                potential_posts.append({
                    'author': author,
                    'content': text,
                    'title': text.split('\n')[0].strip()[:100] if text else "No title"
                })
        
        # Remove duplicates and take top posts
        seen_content = set()
        for post in potential_posts:
            if post['content'] not in seen_content:
                posts.append(post)
                seen_content.add(post['content'])
                if len(posts) >= 20:  # Limit to reasonable number
                    break
        
        if posts:
            logging.info(f"Extracted {len(posts)} posts using fallback strategy")
    
    # Strategy 3: Last resort - extract from all text content
    if not posts:
        all_text = parser.text(strip=True)
        if all_text and len(all_text) > 100:
            # Split by double newlines or common separators
            sections = re.split(r'\n\s*\n|\n-{3,}|\n={3,}', all_text)
            for i, section in enumerate(sections):
                section = section.strip()
                if len(section) > 50:
                    posts.append({
                        'author': f"User_{i+1}",
                        'content': section,
                        'title': section.split('\n')[0][:100] if section else f"Section {i+1}"
                    })
                    if len(posts) >= 10:  # Limit fallback posts
                        break
        
        if posts:
            logging.info(f"Extracted {len(posts)} posts using last resort text splitting")
    
    return posts

def monitor_job(url_id, url, keywords, login_url=None, login_payload=None):
    """
    The main monitoring job: scrapes, compares, analyzes, and reports.
    """
    start_time = time.time()
    logging.info(f"Starting monitor job for URL ID: {url_id}, URL: {url}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 1. Fetch previous content
        previous_html_content = None
        previous_filename = hashlib.md5(url.encode('utf-8')).hexdigest() + ".html"
        previous_path = os.path.join(ARCHIVE_DIR, previous_filename)
        if os.path.exists(previous_path):
            with open(previous_path, 'r', encoding='utf-8') as f:
                previous_html_content = f.read()

        # 2. Scrape current content
        logging.info(f"Scraping {url}...")
        current_html_content, current_archive_path, status_code = scrape_and_save(url, login_url=login_url, login_payload=login_payload)
        
        if current_html_content is None:
            status = f"Failed to scrape (HTTP {status_code})"
            cursor.execute("UPDATE urls SET status = ?, last_scraped = ? WHERE id = ?", (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status, url_id))
            conn.commit()
            logging.error(f"Failed to scrape {url}. Status code: {status_code}")
            return

        current_text = get_clean_text(current_html_content)
        found_keywords_in_page = check_keywords(current_text, keywords)
        logging.info(f"Keywords found on {url}: {found_keywords_in_page}")

        # 3. Compare content (Diffing)
        raw_diff = ""
        changes_detected = False
        if previous_html_content:
            previous_text = get_clean_text(previous_html_content)
            diff_lines = unified_diff(previous_text.splitlines(keepends=True), current_text.splitlines(keepends=True))
            raw_diff = "".join(diff_lines)
            if raw_diff:
                changes_detected = True
                logging.info(f"Changes detected for {url}.")
            else:
                logging.info(f"No significant text changes for {url}.")
        else:
            logging.info(f"No previous content for {url} to compare.")

        # 4. Enumerate Backlinks, Extract Posts & Find New Posts with Keywords
        backlinks_with_keywords = enumerate_backlinks(current_html_content, url, keywords)
        extracted_posts = extract_forum_posts(current_html_content)
        
        new_posts_with_keywords = []
        if previous_html_content:
            previous_posts = extract_forum_posts(previous_html_content)
            # Create a set of previous post contents for efficient lookup (use hash for large content)
            previous_post_hashes = set()
            for post in previous_posts:
                content_hash = hashlib.md5(post['content'].encode('utf-8')).hexdigest()
                previous_post_hashes.add(content_hash)
            
            newly_found_posts = []
            for post in extracted_posts:
                content_hash = hashlib.md5(post['content'].encode('utf-8')).hexdigest()
                if content_hash not in previous_post_hashes:
                    newly_found_posts.append(post)
            
            for post in newly_found_posts:
                # Check for keywords in both title and content
                title_keywords = check_keywords(post.get('title', ''), keywords)
                content_keywords = check_keywords(post['content'], keywords)
                all_found_keywords = list(set(title_keywords + content_keywords))
                
                if all_found_keywords:
                    new_posts_with_keywords.append({
                        "post": post,
                        "found_keywords": all_found_keywords
                    })
            
            if new_posts_with_keywords:
                logging.info(f"Found {len(new_posts_with_keywords)} new posts with keywords for {url}.")

        # 5. LLM Analysis with Posts Data
        logging.info(f"Generating LLM report for {url}...")
        keyword_data = {"page_keywords": found_keywords_in_page, "backlink_keywords": backlinks_with_keywords}
        markdown_content, llm_report_path = analyze_with_llm(url, raw_diff, keyword_data, extracted_posts) # <-- Pass posts here
        
        if markdown_content and not markdown_content.startswith("Error"):
            add_to_vector_store(url, markdown_content, llm_report_path)
            logging.info(f"LLM report for {url} added to vector store.")
        else:
            logging.warning(f"Skipping vector store for {url} due to LLM analysis error.")

        # 6. Generate PDF and CSV Reports
        pdf_report_path = generate_pdf_report(url, found_keywords_in_page, raw_diff, current_archive_path, backlinks_with_keywords)
        csv_report_path = export_to_csv(url, raw_diff, found_keywords_in_page, backlinks_with_keywords)

        # 7. Alert User if needed
        alert_message = ""
        if new_posts_with_keywords:
            post_titles = [p['post'].get('title', 'Untitled') for p in new_posts_with_keywords]
            alert_message += f"NEW POST: Relevant content found in posts titled: {', '.join(post_titles)}\n"
        if changes_detected: alert_message += "Content changes detected.\n"
        if found_keywords_in_page: alert_message += f"Keywords on page: {', '.join(found_keywords_in_page)}\n"
        if backlinks_with_keywords: alert_message += f"Keywords in backlinks found.\n"
        if extracted_posts and not new_posts_with_keywords: alert_message += f"Extracted {len(extracted_posts)} posts (no new keyword matches).\n"
        if alert_message:
            alert_user(url, found_keywords_in_page, alert_message.strip())

        # 8. Update Database Status
        status = "No Changes"
        last_changed = None
        if new_posts_with_keywords:
            status = "Alert Triggered" # New posts with keywords found
            last_changed = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        elif changes_detected:
            status = "New Changes" # Only content changes, no new keyword-related posts
            last_changed = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        update_query = "UPDATE urls SET last_scraped = ?, status = ?"
        params = [datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status]
        if last_changed:
            update_query += ", last_changed = ?"
            params.append(last_changed)
        update_query += " WHERE id = ?"
        params.append(url_id)
        cursor.execute(update_query, tuple(params))
        conn.commit()

        # 9. Update monitoring_log.json for UI display
        log_data = {}
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                try: log_data = json.load(f)
                except json.JSONDecodeError: log_data = {}
        
        if url not in log_data: log_data[url] = {"scans": []}
        
        log_data[url]["scans"].append({
            "timestamp": datetime.now().isoformat(),
            "changes_length": len(raw_diff),
            "keyword_count": len(found_keywords_in_page),
            "backlink_count": len(backlinks_with_keywords),
            "post_count": len(extracted_posts),
            "new_posts_with_keywords": new_posts_with_keywords,
            "extracted_posts": extracted_posts,
            "llm_report_path": llm_report_path,
            "pdf_report_path": pdf_report_path,
            "csv_report_path": csv_report_path,
            "raw_diff": raw_diff,
            "found_keywords": found_keywords_in_page,
            "additional_results": backlinks_with_keywords
        })
        log_data[url]["scans"] = sorted(log_data[url]["scans"], key=lambda x: x['timestamp'], reverse=True)[:10]

        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=4)

        logging.info(f"Monitor job completed for {url}. Status: {status}")

    except Exception as e:
        logging.error(f"Error in monitor_job for {url}: {e}", exc_info=True)
        cursor.execute("UPDATE urls SET status = ? WHERE id = ?", (f"Error: {str(e)}", url_id))
        conn.commit()
    finally:
        conn.close()
        end_time = time.time()
        logging.info(f"Total time for {url}: {end_time - start_time:.2f} seconds.")

def get_site_details(site_id, url):
    """Retrieves detailed monitoring info for a URL from the log file and DB."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM urls WHERE id = ?", (site_id,))
    db_info_tuple = cursor.fetchone()
    if not db_info_tuple:
        conn.close()
        return None
    
    # Create a dictionary from the tuple
    db_info = dict(zip([c[0] for c in cursor.description], db_info_tuple))
    conn.close()
    
    site_data = db_info
    site_data['keywords'] = site_data['keywords'].split(', ') if site_data['keywords'] else []

    log_data = {}
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            try: log_data = json.load(f).get(url, {})
            except json.JSONDecodeError: pass
    
    site_data.update(log_data)
    return site_data

def get_all_sites():
    """Retrieves all monitored sites from the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM urls")
    sites = cursor.fetchall()
    conn.close()
    
    # Convert Row objects to dictionaries
    sites_list = [dict(s) for s in sites]
    for site in sites_list:
        site['keywords'] = site['keywords'].split(', ') if site['keywords'] else []
        
    return sites_list

def get_monitoring_summary():
    """Provides a summary of all monitored URLs."""
    sites = get_all_sites()
    summary = {
        "total_sites": len(sites),
        "sites_with_changes": len([s for s in sites if s['status'] in ["Changes Detected", "Alert Triggered", "New Post Found", "New Changes"]]),
        "monitored_sites": []
    }
    for site in sites:
        site_details = get_site_details(site['id'], site['url'])
        latest_scan = {}
        if site_details and 'scans' in site_details and site_details['scans']:
            latest_scan = max(site_details['scans'], key=lambda x: x['timestamp'])

        summary['monitored_sites'].append({
            "url": site['url'], "status": site.get('status', 'N/A'),
            "last_scraped": site.get('last_scraped', 'N/A'),
            "last_changed": site.get('last_changed', 'N/A'),
            "keywords": site['keywords'],
            "changes_length": latest_scan.get('changes_length', 0),
            "keyword_count": latest_scan.get('keyword_count', 0),
            "backlink_count": latest_scan.get('backlink_count', 0),
            "post_count": latest_scan.get('post_count', 0),
        })
    return summary
