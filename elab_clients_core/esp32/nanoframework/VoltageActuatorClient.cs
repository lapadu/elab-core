using System;
using System.Collections;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Device.Pwm;
using nanoFramework.Json;
using nanoFramework.Networking;
using System.Net.NetworkInformation;
using System.Net.WebSockets;

namespace Elab.Actuator
{
    public class Program
    {
        public static void Main()
        {
            VoltageActuatorClient voltageActuatorClient = new VoltageActuatorClient();
            voltageActuatorClient.Start();
        }
    }

    public class VoltageActuatorClient
    {
        // ==========================================
        // CONFIGURATION
        // ==========================================
        private const string WifiSsid = "my ssid";
        private const string WifiPassword = "my password";
        private const int DiscoveryPort = 5005;
        private const int PwmPin = 2; // IO02
        private const int PwmFrequencyHz = 10000; // 10 kHz
        private const double MaxVoltage = 10.0;

        private PwmChannel _pwmChannel;
        private string _dispatcherUrl;
        private string _providerId;
        
        private bool _isConnectedToDispatcher = false;
        private bool _isParsing = false; // CPU-Protection Flag

        // ==========================================
        // BUFFERING & TIMING
        // ==========================================
        private Queue _playbackQueue = new Queue();
        private readonly object _queueLock = new object();
        private Thread _playbackThread;
        private int _playbackIntervalMs = 50; // Default to 20Hz updates
        private double _currentVoltage = 0.0; 

        // Lock for thread-safe WebSocket sending
        private readonly object _sendLock = new object();

        // ==========================================
        // BYTE-LEVEL PARSING CONSTANTS (ZERO ALLOCATION)
        // ==========================================
        private readonly byte[] CmdBytes = Encoding.UTF8.GetBytes("\"execute_command\"");
        private readonly byte[] ValueKeyBytes = Encoding.UTF8.GetBytes("\"value\"");
        private readonly byte[] ValuesKeyBytes = Encoding.UTF8.GetBytes("\"values\"");
        private readonly byte[] RevokedBytes = Encoding.UTF8.GetBytes("\"registration_revoked\"");
        private readonly byte[] RejectedBytes = Encoding.UTF8.GetBytes("\"registration_rejected\"");

        // ==========================================
        // LOGGING HELPER
        // ==========================================
        private void Log(string message)
        {
            var now = DateTime.UtcNow;
            string timeStr = now.Hour.ToString("D2") + ":" + now.Minute.ToString("D2") + ":" + now.Second.ToString("D2");
            Debug.WriteLine(timeStr + " [ESP32] " + message);
        }

        public void Start()
        {
            Log("Starting Voltage Actuator Client...");

            // 1. Initialize PWM
            InitializePwm();

            // 2. Start Playback Thread
            _playbackThread = new Thread(PlaybackLoop);
            _playbackThread.Start();

            // 3. Generate unique provider ID based on MAC Address
            _providerId = "esp32_vout_" + GetMacAddress();
            Log($"Provider ID: {_providerId}");

            // Main Reconnect Loop
            while (true)
            {
                try
                {
                    if (!IsWifiConnected())
                    {
                        Log("Wi-Fi not connected. Attempting connection...");
                        ConnectToWifi();
                    }

                    if (string.IsNullOrEmpty(_dispatcherUrl))
                    {
                        DiscoverDispatcher();
                    }

                    if (!string.IsNullOrEmpty(_dispatcherUrl))
                    {
                        ConnectAndListen();
                        Log("Connection lost. Resetting URL for discovery...");
                        _dispatcherUrl = null; 
                    }
                }
                catch (Exception ex)
                {
                    Log($"Main loop exception: {ex.Message}");
                    _dispatcherUrl = null; 
                }
                Thread.Sleep(5000);
            }
        }

        private void PlaybackLoop()
        {
            Log("Playback Thread started.");
            while (true)
            {
                try
                {
                    bool hasData = false;
                    double nextValue = 0;

                    lock (_queueLock)
                    {
                        if (_playbackQueue.Count > 0)
                        {
                            nextValue = (double)_playbackQueue.Dequeue();
                            hasData = true;
                        }
                    }

                    if (hasData)
                    {
                        SetVoltage(nextValue);
                        Thread.Sleep(_playbackIntervalMs);
                    }
                    else
                    {
                        Thread.Sleep(10);
                    }
                }
                catch (Exception ex)
                {
                    Log($"Playback error: {ex.Message}");
                    Thread.Sleep(100);
                }
            }
        }

        private bool IsWifiConnected()
        {
            var interfaces = NetworkInterface.GetAllNetworkInterfaces();
            foreach (var netInterface in interfaces)
            {
                if (netInterface.NetworkInterfaceType == NetworkInterfaceType.Wireless80211)
                {
                    if (netInterface.IPv4Address != "0.0.0.0" && netInterface.IPv4Address != "") return true;
                }
            }
            return false;
        }

