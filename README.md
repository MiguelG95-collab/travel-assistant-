# Travel Assistant CRM Gratis

Incluye:

- Panel principal
- Buscador de destinos
- Hoteles, restaurantes, atractivos y transporte
- CRM de clientes
- Cotizaciones
- Proveedores
- Favoritos
- Respaldo de base de datos

## Publicar gratis en Streamlit Community Cloud

1. Descomprime este archivo.
2. Sube `app.py` y `requirements.txt` a tu repositorio de GitHub.
3. Reemplaza los archivos anteriores.
4. Streamlit actualizará la aplicación automáticamente.
5. Si no se actualiza, abre el panel de Streamlit y pulsa Reboot app.

## Importante sobre los datos

En Streamlit Community Cloud, la base SQLite puede reiniciarse cuando la aplicación se actualiza o duerme.
Por eso:

- Descarga un respaldo desde el módulo Respaldo.
- Descarga CSV de clientes, cotizaciones y proveedores.
- Para almacenamiento permanente gratis, después se puede conectar Supabase.

## Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```
