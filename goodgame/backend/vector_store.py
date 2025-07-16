import os
import json
import numpy as np
from backend.llm_analyzer import get_embedding
import logging
from typing import Optional

# --- Configuration ---
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'store')
VECTOR_DB_PATH = os.path.join(DATA_DIR, 'vector_store.json')

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def _load_vector_store():
    """Loads the vector store from a JSON file."""
    if not os.path.exists(VECTOR_DB_PATH):
        return {}
    try:
        with open(VECTOR_DB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Could not read vector store file: {e}")
        return {}

def _save_vector_store(data):
    """Saves the vector store to a JSON file."""
    try:
        with open(VECTOR_DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        logging.error(f"Could not write to vector store file: {e}")

def add_to_vector_store(url, content, relative_report_path):
    """
    Generates an embedding for the content and adds it to the vector store.
    """
    try:
        embedding = get_embedding(content)
        if embedding is None:
            logging.warning(f"Failed to generate embedding for content from {url}")
            return

        vector_store = _load_vector_store()
        
        # Entry for the new vector
        new_entry = {
            "content": content,
            "report_path": relative_report_path,
            "embedding": embedding.tolist() # Convert numpy array to list for JSON serialization
        }
        
        # Store vectors per URL
        if url not in vector_store:
            vector_store[url] = []
        
        vector_store[url].append(new_entry)
        _save_vector_store(vector_store)
        logging.info(f"Added new vector to store for URL: {url}")

    except Exception as e:
        logging.error(f"Failed to add to vector store for {url}: {e}", exc_info=True)

def cosine_similarity(v1, v2):
    """Calculates cosine similarity between two vectors."""
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

def search_vector_store(query: str, url_scope: Optional[str] = None, top_k: int = 5):
    """
    Searches the vector store for the most relevant documents to a query.
    If url_scope is provided, it searches only within that URL's documents.
    If url_scope is None, it performs a global search across all documents.
    """
    try:
        query_embedding = get_embedding(query)
        if query_embedding is None:
            logging.error("Failed to generate embedding for the search query.")
            return []

        vector_store = _load_vector_store()
        
        all_documents = []
        if url_scope:
            # Scoped search: Get documents only for the specified URL
            all_documents = vector_store.get(url_scope, [])
            if not all_documents:
                logging.warning(f"No documents found in vector store for URL: {url_scope}")
                return []
        else:
            # Global search: Get documents from all URLs
            for url_docs in vector_store.values():
                all_documents.extend(url_docs)
        
        if not all_documents:
            logging.warning("No documents found in the vector store to perform a search.")
            return []

        # Calculate similarities
        similarities = []
        for doc in all_documents:
            # Ensure the document has a valid embedding
            if 'embedding' not in doc or not isinstance(doc['embedding'], (list, np.ndarray)):
                continue
            doc_embedding = np.array(doc['embedding'])
            sim = cosine_similarity(query_embedding, doc_embedding)
            similarities.append((sim, doc))

        # Sort by similarity and get top_k results
        similarities.sort(key=lambda x: x[0], reverse=True)
        
        # Format results
        results = [{
            "score": float(sim),
            "content": doc['content'],
            "report_path": doc.get('report_path', 'N/A')
        } for sim, doc in similarities[:top_k]]
        
        return results

    except Exception as e:
        logging.error(f"Error searching vector store: {e}", exc_info=True)
        return []
