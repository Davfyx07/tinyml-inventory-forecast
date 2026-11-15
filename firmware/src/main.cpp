#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "secrets.h"

const char* TEMA_CONFIG = "homeassistant/sensor/pronostico_manzana_7d/config";
const char* TEMA_PRONOSTICO = "inventario/manzana/pronostico";

const char* CONFIG_SENSOR = R"({
  "name": "Pronóstico manzana 7d",
  "unique_id": "pronostico_manzana_7d",
  "state_topic": "inventario/manzana/pronostico",
  "value_template": "{{ value_json.total_7d }}",
  "json_attributes_topic": "inventario/manzana/pronostico",
  "unit_of_measurement": "unidades"
})";

const unsigned long INTERVALO_MS = 60000;  // etapa 1: cada minuto, para ver el resultado rápido

WiFiClient clienteRed;
PubSubClient mqtt(clienteRed);
unsigned long ultimoEnvio = 0;

void conectarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi conectado. IP del ESP32: %s\n", WiFi.localIP().toString().c_str());
}

void conectarMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Conectando a MQTT... ");
    if (mqtt.connect("esp32-inventario", MQTT_USER, MQTT_PASS)) {
      Serial.println("conectado");
      mqtt.publish(TEMA_CONFIG, CONFIG_SENSOR, true);
    } else {
      Serial.printf("falló (código %d), reintento en 5 s\n", mqtt.state());
      delay(5000);
    }
  }
}

void publicarPronostico() {
  // Etapa 1: valores fijos de prueba. En la etapa 3 los calcula el modelo.
  char mensaje[256];
  snprintf(mensaje, sizeof(mensaje),
           "{\"total_7d\": 52, \"lunes\": 9, \"martes\": 6, \"miercoles\": 6, \"jueves\": 7, "
           "\"viernes\": 8, \"sabado\": 9, \"domingo\": 7, \"origen\": \"esp32\", \"segundos_encendido\": %lu}",
           millis() / 1000);
  bool enviado = mqtt.publish(TEMA_PRONOSTICO, mensaje, true);
  Serial.printf("Pronóstico publicado: %s\n", enviado ? "sí" : "no");
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  conectarWiFi();
  mqtt.setServer(MQTT_HOST, 1883);
  mqtt.setBufferSize(512);  // el mensaje de descubrimiento supera los 256 bytes por defecto
}

void loop() {
  if (!mqtt.connected()) {
    conectarMQTT();
  }
  mqtt.loop();
  if (ultimoEnvio == 0 || millis() - ultimoEnvio >= INTERVALO_MS) {
    publicarPronostico();
    ultimoEnvio = millis();
  }
}