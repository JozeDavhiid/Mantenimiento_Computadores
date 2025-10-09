# Mantenimiento Web - Flask

Proyecto migrado desde Tkinter a una app web con Flask, Bootstrap y SQLite.

## Características
- Login de técnicos
- Registro de técnicos
- CRUD completo de registros de mantenimiento
- Búsqueda y filtro por sede
- Exportar a Excel (XLSX)

## Ejecutar localmente
1. Crear y activar un entorno virtual (recomendado)
2. Instalar dependencias:
   ```
   pip install -r requirements.txt
   ```
3. Inicializar la base de datos (opcional — la app también la crea al iniciarse):
   ```
   python init_db.py
   ```
4. Ejecutar:
   ```
   python app.py
   ```
5. Abrir en el navegador: http://localhost:5000

## Despliegue en Render
1. Crear un nuevo Web Service en Render.
2. Conectar tu repositorio (GitHub/GitLab).
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Añade variable de entorno `SECRET_KEY` para seguridad y `DB_NAME` si deseas otro nombre de DB.