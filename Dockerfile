FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

#CLI standalone de Tailwind (sin Node/npm) — pineado a v3.4.17 para que coincida con el config
#(tailwind.config.js usa la sintaxis de theme.extend de v3, no la de v4).
RUN curl -sL -o /usr/local/bin/tailwindcss \
        https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64 \
    && chmod +x /usr/local/bin/tailwindcss

COPY . .

#Compila el CSS real (necesita el código ya copiado, escanea los .html) y junta los estáticos.
#collectstatic no dispara pedidos/apps.py::ready() (solo "runserver" lo hace, ver ese archivo) —
#no necesita Postgres disponible durante el build de la imagen.
RUN tailwindcss -i static/css/tailwind-src.css -o static/css/app.css --minify \
    && python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "gestorBQ.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
