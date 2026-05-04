try:
  import usocket as socket
except:
  import socket
import network
import esp
esp.osdebug(None)
import uos
import ujson
import sys
import os
import machine
import ubinascii

SSID = 'AP-M5DiabConf'
PASSWORD = '123456789'
CONFIG = 'config'
CONFIG_FILE = 'config.json'

DEFAULT_CONFIG = {
    "config": 0,
    "brightness": 1,
    "screen-mode": 0,
    "api-endpoint": "https://www.gms-world.net/s/diabetes/1/api/v1",
    "api-token": "",
    "locale":"",
    "min": 75,
    "max": 180,
    "emergencyMin": 55,
    "emergencyMax": 250, 
    "timezone":"+02:00",
    "beeper": 0,
    "beeperStartTime": "00:00:00",
    "beeperEndTime": "23:59:59",
    "oldData": 15,
    "oldDataEmergenc": 1440,
    "wifi": []
}

ipconfig = None

def xor_data(data):
  try:
    key = machine.unique_id()
  except:
    key = b'fallback_key'
  
  if isinstance(data, str):
    data = data.encode()
  
  l_key = len(key)
  res = bytearray(len(data))
  for i in range(len(data)):
    res[i] = data[i] ^ key[i % l_key]
  return res

def encode_val(val):
  if not val: return ""
  try:
    return ubinascii.hexlify(xor_data(val)).decode()
  except:
    return val

def decode_val(val):
  if not val: return ""
  try:
    return xor_data(ubinascii.unhexlify(val)).decode()
  except:
    return val

def saveConfigFile(config):
  try:
    encoded_config = ujson.loads(ujson.dumps(config))
    
    if "api-token" in encoded_config:
      encoded_config["api-token"] = encode_val(encoded_config["api-token"])
      
    if "wifi" in encoded_config:
      for entry in encoded_config["wifi"]:
        if "password" in entry:
          entry["password"] = encode_val(entry["password"])

    with open(CONFIG_FILE, 'w') as confFile:
      ujson.dump(encoded_config, confFile) 
    print("Successfully saved config file")
  except Exception as e:
    sys.print_exception(e) 

def readConfigFile():
  try:
    config = {}
    if CONFIG_FILE in os.listdir():
      with open(CONFIG_FILE, 'r') as confFile:
         config = ujson.loads(confFile.read())
    else:
      return DEFAULT_CONFIG

    if "api-token" in config:
      config["api-token"] = decode_val(config["api-token"])
      
    for entry in config["wifi"]:
      if "password" in entry:
        entry["password"] = decode_val(entry["password"])
          
    return config
  except Exception as e:
    sys.print_exception(e) 
    return DEFAULT_CONFIG    

def randstr(length=20):
  source = 'abcdefghijklmnopqrstuvwxyz1234567890'
  return ''.join([source[x] for x in [(uos.urandom(1)[0] % len(source)) for _ in range(length)]])

def readHtmlFile(filename):
  try:
    with open(filename, 'r') as htmlFile:
      html = htmlFile.read()
    return html
  except Exception as e:
    sys.print_exception(e) 
    return "<html><body>Error loading page</body></html>"
  
def readHtmlConfigFile(filename):
  try:
    with open(filename, 'r') as htmlFile:
      html = htmlFile.read()
    config = readConfigFile()
    
    ignore = ["config","brightness","screen-mode","beeper","locale", "wifi"]
    if config.get("beeper") == 0:
      config["beeper_disabled"] = "selected"
      config["beeper_enabled"] = ""
    else:
      config["beeper_enabled"] = "selected"
      config["beeper_disabled"] = ""    
    
    for key, value in config.items():
      if key in ignore:
        continue
      placeholder = "{{" + key + "}}"
      if placeholder in html:
        html = html.replace(placeholder, str(value))
    
    wifi_json = ujson.dumps(config.get("wifi", []))
    html = html.replace("{{wifi_json}}", wifi_json)
    
    return html
  except Exception as e:
    sys.print_exception(e)
    return "<html><body>Error loading page</body></html>"  

def unquote(string):
    if not string:
        return b''

    if isinstance(string, str):
        string = string.encode('utf-8')

    bits = string.split(b'%')
    if len(bits) == 1:
        return string

    res = bytearray(bits[0])
    append = res.append
    extend = res.extend

    for item in bits[1:]:
        try:
            append(int(item[:2], 16))
            extend(item[2:])
        except KeyError:
            append(b'%')
            extend(item)

    return bytes(res)

def open_access_point(successCallback):

  ap = network.WLAN(network.AP_IF)
  ap.active(True)
  ssid = SSID + "-" + randstr(5)
  ap.config(essid=ssid, password=PASSWORD)
  ap.config(max_clients=1) 

  while ap.active() == False:
    pass
  
  ipconfig = ap.ifconfig()

  print('AP config: ' + str(ipconfig))

  s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  s.bind(('', 80))
  s.listen(5)

  configHtml = readHtmlConfigFile('config.html')
  successHtml = readHtmlFile('success.html')

  print('Web server is running on port 80')

  while True:
    conn, addr = s.accept()
    print('Got a connection from %s' % str(addr))
    request = conn.recv(1024)
    contentStr = request.decode()
    print('Content = %s' % contentStr)
    splittedRequest = contentStr.split()
    if not splittedRequest:
        conn.close()
        continue
    #rmethod = splittedRequest[0]
    rurl = splittedRequest[1]
  
    conn.send('HTTP/1.1 200 OK\n')
    conn.send('Content-Type: text/html\n')
    conn.send('Connection: close\n\n')

    if rurl.find("/config") != -1:
      splittedRequest = contentStr.split('\r\n')
      configParams = splittedRequest[len(splittedRequest)-1]
      print('Config params: ' + configParams) 
      entries = configParams.split('&') 
      
      wifi_ssids = []
      wifi_passwords = []
      config = {}
      
      for entry in entries:
        parts = entry.split('=')
        if len(parts) != 2: continue
        k = parts[0]
        v = parts[1]
        value = unquote(v).decode()
        if k == 'ssid':
            if value: wifi_ssids.append(value)
        elif k == 'wifi_password':
            wifi_passwords.append(value)
        else:
            if value.isdigit(): value = int(value) 
            config[k] = value
            print("Saved config parameter " + k)
            
      config["wifi"] = []
      for i in range(len(wifi_ssids)):
          config["wifi"].append({
              "ssid": wifi_ssids[i],
              "password": wifi_passwords[i] if i < len(wifi_passwords) else ""
          })
          print("Saved wifi: " + wifi_ssids[i])
          
      config[CONFIG] = 1
      config["brightness"] = 1
      config["screen-mode"] = 0
      saveConfigFile(config)   
      
      successCallback()
      conn.send(successHtml)   
    else: 
      conn.send(configHtml)
      
    conn.close()