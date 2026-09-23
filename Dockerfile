# Two stages: dependencies are built once into a wheel cache, then only the runtime
# bits are copied into a slim image — no compilers, no pip cache, no build leftovers.
FROM python:3.12-slim AS build
WORKDIR /build
COPY app/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /install /usr/local
COPY app/ .

# Unprivileged, fixed uid (the pipeline asserts it); the task runs with a read-only rootfs.
# Strip pip (and its vendored setuptools/wheel) from the RUNTIME image. A
# production container has no business carrying a package installer — and pip
# VENDORS its own msgpack and setuptools, which is where trivy found
# GHSA-6v7p-g79w-8964 and CVE-2025-47273 in the sibling repos. Upgrading our own
# dependencies does nothing for pip's vendored ones; only removing pip does.
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip* \
           /usr/local/lib/python3.12/site-packages/setuptools* \
           /usr/local/lib/python3.12/site-packages/wheel* \
           /usr/local/bin/pip*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
USER appuser

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
# Liveness for docker/compose users; ECS uses the ALB's /health target-group check.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
