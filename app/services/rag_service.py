import io
from openai import OpenAI
from flask import current_app
from langsmith import traceable
from app.extensions import db
from app.models import Document, DocumentChunk


ALLOWED_EXTENSIONS = {"txt", "md", "pdf", "docx"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def parse_file(file_storage):
    filename = file_storage.filename
    ext = filename.rsplit(".", 1)[1].lower()

    if ext == "txt" or ext == "md":
        return file_storage.read().decode("utf-8")

    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_storage.read()))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)

    if ext == "docx":
        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(file_storage.read()))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    raise ValueError(f"不支持的文件类型: {ext}")


def chunk_text(text, chunk_size=None, overlap=None):
    if chunk_size is None:
        chunk_size = current_app.config["CHUNK_SIZE"]
    if overlap is None:
        overlap = current_app.config["CHUNK_OVERLAP"]

    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        chunk = text[start:end]
        last_sep = -1
        for sep in ["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", " ", ""]:
            idx = chunk.rfind(sep)
            if idx > chunk_size // 3:
                last_sep = idx + len(sep)
                break
        if last_sep > 0:
            chunk = chunk[:last_sep]
            end = start + last_sep
        chunks.append(chunk.strip())
        start = end - overlap if end > overlap else end

    return [c for c in chunks if c]


def get_embedding_client():
    return OpenAI(
        api_key="ollama",
        base_url=current_app.config["OLLAMA_BASE_URL"],
    )


def get_embeddings(texts):
    if not texts:
        return []
    client = get_embedding_client()
    model = current_app.config["EMBEDDING_MODEL"]
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


@traceable(name="rag_process_and_store")
def process_and_store(file_storage):
    filename = file_storage.filename
    ext = filename.rsplit(".", 1)[1].lower()
    file_size = file_storage.content_length or 0

    content = parse_file(file_storage)
    chunks = chunk_text(content)

    if not chunks:
        raise ValueError("文件中没有提取到有效内容")

    embeddings = get_embeddings(chunks)

    doc = Document(
        filename=filename,
        file_type=ext,
        file_size=file_size,
        chunk_count=len(chunks),
    )
    db.session.add(doc)
    db.session.flush()

    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        dc = DocumentChunk(
            document_id=doc.id,
            chunk_index=i,
            content=chunk,
            embedding=embedding,
        )
        db.session.add(dc)

    db.session.commit()
    return doc


@traceable(name="rag_search")
def search(query, top_k=None):
    if top_k is None:
        top_k = current_app.config["RAG_TOP_K"]

    query_embedding = get_embeddings([query])[0]

    results = (
        db.session.query(DocumentChunk, Document.filename)
        .join(Document, DocumentChunk.document_id == Document.id)
        .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
        .all()
    )

    return [
        {
            "content": chunk.content,
            "document_id": chunk.document_id,
            "filename": filename,
            "chunk_index": chunk.chunk_index,
        }
        for chunk, filename in results
    ]


def delete_document(doc_id):
    doc = db.session.get(Document, doc_id)
    if not doc:
        return False
    db.session.delete(doc)
    db.session.commit()
    return True


def list_documents():
    docs = Document.query.order_by(Document.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "file_type": d.file_type,
            "file_size": d.file_size,
            "chunk_count": d.chunk_count,
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]
