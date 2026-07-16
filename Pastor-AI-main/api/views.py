import os

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama
from langchain_classic.chains.retrieval import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

from .serializers import (
    GoogleAuthSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
)

# ─── Sermon RAG chain ──────────────────────────────────────────
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./sermon_brain_db", embedding_function=embeddings)
retriever = vector_db.as_retriever(search_kwargs={"k": 3})
llm = ChatOllama(model="llama3.2", temperature=0)

system_prompt = "You are a helpful pastor's assistant. Use ONLY the sermon notes. {context}"
prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{input}")])
qa_chain = create_stuff_documents_chain(llm, prompt)
rag_chain = create_retrieval_chain(retriever, qa_chain)


class ChatAPI(APIView):
    # Left open so guests can keep chatting without an account.
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user_query = request.data.get("prompt") or request.data.get("query")

        result = rag_chain.invoke({"input": user_query})

        return Response({
            "answer": result["answer"],
            "sources": [os.path.basename(doc.metadata.get("source", "Unknown")) for doc in result["context"]]
        })


# ─── Auth ───────────────────────────────────────────────────────────────────
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


class GoogleAuthView(APIView):
    """Exchange a Google ID token for a DRF auth Token.

    Matches Flutter AuthService.signInWithGoogle():
    POST /api/auth/google/  body: { "id_token": "..." }
    -> { "token": "...", "user": { id, email, name, avatar_url } }
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_id_token = serializer.validated_data["id_token"]

        client_id = getattr(settings, "GOOGLE_CLIENT_ID", "") or ""
        if not client_id:
            return Response(
                {"detail": "Google Sign-In is not configured on the server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            idinfo = google_id_token.verify_oauth2_token(
                raw_id_token,
                google_requests.Request(),
                audience=client_id,
            )
        except ValueError:
            return Response(
                {"detail": "Invalid Google ID token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email = (idinfo.get("email") or "").lower().strip()
        if not email:
            return Response(
                {"detail": "Google account did not provide an email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not idinfo.get("email_verified", False):
            return Response(
                {"detail": "Google account email is not verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = (idinfo.get("name") or "").strip() or email.split("@")[0]
        picture = idinfo.get("picture") or ""

        user = User.objects.filter(username=email).first()
        created = False
        if user is None:
            first_name, _, last_name = name.partition(" ")
            user = User(username=email, email=email, first_name=first_name, last_name=last_name)
            user.set_unusable_password()
            user.save()
            created = True
        else:
            # Keep profile fresh without overwriting a deliberately set password account.
            if not user.get_full_name() and name:
                first_name, _, last_name = name.partition(" ")
                user.first_name = first_name
                user.last_name = last_name
                user.save(update_fields=["first_name", "last_name"])

        profile = getattr(user, "profile", None)
        if profile is not None and picture and profile.avatar_url != picture:
            profile.avatar_url = picture
            profile.save(update_fields=["avatar_url"])

        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"token": token.key, "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