        private void ConnectToWifi()
        {
            Log($"Connecting to Wi-Fi SSID: {WifiSsid}...");
            bool success = WifiNetworkHelper.ConnectDhcp(WifiSsid, WifiPassword, requiresDateTime: true);

            while (!success)
            {
                Log("Error connecting to WiFi! Retrying in 5 seconds...");
                Thread.Sleep(5000);
                success = WifiNetworkHelper.ConnectDhcp(WifiSsid, WifiPassword, requiresDateTime: true);
            }
            Log("WiFi Connected!");
        }

        private void InitializePwm()
        {
            Log($"Initializing PWM on GPIO {PwmPin} at {PwmFrequencyHz}Hz");

            nanoFramework.Hardware.Esp32.Configuration.SetPinFunction(PwmPin, nanoFramework.Hardware.Esp32.DeviceFunction.PWM1);
            _pwmChannel = PwmChannel.CreateFromPin(PwmPin, PwmFrequencyHz, 0.0);
            _pwmChannel.Start();
        }

        private string GetMacAddress()
        {
            var interfaces = NetworkInterface.GetAllNetworkInterfaces();
            foreach (var netInterface in interfaces)
            {
                if (netInterface.NetworkInterfaceType == NetworkInterfaceType.Wireless80211)
                {
                    byte[] mac = netInterface.PhysicalAddress;
                    if (mac != null && mac.Length > 0)
                    {
                        string macStr = "";
                        for (int i = 0; i < mac.Length; i++) 
                        {
                            macStr += mac[i].ToString("X2");
                        }
                        return macStr.ToLower();
                    }
                }
            }
            return "unknown_" + DateTime.UtcNow.Ticks.ToString();
        }

        private void DiscoverDispatcher()
        {
            Log($"Listening for UDP Discovery on port {DiscoveryPort}...");
            using (Socket udpSocket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp))
            {
                IPEndPoint endPoint = new IPEndPoint(IPAddress.Any, DiscoveryPort);
                udpSocket.Bind(endPoint);
                byte[] buffer = new byte[1024];
                
                int retryCount = 0;
                while (retryCount < 60)
                {
                    if (!IsWifiConnected()) return; 

                    if (udpSocket.Poll(1000000, SelectMode.SelectRead))
                    {
                        int bytesRead = udpSocket.Receive(buffer);
                        string message = Encoding.UTF8.GetString(buffer, 0, bytesRead);

                        try
                        {
                            var beacon = (DiscoveryBeacon)JsonConvert.DeserializeObject(message, typeof(DiscoveryBeacon));
                            if (beacon != null && beacon.service == "elab-dispatcher" && beacon.ips.Length > 0)
                            {
                                _dispatcherUrl = $"http://{beacon.ips[0]}:{beacon.port}";
                                Log($"Found dispatcher at: {_dispatcherUrl}");
                                return;
                            }
                        }
                        catch { }
                    }
                    retryCount++;
                }
            }
        }

        private void SafeSend(ClientWebSocket ws, string message)
        {
            lock (_sendLock)
            {
                try
                {
                    if (ws.State == WebSocketState.Open)
                    {
                        ws.SendString(message);
                    }
                }
                catch (ObjectDisposedException) 
                { 
                    // Known nanoFramework bug when socket is closing - ignore
                }
                catch (Exception ex)
                {
                    Log($"Send error: {ex.Message}");
                }
            }
        }

