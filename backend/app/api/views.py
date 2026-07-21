import os
import sys

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PrayerRequest
from .serializers import PrayerRequestSerializer, PrayerRequestStaffUpdateSerializer


QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "sermon_brain")


# --- GLOBAL STORE FOR SESSIONS (This is fine here) ---
store = {}

def get_session_history(session_id: str):
    from langchain_community.chat_message_histories import ChatMessageHistory

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
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_qdrant import QdrantVectorStore
        from langchain_ollama import ChatOllama
        from langchain_classic.chains.retrieval import create_retrieval_chain
        from langchain_classic.chains.combine_documents import create_stuff_documents_chain
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
        from langchain_classic.chains.history_aware_retriever import create_history_aware_retriever
        from langchain_core.runnables.history import RunnableWithMessageHistory
        from qdrant_client import QdrantClient

        print("DEBUG: Initializing AI Brain for the first time...")

        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        client = QdrantClient(url=QDRANT_URL)
        vector_db = QdrantVectorStore(
            client=client,
            collection_name=QDRANT_COLLECTION,
            embedding=embeddings,
        )

        try:
            count = client.get_collection(QDRANT_COLLECTION).points_count
            print(f"DEBUG: Items in Qdrant collection '{QDRANT_COLLECTION}': {count}")
        except Exception as exc:
            print(f"DEBUG: Could not read Qdrant collection count: {exc}")

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
    # Left open so guests can keep chatting without an account.
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # CHANGE "prompt" TO "query"
        user_query = request.data.get("query")
        session_id = request.data.get("session_id", "default_session")

        # Add this tiny safety check to prevent the 500 crash in the future
        if not user_query:
            return Response({"error": "No query provided"}, status=400)

        brain = get_rag_chain()

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


class PrayerRequestListCreateAPI(APIView):
    """GET /api/prayer-requests/ — staff inbox list. POST — public submission."""

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    def get(self, request):
        qs = PrayerRequest.objects.all()
        followed_up = request.query_params.get('followed_up')
        if followed_up is not None:
            flag = followed_up.lower() in ('true', '1', 'yes')
            qs = qs.filter(followed_up=flag)
        data = PrayerRequestSerializer(qs, many=True).data
        return Response({'results': data})

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


class PrayerRequestDetailAPI(APIView):
    """GET/PATCH /api/prayer-requests/<id>/ — staff view and follow-up updates."""

    permission_classes = [permissions.IsAdminUser]

    def get(self, request, pk):
        prayer = get_object_or_404(PrayerRequest, pk=pk)
        return Response(PrayerRequestSerializer(prayer).data)

    def patch(self, request, pk):
        prayer = get_object_or_404(PrayerRequest, pk=pk)
        serializer = PrayerRequestStaffUpdateSerializer(
            prayer,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(PrayerRequestSerializer(prayer).data)


# Skip heavy RAG startup work during `manage.py test` / migrations.
if "test" not in sys.argv and "migrate" not in sys.argv:
    try:
        from qdrant_client import QdrantClient

        print("--- SERVER STARTUP DATABASE CHECK ---")
        client = QdrantClient(url=QDRANT_URL)
        info = client.get_collection(QDRANT_COLLECTION)
        print(
            f"SUCCESS: Found {info.points_count} points in Qdrant "
            f"collection '{QDRANT_COLLECTION}' at {QDRANT_URL}."
        )
    except Exception as e:
        print(f"ERROR DURING STARTUP: {e}")
