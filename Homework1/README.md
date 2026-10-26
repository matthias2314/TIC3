# Tarea 1 – TIC3: cómo ejecutar el código

## 1. Crear la red WiFi en la Raspberry Pi

```bash
chmod +x AccessPoint.sh      # solo la primera vez
./AccessPoint.sh
```

Crea la red `RACCOON` (clave `12345678`, 2,4 GHz). La Raspberry queda con la IP **10.42.0.1**.

## 2. Iniciar el servidor en la Raspberry Pi

```bash
cd TCP_server
python3 web_server.py
```

Solo usa la biblioteca estándar de Python (3.9 o superior); no hay que instalar nada.

## 3. Encender el ESP32

El ESP32 ya está programado para conectarse a la red `RACCOON` y al servidor `10.42.0.1`. Basta con alimentarlo: se conecta solo.

Para volver a programarlo (ESP-IDF 6.1): copiar `esp32/main/secrets.h.example` como `secrets.h`, completar la red y la IP, y desde `esp32/` ejecutar:

```bash
idf.py set-target esp32s3
idf.py build flash monitor
```

## 4. Abrir la interfaz

Conectar el computador (o el celular) a la red `RACCOON` y abrir en el navegador:

```
http://10.42.0.1:8080
```

Elegir transporte, modo, frecuencia, rango y duración, y presionar **Start**. Los datos de cada sesión se guardan en `TCP_server/sensores/` (un CSV y un JSON por sesión).
