import os
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import PrayerRequest
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama
from langchain_classic.chains.retrieval import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_classic.chains.history_aware_retriever import create_history_aware_retriever
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory


# --- GLOBAL STORE FOR SESSIONS (This is fine here) ---
store = {}

def get_session_history(session_id: str):
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

# --- THE "BRAIN" INITIALIZER ---
# This function only runs once when the first person asks a question.
# It prevents Django's autoreloader from crashing with PyTorch.
_conversational_rag_chain = None

def get_rag_chain():
    global _conversational_rag_chain
    if _conversational_rag_chain is None:
        print("DEBUG: Initializing AI Brain for the first time...")
        
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        vector_db = Chroma(persist_directory="./sermon_brain_db", embedding_function=embeddings)
        
        # Verify database is not empty
        count = vector_db._collection.count()
        print(f"DEBUG: Items in vector store: {count}")

        retriever = vector_db.as_retriever(search_kwargs={"k": 5})
        llm = ChatOllama(model="llama3.2", temperature=0)

        # Contextualization logic
        context_system_prompt = (
            "Given a chat history and the latest user question which might reference context in the chat history, "
            "formulate a standalone question which can be understood without the chat history. "
            "Do NOT answer the question, just reformulate it if needed and otherwise return it as is."
        )
        context_prompt = ChatPromptTemplate.from_messages([
            ("system", context_system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ])
        history_aware_retriever = create_history_aware_retriever(llm, retriever, context_prompt)

        # QA logic
        qa_system_prompt = (
            "You are a knowledgeable and supportive AI Pastor's Assistant for Pastor Don. "
            "Your goal is to help users explore specific sermon topics, scriptures, and teachings "
            "found within the provided sermon notes. "
            "\n\n"
            "Guidelines:\n"
            "1. Use ONLY the following pieces of retrieved context from the sermons to answer.\n"
            "2. If the user asks about a topic not in the notes, politely say it hasn't been covered in recent sermons.\n"
            "3. Be specific: mention which sermon or scripture the information comes from if possible.\n"
            "4. Maintain the context of the ongoing conversation.\n\n"
            "Context from Sermons:\n"
            "{context}"
        )
        qa_prompt = ChatPromptTemplate.from_messages([
            ("system", qa_system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ])

        # Build Pipeline
        question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
        rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)


        _conversational_rag_chain = RunnableWithMessageHistory(
            rag_chain,
            get_session_history,
            input_messages_key="input",
            history_messages_key="chat_history",
            output_messages_key="answer",
        )
    return _conversational_rag_chain

# --- 5. THE API VIEW ---
class ChatAPI(APIView):
    def post(self, request):
        # CHANGE "prompt" TO "query"
        user_query = request.data.get("query") 
        session_id = request.data.get("session_id", "default_session")
        
        # Add this tiny safety check to prevent the 500 crash in the future
        if not user_query:
            return Response({"error": "No query provided"}, status=400)
            
        brain = get_rag_chain()
        
        # ... rest of your code
        
        response = brain.invoke(
            {"input": user_query},
            config={"configurable": {"session_id": session_id}}
        )
        
        sources = []
        # 'context' comes from the retrieval chain
        for doc in response.get("context", []):
            name = os.path.basename(doc.metadata.get("source", "Unknown Sermon"))
            if name not in sources:
                sources.append(name)
        
        return Response({
            "answer": response["answer"],
            "sources": sources
        })


class PrayerRequestAPI(APIView):
    """POST /api/prayer-requests/ — accepts prayer form submissions from Flutter."""

    def post(self, request):
        prayer_text = (request.data.get('prayer_text') or '').strip()
        if len(prayer_text) < 10:
            return Response(
                {'detail': 'Prayer request must be at least 10 characters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_anonymous = bool(request.data.get('is_anonymous', False))
        name = '' if is_anonymous else (request.data.get('name') or '').strip()
        email = '' if is_anonymous else (request.data.get('email') or '').strip()
        phone = (request.data.get('phone') or '').strip()

        if not is_anonymous and (not name or not email):
            return Response(
                {'detail': 'Name and email are required unless submitting anonymously.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user if request.user.is_authenticated else None
        prayer = PrayerRequest.objects.create(
            name=name,
            email=email,
            phone=phone,
            prayer_text=prayer_text,
            is_anonymous=is_anonymous,
            user=user,
        )

        return Response(
            {
                'success': True,
                'id': prayer.id,
                'message': 'Prayer request received.',
            },
            status=status.HTTP_201_CREATED,
        )
    
# This forces Django to run the check as soon as the file is loaded
try:
    print("--- SERVER STARTUP DATABASE CHECK ---")
    check_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    check_db = Chroma(persist_directory="./sermon_brain_db", embedding_function=check_embeddings)
    print(f"SUCCESS: Found {check_db._collection.count()} sermons in the database.")
except Exception as e:
    print(f"ERROR DURING STARTUP: {e}")