"""Streamlit UI. Talks to the FastAPI backend over HTTP only, so it can be deployed separately.

Run:
    streamlit run frontend/app.py
Env:
    API_URL  (default http://localhost:8000)
"""

import os

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(page_title="Azure PDF RAG Assistant", page_icon="📄", layout="wide")


@st.cache_resource
def api() -> httpx.Client:
    # Generous timeout: indexing a large PDF embeds every chunk.
    return httpx.Client(base_url=API_URL, timeout=300)


def error_detail(response: httpx.Response) -> str:
    try:
        return response.json().get("detail", response.text)
    except ValueError:
        return response.text


def call(method: str, path: str, **kwargs) -> httpx.Response | None:
    try:
        response = api().request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        st.error(f"Cannot reach the API at {API_URL}: {exc}")
        return None
    if response.is_error:
        st.error(f"{response.status_code}: {error_detail(response)}")
        return None
    return response


# ---------- Sidebar: documents ----------
with st.sidebar:
    st.header("📄 Documents")

    with st.form("upload", clear_on_submit=True):
        files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
        submitted = st.form_submit_button("Upload & index", type="primary", use_container_width=True)
    if submitted and files:
        for f in files:
            with st.spinner(f"Indexing {f.name}…"):
                r = call("POST", "/upload", files={"file": (f.name, f.getvalue(), "application/pdf")})
            if r:
                st.success(f"{f.name}: {r.json()['chunks']} chunks indexed")

    r = call("GET", "/documents")
    docs = r.json() if r else []
    if not docs:
        st.caption("No documents indexed yet.")
    for doc in docs:
        name_col, delete_col = st.columns([5, 1])
        name_col.markdown(f"**{doc['filename']}**  \n`{doc['document_id']}`")
        if delete_col.button("🗑️", key=f"del-{doc['document_id']}", help=f"Delete {doc['filename']}"):
            if call("DELETE", f"/documents/{doc['document_id']}"):
                st.rerun()

    st.divider()
    top_k = st.slider("Chunks to retrieve (top-k)", 1, 20, 5)
    show_chunks = st.toggle("Show retrieved chunks", value=False)
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    health = call("GET", "/health")
    if health:
        h = health.json()
        st.caption(
            f"LLM: {h['llm_provider']} · embeddings: {h['embedding_provider']} · "
            f"search: {h['vector_store']} · storage: {h['document_storage']}"
        )


# ---------- Main: chat ----------
st.title("Azure PDF RAG Assistant")
st.caption("Answers come only from your uploaded PDFs, with page citations.")


def render_answer(answer: dict, show: bool) -> None:
    st.markdown(answer["answer"])
    if answer["citations"]:
        st.markdown(
            "**Sources:** "
            + " · ".join(f"📄 {c['filename']}, p. {c['page_number']}" for c in answer["citations"])
        )
    if show and answer["sources"]:
        with st.expander(f"Retrieved chunks ({len(answer['sources'])})"):
            for s in answer["sources"]:
                c = s["chunk"]
                st.markdown(f"**{c['filename']} · page {c['page_number']}** · score `{s['score']:.4f}`")
                st.text(c["content"])


if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
        else:
            render_answer(msg["content"], show_chunks)

if question := st.chat_input("Ask a question about your documents"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching documents…"):
            r = call("POST", "/chat", json={"question": question, "top_k": top_k})
        if r:
            answer = r.json()
            render_answer(answer, show_chunks)
            st.session_state.messages.append({"role": "assistant", "content": answer})
