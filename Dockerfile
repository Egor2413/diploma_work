FROM python:3.10-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y gcc

WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Открываем порт
EXPOSE 8000

# Команда по умолчанию (для веб-сервера)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]