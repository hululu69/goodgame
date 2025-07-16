import streamlit as st
import requests
import os
import json
from datetime import datetime
import time
import pandas as pd
import plotly.express as px
import threading
from typing import Dict, List, Optional

# --- Configuration ---
API_BASE_URL = "http://127.0.0.1:8000"  # URL of your FastAPI backend

# --- Streamlit App ---
st.set_page_config(layout="wide", page_title="Kautilya: Dark Web Monitoring Tool")

# --- Session State Initialization ---
if 'selected_site_id' not in st.session_state:
    st.session_state.selected_site_id = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = {}
if 'global_chat_history' not in st.session_state:
    st.session_state.global_chat_history = []
if 'auto_scan_active' not in st.session_state:
    st.session_state.auto_scan_active = False
if 'auto_scan_thread' not in st.session_state:
    st.session_state.auto_scan_thread = None
if 'scan_frequency' not in st.session_state:
    st.session_state.scan_frequency = 60  # Default 60 minutes
if 'selected_sites_for_auto_scan' not in st.session_state:
    st.session_state.selected_sites_for_auto_scan = []
if 'edit_mode' not in st.session_state:
    st.session_state.edit_mode = {}
# Add a threading event to control the worker
if 'auto_scan_stop_event' not in st.session_state:
    st.session_state.auto_scan_stop_event = None

