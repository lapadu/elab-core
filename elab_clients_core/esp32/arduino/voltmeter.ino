#include <WiFi.h>
#include <WiFiUdp.h>
#include <SocketIOclient.h>
#include <ArduinoJson.h>
#include <freertos/queue.h>
#include "driver/i2s.h"
#include "esp_task_wdt.h"
#include <Preferences.h>
#include <mbedtls/md.h>
#include <time.h>
#include <sys/time.h>

// --- WATCHDOG CONFIGURATION ---
// Hardware task watchdog timeout. The processing task and the main loop
// must reset the WDT regularly; otherwise the chip resets cleanly instead
// of dropping into an undefined state when WiFi/I2S blocks unexpectedly.
static const uint32_t WDT_TIMEOUT_SECONDS = 8;

// --- TX FRAME LIMIT ---
// Maximum uint16 sample values packed into a single Socket.IO frame.
// Keeps the resulting JSON well below typical WebSocket buffer limits
// (~8 KB on the engineio server side) and prevents the truncated-payload
// JSONDecodeError that the dispatcher previously had to filter out.
static const int MAX_VALUES_PER_FRAME = 1024;

// --- CONFIGURATION ---
const char* ssid = "my ssid";
const char* password = "my password";
// e_Lab configuration
const int UDP_DISCOVERY_PORT = 5005;
String serverIPs[10];
int serverIPCount = 0;
int currentServerIPIndex = 0;
String serverIP = "";
uint16_t serverPort = 0;
bool serverFound = false;

// Calculation constants
const float MEASUREMENT_RANGE = 40.0;
const float VALUE_RANGE = 2402.0;
const float ZERO_VALUE = 1201.0;

// --- DYNAMIC PARAMETERS (configurable through e_Lab) ---
int currentSampleRate = 20000;
int currentMedianGroupSize = 5;
int currentDmaBufferSamples = 2560;

// --- STATE MANAGEMENT ---
enum State { DISCOVERY, STANDARD_MODUS, RAW_START, RAW_MESSUNG_LAEUFT, RAW_WIEDERVERBINDEN, RAW_DATEN_SENDEN, RAW_ENDE };
volatile State currentState = DISCOVERY;

// --- GLOBAL OBJECTS ---
WiFiUDP udp;
SocketIOclient socketIO;
QueueHandle_t dataQueue;
class VoltMeter;
VoltMeter* voltMeter = nullptr;
TaskHandle_t voltMeterTaskHandle = NULL;

// Dynamic buffer used for raw capture.
uint8_t* rawDataBuffer = nullptr;
int rawDataBufferSize = 0;

volatile bool i2s_driver_is_installed = false;
volatile bool justConnected = false;

volatile bool stopProcessingTask = false;
volatile bool taskIsFinished = true;
volatile bool configChangePending = false;
volatile bool sendRawBeforeStandard = false;

// --- RECONNECT MANAGEMENT ---
volatile bool needsReconnect = false;
unsigned long reconnectStartTime = 0;
int reconnectAttempt = 0;
const int MAX_RECONNECT_ATTEMPTS = 5;

// WDT subscription state for the main loop task. We defer subscription
// until the socket is connected, because socketIO.loop() can block for
// >8 s during TCP handshake, which would trigger a false WDT reset.
static bool loopWdtActive = false;

// ======================================================================
// AUTHENTICATION (TOFU pairing + HMAC-SHA256 signing of data_stream)
// ======================================================================
// The dispatcher quarantines unknown providers until an operator approves
// them in the workbench. After approval the dispatcher sends back a
// one-shot shared secret (`registration_approved`) which we persist in
// NVS. Every subsequent `data_stream` packet is signed with HMAC-SHA256
// over ("<ts>\n" + canonical JSON of payload-without-auth). The server
// drops any packet that doesn't carry a valid signature.
//
// CRITICAL: the inner payload JSON MUST be emitted with keys in strict
// alphabetical order so that the bytes we hash here match what the server
// canonicalizes via json.dumps(sort_keys=True, separators=(",",":")).
static Preferences authPrefs;
static String hmacSecretHex = "";   // 64 hex chars when present
static bool   isApproved    = false;
static const char* AUTH_NVS_NS  = "elab_auth";
static const char* AUTH_NVS_KEY = "secret";
static const char* DEVICE_ID    = "esp32_voltmeter_01"; // must match manifest.id

static void loadStoredSecret() {
    authPrefs.begin(AUTH_NVS_NS, true /* readonly */);
    String stored = authPrefs.getString(AUTH_NVS_KEY, "");
    authPrefs.end();
    if (stored.length() == 64) {
        hmacSecretHex = stored;
        isApproved = true;
        Serial.println("[AUTH] Cached pairing secret loaded from NVS.");
    } else {
        Serial.println("[AUTH] No pairing secret yet — waiting for operator approval.");
    }
}

static void saveSecret(const String& sec) {
    authPrefs.begin(AUTH_NVS_NS, false /* read/write */);
    authPrefs.putString(AUTH_NVS_KEY, sec);
    authPrefs.end();
}

static void clearSecret() {
    authPrefs.begin(AUTH_NVS_NS, false);
    authPrefs.remove(AUTH_NVS_KEY);
    authPrefs.end();
    hmacSecretHex = "";
    isApproved = false;
    Serial.println("[AUTH] Pairing secret cleared (revoked).");
}

// Convert hex string to byte array. Returns true on success.
static bool hexToBytes(const String& hex, uint8_t* out, size_t outLen) {
    if (hex.length() != outLen * 2) return false;
    for (size_t i = 0; i < outLen; i++) {
        char hi = hex.charAt(i * 2);
        char lo = hex.charAt(i * 2 + 1);
        auto nib = [](char c) -> int {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
            if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
            return -1;
        };
        int h = nib(hi), l = nib(lo);
        if (h < 0 || l < 0) return false;
        out[i] = (uint8_t)((h << 4) | l);
    }
    return true;
}

