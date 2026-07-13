import os

from django.contrib.auth import authenticate
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import LoginSerializer, RegisterSerializer, UserSerializer

_rag_chain = None


def get_rag_chain():
    """Lazy-load the sermon RAG stack so auth endpoints/tests start without Ollama."""
    global _rag_chain
    if _rag_chain is not None:
        return _rag_chain

    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma
    from langchain_ollama import ChatOllama
    from langchain_classic.chains.retrieval import create_retrieval_chain
    from langchain_classic.chains.combine_documents import create_stuff_documents_chain
    from langchain_core.prompts import ChatPromptTemplate

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_db = Chroma(persist_directory="./sermon_brain_db", embedding_function=embeddings)
    retriever = vector_db.as_retriever(search_kwargs={"k": 3})
    llm = ChatOllama(model="llama3.2", temperature=0)
    system_prompt = "You are a helpful pastor's assistant. Use ONLY the sermon notes. {context}"
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
    qa_chain = create_stuff_documents_chain(llm, prompt)
    _rag_chain = create_retrieval_chain(retriever, qa_chain)
    return _rag_chain


class ChatAPI(APIView):
    # Left open so guests can keep chatting without an account.
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user_query = request.data.get("prompt") or request.data.get("query")

        result = get_rag_chain().invoke({"input": user_query})

        return Response({
            "answer": result["answer"],
            "sources": [os.path.basename(doc.metadata.get("source", "Unknown")) for doc in result["context"]]
        })


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"token": token.key, "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower().strip()
        password = serializer.validated_data["password"]

        # username == email in our setup (see RegisterSerializer.create)
        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data})


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Deletes the token so it can no longer authenticate requests.
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
