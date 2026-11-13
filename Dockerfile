FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# bake the face models into the image so cold starts don't download them
RUN python -c "from app import face; face.ensure_models()"
ENV PORT=8000
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