static void bytesToHex(const uint8_t* in, size_t len, char* out) {
    static const char* HEX_CHARS = "0123456789abcdef";
    for (size_t i = 0; i < len; i++) {
        out[i * 2]     = HEX_CHARS[(in[i] >> 4) & 0x0F];
        out[i * 2 + 1] = HEX_CHARS[in[i] & 0x0F];
    }
    out[len * 2] = '\0';
}

// Compute HMAC-SHA256 over (prefix || data). Writes 64 hex chars + NUL.
static bool computeHmacHex(const uint8_t* key, size_t keyLen,
                           const char* prefix, size_t prefixLen,
                           const char* data,   size_t dataLen,
                           char* sigHexOut) {
    const mbedtls_md_info_t* mdInfo = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (!mdInfo) return false;
    mbedtls_md_context_t ctx;
    mbedtls_md_init(&ctx);
    if (mbedtls_md_setup(&ctx, mdInfo, 1 /* HMAC */) != 0) {
        mbedtls_md_free(&ctx);
        return false;
    }
    uint8_t mac[32];
    int rc = mbedtls_md_hmac_starts(&ctx, key, keyLen);
    if (rc == 0) rc = mbedtls_md_hmac_update(&ctx, (const uint8_t*)prefix, prefixLen);
    if (rc == 0) rc = mbedtls_md_hmac_update(&ctx, (const uint8_t*)data, dataLen);
    if (rc == 0) rc = mbedtls_md_hmac_finish(&ctx, mac);
    mbedtls_md_free(&ctx);
    if (rc != 0) return false;
    bytesToHex(mac, sizeof(mac), sigHexOut);
    return true;
}

// Get wall-clock time as seconds + microseconds since the Unix epoch.
// Returns false if NTP hasn't synced yet (year < 2020).
static bool getEpochTime(unsigned long* secOut, unsigned long* usecOut) {
    struct timeval tv;
    if (gettimeofday(&tv, nullptr) != 0) return false;
    if (tv.tv_sec < 1577836800UL /* 2020-01-01 */) return false;
    *secOut  = (unsigned long)tv.tv_sec;
    *usecOut = (unsigned long)tv.tv_usec;
    return true;
}

// ======================================================================
// MANIFEST FOR E-LAB
// ======================================================================
void sendManifest() {
    Serial.println("[MANIFEST] Generiere Manifest...");
   
    // Reserve enough document space for configFields, decoder settings, and extra views.
    DynamicJsonDocument doc(5120);
    JsonArray array = doc.to<JsonArray>();
   
    array.add("register_provider");
   
    JsonObject manifest = array.createNestedObject();
    manifest["id"] = "esp32_voltmeter_01";
    manifest["name"] = "ESP32 High-Speed ADC";
    manifest["category"] = "HARDWARE";
    manifest["isUiInstance"] = false; // Prevent the frontend from classifying it as a hidden UI plugin.
    manifest["version"] = "1.0";
   
    JsonArray capabilities = manifest.createNestedArray("capabilities");
    capabilities.add("measure");
    capabilities.add("voltage");

    JsonArray tasks = manifest.createNestedArray("tasks");
    JsonObject task1 = tasks.createNestedObject();
    task1["id"] = "esp32_voltmeter_01_ch1";
    task1["name"] = "Spannung CH1";
    task1["type"] = "SENSOR";
    task1["groupId"] = "plugin_volt_v1";
    task1["virtual"] = false;
    task1["color"] = "#eab308";
   
    JsonObject config = task1.createNestedObject("config");
    JsonArray range = config.createNestedArray("range");
    range.add(-20);
    range.add(20);
    config["unit"] = "mV";
    config["factor"] = 1.0;
    // Markiere als singleSource, damit der ScopeGraphWidget die eignen Daten anzeigt
    config["singleSource"] = true;

    // --- ACCURACY MODEL (ESP32 SAR ADC) ---
    // Specs: 12-bit, INL ±12 LSB, ±6% variation among samples.
    // LSB in mV = MEASUREMENT_RANGE / VALUE_RANGE ≈ 0.01665 mV
    // Systematic (INL): 12 LSB * LSB = ~0.2 mV absolute offset.
    // Random (noise): ±6% of reading, reduced by median filter: 6% / sqrt(n).
    // Model: percent_reading_plus_absolute combines both contributions.
    JsonObject accuracy = config.createNestedObject("accuracy");
    accuracy["model"] = "percent_reading_plus_absolute";
    accuracy["relativePctReading"] = 6.0 / sqrt((double)currentMedianGroupSize);
    accuracy["absoluteOffset"] = 12.0 * (MEASUREMENT_RANGE / VALUE_RANGE);
    accuracy["confidenceK"] = 2.0;
   
    // Describe the configurable parameters for the DeviceConfig template.
    JsonArray configFields = config.createNestedArray("configFields");

    JsonObject field1 = configFields.createNestedObject();
    field1["key"] = "sampleRate";
    field1["label"] = "Sample Rate";
    field1["type"] = "slider";
    field1["min"] = 1000;
    field1["max"] = 100000;
    field1["step"] = 1000;
    field1["unit"] = "Hz";
    field1["value"] = currentSampleRate;

    JsonObject field2 = configFields.createNestedObject();
    field2["key"] = "medianGroupSize";
    field2["label"] = "Median Group Size";
    field2["type"] = "slider";
    field2["min"] = 1;
    field2["max"] = 51;
    field2["step"] = 2;
    field2["unit"] = "";
    field2["value"] = currentMedianGroupSize;

    JsonObject field3 = configFields.createNestedObject();
    field3["key"] = "dmaBufferSamples";
    field3["label"] = "DMA Buffer Samples";
    field3["type"] = "slider";
    field3["min"] = 256;
    // Cap at 4096 samples; larger blocks would still be chunked at the
    // WS layer, so allowing more here only wastes RAM.
    field3["max"] = 4096;
    field3["step"] = 256;
    field3["unit"] = "Samples";
    field3["value"] = currentDmaBufferSamples;

    // Decoder configuration: the server converts raw_bytes into floats.
    JsonObject decoder = task1.createNestedObject("decoder");
    decoder["type"] = "generic_binary";
    JsonObject decParams = decoder.createNestedObject("parameters");
    decParams["dataType"] = "uint16";
    decParams["endianness"] = "big";
    decParams["zeroValue"] = ZERO_VALUE;
    decParams["valueRange"] = VALUE_RANGE;
    decParams["measurementRange"] = MEASUREMENT_RANGE;

    JsonObject ui = task1.createNestedObject("ui");
    ui["mode"] = "generic";
    ui["defaultTemplate"] = "tpl_scope"; // The React UI expects defaultTemplate here.

    // Declare supported special actions so the UI can show them selectively.
    JsonArray actions = task1.createNestedArray("actions");
    JsonObject rawAction = actions.createNestedObject();
    rawAction["id"] = "START_RAW";
    rawAction["label"] = "RAW Capture";
    rawAction["icon"] = "Camera";
   
    JsonArray views = ui.createNestedArray("views");
    JsonObject view1 = views.createNestedObject();
    view1["id"] = "graph";
    view1["label"] = "Scope";
    view1["icon"] = "Activity";
    view1["template"] = "tpl_scope";
   
    JsonObject view2 = views.createNestedObject();
    view2["id"] = "metric";
    view2["label"] = "Metric";
    view2["icon"] = "Maximize2";
    view2["template"] = "tpl_metric";
   
    JsonObject view3 = views.createNestedObject();
    view3["id"] = "config";
    view3["label"] = "Config";
    view3["icon"] = "Settings";
    view3["template"] = "tpl_device_config";

    String output;
    serializeJson(doc, output);
   
    Serial.println("[MANIFEST] JSON-Payload der gesendet wird:");
    Serial.println(output);
   
    socketIO.sendEVENT(output);
    Serial.printf("[MANIFEST] Erfolgreich an e_Lab gesendet. (Länge: %d Bytes)\n", output.length());
}

