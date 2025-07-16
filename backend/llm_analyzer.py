import ollama
import json
import os
from datetime import datetime
from urllib.parse import urlparse
import logging
import numpy as np
from sentence_transformers import SentenceTransformer

# --- Configuration ---
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'store'))
MARKDOWN_REPORT_DIR = os.path.join(DATA_DIR, 'markdown_reports')
os.makedirs(MARKDOWN_REPORT_DIR, exist_ok=True)

# --- Model Initialization ---
try:
    embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
except Exception as e:
    logging.error(f"Failed to load SentenceTransformer model: {e}")
    embedding_model = None

LLM_MODEL_NAME = 'llama3'

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def sanitize_filename(url):
    """Sanitizes a URL to be used as a filename."""
    parsed_url = urlparse(url)
    filename = parsed_url.netloc + parsed_url.path.replace('/', '_').replace('.', '_')
    filename = ''.join(c for c in filename if c.isalnum() or c in ('-', '_')).strip('_')
    return filename or "untitled_report"

def get_embedding(text):
    """Generates a vector embedding for the given text."""
    if not embedding_model:
        logging.error("Embedding model is not available.")
        return None
    try:
        embedding = embedding_model.encode(text, convert_to_tensor=False)
        return embedding
    except Exception as e:
        logging.error(f"Error generating embedding: {e}")
        return None

def analyze_with_llm(url, changes, keyword_data, posts_data, prompt="Analyze the following data. Summarize key changes, keyword hits, and discussion topics from the posts. Identify notable authors and potential risks."):
    """Analyzes all available data using Ollama and generates a markdown report."""
    page_keywords = keyword_data.get("page_keywords", [])
    backlink_keywords = keyword_data.get("backlink_keywords", [])

    backlink_info = ""
    if backlink_keywords:
        backlink_info = "### Backlinks with Keyword Hits:\n"
        for bl in backlink_keywords:
            backlink_info += f"- URL: {bl['url']}\n  Keywords: {', '.join(bl['found_keywords'])}\n"
    
    posts_info = ""
    if posts_data:
        posts_info = "### Extracted Posts for Analysis:\n"
        # Limit the number of posts sent to the LLM to avoid overly long prompts
        for i, post in enumerate(posts_data[:10]): 
            posts_info += f"#### Post {i+1}\n"
            posts_info += f"- **Author**: {post.get('author', 'N/A')}\n"
            posts_info += f"- **Title**: {post.get('title', 'N/A')}\n"
            # Limit content length per post
            posts_info += f"- **Content Snippet**: {post.get('content', '')[:500]}...\n\n"
    else:
        posts_info = "No structured posts were extracted from this page."


    context = f"""
        You are a web intelligence analyst. Your task is to provide a comprehensive summary of the monitoring data for the URL, including all the new posts, content and active users on this site/forum: {url}

        **1. Detected Content Changes (Diff)**:
        ```diff
        {changes[:4000] if changes else "No textual changes detected since last scan."}
        ```

        **2. Keywords Found on Main Page**: {json.dumps(page_keywords) if page_keywords else "None"}

        **3. Backlinks Analysis**:
        {backlink_info if backlink_info else "No backlinks with keywords were found."}
        
        **4. Forum/Marketplace Post Analysis**:
        {posts_info}

        **Your Task**: {prompt}
        ---
        Based on all the information above, generate a concise and structured markdown report below. Focus on actionable intelligence.
        """
    try:
        response = ollama.chat(model=LLM_MODEL_NAME, messages=[{'role': 'user', 'content': context}])
        markdown_content = response['message']['content']

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_url_name = sanitize_filename(url)
        filename = f"{safe_url_name}_{timestamp}_report.md"
        filepath = os.path.join(MARKDOWN_REPORT_DIR, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        logging.info(f"LLM markdown report saved to: {filepath}")
        relative_report_path = os.path.relpath(filepath, DATA_DIR)
        return markdown_content, relative_report_path

    except ollama.ResponseError as e:
        logging.error(f"Ollama API Error: {e}. Is the Ollama server running and model '{LLM_MODEL_NAME}' downloaded?")
        return f"Error: Ollama API failed. {e}", None
    except Exception as e:
        logging.error(f"Unexpected error during LLM analysis: {e}", exc_info=True)
        return f"Error: An unexpected error occurred. {e}", None

def answer_question_with_llm(question, context_from_vector_store):
    """Answers a user's question using context from the vector store."""
    prompt = f"""
    You are a helpful Q&A assistant for a web monitoring tool.
    Answer the following question based *only* on the provided context.
    If the context doesn't contain the answer, say "I don't have enough information to answer that."

    **Context:**
    ---
    {context_from_vector_store}
    ---

    **Question:** {question}

    **Answer:**
    """
    try:
        response = ollama.chat(model=LLM_MODEL_NAME, messages=[{'role': 'user', 'content': prompt}])
        return response['message']['content']
    except ollama.ResponseError as e:
        logging.error(f"Ollama API Error during Q&A: {e}")
        return "Error: The AI model is currently unavailable."
    except Exception as e:
        logging.error(f"Unexpected error during Q&A: {e}", exc_info=True)
        return "Error: An unexpected error occurred while processing the answer."