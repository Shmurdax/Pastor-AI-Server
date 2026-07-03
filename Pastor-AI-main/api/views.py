import os
import re

import unsloth  # noqa: F401
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from rest_framework.response import Response
from rest_framework.views import APIView
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template

BASE_MODEL = os.environ.get(
    "CHRISTIANAI_BASE_MODEL", "unsloth/Qwen2.5-14B-Instruct-bnb-4bit"
)
LORA_DIR = os.environ.get("CHRISTIANAI_LORA_DIR", "/root/christianai-lora")
MAX_SEQ_LENGTH = int(os.environ.get("CHRISTIANAI_MAX_SEQ_LENGTH", "1536"))

_model = None
_tokenizer = None
_retriever = None
_embeddings = None

SYSTEM_PROMPT = (
    "You are a thoughtful evangelical Christian teacher and pastor's assistant. "
    "Use ONLY the following sermon notes and Bible passages to answer. "
    "Answer in 2-4 paragraphs with pastoral warmth and biblical language. "
    "Do not include radio outros, show sign-offs, or host introductions. "
    "If the answer is not in the context, say you don't have that information.\n\n"
    "Context:\n{context}"
)


def clean_answer(text: str, question: str = "") -> str:
    if question and question in text:
        text = text.split(question, 1)[-1]
    if re.search(r"\bassistant\b", text, re.IGNORECASE):
        text = re.split(r"\bassistant\b", text, flags=re.IGNORECASE)[-1]
    return re.sub(r"^(assistant|user)\s*", "", text, flags=re.IGNORECASE).strip()


def get_retriever():
    global _embeddings, _retriever

    if _retriever is not None:
        return _retriever

    _embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_db = QdrantVectorStore.from_existing_collection(
        embedding=_embeddings,
        url="http://localhost:6333",
        collection_name="sermon_brain",
    )
    _retriever = vector_db.as_retriever(search_kwargs={"k": 3})
    return _retriever


def get_model():
    global _model, _tokenizer

    if _model is not None and _tokenizer is not None:
        return _model, _tokenizer

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )
    if os.path.isdir(LORA_DIR):
        model.load_adapter(LORA_DIR)
    tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
    FastLanguageModel.for_inference(model)
    _model = model
    _tokenizer = tokenizer
    return _model, _tokenizer


def generate_answer(question: str, context: str) -> str:
    model, tokenizer = get_model()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
        {"role": "user", "content": question},
    ]
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
    outputs = model.generate(
        **inputs,
        max_new_tokens=512,
        temperature=0.7,
        top_p=0.9,
        do_sample=True,
        use_cache=True,
    )
    new_tokens = outputs[0][inputs["input_ids"].shape[1] :]
    raw = tokenizer.decode(new_tokens, skip_special_tokens=True)
    return clean_answer(raw, question)


class ChatAPI(APIView):
    def post(self, request):
        user_query = request.data.get("prompt") or request.data.get("query")
        if not user_query:
            return Response({"error": "No query provided"}, status=400)

        try:
            retriever = get_retriever()
            docs = retriever.invoke(user_query)
            context = "\n\n".join(doc.page_content for doc in docs)
            answer = generate_answer(user_query, context)
        except Exception as exc:  # noqa: BLE001
            return Response(
                {
                    "error": "AI system not ready.",
                    "detail": str(exc),
                },
                status=503,
            )

        return Response(
            {
                "answer": answer,
                "sources": [
                    os.path.basename(doc.metadata.get("source", "Unknown"))
                    for doc in docs
                ],
            }
        )