// ======================================================================
// UDP DISCOVERY (finds the e_Lab server on the network)
// ======================================================================
void discoverServer() {
    static bool udpBegun = false;
    if (!udpBegun) {
        Serial.printf("\n[DISCOVERY] Suche e_Lab Server via UDP Broadcast (Port %d)...\n", UDP_DISCOVERY_PORT);
        udp.begin(UDP_DISCOVERY_PORT);
        udpBegun = true;
    }
   
    unsigned long lastDotTime = 0;
    while (!serverFound) {
        if (millis() - lastDotTime > 1000) {
            Serial.print(".");
            lastDotTime = millis();
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
                    serverIPCount = 0;
                    currentServerIPIndex = 0;
                    
                    // Parse the IP list sent by the server.
                    if (doc["ips"].is<JsonArray>()) {
                        JsonArray ips = doc["ips"].as<JsonArray>();
                        for (JsonVariant ip : ips) {
                            if (serverIPCount < 10) {
                                String ipStr = ip.as<String>();
                                if (ipStr != "127.0.0.1" && ipStr != "localhost") {
                                    serverIPs[serverIPCount++] = ipStr;
                                }
                            }
                        }
                    }
                    
                    // Append the actual packet sender IP as a candidate if not already present
                    String remoteIPStr = udp.remoteIP().toString();
                    bool remoteIPExists = false;
                    for (int i = 0; i < serverIPCount; i++) {
                        if (serverIPs[i] == remoteIPStr) {
                            remoteIPExists = true;
                            break;
                        }
                    }
                    if (!remoteIPExists && serverIPCount < 10) {
                        serverIPs[serverIPCount++] = remoteIPStr;
                    }
                    
                    // If no valid external IPs were found, include the loopback address as a last resort
                    if (serverIPCount == 0) {
                        serverIPs[serverIPCount++] = "127.0.0.1";
                    }
                    
                    serverIP = serverIPs[0];
                    serverPort = doc["port"].as<uint16_t>();
                    serverFound = true;
                    Serial.printf("[DISCOVERY] -> e_Lab Dispatcher GEFUNDEN: %s:%d (Version: %s, Protocol: %s)\n", 
                                  serverIP.c_str(), serverPort, 
                                  doc["version"].as<String>().c_str(), 
                                  doc["protocol"].as<String>().c_str());
                                  
                    Serial.print("[DISCOVERY] IP-Kandidaten: ");
                    for (int i = 0; i < serverIPCount; i++) {
                        Serial.printf("%s%s", serverIPs[i].c_str(), (i == serverIPCount - 1) ? "" : ", ");
                    }
                    Serial.println();
                    
                    udp.stop();
                    udpBegun = false;
                } else {
                    Serial.println("[DISCOVERY] -> Paket ignoriert (Kein e_Lab Service).");
                }
            } else {
                Serial.printf("[DISCOVERY] -> JSON Parse Error: %s\n", error.c_str());
            }
        }
        delay(10); // Small delay to feed the watchdog while still catching packets quickly.
    }
}

void startStandardMode(); // Forward declaration

