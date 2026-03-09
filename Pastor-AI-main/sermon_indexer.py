import os
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# === CONFIG ===
DATA_DIR = r'C:\Users\MC_Mill\Documents\GitHub\Pastor-AI-GUI\Pastor-AI-main\converted_markdown\converted_markdown'  
DB_DIR = "./sermon_brain_db"

# 1. Load all Markdown files
# 1. Load all Markdown files with UTF-8 encoding
print("--- Loading Files ---")
loader = DirectoryLoader(
    DATA_DIR, 
    glob="*.md", 
    loader_cls=TextLoader,
    loader_kwargs={'encoding': 'utf-8'}  # <--- THIS IS THE FIX
)
docs = loader.load()
print(f"Found {len(docs)} files.")

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
print("--- Splitting Documents ---")
for doc in docs:
    file_name = os.path.basename(doc.metadata["source"])
    
    # Check if the file has Bible-style headers
    if "# " in doc.page_content:
        # Extract headers as metadata
        intermediate_splits = markdown_splitter.split_text(doc.page_content)
        # Ensure these are small enough for the model
        final_splits = text_splitter.split_documents(intermediate_splits)
    else:
        # Standard sermon note splitting
        final_splits = text_splitter.split_documents([doc])

    # Universal Metadata: Tag everything with the filename
    for split in final_splits:
        split.metadata["source"] = file_name
        # If it's a sermon note, it won't have 'Book' or 'Chapter', which is fine!
        all_chunks.append(split)

# 4. Create the Vector Database
print(f"--- Creating Vector DB with {len(all_chunks)} chunks ---")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

vector_db = Chroma.from_documents(
    documents=all_chunks, 
    embedding=embeddings, 
    persist_directory=DB_DIR
)

print(f"✅ DONE! Your 'Sermon Brain' is ready at: {DB_DIR}")