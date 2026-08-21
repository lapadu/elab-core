#include <WiFi.h>
#include <WiFiUdp.h>
#include <SocketIOclient.h>
#include <ArduinoJson.h>
#include <freertos/queue.h>
#include <mbedtls/base64.h>

// --- CONFIGURATION ---
const char* ssid = "my ssid";
const char* password = "my password";
const int RGB_LED_PIN = 8; // ESP32-C6 Mini builtin RGB LED is usually on GPIO 8
volatile float currentMinVoltage = -10.0;
volatile float currentMaxVoltage = 10.0;

const int UDP_DISCOVERY_PORT = 5005;
String serverIP = "";
uint16_t serverPort = 0;
bool serverFound = false;
bool isConnected = false;

WiFiUDP udp;
SocketIOclient socketIO;

// Queue for smooth playback
QueueHandle_t valueQueue;
const int QUEUE_SIZE = 4096; // buffer up to 4096 values
volatile int currentBufferSize = 0; // 0 = Push-Mode with Values

String providerId;

// ==========================================
// DISCOVERY
// ==========================================
void discoverServer() {
    static bool udpBegun = false;
    if (!udpBegun) {
        Serial.printf("\n[DISCOVERY] Suche e_Lab Server via UDP Broadcast (Port %d)...\n", UDP_DISCOVERY_PORT);
        udp.begin(UDP_DISCOVERY_PORT);
        udpBegun = true;
    }
    
    unsigned long lastPrint = 0;
    while (!serverFound) {
        if (millis() - lastPrint > 1000) {
            Serial.print(".");
            lastPrint = millis();
        }

        int packetSize = udp.parsePacket();
        if (packetSize) {
            Serial.printf("\n[DISCOVERY] UDP Paket empfangen! Größe: %d Bytes, Von: %s:%d\n",
                          packetSize, udp.remoteIP().toString().c_str(), udp.remotePort());
            
            char packetBuffer[255];
            int len = udp.read(packetBuffer, 255);
            if (len > 0) packetBuffer[len] = 0;
            
            Serial.printf("[DISCOVERY] Paket-Inhalt: %s\n", packetBuffer);
            
            DynamicJsonDocument doc(512);
            DeserializationError error = deserializeJson(doc, packetBuffer);
            
            if (!error) {
                if (doc["service"] == "elab-dispatcher") {
                    if (doc["ips"].is<JsonArray>()) {
                        JsonArray ips = doc["ips"].as<JsonArray>();
                        for (JsonVariant ip : ips) {
                            String ipStr = ip.as<String>();
                            if (ipStr != "127.0.0.1" && ipStr != "localhost") {
                                serverIP = ipStr;
                                break;
                            }
                        }
                    }
                    if (serverIP == "") serverIP = udp.remoteIP().toString();
                    
                    serverPort = doc["port"].as<uint16_t>();
                    serverFound = true;
                    Serial.printf("[DISCOVERY] -> e_Lab Dispatcher GEFUNDEN: %s:%d (Version: %s, Protocol: %s)\n", 
                                  serverIP.c_str(), serverPort, 
                                  doc["version"].as<String>().c_str(), 
                                  doc["protocol"].as<String>().c_str());
                    
                    udp.stop();
                    udpBegun = false;
                } else {
                    Serial.println("[DISCOVERY] -> Paket ignoriert (Kein e_Lab Service).");
                }
            } else {
                Serial.printf("[DISCOVERY] -> JSON Parse Error: %s\n", error.c_str());
            }
        }
        delay(10);
    }
}

