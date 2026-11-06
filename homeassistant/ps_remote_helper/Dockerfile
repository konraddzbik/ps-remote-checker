# Official multi-arch image (amd64 / arm64 / arm/v7); Supervisor picks the platform via --platform.
FROM python:3.12-alpine3.20

RUN adduser -D -H -s /sbin/nologin psrc

WORKDIR /app
COPY ps_remote_checker /app/ps_remote_checker
COPY addon.py panel.html panel.js /app/

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python3", "/app/addon.py"]
