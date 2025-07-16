import requests
from bs4 import BeautifulSoup
import os
import hashlib
import time
import re
import socket
from urllib.parse import urljoin, urlparse

ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), '..', 'store', 'archive')
MAX_ATTEMPTS = 5
DEFAULT_WAIT = 5

os.makedirs(ARCHIVE_DIR, exist_ok=True)

def get_session(is_onion):
    """
    Returns a requests session configured for Clearnet or Tor.
    """
    session = requests.session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    }
    session.headers.update(headers)
    if is_onion:
        session.proxies.update({
            'http': 'socks5h://127.0.0.1:9050',
            'https': 'socks5h://127.0.0.1:9050'
        })
    return session, ("Tor" if is_onion else "Clearnet")

def is_queue_page(html_content):
    """
    Checks if the HTML content indicates a queue or waiting page.
    """
    return bool(re.search(r'queue|waiting|please wait|javascript refresh|cloudflare', str(html_content).lower()))

def sanitize_filename(url):
    """
    Sanitizes a URL to be used as a filename by hashing it.
    """
    return hashlib.md5(url.encode('utf-8')).hexdigest()

def save_content(content, url):
    """
    Saves the HTML content to a file in the archive directory.
    """
    filename = sanitize_filename(url) + ".html"
    path = os.path.join(ARCHIVE_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path

def scrape_and_save(url, section=None, login_url=None, login_payload=None):
    """
    Scrapes the given URL, handles retries, and saves the content.
    Returns the HTML content, file path, and status code.
    """
    is_onion = '.onion' in url
    session, session_type = get_session(is_onion)
    attempt = 0
    wait_time = DEFAULT_WAIT
    timeout = 60 if not is_onion else 90

    print(f"[{session_type}] Scraping: {url}")

    # Handle login if credentials are provided
    if login_url and login_payload:
        try:
            print(f"Attempting to login at {login_url}")
            import json
            payload_dict = json.loads(login_payload)
            login_res = session.post(login_url, data=payload_dict, timeout=timeout)
            login_res.raise_for_status()
            if login_res.ok:
                print(f"Login successful for session targeting {url}")
            else:
                print(f"Login failed with status {login_res.status_code}. Scraping might fail.")
        except Exception as e:
            print(f"An error occurred during login: {e}. Proceeding without login.")

    while attempt < MAX_ATTEMPTS:
        try:
            res = session.get(url, timeout=timeout)
            if res.status_code == 404:
                print(f"[404] URL not found: {url}. Skipping permanently.")
                return None, None, 404
            res.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
            soup = BeautifulSoup(res.text, 'lxml')

            if is_onion and is_queue_page(soup):
                print(f"[Queue] Waiting for {url} {wait_time}s...")
                time.sleep(wait_time)
                wait_time *= 2
                attempt += 1
                continue

            content = soup.find(id=section) if section else soup
            if not content:
                print(f"[Error] No content found for section '{section}' or overall for {url}.")
                content = soup 
                if not content:
                    raise Exception("Unable to extract any content from the page.")


            html = str(content)
            path = save_content(html, url)
            print(f"[Success] Saved: {path}")
            return html, path, res.status_code

        except (requests.exceptions.RequestException, socket.gaierror) as e:
            print(f"[Attempt {attempt + 1}/{MAX_ATTEMPTS}] Error scraping {url}: {e}")
            attempt += 1
            time.sleep(wait_time)
            wait_time *= 2
        except Exception as e:
            print(f"[Error] An unexpected error occurred while scraping {url}: {e}")
            return None, None, 500 # Generic error status

    print(f"[Failed] Max attempts reached for {url}.")
    return None, None, 500