// ==========================================
// MANIFEST REGISTRATION
// ==========================================
void sendManifest() {
    DynamicJsonDocument doc(1024);
    JsonArray array = doc.to<JsonArray>();
    array.add("register_provider");
    
    JsonObject manifest = array.createNestedObject();
    manifest["id"] = providerId;
    manifest["name"] = "ESP32-C6 RGB Actuator";
    manifest["category"] = "HARDWARE";
    
    JsonArray tasks = manifest.createNestedArray("tasks");
    JsonObject task = tasks.createNestedObject();
    task["id"] = providerId + "_rgb_out";
    task["name"] = "Voltage RGB LED";
    task["type"] = "ACTUATOR";
    
    JsonObject ui = task.createNestedObject("ui");
    ui["mode"] = "generic";
    ui["defaultTemplate"] = "tpl_generic_actuator";
    
    JsonArray views = ui.createNestedArray("views");
    JsonObject view1 = views.createNestedObject();
    view1["id"] = "control";
    view1["label"] = "Control";
    view1["icon"] = "Sliders";
    view1["template"] = "tpl_generic_actuator";
    
    JsonObject view2 = views.createNestedObject();
    view2["id"] = "config";
    view2["label"] = "Config";
    view2["icon"] = "Settings";
    view2["template"] = "tpl_device_config";
    
    JsonObject config = task.createNestedObject("config");
    config["unit"] = "V";
    JsonArray range = config.createNestedArray("range");
    range.add(currentMinVoltage);
    range.add(currentMaxVoltage);
    config["min"] = currentMinVoltage;
    config["max"] = currentMaxVoltage;
    config["step"] = 0.1;
    
    // Support array data for high-speed streaming
    JsonArray accepts = config.createNestedArray("accepts");
    accepts.add("scalar");
    accepts.add("array");
    accepts.add("stream");
    
    config["maxRateHz"] = 200; // Recommend 200Hz max to server
    
    JsonArray configFields = config.createNestedArray("configFields");
    JsonObject field1 = configFields.createNestedObject();
    field1["key"] = "bufferSize";
    field1["label"] = "Buffer Size";
    field1["type"] = "select";
    field1["unit"] = "Bytes";
    field1["value"] = currentBufferSize;
    
    JsonArray options = field1.createNestedArray("options");
    
    JsonObject opt0 = options.createNestedObject();
    opt0["label"] = "0 (Push-Mode)";
    opt0["value"] = 0;
    
    JsonObject opt1 = options.createNestedObject();
    opt1["label"] = "1";
    opt1["value"] = 1;
    
    JsonObject opt2 = options.createNestedObject();
    opt2["label"] = "2";
    opt2["value"] = 2;
    
    JsonObject opt4 = options.createNestedObject();
    opt4["label"] = "4";
    opt4["value"] = 4;
    
    JsonObject opt8 = options.createNestedObject();
    opt8["label"] = "8";
    opt8["value"] = 8;
    
    JsonObject opt16 = options.createNestedObject();
    opt16["label"] = "16";
    opt16["value"] = 16;
    
    JsonObject opt32 = options.createNestedObject();
    opt32["label"] = "32";
    opt32["value"] = 32;
    
    JsonObject opt64 = options.createNestedObject();
    opt64["label"] = "64";
    opt64["value"] = 64;
    
    JsonObject opt128 = options.createNestedObject();
    opt128["label"] = "128";
    opt128["value"] = 128;
    
    JsonObject opt256 = options.createNestedObject();
    opt256["label"] = "256";
    opt256["value"] = 256;
    
    JsonObject opt512 = options.createNestedObject();
    opt512["label"] = "512";
    opt512["value"] = 512;
    
    JsonObject opt1024 = options.createNestedObject();
    opt1024["label"] = "1024";
    opt1024["value"] = 1024;
    
    JsonObject opt2048 = options.createNestedObject();
    opt2048["label"] = "2048";
    opt2048["value"] = 2048;
    
    JsonObject opt4096 = options.createNestedObject();
    opt4096["label"] = "4096";
    opt4096["value"] = 4096;
    
    JsonObject field2 = configFields.createNestedObject();
    field2["key"] = "minVoltage";
    field2["label"] = "Min Voltage";
    field2["type"] = "number";
    field2["min"] = -1000.0;
    field2["max"] = 1000.0;
    field2["step"] = 0.1;
    field2["unit"] = "V";
    field2["value"] = currentMinVoltage;
    
    JsonObject field3 = configFields.createNestedObject();
    field3["key"] = "maxVoltage";
    field3["label"] = "Max Voltage";
    field3["type"] = "number";
    field3["min"] = -1000.0;
    field3["max"] = 1000.0;
    field3["step"] = 0.1;
    field3["unit"] = "V";
    field3["value"] = currentMaxVoltage;
    
    if (currentBufferSize > 0) {
        config["maxBufferSize"] = currentBufferSize;
        config["sampleRate"] = 1000;
        
        JsonObject decoder = config.createNestedObject("decoder");
        decoder["type"] = "generic_binary";
        decoder["dataType"] = "int16";
        decoder["endianness"] = "little";
        decoder["zeroValue"] = 0.0;
        decoder["valueRange"] = 32767.0;
        decoder["measurementRange"] = 10.0;
    }

    String output;
    serializeJson(doc, output);
    socketIO.sendEVENT(output);
    Serial.println("Manifest gesendet.");
}

