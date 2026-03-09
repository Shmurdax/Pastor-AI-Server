import os
from rest_framework.views import APIView
from rest_framework.response import Response
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama
from langchain_classic.chains.retrieval import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

# Initialize once so the AI stays "warm" in memory
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./sermon_brain_db", embedding_function=embeddings)
retriever = vector_db.as_retriever(search_kwargs={"k": 3})
llm = ChatOllama(model="llama3.2", temperature=0)

system_prompt = "You are a helpful pastor's assistant. Use ONLY the sermon notes. {context}"
prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
qa_chain = create_stuff_documents_chain(llm, prompt)
rag_chain = create_retrieval_chain(retriever, qa_chain)

class ChatAPI(APIView):
    def post(self, request):
        user_query = request.data.get("prompt")
        
        # Run the RAG logic
        result = rag_chain.invoke({"input": user_query})
        
        return Response({
            "answer": result['answer'],
            "sources": [os.path.basename(doc.metadata.get('source', 'Unknown')) for doc in result['context']]
        })