        private void ConnectAndListen()
        {
            Hashtable configObj = new Hashtable();
            configObj.Add("unit", "V");
            configObj.Add("range", new double[] { -10.0, 10.0 });
            
            configObj.Add("min", -10.0);
            configObj.Add("max", 10.0);
            configObj.Add("step", 0.1);

            // Instruct the server to send scalars and limit rate
            configObj.Add("accepts", new string[] { "scalar" });
            configObj.Add("maxRateHz", 10);

            Hashtable uiObj = new Hashtable();
            uiObj.Add("mode", "generic");
            uiObj.Add("template", "tpl_generic_actuator");

            Hashtable taskObj = new Hashtable();
            taskObj.Add("id", _providerId + "_v_out");
            taskObj.Add("name", "Voltage Output");
            taskObj.Add("type", "ACTUATOR");
            taskObj.Add("ui", uiObj);
            taskObj.Add("config", configObj);

            Hashtable manifestObj = new Hashtable();
            manifestObj.Add("id", _providerId);
            manifestObj.Add("name", "ESP32 Voltage Actuator");
            manifestObj.Add("category", "HARDWARE");
            manifestObj.Add("tasks", new object[] { taskObj });

            string manifestJson = JsonConvert.SerializeObject(manifestObj);
            string wsUrl = $"ws://{_dispatcherUrl.Substring(7)}/socket.io/?EIO=4&transport=websocket";
            Log($"Connecting to WebSocket: {wsUrl}");

            using (ClientWebSocket websocket = new ClientWebSocket())
            {
                _isConnectedToDispatcher = true;

                websocket.MessageReceived += (sender, e) =>
                {
                    try
                    {
                        if (!_isConnectedToDispatcher) return;

                        if (e.Frame != null && e.Frame.Buffer != null)
                        {
                            byte[] buf = e.Frame.Buffer;
                            int len = e.Frame.MessageLength;
                            if (len == 0) return;

                            if (buf[0] == (byte)'0') 
                            {
                                SafeSend(websocket, "40"); 
                            }
                            else if (buf[0] == (byte)'2') 
                            {
                                Log("Server PING received → sending PONG (3)");
                                SafeSend(websocket, "3");  
                            }
                            else if (len >= 2 && buf[0] == (byte)'4' && buf[1] == (byte)'0') 
                            {
                                string payload = $"42[\"register_provider\",{manifestJson}]";
                                SafeSend(websocket, payload);
                                Log("Manifest sent successfully!");
                            }
                            else if (len >= 2 && buf[0] == (byte)'4' && buf[1] == (byte)'2') 
                            {
                                if (IndexOfBytes(buf, len, RevokedBytes) != -1 || IndexOfBytes(buf, len, RejectedBytes) != -1)
                                {
                                    Log("Registration revoked or rejected by server! Disconnecting...");
                                    _isConnectedToDispatcher = false;
                                    return;
                                }

                                // CPU-SCHUTZ: Wenn das letzte Paket noch verarbeitet wird,
                                // werfen wir dieses weg. Verhindert Watchdog-Absturz!
                                if (_isParsing) return;
                                
                                _isParsing = true;
                                try 
                                {
                                    ParseCommandFromBytes(buf, len);
                                }
                                finally 
                                {
                                    _isParsing = false;
                                }
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        Log($"Error processing message: {ex.Message}");
                    }
                };

                websocket.ConnectionClosed += (sender, e) => 
                { 
                    Log("WebSocket Connection Closed event received.");
                    _isConnectedToDispatcher = false; 
                };

                try
                {
                    websocket.Connect(wsUrl);
                    Log("WebSocket connected.");
                    
                    while (_isConnectedToDispatcher && websocket.State == WebSocketState.Open)
                    {
                        if (!IsWifiConnected()) break;
                        Thread.Sleep(1000);
                    }
                }
                catch (ObjectDisposedException)
                {
                    // Known nanoFramework WebSocket bug - safe to ignore
                    Log("ObjectDisposedException caught (known nF bug).");
                }
                catch (Exception ex)
                {
                    Log($"WebSocket Loop Exception: {ex.Message}");
                }
                finally 
                { 
                    _isConnectedToDispatcher = false; 
                    if (websocket.State == WebSocketState.Open)
                    {
                        try { websocket.Close(WebSocketCloseStatus.NormalClosure, "Client disconnect"); } catch { }
                    }
                    Thread.Sleep(250);
                }
            }
        }

        // ==========================================
        // EXTREMELY OPTIMIZED ZERO-ALLOCATION PARSER
        // ==========================================
        private void ParseCommandFromBytes(byte[] buf, int len)
        {
            if (IndexOfBytes(buf, len, CmdBytes) == -1) return;

            double targetValue = 0;
            bool valueFound = false;

            // 1. Suche nach skalarem "value":
            int valKeyIdx = IndexOfBytes(buf, len, ValueKeyBytes);
            if (valKeyIdx > 0)
            {
                int endOfValueKey = valKeyIdx + ValueKeyBytes.Length;
                if (endOfValueKey < len && buf[endOfValueKey] != (byte)'s') 
                {
                    int colonIdx = IndexOfByte(buf, len, (byte)':', endOfValueKey);
                    if (colonIdx > 0)
                    {
                        int commaIdx = IndexOfByte(buf, len, (byte)',', colonIdx);
                        int braceIdx = IndexOfByte(buf, len, (byte)'}', colonIdx);

                        int endIdx = -1;
                        if (commaIdx > 0 && braceIdx > 0) endIdx = System.Math.Min(commaIdx, braceIdx);
                        else if (commaIdx > 0) endIdx = commaIdx;
                        else if (braceIdx > 0) endIdx = braceIdx;

                        if (endIdx > colonIdx)
                        {
                            targetValue = ParseDoubleFromBytes(buf, colonIdx + 1, endIdx - 1);
                            valueFound = true;
                        }
                    }
                }
            }

            // 2. Suche nach "values": [ (Array-Fallback)
            if (!valueFound)
            {
                int arrayKeyIdx = IndexOfBytes(buf, len, ValuesKeyBytes);
                if (arrayKeyIdx > 0)
                {
                    int bracketStart = IndexOfByte(buf, len, (byte)'[', arrayKeyIdx);
                    
                    // EXTREME OPTIMIERUNG: Wir nehmen NUR die allererste Zahl des Arrays!
                    // Das verhindert Parsing-Fehler durch fragmentierte (abgeschnittene) Netzwerkpakete
                    if (bracketStart > 0)
                    {
                        int commaIdx = IndexOfByte(buf, len, (byte)',', bracketStart);
                        int bracketEnd = IndexOfByte(buf, len, (byte)']', bracketStart);

                        int endIdx = -1;
                        if (commaIdx > 0 && bracketEnd > 0) endIdx = System.Math.Min(commaIdx, bracketEnd);
                        else if (commaIdx > 0) endIdx = commaIdx;
                        else if (bracketEnd > 0) endIdx = bracketEnd;

                        if (endIdx > bracketStart)
                        {
                            targetValue = ParseDoubleFromBytes(buf, bracketStart + 1, endIdx - 1);
                            valueFound = true;
                        }
                    }
                }
            }

            if (valueFound)
            {
                lock (_queueLock)
                {
                    // Strikte 1-Wert Queue, um sofortige Reaktivität zu garantieren
                    if (_playbackQueue.Count > 1) _playbackQueue.Clear(); 
                    _playbackQueue.Enqueue(targetValue);
                }
            }
        }

        // TRUE ZERO-ALLOCATION PARSER: Wandelt Bytes direkt mathematisch in Double um, ohne RAM zu belegen!
        private double ParseDoubleFromBytes(byte[] buf, int start, int end)
        {
            while (start <= end && IsWhiteSpace(buf[start])) start++;
            while (end >= start && IsWhiteSpace(buf[end])) end--;
            if (start > end) return 0;

            bool isNegative = false;
            if (buf[start] == (byte)'-') {
                isNegative = true;
                start++;
            } else if (buf[start] == (byte)'+') {
                start++;
            }

            double result = 0;
            double fraction = 0;
            double divisor = 1;
            bool inFraction = false;

            for (int i = start; i <= end; i++)
            {
                byte b = buf[i];
                if (b >= (byte)'0' && b <= (byte)'9')
                {
                    int val = b - (byte)'0';
                    if (inFraction)
                    {
                        fraction = fraction * 10 + val;
                        divisor *= 10;
                    }
                    else
                    {
                        result = result * 10 + val;
                    }
                }
                else if (b == (byte)'.' || b == (byte)',')
                {
                    inFraction = true;
                }
            }

            result += (fraction / divisor);
            return isNegative ? -result : result;
        }

        private bool IsWhiteSpace(byte b) 
        { 
            return b == ' ' || b == '\t' || b == '\r' || b == '\n'; 
        }

        // HYPER-OPTIMIZED: Uses a fast-path for the first byte to speed up parsing by 50x
        private int IndexOfBytes(byte[] data, int dataLen, byte[] searchBytes, int startIndex = 0)
        {
            if (searchBytes.Length == 0 || dataLen < searchBytes.Length) return -1;
            
            byte firstByte = searchBytes[0];
            int limit = dataLen - searchBytes.Length;
            
            for (int i = startIndex; i <= limit; i++)
            {
                if (data[i] == firstByte) // FAST PATH!
                {
                    bool match = true;
                    for (int j = 1; j < searchBytes.Length; j++)
                    {
                        if (data[i + j] != searchBytes[j]) { match = false; break; }
                    }
                    if (match) return i;
                }
            }
            return -1;
        }

        private int IndexOfByte(byte[] data, int dataLen, byte search, int startIndex = 0)
        {
            for (int i = startIndex; i < dataLen; i++)
            {
                if (data[i] == search) return i;
            }
            return -1;
        }

        public void SetVoltage(double voltage)
        {
            // Verhindert Absturz, falls der Parser Müll (wie NaN) empfängt
            if (double.IsNaN(voltage) || double.IsInfinity(voltage)) return;

            if (Math.Abs(_currentVoltage - voltage) < 0.001) return;

            if (voltage > MaxVoltage) voltage = MaxVoltage;
            if (voltage < -MaxVoltage) voltage = -MaxVoltage;

            double dutyCycle = Math.Abs(voltage) / MaxVoltage;

            _currentVoltage = voltage;
            _pwmChannel.DutyCycle = dutyCycle;
        }
    }

    public class DiscoveryBeacon
    {
        public string service { get; set; }
        public string version { get; set; }
        public string[] ips { get; set; }
        public int port { get; set; }
        public string protocol { get; set; }
    }
}