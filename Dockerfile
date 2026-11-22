# Quyu well intelligence studio - container image (works on Hugging Face Spaces, Render, Railway, any Docker host)
FROM python:3.12-slim
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 PORT=8765 QUYU_PUBLIC=1 MPLBACKEND=Agg
WORKDIR $HOME/app
COPY --chown=user requirements.txt .
# ipykernel is only needed for the notebooks
RUN grep -v ipykernel requirements.txt > /tmp/req.txt && pip install --no-cache-dir --user -r /tmp/req.txt
COPY --chown=user . .
EXPOSE 8765
CMD ["python", "run.py", "--no-browser"]
