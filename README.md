# Asistente de Destinos para Agencia de Viajes

Aplicación local para Windows. Permite buscar una ciudad y consultar:

- Hora local y diferencia con Ciudad de México
- Clima actual
- Hoteles y clasificación por estrellas cuando esté registrada
- Restaurantes, teléfonos, horarios y sitios web cuando estén registrados
- Lugares turísticos
- Estaciones, paradas y aeropuertos
- Distancias desde el centro
- Mapa interactivo
- Favoritos propios de la agencia
- Exportación CSV y resumen TXT

## Instalación en Windows

1. Instala Python 3.11 o superior desde python.org.
2. Durante la instalación activa la opción **Add Python to PATH**.
3. Extrae esta carpeta completa.
4. Haz doble clic en `INSTALAR.bat`.
5. Cuando termine, haz doble clic en `INICIAR_APP.bat`.
6. La aplicación abrirá en el navegador, normalmente en `http://localhost:8501`.

## Importante

La primera versión usa Open-Meteo y datos colaborativos de OpenStreetMap/Overpass.
Por eso algunos negocios pueden no tener teléfono, sitio web, horario o estrellas cargados.

Para una segunda versión se pueden agregar:
- Google Places para teléfonos y fichas comerciales más completas
- Amadeus para hoteles, tarifas y disponibilidad
- Generación de PDF con el logotipo de la agencia
- Integración con WhatsApp
- Usuarios para empleados
- Tarifas, comisiones y proveedores internos

## Solución rápida de problemas

- Si Windows bloquea un archivo `.bat`, pulsa “Más información” y luego “Ejecutar de todas formas”.
- Si aparece que Python no existe, reinstálalo activando “Add Python to PATH”.
- Para cerrar la aplicación, cierra la ventana negra o presiona `Ctrl + C`.
