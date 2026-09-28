FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium
COPY search_terms.py goofish_monitor.py monitor_service.py admin_ui.py admin.html admin.js run_with_admin.py ./
EXPOSE 9087
CMD ["python", "run_with_admin.py"]