// ==========================================
// SOCKET.IO EVENT HANDLER
// ==========================================
void socketIOEvent(socketIOmessageType_t type, uint8_t * payload, size_t length) {
    switch(type) {
        case sIOtype_DISCONNECT:
            Serial.printf("\n[SIO] Verbindung zum Dispatcher verloren! (DISCONNECTED) Grund: %s\n", payload ? (char*)payload : "unbekannt");
            isConnected = false;
            break;
        case sIOtype_CONNECT:
            Serial.printf("\n[SIO] Verbindung zum Dispatcher HERGESTELLT! URL: %s\n", payload);
            socketIO.send(sIOtype_CONNECT, "/");
            isConnected = true;
            sendManifest();
            break;
        case sIOtype_EVENT: {
            // Allocate a large document to handle array payload. ESP32-C6 has enough RAM.
            DynamicJsonDocument doc(8192);
            DeserializationError err = deserializeJson(doc, payload);
            if (err) {
                Serial.printf("JSON parse error: %s\n", err.c_str());
                break;
            }
            
            String eventName = doc[0];
            if (eventName == "execute_command") {
                JsonObject commandObj = doc[1]["command"];
                String action = commandObj["action"];
                JsonObject payloadObj = commandObj["payload"];
                
                if (action == "update_config") {
                    bool changed = false;
                    if (payloadObj.containsKey("bufferSize")) {
                        currentBufferSize = payloadObj["bufferSize"].as<int>();
                        Serial.printf("  -> Neue Buffer Size: %d\n", currentBufferSize);
                        changed = true;
                    }
                    if (payloadObj.containsKey("minVoltage")) {
                        currentMinVoltage = payloadObj["minVoltage"].as<float>();
                        Serial.printf("  -> Neue Min Voltage: %.1f\n", currentMinVoltage);
                        changed = true;
                    }
                    if (payloadObj.containsKey("maxVoltage")) {
                        currentMaxVoltage = payloadObj["maxVoltage"].as<float>();
                        Serial.printf("  -> Neue Max Voltage: %.1f\n", currentMaxVoltage);
                        changed = true;
                    }
                    if (changed) {
                        sendManifest();
                    }
                } else {
                    // Parse scalar value
                    if (payloadObj.containsKey("value") && !payloadObj["value"].isNull()) {
                        float val = payloadObj["value"].as<float>();
                        xQueueSend(valueQueue, &val, 0);
                    }
                    
                    // Parse array values (JSON)
                    if (payloadObj.containsKey("values")) {
                        JsonArray arr = payloadObj["values"].as<JsonArray>();
                        int count = arr.size();
                        if (count > 0) {
                            for (JsonVariant v : arr) {
                                float val = v.as<float>();
                                if (xQueueSend(valueQueue, &val, 0) != pdPASS) {
                                    break;
                                }
                            }
                        }
                    }
                    
                    // Parse binary values (Base64)
                    if (payloadObj.containsKey("binary_payload_b64")) {
                        const char* b64 = payloadObj["binary_payload_b64"];
                        size_t b64_len = strlen(b64);
                        size_t out_len = 0;
                        
                        // Buffer for max 2048 int16 = 4096 bytes
                        uint8_t bin_buf[4096];
                        int ret = mbedtls_base64_decode(bin_buf, sizeof(bin_buf), &out_len, (const unsigned char*)b64, b64_len);
                        
                        if (ret == 0) {
                            int count = out_len / 2; // int16 is 2 bytes
                            if (count > 0) {
                                int16_t* pValues = (int16_t*)bin_buf;
                                for (int i = 0; i < count; i++) {
                                    float val = ((float)pValues[i] / 32767.0f) * 10.0f;
                                    if (xQueueSend(valueQueue, &val, 0) != pdPASS) {
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
            }
            break;
        }
        case sIOtype_ERROR:
            Serial.printf("\n[SIO] Socket.IO Fehler: %s\n", payload ? (char*)payload : "unbekannt");
            break;
        default: break;
    }
}

// ==========================================
// LED PLAYBACK TASK
// ==========================================
void playbackTask(void * pvParameters) {
    float val;
    while(true) {
        // Wait for a value to arrive in the queue
        if (xQueueReceive(valueQueue, &val, portMAX_DELAY) == pdPASS) {
            
            // Limit to [currentMinVoltage, currentMaxVoltage]
            if (val > currentMaxVoltage) val = currentMaxVoltage;
            if (val < currentMinVoltage) val = currentMinVoltage;
            
            int brightness = 0;
            if (val > 0 && currentMaxVoltage > 0) {
                brightness = (int)((val / currentMaxVoltage) * 255.0);
                if (brightness > 255) brightness = 255;
                neopixelWrite(RGB_LED_PIN, 0, brightness, 0); // Green
            } else if (val < 0 && currentMinVoltage < 0) {
                brightness = (int)((val / currentMinVoltage) * 255.0);
                if (brightness > 255) brightness = 255;
                neopixelWrite(RGB_LED_PIN, brightness, 0, 0); // Red
            } else {
                // Zero: Off
                neopixelWrite(RGB_LED_PIN, 0, 0, 0);
            }
        }
    }
}

// ==========================================
// SETUP & LOOP
// ==========================================
void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\nStarte ESP32-C6 RGB Actuator...");

    // Turn off LED initially
    neopixelWrite(RGB_LED_PIN, 0, 0, 0);

    // Create FreeRTOS queue
    valueQueue = xQueueCreate(QUEUE_SIZE, sizeof(float));

    // Connect to WiFi
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);
    Serial.print("Verbinde mit WLAN");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWLAN verbunden.");

    // Get unique provider ID based on MAC (must be done AFTER WiFi is initialized)
    String mac = WiFi.macAddress();
    mac.replace(":", "");
    providerId = "esp32c6_rgb_" + mac;

    // Start playback task on Core 1 (or 0 since C6 is single core, FreeRTOS handles it)
    xTaskCreate(playbackTask, "Playback", 2048, NULL, 1, NULL);

    discoverServer();

    // Connect to Socket.IO
    String url = serverIP;
    socketIO.begin(url, serverPort, "/socket.io/?EIO=4");
    socketIO.onEvent(socketIOEvent);
}

void loop() {
    socketIO.loop();
    
    // Auto-reconnect if discovery lost
    if (!isConnected && serverFound) {
        // Could implement reconnect logic here, but SocketIOclient auto-reconnects
    }
}