// ======================================================================
// SOCKET.IO EVENT HANDLER
// ======================================================================
void socketIOEvent(socketIOmessageType_t type, uint8_t * payload, size_t length) {
    switch(type) {
        case sIOtype_DISCONNECT:
            Serial.printf("\n[SIO] Verbindung zum Dispatcher verloren! (DISCONNECTED) Grund: %s\n", payload ? (char*)payload : "unbekannt");
            needsReconnect = true;
            reconnectStartTime = millis();
            reconnectAttempt = 0;
            Serial.println("[SIO] Automatischer Reconnect wird gestartet...");
            break;
        case sIOtype_CONNECT:
            Serial.printf("\n[SIO] Verbindung zum Dispatcher HERGESTELLT! URL: %s\n", payload);
            
            // Socket.IO v4 (EIO=4) requires joining the "/" namespace explicitly.
            socketIO.send(sIOtype_CONNECT, "/");
            
            needsReconnect = false;
            reconnectAttempt = 0;
            justConnected = true; // Only set a flag here; avoid blocking calls in the event handler.
            break;
        case sIOtype_EVENT: {
            // Use a slightly larger document for incoming commands.
            DynamicJsonDocument doc(2048);
            deserializeJson(doc, payload);
            String eventName = doc[0];
           
            // Handle errors returned by the e_Lab server, such as an invalid manifest.
            if (eventName == "registration_error") {
                Serial.println("\n[ERROR] Das e_Lab hat die Registrierung ABGELEHNT!");
                String errorMsg = doc[1]["message"].as<String>();
                Serial.printf("        Grund: %s\n", errorMsg.c_str());
            }
            // --- Pairing flow ---------------------------------------------
            else if (eventName == "registration_pending") {
                Serial.println("\n[AUTH] Geraet wartet auf Operator-Freigabe in der Workbench (Kategorie 'Registrierung').");
            }
            else if (eventName == "registration_approved") {
                JsonObject payloadObj = doc[1];
                String dev    = payloadObj["deviceId"].as<String>();
                String secret = payloadObj["secret"].as<String>();
                if (dev == DEVICE_ID && secret.length() == 64) {
                    hmacSecretHex = secret;
                    isApproved = true;
                    saveSecret(secret);
                    Serial.println("\n[AUTH] Pairing erfolgreich! Secret in NVS gespeichert.");
                } else {
                    Serial.printf("\n[AUTH] registration_approved fuer fremdes Device ignoriert (%s).\n", dev.c_str());
                }
            }
            else if (eventName == "registration_revoked") {
                JsonObject payloadObj = doc[1];
                String dev = payloadObj["deviceId"].as<String>();
                if (dev == DEVICE_ID) {
                    clearSecret();
                }
            }
            else if (eventName == "execute_command") {
                JsonObject commandData = doc[1];
                String action = commandData["command"]["action"];
               
                if (action == "START_RAW" && currentState == STANDARD_MODUS) {
                    Serial.println("\n[COMMAND] Server fordert RAW-Aufnahme an.");
                    currentState = RAW_START;
                }
                // Apply configuration updates live.
                else if (action == "update_config") {
                    Serial.println("\n[COMMAND] Konfigurations-Update vom e_Lab empfangen.");
                    JsonObject payloadObj = commandData["command"]["payload"];
                    bool configChanged = false;

                    if (payloadObj.containsKey("sampleRate")) {
                        currentSampleRate = payloadObj["sampleRate"].as<int>();
                        Serial.printf("  -> Neue SampleRate: %d\n", currentSampleRate);
                        configChanged = true;
                    }
                    if (payloadObj.containsKey("medianGroupSize")) {
                        currentMedianGroupSize = payloadObj["medianGroupSize"].as<int>();
                        Serial.printf("  -> Neue MedianGroupSize: %d\n", currentMedianGroupSize);
                        configChanged = true;
                    }
                    if (payloadObj.containsKey("dmaBufferSamples")) {
                        currentDmaBufferSamples = payloadObj["dmaBufferSamples"].as<int>();
                        Serial.printf("  -> Neue DmaBufferSamples: %d\n", currentDmaBufferSamples);
                        configChanged = true;
                    }

                    if (configChanged && currentState == STANDARD_MODUS) {
                        Serial.println("[MODUS] Konfiguration geändert. Neustart wird vorbereitet...");
                        configChangePending = true; // Defer the restart to the main loop.
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

// ======================================================================
// VOLTMETER CLASS (dynamic memory)
// ======================================================================
class VoltMeter {
public:
    int sampleRate;
    int medianGroupSize;
    int dmaBufferSamples;
    int sendBufferValues;
    int sendBufferLength;
   
    uint8_t* _sendBuffers[2]; // Double-buffer to prevent races with the I2S task.
    int _writeIdx;
    uint16_t* dma_buffer;
    int* median_values;
   
    VoltMeter(adc1_channel_t adcPin, QueueHandle_t queue, int sr, int mgs, int dbs)
        : _adcPin(adcPin), _queue(queue), sampleRate(sr), medianGroupSize(mgs), dmaBufferSamples(dbs)
    {
        sendBufferValues = dmaBufferSamples / medianGroupSize;
        sendBufferLength = sendBufferValues * 2;
        _writeIdx = 0;
       
        // Two buffers: one is written while the other one is being read.
        _sendBuffers[0] = (uint8_t*)malloc(sendBufferLength);
        _sendBuffers[1] = (uint8_t*)malloc(sendBufferLength);
        dma_buffer = (uint16_t*)malloc(dmaBufferSamples * sizeof(uint16_t));
        median_values = (int*)malloc(medianGroupSize * sizeof(int));
    }

    ~VoltMeter() {
        if (_sendBuffers[0]) free(_sendBuffers[0]);
        if (_sendBuffers[1]) free(_sendBuffers[1]);
        if (dma_buffer) free(dma_buffer);
        if (median_values) free(median_values);
    }

    void performRawCapture(uint8_t* targetBuffer) {
        Serial.println("[ADC] Starte exklusive RAW-Messung...");
        i2sInit();
        size_t bytes_read = 0;
        esp_err_t result = i2s_read(I2S_NUM_0, dma_buffer, dmaBufferSamples * sizeof(uint16_t), &bytes_read, portMAX_DELAY);
       
        if (result == ESP_OK && bytes_read == dmaBufferSamples * sizeof(uint16_t)) {
            for (int i = 0; i < sendBufferValues; i++) {
                for(int j=0; j<medianGroupSize; j++){
                    insertSorted(median_values, j, dma_buffer[i * medianGroupSize + j] & 0x0FFF);
                }
                int median = median_values[medianGroupSize / 2];
                targetBuffer[i * 2] = (uint8_t)(median >> 8);
                targetBuffer[i * 2 + 1] = (uint8_t)median;
            }
        }
        if (i2s_driver_is_installed) {
            i2s_zero_dma_buffer(I2S_NUM_0);
            delay(10);
            i2s_adc_disable(I2S_NUM_0); // Disable the ADC before uninstalling the driver.
            delay(10);
            i2s_driver_uninstall(I2S_NUM_0);
            i2s_driver_is_installed = false;
        }
        Serial.println("[ADC] RAW-Messung abgeschlossen.");
    }

    void processingTaskLoop() {
        Serial.println("[TASK] ProcessingTask läuft. Rufe i2sInit() auf...");
        i2sInit();
        Serial.println("[TASK] i2sInit() erfolgreich abgeschlossen. Betrete Endlosschleife...");

        // Subscribe this FreeRTOS task to the watchdog as well so a wedged
        // i2s_read does not leave the WDT unfed indefinitely.
        esp_task_wdt_add(NULL);

        unsigned long lastDebugPrint = millis();

        while (!stopProcessingTask) {
            esp_task_wdt_reset();
            size_t bytes_read = 0;
            
            // Use a timeout instead of portMAX_DELAY so the stop flag can be checked.
            i2s_read(I2S_NUM_0, dma_buffer, dmaBufferSamples * sizeof(uint16_t), &bytes_read, 100 / portTICK_PERIOD_MS);
            
            if (bytes_read == dmaBufferSamples * sizeof(uint16_t)) {
                uint8_t* writeBuf = _sendBuffers[_writeIdx];
                for (int i = 0; i < sendBufferValues; i++) {
                     for(int j=0; j<medianGroupSize; j++){
                        insertSorted(median_values, j, dma_buffer[i * medianGroupSize + j] & 0x0FFF);
                    }
                    int median = median_values[medianGroupSize / 2];
                    writeBuf[i * 2] = (uint8_t)(median >> 8);
                    writeBuf[i * 2 + 1] = (uint8_t)median;
                }
                uint8_t* readyBuf = writeBuf;
                _writeIdx = 1 - _writeIdx; // Switch to the other buffer for the next write.
                if (xQueueSend(_queue, &readyBuf, (TickType_t)0) != pdPASS) {
                    // The queue is full; avoid logging this on every iteration.
                }
            }
        }

        Serial.println("[TASK] Beende I2S und Task (Graceful Shutdown)...");
        if (i2s_driver_is_installed) {
            i2s_zero_dma_buffer(I2S_NUM_0); // Clear the DMA buffer before shutdown.
            delay(10);
            i2s_adc_disable(I2S_NUM_0); // Disable the ADC before uninstalling the driver.
            delay(10);
            i2s_driver_uninstall(I2S_NUM_0);
            i2s_driver_is_installed = false;
        }
        taskIsFinished = true;
        // Unsubscribe from the WDT before deleting ourselves, otherwise
        // the watchdog would fire after the task is gone.
        esp_task_wdt_delete(NULL);
        vTaskDelete(NULL);
    }
private:
    adc1_channel_t _adcPin;
    QueueHandle_t _queue;
   
    void i2sInit() {
        // If an old driver is still installed, tear it down cleanly first.
        if (i2s_driver_is_installed) {
            Serial.println("[I2S] WARNUNG: Alter Treiber noch aktiv, baue ab...");
            i2s_zero_dma_buffer(I2S_NUM_0);
            delay(10);
            i2s_adc_disable(I2S_NUM_0);
            delay(10);
            i2s_driver_uninstall(I2S_NUM_0);
            i2s_driver_is_installed = false;
            delay(100);
        }
        Serial.println("[I2S] Konfiguriere i2s_config_t...");
        i2s_config_t i2s_config = {
            .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_ADC_BUILT_IN),
            .sample_rate = sampleRate,
            .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
            .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
            .communication_format = I2S_COMM_FORMAT_STAND_MSB,
            .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
            .dma_buf_count = 4,
            .dma_buf_len = 1024,
            .use_apll = true
        };
        
        Serial.println("[I2S] Führe i2s_driver_install aus...");
        i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
        
        Serial.println("[I2S] Führe i2s_set_adc_mode aus...");
        i2s_set_adc_mode(ADC_UNIT_1, _adcPin);
        
        Serial.println("[I2S] Aktiviere ADC (i2s_adc_enable)...");
        i2s_adc_enable(I2S_NUM_0);
        
        i2s_driver_is_installed = true;
        Serial.println("[I2S] Initialisierung fertig!");
    }
   
    void insertSorted(int* array, int length, int newValue) {
        int i;
        for (i = length - 1; (i >= 0 && array[i] > newValue); i--) { array[i + 1] = array[i]; }
        array[i + 1] = newValue;
    }
};

void rawCaptureTask(void* param) {
    // Create a temporary VoltMeter object with the current parameters.
    VoltMeter tempMeter(ADC1_CHANNEL_6, NULL, currentSampleRate, currentMedianGroupSize, currentDmaBufferSamples);
    tempMeter.performRawCapture(rawDataBuffer);
    currentState = RAW_WIEDERVERBINDEN;
    vTaskDelete(NULL);
}

// ======================================================================
// SEND DATA TO E-LAB (raw-byte mode)
// ======================================================================
// Send the byte buffer directly as a JSON integer array.
// The server decodes the values with the decoder configured in the manifest.
// This avoids ArduinoJson use, float overhead, and string allocation issues.

// Static send buffer allocated once and reused.
static char* txBuffer = nullptr;
static size_t txBufferSize = 0;

// Forward declaration: chunk dispatcher splits oversized blocks before
// delegating to the per-chunk JSON builder below.
static void sendDataChunkToELab(uint8_t* buffer, int numValues,
                                const char* sourceId,
                                unsigned long startTimeMs,
                                unsigned long endTimeMs);

void sendDataToELab(uint8_t* buffer, int numValues, const char* sourceId) {
    if (numValues <= 0) return;

    // Compute the timestamp window for the *whole* block, then split it
    // proportionally across chunks so the receiver still sees a contiguous
    // linear-distribution stream.
    static unsigned long nextExpectedStartTime = 0;
    unsigned long chunkDurationMs =
        (numValues * 1000UL * currentMedianGroupSize) / currentSampleRate;
    unsigned long now = millis();
    unsigned long startTime;
    if (nextExpectedStartTime == 0 ||
        (now > nextExpectedStartTime && (now - nextExpectedStartTime) > 1000)) {
        startTime = now - chunkDurationMs;
    } else {
        startTime = nextExpectedStartTime;
    }
    unsigned long endTime = startTime + chunkDurationMs;
    nextExpectedStartTime = endTime;

    // Fast path: small enough to fit into one frame.
    if (numValues <= MAX_VALUES_PER_FRAME) {
        sendDataChunkToELab(buffer, numValues, sourceId, startTime, endTime);
        return;
    }

    // Slow path: split into MAX_VALUES_PER_FRAME-sized chunks.
    int offset = 0;
    while (offset < numValues) {
        int chunk = numValues - offset;
        if (chunk > MAX_VALUES_PER_FRAME) chunk = MAX_VALUES_PER_FRAME;

        unsigned long chunkStart =
            startTime + ((endTime - startTime) * offset) / numValues;
        unsigned long chunkEnd =
            startTime + ((endTime - startTime) * (offset + chunk)) / numValues;

        // Each value occupies 2 bytes in the source buffer.
        sendDataChunkToELab(buffer + (offset * 2), chunk, sourceId,
                            chunkStart, chunkEnd);
        offset += chunk;

        // Yield so the WiFi/Socket.IO stack can flush between frames.
        socketIO.loop();
        delay(1);
    }
}

static void sendDataChunkToELab(uint8_t* buffer, int numValues,
                                const char* sourceId,
                                unsigned long startTimeMs,
                                unsigned long endTimeMs) {
    // Drop everything until the operator has approved this device. The
    // server would discard unsigned packets anyway, so don't waste WiFi.
    if (!isApproved || hmacSecretHex.length() != 64) {
        static unsigned long lastWarn = 0;
        if (millis() - lastWarn > 5000) {
            Serial.println("[STREAM] Geraet noch nicht freigegeben \u2014 verwerfe Daten.");
            lastWarn = millis();
        }
        return;
    }

    // Two bytes per uint16 value.
    int numBytes = numValues * 2;
    // Buffer size: header plus up to 4 chars per byte ("255,"), auth block, trailer.
    size_t needed = 512 + ((size_t)numBytes * 4);

    // Grow the static buffer on demand.
    if (txBuffer == nullptr || txBufferSize < needed) {
        if (txBuffer) free(txBuffer);
        txBuffer = (char*)malloc(needed);
        if (!txBuffer) {
            txBufferSize = 0;
            Serial.println("[STREAM] txBuffer malloc failed!");
            return;
        }
        txBufferSize = needed;
    }

    // --- Build the wrapper + inner payload in CANONICAL key order -------
    // We need the inner object exactly the way Python's json.dumps(...,
    // sort_keys=True, separators=(",", ":")) would emit it, otherwise the
    // HMAC won't match server-side.
    //
    // Canonical inner keys (alphabetical): distribution, endTime,
    // raw_bytes, sourceId, startTime. The auth block is appended *after*
    // signing and intentionally violates alphabetical order \u2014 the server
    // strips it before re-canonicalizing.
    const char wrapperPrefix[] = "[\"data_stream\",";
    const size_t innerStart = sizeof(wrapperPrefix) - 1;  // index of inner '{'

    int pos = snprintf(txBuffer, txBufferSize,
        "%s{\"distribution\":\"linear\",\"endTime\":%lu,\"raw_bytes\":[",
        wrapperPrefix, endTimeMs);

    // Write byte array (decimal integers separated by ',').
    for (int i = 0; i < numBytes; i++) {
        if (i > 0) txBuffer[pos++] = ',';
        uint8_t val = buffer[i];
        if (val >= 100) {
            txBuffer[pos++] = '0' + (val / 100);
            txBuffer[pos++] = '0' + ((val / 10) % 10);
            txBuffer[pos++] = '0' + (val % 10);
        } else if (val >= 10) {
            txBuffer[pos++] = '0' + (val / 10);
            txBuffer[pos++] = '0' + (val % 10);
        } else {
            txBuffer[pos++] = '0' + val;
        }
    }

    // Close raw_bytes and append remaining canonical keys, then close the
    // inner object. After this, the bytes at [innerStart .. pos) ARE the
    // canonical inner JSON.
    pos += snprintf(txBuffer + pos, txBufferSize - pos,
        "],\"sourceId\":\"%s\",\"startTime\":%lu}",
        sourceId, startTimeMs);

    // --- Compute HMAC over (ts\n + canonical inner JSON) ----------------
    unsigned long tsSec = 0, tsUsec = 0;
    if (!getEpochTime(&tsSec, &tsUsec)) {
        // NTP not synced yet \u2014 don't ship an unsignable packet.
        static unsigned long lastWarn = 0;
        if (millis() - lastWarn > 5000) {
            Serial.println("[AUTH] NTP-Zeit noch nicht synchron \u2014 verwerfe Frame.");
            lastWarn = millis();
        }
        return;
    }
    char tsBuf[32];
    int tsLen = snprintf(tsBuf, sizeof(tsBuf), "%lu.%06lu\n", tsSec, tsUsec);

    uint8_t keyBytes[32];
    if (!hexToBytes(hmacSecretHex, keyBytes, sizeof(keyBytes))) {
        Serial.println("[AUTH] Secret in NVS korrupt \u2014 loesche und fordere neues Pairing an.");
        clearSecret();
        return;
    }

    char sigHex[65];
    if (!computeHmacHex(keyBytes, sizeof(keyBytes),
                        tsBuf, (size_t)tsLen,
                        txBuffer + innerStart, (size_t)(pos - innerStart),
                        sigHex)) {
        Serial.println("[AUTH] HMAC-Berechnung fehlgeschlagen \u2014 verwerfe Frame.");
        return;
    }

    // Splice the auth block in: rewind the closing '}' of the inner
    // object, append ',"auth":{"sig":"<hex>","ts":TS.NNNNNN}}' followed by
    // the wrapper's closing ']'.
    pos -= 1;  // drop trailing '}'
    pos += snprintf(txBuffer + pos, txBufferSize - pos,
        ",\"auth\":{\"sig\":\"%s\",\"ts\":%lu.%06lu}}]",
        sigHex, tsSec, tsUsec);

    socketIO.sendEVENT(txBuffer, pos);
}

// ======================================================================
// SETUP AND LOOP
// ======================================================================
void connectToBestWiFi() {
  Serial.printf("\n[WLAN] Scanne nach stärkstem Signal für '%s'...\n", ssid);
  
  int n = WiFi.scanNetworks();
  int bestRSSI = -1000;
  uint8_t bestBSSID[6];
  int32_t bestChannel = 0;
  bool found = false;

  for (int i = 0; i < n; ++i) {
    if (WiFi.SSID(i) == ssid) {
      Serial.printf(" -> AP gefunden: Kanal %d, RSSI: %d dBm, BSSID: %s\n", 
                    WiFi.channel(i), WiFi.RSSI(i), WiFi.BSSIDstr(i).c_str());
      
      // Wenn das Signal stärker ist als das bisher beste, merke dir diesen AP
      if (WiFi.RSSI(i) > bestRSSI) {
        bestRSSI = WiFi.RSSI(i);
        bestChannel = WiFi.channel(i);
        memcpy(bestBSSID, WiFi.BSSID(i), 6);
        found = true;
      }
    }
  }

  if (found) {
    Serial.printf("[WLAN] Verbinde mit stärkstem AP (Kanal %d, RSSI %d dBm)...\n", bestChannel, bestRSSI);
    // Gezielte Verbindung mit dem stärksten Access Point (BSSID)
    WiFi.begin(ssid, password, bestChannel, bestBSSID);
  } else {
    Serial.println("[WLAN] SSID im Scan nicht gefunden! Versuche Standard-Verbindung...");
    WiFi.begin(ssid, password);
  }
}

void setup() {
    Serial.begin(115200);
    Serial.println("\n\n========================================");
    Serial.println("   ESP32 e_Lab Voltmeter Systemstart");
    Serial.println("========================================");

    // Arm the task watchdog so a wedged WiFi/I2S call resets the chip
    // instead of leaving it in a half-dead state.
    esp_task_wdt_config_t wdt_config = {
        .timeout_ms = WDT_TIMEOUT_SECONDS * 1000,
        .idle_core_mask = (1 << portNUM_PROCESSORS) - 1,
        .trigger_panic = true
    };
    esp_task_wdt_init(&wdt_config);
    // NOTE: loopTask is subscribed later (once the socket connects) to
    // avoid false WDT resets caused by blocking TCP handshakes inside
    // socketIO.loop().

    dataQueue = xQueueCreate(2, sizeof(uint8_t*));

    Serial.printf("\n[WLAN] Verbinde mit SSID: %s\n", ssid);
    connectToBestWiFi();
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\n[WLAN] Erfolgreich verbunden!");
    Serial.printf("[WLAN] Zugewiesene IP-Adresse: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("[WLAN] Signalstärke (RSSI): %d dBm\n", WiFi.RSSI());

    // --- Time sync via SNTP --------------------------------------------
    // The HMAC timestamp must be wall-clock epoch seconds within the
    // server's accepted skew window (5 min), so we need NTP before we can
    // sign any data_stream packet.
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");
    Serial.println("[SNTP] Warte auf Zeitsynchronisation...");
    {
        time_t now = 0;
        int waited = 0;
        while ((now = time(nullptr)) < 1577836800UL /* 2020 */ && waited < 20) {
            delay(500);
            Serial.print(".");
            waited++;
        }
        if (now < 1577836800UL) {
            Serial.println("\n[SNTP] WARNUNG: keine Zeit synchronisiert (Frames werden vorerst verworfen).");
        } else {
            Serial.printf("\n[SNTP] OK: %ld\n", (long)now);
        }
    }

    // --- Load cached pairing secret (if any) ---------------------------
    loadStoredSecret();

    currentState = DISCOVERY;
}

void loop() {
    // Always run the Socket.IO loop to keep the connection alive.
    socketIO.loop();

    // Feed the watchdog (no-op if not yet subscribed).
    if (loopWdtActive) esp_task_wdt_reset();

    // Reconnect logic with exponential backoff.
    // Unsubscribe from WDT while reconnecting — socketIO.loop() may
    // block for multiple seconds during the TCP re-handshake.
    if (needsReconnect && loopWdtActive) {
        esp_task_wdt_delete(NULL);
        loopWdtActive = false;
    }
    if (needsReconnect && serverFound) {
        unsigned long backoffMs = min(3000UL * (1UL << reconnectAttempt), 30000UL);
        if (millis() - reconnectStartTime >= backoffMs) {
            reconnectAttempt++;
            if (reconnectAttempt > MAX_RECONNECT_ATTEMPTS) {
                Serial.println("[SIO] Max. Reconnect-Versuche erreicht. Starte Neustart...");
                ESP.restart();
            }
            
            // Switch to the next candidate IP if multiple are available
            if (serverIPCount > 1) {
                currentServerIPIndex = (currentServerIPIndex + 1) % serverIPCount;
                serverIP = serverIPs[currentServerIPIndex];
                Serial.printf("[SIO] Wechsle zu IP-Kandidat: %s (Index %d/%d)\n", 
                              serverIP.c_str(), currentServerIPIndex + 1, serverIPCount);
            }
            
            Serial.printf("[SIO] Reconnect-Versuch %d/%d (Backoff: %lu ms) mit %s:%d...\n",
                          reconnectAttempt, MAX_RECONNECT_ATTEMPTS, backoffMs, serverIP.c_str(), serverPort);
            socketIO.begin(serverIP, serverPort, "/socket.io/?EIO=4");
            socketIO.onEvent(socketIOEvent);
            reconnectStartTime = millis();
        }
    }

    // The event handler sets justConnected once the socket is ready.
    if (justConnected) {
        justConnected = false;

        // (Re-)subscribe the main loop to WDT now that the connection
        // is established and socketIO.loop() won't block anymore.
        if (!loopWdtActive) {
            esp_task_wdt_add(NULL);
            loopWdtActive = true;
        }
        esp_task_wdt_reset();

        sendManifest();

        // If raw data must be sent first, do not switch back to standard mode yet.
        if (currentState == RAW_DATEN_SENDEN) {
            sendRawBeforeStandard = true;
        } else {
            startStandardMode();
        }
    }

    // Handle configuration changes in the main loop, not in the callback.
    if (configChangePending) {
        configChangePending = false;
        Serial.println("[MODUS] Konfiguration geändert. Sende aktualisiertes Manifest...");
        sendManifest(); // Re-register with updated accuracy (depends on medianGroupSize).
        startStandardMode();
    }

    switch(currentState) {
        case DISCOVERY: {
            // In discovery state, only initiate the connection if not already connected.
            // The sIOtype_CONNECT event handler completes the rest.
            if (!serverFound) {
                // Search for the server; this blocks until one is found.
                discoverServer();
                
                Serial.printf("\n[SIO] Verbinde mit Socket.IO Server %s:%d ...\n", serverIP.c_str(), serverPort);
                socketIO.begin(serverIP, serverPort, "/socket.io/?EIO=4");
                socketIO.onEvent(socketIOEvent);
            }
            break;
        }
           
        case RAW_START:
            Serial.println("\n[MODUS] Stoppe Standard-Modus für exklusive RAW-Aufnahme...");
            if (!taskIsFinished) {
                stopProcessingTask = true;
                while (!taskIsFinished) { delay(10); }
            }
            if (voltMeter != nullptr) {
                delete voltMeter;
                voltMeter = nullptr;
            }
           
            // Reallocate the raw buffer if capture parameters changed.
            if (rawDataBuffer != nullptr) { free(rawDataBuffer); }
            rawDataBufferSize = (currentDmaBufferSamples / currentMedianGroupSize) * 2;
            rawDataBuffer = (uint8_t*)malloc(rawDataBufferSize);
           
            socketIO.disconnect();
            WiFi.disconnect(true); WiFi.mode(WIFI_OFF);
            Serial.println("[WLAN] Funkmodul wurde deaktiviert für ungestörte I2S-Messung.");
           
            currentState = RAW_MESSUNG_LAEUFT;
            break;
           
        case RAW_MESSUNG_LAEUFT:
            xTaskCreate(rawCaptureTask, "RawCaptureTask", 4096, NULL, 5, NULL);
            while(currentState == RAW_MESSUNG_LAEUFT) { esp_task_wdt_reset(); delay(10); }
            break;
           
        case RAW_WIEDERVERBINDEN:
            Serial.println("\n[WLAN] Reaktiviere Funkmodul für Datenübertragung...");
            WiFi.mode(WIFI_STA);
            connectToBestWiFi();
            while (WiFi.status() != WL_CONNECTED) {
                esp_task_wdt_reset();
                delay(500);
                Serial.print(".");
            }
            Serial.printf("\n[WLAN] Wieder verbunden! IP: %s\n", WiFi.localIP().toString().c_str());
           
            Serial.println("[SIO] Baue Socket.IO Verbindung wieder auf...");
            // Temporarily disable WDT — socketIO.loop() may block during
            // the TCP handshake on the next iteration. It will be re-enabled
            // once justConnected fires.
            if (loopWdtActive) {
                esp_task_wdt_delete(NULL);
                loopWdtActive = false;
            }
            socketIO.begin(serverIP, serverPort, "/socket.io/?EIO=4");
            socketIO.onEvent(socketIOEvent); // Re-register the event handler.
            currentState = RAW_DATEN_SENDEN;
            break;
           
        case RAW_DATEN_SENDEN:
            // socketIO.loop() is already executed at the top of the loop.
            if (socketIO.isConnected() && sendRawBeforeStandard) {
                Serial.println("[STREAM] Sende gepufferten RAW-Block an das e_Lab...");
                sendDataToELab(rawDataBuffer, rawDataBufferSize / 2, "esp32_voltmeter_01_ch1");
                Serial.println("[STREAM] RAW-Daten erfolgreich übertragen.");
                sendRawBeforeStandard = false;
                currentState = RAW_ENDE;
            }
            break;
           
        case RAW_ENDE:
            Serial.println("\n[MODUS] RAW-Sequenz beendet. Kehre zurück...");
            startStandardMode();
            break;
           
        case STANDARD_MODUS: {
            // socketIO.loop() already ran at the top of the loop.
           
            uint8_t* readyBuffer = nullptr;
            if (xQueueReceive(dataQueue, &readyBuffer, (TickType_t)0) == pdPASS && readyBuffer != nullptr) {
                if (socketIO.isConnected() && voltMeter != nullptr) {
                    static unsigned long lastSendLog = 0;
                    if (millis() - lastSendLog > 2000) {
                        lastSendLog = millis();
                    }
                    sendDataToELab(readyBuffer, voltMeter->sendBufferValues, "esp32_voltmeter_01_ch1");
                } else if (!socketIO.isConnected()) {
                    static unsigned long lastWarnLog = 0;
                    if (millis() - lastWarnLog > 2000) {
                        Serial.println("[LOOP] WARNUNG: Daten liegen bereit, aber Socket.IO ist NICHT verbunden!");
                        lastWarnLog = millis();
                    }
                }
            }
            break;
        }
    }
}

void startStandardMode() {
    Serial.println("\n[MODUS] Initialisiere STANDARD_MODUS (Kontinuierlicher Stream)");
   
    if (!taskIsFinished) {
        Serial.println("[SYSTEM] Stoppe alten Task...");
        stopProcessingTask = true;
        while (!taskIsFinished) { delay(10); }
        // Give the FreeRTOS idle task and the ADC time to shut down cleanly.
        delay(200);
    }
   
    // Delete the old object cleanly to release RAM.
    if (voltMeter != nullptr) {
        delete voltMeter;
    }
   
    // Initialize a new object with the current dynamic parameters.
    voltMeter = new VoltMeter(ADC1_CHANNEL_6, dataQueue, currentSampleRate, currentMedianGroupSize, currentDmaBufferSamples);
   
    stopProcessingTask = false;
    taskIsFinished = false;

    Serial.println("[SYSTEM] Starte I2S Processing Task...");
    xTaskCreatePinnedToCore(
        [](void* param){ ((VoltMeter*)param)->processingTaskLoop(); },
        "ProcessingTask", 4096, voltMeter, 2, &voltMeterTaskHandle, 0
    );
    currentState = STANDARD_MODUS;
}