
# Dory: Digital Engineering Assistant

Dory is an AI-powered **Digital Engineering (DE)** assistant designed to enhance learning, engagement, and applied understanding of modern digital engineering practices. It supports students, professionals, and organisations by providing clear explanations, contextual guidance, and on-demand access to high-value engineering knowledge.

Dory helps make Digital Engineering more accessible by combining advanced LLM reasoning with curated knowledge sources and configurable retrieval mechanisms. It supports educational use, professional development, and applied DE workflows.

One real-world application of Dory is its role as an interactive companion for the **Australian Digital Engineering Summit (ADES)**, helping attendees explore program sessions, speakers, workshops, and key DE topics.

---

## Features

### Digital Engineering Knowledge Support
- Explains core DE concepts, principles, and workflows.
- Helps users understand model-based practices, digital threads, data-driven engineering, and end-to-end lifecycle integration.
- Provides applied and practical guidance for DE activities.

### Retrieval-Augmented Generation (RAG)
Dory uses a configurable **RAG pipeline**, featuring:
- Integration of curated DE knowledge sources
- Fast and accurate semantic retrieval
- Support for multiple embedding backends (OpenAI, HuggingFace, Ollama, or any HTTP-compatible server)

### Query Routing
Dory automatically routes incoming questions to the most relevant domain:
- General Digital Engineering knowledge  
- Application-specific knowledge (e.g., Summit materials)  
- Pure LLM reasoning when documents are unnecessary  

This improves accuracy, reduces hallucination, and maintains contextual relevance.

### Behavioural Governance Layer
Dory includes a robust behavioural control system that:
- Ensures factual and transparent responses  
- Avoids speculation when context is missing  
- Maintains a concise, professional, and friendly tone  
- Provides safe fallback behaviour when uncertain  
- Allows configurable persona traits for tone and scope  

### FastAPI Backend
The backend relies on **FastAPI**, providing:
- Structured chat sessions with history  
- Conversation logging and tracing  
- Runtime model switching  
- Centralised configuration via environment variables  
- A stable, clean interface for front-end clients  

### Fuzzy Answer Support
A fuzzy-matching layer enables:
- Fast responses to frequently asked questions  
- Robust matching even with differently phrased user queries  
- Low-latency lookup for common DE concepts or application resources  

---

## Configurable Embedding System

Dory supports multiple embedding providers through simple runtime configuration:

- **OpenAI embeddings**  
- **HuggingFace local embedding models**  
- **Ollama-hosted embeddings**  
- **Custom HTTP-compatible embedding servers**

You can also configure:
- Document/query prefixes  
- Batch embedding size  
- Embedding model names  
- Embedding providers per domain  

This allows Dory to be adapted easily across different performance, security, and hardware environments.

---

## Purpose and Vision

Dory is built to:

- Make Digital Engineering more accessible and interactive  
- Provide accurate, contextual, and applied insight on demand  
- Support education, training, and professional development  
- Demonstrate responsible, controlled AI integration in engineering  
- Offer a reusable and extensible framework for AI-enabled DE assistants  

By combining structured retrieval with controlled LLM reasoning, Dory supports both **learning** and **operational engineering workflows**, enabling scalable and reliable DE assistance across academic, industry, and defence environments.



