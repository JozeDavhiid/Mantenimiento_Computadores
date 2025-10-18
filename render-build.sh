#!/usr/bin/env bash
# Script de instalación para Render: instala dependencias del sistema necesarias para WeasyPrint

set -o errexit  # Detener en caso de error

echo "==> Instalando dependencias del sistema necesarias para WeasyPrint..."
apt-get update && apt-get install -y \
  libpango-1.0-0 \
  libcairo2 \
  libpangoft2-1.0-0 \
  libgdk-pixbuf2.0-0 \
  shared-mime-info \
  fonts-liberation \
  fonts-dejavu-core

echo "==> Instalando dependencias de Python..."
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Instalación completada."
