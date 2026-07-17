import os
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore

# === CONFIG ===
DATA_DIR = os.environ.get("SERMON_MARKDOWN_DIR", "./converted_markdown")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "sermon_brain")


def run_ingestion():
    # 1. Load all Markdown files
    print("--- 📂 Loading Files ---")
    if not os.path.exists(DATA_DIR):
        print(f"❌ Error: The directory {DATA_DIR} does not exist!")
        return

    loader = DirectoryLoader(
        DATA_DIR,
        glob="*.md",
        loader_cls=TextLoader,
        loader_kwargs={'encoding': 'utf-8'}
    )
    docs = loader.load()
    print(f"✅ Found {len(docs)} files.")

    # 2. Define Splitters
    # Mode A: Bible Structure (extracting Book and Chapter)
    headers_to_split_on = [("#", "Book"), ("##", "Chapter")]
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

    # Mode B: General Text (for sermons and long Bible chapters)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", " ", ""]
    )

    all_chunks = []

    # 3. Process each document
    print("--- ✂️  Splitting Documents into Sermon/Bible Chunks ---")
    for doc in docs:
        # Get just the filename (e.g., "Genesis.md")
        file_name = os.path.basename(doc.metadata["source"])

        # Check if the file has Bible-style headers
        if "# " in doc.page_content:
            # Extract headers as metadata (Book/Chapter)
            intermediate_splits = markdown_splitter.split_text(doc.page_content)
            # Ensure these are small enough for Llama 3.2 3B
            final_splits = text_splitter.split_documents(intermediate_splits)
        else:
            # Standard sermon note splitting
            final_splits = text_splitter.split_documents([doc])

        # Universal Metadata: Tag everything with the filename for the UI
        for split in final_splits:
            split.metadata["source"] = file_name
            all_chunks.append(split)

    # 4. Create / refresh the Qdrant collection
    print(f"--- 🧠 Writing {len(all_chunks)} chunks to Qdrant ({QDRANT_URL}/{QDRANT_COLLECTION}) ---")
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    QdrantVectorStore.from_documents(
        documents=all_chunks,
        embedding=embeddings,
        url=QDRANT_URL,
        collection_name=QDRANT_COLLECTION,
    )

    print(f"✅ DONE! Sermon brain is in Qdrant collection '{QDRANT_COLLECTION}'.")


if __name__ == "__main__":
    run_ingestion()
