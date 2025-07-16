import sys
import os
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import uvicorn
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'store'))


from backend.monitor import monitor_job, get_site_details, get_all_sites, get_monitoring_summary, init_db
from backend.llm_analyzer import answer_question_with_llm
from backend.vector_store import search_vector_store

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Dark Web Monitoring Backend",
    description="API for scraping, analyzing, and querying dark web sites.",
    version="1.0.0"
)

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for simplicity, restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database and Logging Setup ---
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'urls.db')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Pydantic Models for Request Bodies ---
class AddUrlRequest(BaseModel):
    url: str
    keywords: list[str]
    alias: str | None = None
    login_url: str | None = None
    login_payload: str | None = None


class QARequest(BaseModel):
    query: str
    url: str # To scope the search to a specific site's data

class GlobalQARequest(BaseModel):
    query: str

# --- Helper Functions ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- API Endpoints ---
@app.on_event("startup")
def on_startup():
    """Initialize the database when the application starts."""
    init_db()
    logging.info("FastAPI application started and database initialized.")

@app.get("/")
def read_root():
    return {"message": "Dark Web Monitoring API is running."}

@app.post("/sites/add")
def add_url(request: AddUrlRequest):
    """Adds a new URL and its alias to the monitoring database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        keywords_str = ", ".join(request.keywords)
        cursor.execute("INSERT INTO urls (url, keywords, alias, status, login_url, login_payload) VALUES (?, ?, ?, ?, ?, ?)",
                       (request.url, keywords_str, request.alias, "Pending", request.login_url, request.login_payload))
        conn.commit()
        return {"message": f"URL '{request.url}' added successfully."}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"URL '{request.url}' is already being monitored.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding URL: {e}")
    finally:
        conn.close()

@app.delete("/sites/remove/{site_id}")
def remove_url(site_id: int):
    """Removes a URL from monitoring by its ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM urls WHERE id = ?", (site_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Site with ID {site_id} not found.")
        return {"message": f"URL with ID {site_id} removed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error removing URL: {e}")
    finally:
        conn.close()

@app.get("/sites")
def list_all_sites():
    """Retrieves a list of all monitored sites."""
    try:
        sites = get_all_sites()
        return sites
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve sites: {e}")

@app.get("/sites/{site_id}")
def get_single_site_details(site_id: int):
    """Retrieves detailed monitoring information for a specific site."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM urls WHERE id = ?", (site_id,))
    site = cursor.fetchone()
    conn.close()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site with ID {site_id} not found.")
    
    try:
        details = get_site_details(site_id, site['url'])
        return details
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve site details: {e}")

@app.post("/scan/all")
def scan_all_sites(background_tasks: BackgroundTasks):
    """Triggers a background scan for all monitored sites."""
    sites = get_all_sites()
    if not sites:
        raise HTTPException(status_code=404, detail="No sites to scan.")
    
    for site in sites:
        background_tasks.add_task(monitor_job, site['id'], site['url'], site['keywords'], site.get('login_url'), site.get('login_payload'))
        logging.info(f"Queued background scan for {site['url']}")
        
    return {"message": f"Started scanning {len(sites)} sites in the background."}

@app.post("/scan/site/{site_id}")
def scan_single_site(site_id: int, background_tasks: BackgroundTasks):
    """Triggers a background scan for a single monitored site."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, url, keywords, login_url, login_payload FROM urls WHERE id = ?", (site_id,))
    site = cursor.fetchone()
    conn.close()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site with ID {site_id} not found.")

    site_dict = dict(site)
    keywords_list = site_dict.get('keywords', '').split(', ') if site_dict.get('keywords') else []
    background_tasks.add_task(monitor_job, site_dict['id'], site_dict['url'], keywords_list, site_dict.get('login_url'), site_dict.get('login_payload'))
    logging.info(f"Queued background scan for {site_dict['url']}")

    return {"message": f"Started scanning site {site_dict['url']} in the background."}

@app.get("/summary")
def get_summary():
    """Provides a summary of all monitoring activities."""
    try:
        summary = get_monitoring_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve summary: {e}")

@app.post("/qa")
def ask_question(request: QARequest):
    """
    Answers a question based on the vectorized context of monitored data for a specific URL.
    """
    try:
        # 1. Search vector store for relevant context
        relevant_docs = search_vector_store(request.query, url_scope=request.url)
        
        if not relevant_docs:
            return {"answer": "I could not find any relevant information for that URL to answer your question. Please run a scan first."}

        # 2. Combine context and ask LLM
        context = "\n\n".join([doc['content'] for doc in relevant_docs])
        
        # 3. Get answer from LLM
        answer = answer_question_with_llm(request.query, context)
        
        return {"answer": answer, "context_docs": relevant_docs}
    except Exception as e:
        logging.error(f"Error in /qa endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while processing your question: {e}")

@app.post("/qa/global")
def ask_question_global(request: GlobalQARequest):
    """
    Answers a question based on the vectorized context of ALL monitored data.
    """
    try:
        # 1. Search vector store for relevant context across all sites
        relevant_docs = search_vector_store(request.query, url_scope=None, top_k=10) # Broader search
        
        if not relevant_docs:
            return {"answer": "I could not find any relevant information in the database to answer your question. Please run some scans first."}

        # 2. Combine context and ask LLM
        context = "\n\n".join([f"Context from report {doc.get('report_path', 'N/A')}:\n{doc['content']}" for doc in relevant_docs])
        
        # 3. Get answer from LLM
        answer = answer_question_with_llm(request.query, context)
        
        return {"answer": answer}
    except Exception as e:
        logging.error(f"Error in /qa/global endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while processing your question: {e}")
    
@app.get("/report/{site_id}")
def get_latest_report(site_id: int):
    """
    Serves the latest markdown report file for a given site ID.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM urls WHERE id = ?", (site_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Site not found.")

    url = row["url"]

    # Load vector store and find latest report for this URL
    from backend.vector_store import _load_vector_store
    vector_data = _load_vector_store().get(url, [])
    if not vector_data:
        raise HTTPException(status_code=404, detail="No reports found for this site.")

    # Sort entries by time (they are stored in order, but be explicit)
    latest_entry = vector_data[-1]
    relative_path = latest_entry.get("report_path")
    if not relative_path:
        raise HTTPException(status_code=404, detail="Report path missing.")

    absolute_path = os.path.join(DATA_DIR, relative_path)
    if not os.path.exists(absolute_path):
        raise HTTPException(status_code=404, detail="Report file not found on disk.")

    return FileResponse(absolute_path, media_type="text/markdown", filename=os.path.basename(absolute_path))

if __name__ == "__main__":
    uvicorn.run("fastapi_app:app", host="0.0.0.0", port=8000, reload=True)