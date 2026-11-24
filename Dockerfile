FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=build_ca,target=/etc/ssl/certs/ca-certificates.crt pip install --cert /etc/ssl/certs/ca-certificates.crt --no-cache-dir -r requirements.txt
COPY --chown=65532:65532 bot.py dashboard.py db.py text_parser.py texts.py ./
COPY --chown=65532:65532 growth ./growth
COPY --chown=65532:65532 static ./static
USER 65532:65532
EXPOSE 8000
CMD ["python","dashboard.py"]
