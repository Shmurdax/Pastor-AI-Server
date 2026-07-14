import os
from langchain_community.document_loaders import DirectoryLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# --- AUTO-DETECT PATH ---
# This finds the folder where THIS script is saved
base_dir = os.path.dirname(os.path.abspath(__file__))
markdown_path = os.path.join(base_dir, 'converted_markdown', 'converted_markdown')

print("--- DEBUG INFO ---")
print(f"1. Script location: {os.path.abspath(__file__)}")
print(f"2. Looking for Markdown in: {markdown_path}")

# Check if the folder exists
if not os.path.exists(markdown_path):
    print(f"❌ ERROR: Cannot find the folder at {markdown_path}")
    print(f"Contents of {base_dir}: {os.listdir(base_dir)}")
    exit() # Stop the script here if the path is wrong
else:
    print("✅ Folder found! Loading files...")

# 1. Load sermons
loader = DirectoryLoader(
    markdown_path, 
    glob="./*.md", 
    loader_cls=UnstructuredMarkdownLoader
)
docs = loader.load()

# 2. Split text
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
chunks = text_splitter.split_documents(docs)

# 3. Create Database
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma.from_documents(
    documents=chunks, 
    embedding=embeddings, 
    persist_directory=os.path.join(base_dir, "sermon_brain_db")
)

print(f"✅ Finished! Indexed {len(chunks)} chunks.")