# --- API Helper Functions ---
def api_request(method, endpoint, **kwargs):
    """Helper function to make API requests."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        if response.content:
            return response.json()
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"API Error: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.RequestException as e:
        st.error(f"Connection Error: Could not connect to the backend at {url}. Is it running?")
    return None

# --- Automated Scanning Functions ---
def auto_scan_worker(sites_to_scan: List[int], frequency_minutes: int, stop_event: threading.Event):
    """Worker function for automated scanning in a background thread."""
    while not stop_event.is_set():
        try:
            # Scan selected sites
            for site_id in sites_to_scan:
                if stop_event.is_set():
                    break
                
                # Trigger scan for this specific site
                api_request("post", f"/scan/site/{site_id}")
                
            # Wait for the specified frequency, but check the stop event periodically
            sleep_time = int(frequency_minutes * 60)
            # Check the stop event every second for a responsive stop
            for _ in range(sleep_time):
                if stop_event.is_set():
                    break
                time.sleep(1)
                
        except Exception as e:
            st.error(f"Auto-scan error: {e}")
            break

def start_auto_scan():
    """Start automated scanning."""
    if not st.session_state.selected_sites_for_auto_scan:
        st.warning("Please select at least one site for automated scanning.")
        return
    
    st.session_state.auto_scan_active = True
    # Create and store the stop event
    st.session_state.auto_scan_stop_event = threading.Event()
    
    st.session_state.auto_scan_thread = threading.Thread(
        target=auto_scan_worker, 
        args=(
            st.session_state.selected_sites_for_auto_scan, 
            st.session_state.scan_frequency,
            st.session_state.auto_scan_stop_event  # Pass the event to the thread
        ),
        daemon=True
    )
    st.session_state.auto_scan_thread.start()
    st.success(f"Automated scanning started for {len(st.session_state.selected_sites_for_auto_scan)} sites every {st.session_state.scan_frequency} minutes.")
    st.rerun()

def stop_auto_scan():
    """Stop automated scanning."""
    if st.session_state.auto_scan_stop_event:
        # Signal the event to stop the thread
        st.session_state.auto_scan_stop_event.set()
    
    st.session_state.auto_scan_active = False
    st.session_state.auto_scan_thread = None
    st.session_state.auto_scan_stop_event = None
    st.success("Automated scanning stopped.")
    st.rerun()

# --- UI Components ---
def display_site_card(site):
    """Displays a card with information about a monitored site."""
    site_id = site['id']
    is_edit_mode = st.session_state.edit_mode.get(site_id, False)
    
    card_header = site.get('alias') or site['url']

    if is_edit_mode:
        # Edit mode
        st.markdown(f"#### ✏️ Editing: {card_header}")
        
        with st.form(key=f"edit_form_{site_id}"):
            edited_alias = st.text_input("Alias (Optional)", value=site.get('alias', ''))
            edited_url = st.text_input("URL", value=site['url'])
            current_keywords = ', '.join(site.get('keywords', []))
            edited_keywords = st.text_input("Keywords (comma-separated)", value=current_keywords)
            
            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("Save Changes"):
                    keywords_list = [k.strip() for k in edited_keywords.split(',') if k.strip()]
                    
                    # Remove old site and add new one to update details
                    api_request("delete", f"/sites/remove/{site_id}")
                    api_request("post", "/sites/add", json={
                        "url": edited_url, 
                        "alias": edited_alias,
                        "keywords": keywords_list
                    })
                    
                    st.session_state.edit_mode[site_id] = False
                    st.success(f"Updated site details for {edited_alias or edited_url}")
                    st.rerun()
            
            with col2:
                if st.form_submit_button("Cancel"):
                    st.session_state.edit_mode[site_id] = False
                    st.rerun()
    else:
        # Normal display mode
        st.markdown(f"#### 🌐 {card_header}")
        if site.get('alias'):
            st.caption(f"URL: {site['url']}") # Show URL in caption if alias is used

        status = site.get('status', 'N/A')
        status_color = "red" if "Failed" in status or "Error" in status else (
            "orange" if "Alert Triggered" in status else (
                "yellow" if "New Changes" in status else "green"
            )
        )
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Status:** <span style='color:{status_color}; border-radius:5px; padding: 2px 6px; background-color: #262730;'>{status}</span>", unsafe_allow_html=True)
        with col2:
            st.write(f"**Keywords:** {', '.join(site.get('keywords', [])) or 'None'}")
        
        # Action buttons
        actions_col1, actions_col2, actions_col3 = st.columns([1,1,1])
        with actions_col1:
            if st.button("View Details", key=f"details_{site['id']}"):
                st.session_state.selected_site_id = site['id']
                st.rerun()
        with actions_col2:
            if st.button("Edit", key=f"edit_{site['id']}"):
                st.session_state.edit_mode[site_id] = True
                st.rerun()
        with actions_col3:
            if st.button("Remove", key=f"remove_{site['id']}"):
                with st.spinner(f"Removing {card_header}..."):
                    api_request("delete", f"/sites/remove/{site_id}")
                st.success(f"Removed {card_header}.")
                if st.session_state.selected_site_id == site['id']:
                    st.session_state.selected_site_id = None
                if site_id in st.session_state.selected_sites_for_auto_scan:
                    st.session_state.selected_sites_for_auto_scan.remove(site_id)
                st.rerun()
    
    st.markdown("---")

def display_main_dashboard():
    """The main view showing all monitored sites and the global chatbot."""
    st.header("Kautilya Dashboard")

    # Global Chatbot
    with st.expander("🤖 Chat with the Global AI Analyst"):
        for msg in st.session_state.global_chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Ask about trends across all monitored sites..."):
            st.session_state.global_chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                with st.spinner("Analyzing data from all sites..."):
                    response = api_request("post", "/qa/global", json={"query": prompt})
                    if response and "answer" in response:
                        full_response = response["answer"]
                        message_placeholder.markdown(full_response)
                        st.session_state.global_chat_history.append({"role": "assistant", "content": full_response})
                    else:
                        message_placeholder.error("Sorry, I couldn't get a response from the AI.")
                        st.session_state.global_chat_history.append({"role": "assistant", "content": "Sorry, I couldn't get a response."})

    st.markdown("### Monitored Sites")
    sites = api_request("get", "/sites")
    if sites:
        for site in sites:
            display_site_card(site)
    elif sites == []:
        st.info("No URLs added for monitoring yet. Add a URL using the sidebar.")

def display_site_details(site_id):
    """The detailed view for a single selected site."""
    with st.spinner("Loading site details..."):
        details = api_request("get", f"/sites/{site_id}")
    
    if not details:
        st.error("Could not load details for this site.")
        st.session_state.selected_site_id = None
        return

    header = details.get('alias') or details['url']
    st.header(f"Details for {header}")
    if st.button("← Back to Dashboard"):
        st.session_state.selected_site_id = None
        st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["📄 AI Report", "💬 Extracted Posts", "🤖 AI Chat (This Site)", "📊 Raw Data"])

    with tab1:
        st.subheader("AI generated report")
        scans = details.get('scans', [])
        if scans:
            latest_scan = max(scans, key=lambda x: x['timestamp'])
            report_path = latest_scan.get('llm_report_path')

            if not report_path:
                st.warning("⚠️ The LLM analysis failed or did not produce a report for the latest scan. Please check the backend console logs for errors related to Ollama.")
            elif report_path:
                try:
                    report_url = f"{API_BASE_URL}/report/{site_id}"
                    response = requests.get(report_url)
                    if response.status_code == 200:
                        st.markdown(response.text)
                    else:
                        st.error(f"❌ A report was expected but could not be retrieved. Server responded with status {response.status_code}.")
                except Exception as e:
                    st.error(f"❌ Error fetching report: {e}")
        else:
            st.info("No scan data available for this site.")

    with tab2:
        st.subheader("Extracted Posts from Latest Scan")
        scans = details.get('scans', [])
        if scans:
            latest_scan = max(scans, key=lambda x: x['timestamp'])
            new_posts = latest_scan.get('new_posts_with_keywords', [])
            
            if new_posts:
                st.markdown("### 🔥 New Posts with Keyword Hits (Critical!)")
                for new_post_data in new_posts:
                    post = new_post_data['post']
                    keywords = new_post_data['found_keywords']
                    with st.expander(f"🚨 **NEW POST:** {post.get('title', 'No Title')[:100]}... | **Author:** {post.get('author', 'N/A')}"):
                        st.markdown(f"**🎯 Matched Keywords:** `{', '.join(keywords)}`")
                        st.markdown("**📝 Content:**")
                        st.markdown(f"```\n{post.get('content', 'No content.')}\n```")
                        st.markdown("---")
                st.markdown("---")
                st.subheader("All Other Extracted Posts")
            else:
                st.info("No new posts with keyword hits were found in the latest scan.")

            posts = latest_scan.get('extracted_posts', [])
            if posts:
                st.metric("Total Posts Found (including new)", len(posts))
                new_post_contents_set = {p_data['post']['content'] for p_data in new_posts}
                other_posts = [p for p in posts if p['content'] not in new_post_contents_set]

                if other_posts:
                    for post in other_posts:
                        with st.expander(f"**Author:** {post.get('author', 'N/A')} | **Title:** {post.get('title', 'N/A')}"):
                            st.markdown(post.get('content', 'No content.'))
                else:
                    st.info("No other extracted posts to display.")
            else:
                st.info("No structured posts were extracted during the last scan.")
        else:
            st.info("No scan data available to show posts.")

    with tab3:
        st.subheader(f"Chat with AI about {header}")
        if site_id not in st.session_state.chat_history:
            st.session_state.chat_history[site_id] = []
        for msg in st.session_state.chat_history[site_id]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
        if prompt := st.chat_input("Ask about recent changes or risks..."):
            st.session_state.chat_history[site_id].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                with st.spinner("Thinking..."):
                    response = api_request("post", "/qa", json={"query": prompt, "url": details['url']})
                    if response and "answer" in response:
                        message_placeholder.markdown(response["answer"])
                        st.session_state.chat_history[site_id].append({"role": "assistant", "content": response["answer"]})
                    else:
                        message_placeholder.markdown("Sorry, I couldn't get a response.")
                        st.session_state.chat_history[site_id].append({"role": "assistant", "content": "Sorry, I couldn't get a response."})

    with tab4:
        st.subheader("Raw Content Changes (Diff)")
        scans = details.get('scans', [])
        if scans:
            latest_scan = max(scans, key=lambda x: x['timestamp'])
            st.code(latest_scan.get('raw_diff', "No diff available."), language='diff')
            
            st.subheader("Backlinks Found")
            backlinks = latest_scan.get('additional_results', [])
            if backlinks:
                df = pd.DataFrame(backlinks).drop_duplicates(subset="url")
                st.dataframe(df)
            else:
                st.info("No backlinks found in the latest scan.")
        else:
            st.info("No scan data available.")

# --- Sidebar ---
with st.sidebar:
    st.header("Controls")
    
    with st.form(key="add_url_form", clear_on_submit=True):
        new_url = st.text_input("Enter URL to Monitor")
        new_alias = st.text_input("Alias (Optional)", help="A nickname for the URL, shown on the dashboard.")
        new_keywords = st.text_input("Keywords (comma-separated)")
        
        with st.expander("🔐 Optional: Login Credentials"):
            login_url = st.text_input("Login Page URL")
            login_payload = st.text_area("Login Payload (JSON format)", 
                                         help='Example: {"username": "user", "password": "pass", "login": "Login"}')

        if st.form_submit_button("Add URL"):
            if new_url:
                keywords_list = [k.strip() for k in new_keywords.split(',') if k.strip()]
                with st.spinner(f"Adding {new_url}..."):
                    api_request("post", "/sites/add", json={
                        "url": new_url, 
                        "alias": new_alias if new_alias else None,
                        "keywords": keywords_list,
                        "login_url": login_url if login_url else None,
                        "login_payload": login_payload if login_payload else None
                    })
                st.success(f"Added {new_alias or new_url} for monitoring.")
                st.rerun()
            else:
                st.warning("Please enter a URL.")

    st.markdown("---")
    
    st.header("Manual Scan")
    if st.button("Scan All Sites Now"):
        with st.spinner("Sending scan request for all sites..."):
            response = api_request("post", "/scan/all")
            if response:
                st.success(response.get("message", "Scan initiated."))
                time.sleep(2)
                st.rerun()

    st.markdown("---")
    
    st.header("🔄 Automated Scanning")
    
    sites = api_request("get", "/sites")
    if sites:
        site_options = {f"{site.get('alias') or site['url']}": site['id'] for site in sites}
        selected_site_names = st.multiselect(
            "Select sites to monitor automatically:",
            options=list(site_options.keys()),
            default=[name for name, site_id in site_options.items() if site_id in st.session_state.selected_sites_for_auto_scan]
        )
        
        st.session_state.selected_sites_for_auto_scan = [site_options[name] for name in selected_site_names]
        
        st.session_state.scan_frequency = st.selectbox(
            "Scan frequency (minutes):",
            options=[0.1, 15, 30, 60, 120, 240, 480, 720, 1440],
            index=3,
            format_func=lambda x: f"{int(x)} minutes" if x < 60 else f"{int(x//60)} hour{'s' if x//60 > 1 else ''}"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ Start Auto-Scan", disabled=st.session_state.auto_scan_active):
                start_auto_scan()
        
        with col2:
            if st.button("⏹️ Stop Auto-Scan", disabled=not st.session_state.auto_scan_active):
                stop_auto_scan()
        
        if st.session_state.auto_scan_active:
            st.success("🟢 Auto-scan is ACTIVE")
            st.info(f"Scanning {len(st.session_state.selected_sites_for_auto_scan)} sites every {st.session_state.scan_frequency} minutes")
        else:
            st.info("🔴 Auto-scan is STOPPED")
    else:
        st.info("No sites available for automated scanning. Add some URLs first.")

# --- Main App Logic ---
if st.session_state.selected_site_id:
    display_site_details(st.session_state.selected_site_id)
else:
    display_main_dashboard()