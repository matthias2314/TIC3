#!/bin/bash
# Crea en la Raspberry Pi la red WiFi (punto de acceso) a la que se conecta el ESP32.
# La Raspberry queda con la IP 10.42.0.1. Uso: ./AccessPoint.sh

# Configuración
SSID_NAME="RACCOON"
PASSWORD="12345678" # mínimo 8 caracteres
INTERFACE="wlan0"

echo "=== Configurando el punto de acceso '$SSID_NAME' ==="

# 1. Borrar un perfil anterior con el mismo nombre, para evitar conflictos
sudo nmcli connection delete "$SSID_NAME" 2>/dev/null

# 2. Crear e iniciar el punto de acceso (band bg = 2,4 GHz, la única que usa el ESP32-S3)
sudo nmcli device wifi hotspot ifname "$INTERFACE" con-name "$SSID_NAME" \
  ssid "$SSID_NAME" band bg password "$PASSWORD"

# 3. Iniciarlo automáticamente al encender la Raspberry
sudo nmcli connection modify "$SSID_NAME" connection.autoconnect yes

echo "=== Listo: la red '$SSID_NAME' está activa ==="
echo "IP de la Raspberry: $(hostname -I | awk '{print $1}')"
