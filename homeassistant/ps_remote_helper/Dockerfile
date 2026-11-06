ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 \
    && adduser -D -H -s /sbin/nologin psrc

WORKDIR /app
COPY ps_remote_checker /app/ps_remote_checker
COPY addon.py panel.html panel.js /app/

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python3", "/app/addon.py"]
