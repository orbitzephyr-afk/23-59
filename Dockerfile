FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY engine ./engine
COPY prompts ./prompts
COPY scenario ./scenario
COPY web ./web

ENV PORT=7860
ENV LLM_BASE_URL=https://api-inference.modelscope.cn/v1/
ENV NPC_MODEL=Qwen/Qwen2.5-7B-Instruct
ENV LLM_MOCK=0
ENV LLM_TIMEOUT=20

EXPOSE 7860

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
