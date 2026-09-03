from flask import Blueprint, request, jsonify, current_app
from app.services import rag_service

rag_bp = Blueprint("rag", __name__)


@rag_bp.route("/api/documents/upload", methods=["POST"])
def upload_document():
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "未选择文件"}), 400

    if not rag_service.allowed_file(file.filename):
        return jsonify({"error": f"不支持的文件类型，支持: {', '.join(rag_service.ALLOWED_EXTENSIONS)}"}), 400

    try:
        doc = rag_service.process_and_store(file)
        return jsonify({
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "chunk_count": doc.chunk_count,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"处理文件失败: {str(e)}"}), 500


@rag_bp.route("/api/documents")
def list_documents():
    docs = rag_service.list_documents()
    return jsonify(docs)


@rag_bp.route("/api/documents/<int:doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    if rag_service.delete_document(doc_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "文档不存在"}), 404


@rag_bp.route("/api/documents/search", methods=["POST"])
def search_documents():
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "搜索内容不能为空"}), 400

    top_k = data.get("top_k", current_app.config["RAG_TOP_K"])
    results = rag_service.search(query, top_k=top_k)
    return jsonify(results)
