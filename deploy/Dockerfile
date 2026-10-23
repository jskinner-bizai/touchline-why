# Preparation only. No image was pulled or built during this task.
# Build context must be hosted-playtest/, not the workstation or canonical source.
# Supply an approved, security-reviewed Python 3.12 Linux image pinned by digest.
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Explicit application allowlist: excludes runtime data, feedback, test grants,
# review evidence, frozen distribution archives and workstation configuration.
COPY base/ /app/base/
COPY web/ /app/web/
COPY hosted_app.py feedback_admin.py /app/

RUN ["mkdir", "-p", "/data"]
RUN ["chown", "10001:10001", "/data"]
USER 10001:10001
EXPOSE 8080
VOLUME ["/data"]

ENTRYPOINT ["python", "-B", "hosted_app.py", "--data-dir", "/data", "--bind", "0.0.0.0", "--port", "8080"]
# The deployment supplies --origin. No permissive default origin or test grant.
